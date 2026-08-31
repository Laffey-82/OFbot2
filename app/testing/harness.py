"""插件级端到端测试夹具：假 Chronocat（Red WS+HTTP）+ 子进程启动真实机器人。

用法：
    async with FakeBotHarness(
        plugins={"system": True, "order_ledger": True},
        plugin_configs={"order_ledger": {}},
    ) as bot:
        reply = await bot.send_group("200", "/ping")
        assert "pong" in reply
"""

from __future__ import annotations

import asyncio
import json
import socket
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Self

import websockets
import yaml


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def make_group_payload(group_id: str, message: str, seq: int = 1) -> dict:
    return {
        "type": "message::recv",
        "payload": [
            {
                "msgId": f"msg-{seq}",
                "chatType": 2,
                "subMsgType": 0,
                "sendType": 1,
                "senderUid": "u-100",
                "senderUin": "100",
                "peerUid": f"u-{group_id}",
                "peerUin": group_id,
                "msgTime": "0",
                "msgSeq": str(seq),
                "cntSeq": str(seq),
                "elements": [{"elementType": 1, "textElement": {"content": message}}],
                "sendMemberName": "tester",
                "sendNickName": "tester",
                "peerName": "fake-group",
                "records": [],
                "emojiLikesList": [],
            }
        ],
    }


def extract_text(body: str) -> str:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return body
    parts: list[str] = []
    for element in payload.get("elements", []):
        if element.get("elementType") == 1:
            parts.append(element.get("textElement", {}).get("content", ""))
    return "".join(parts)


def _make_api_handler(captured: list[str]) -> type[BaseHTTPRequestHandler]:
    class ApiHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8", "replace")
            captured.append(body)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok": true}')

        def log_message(self, format: str, *args) -> None:
            pass

    return ApiHandler


class FakeBotHarness:
    """启动假 Chronocat + 真实机器人子进程，向指定群/私聊注入消息并捕获回复。"""

    def __init__(
        self,
        *,
        plugins: dict[str, bool] | None = None,
        plugin_configs: dict[str, Any] | None = None,
        config_extra: dict[str, Any] | None = None,
        root: str | Path | None = None,
    ) -> None:
        self.root = Path(root) if root else Path(__file__).resolve().parents[2]
        self.plugins = plugins or {"system": True, "template": True}
        self.plugin_configs = plugin_configs or {}
        self.config_extra = config_extra or {}
        self.ws_port = _free_port()
        self.api_port = _free_port()
        self.web_port = _free_port()
        self.captured: list[str] = []
        self._connections: list[Any] = []
        self._api_server: ThreadingHTTPServer | None = None
        self._ws_server: Any = None
        self._process: asyncio.subprocess.Process | None = None
        self._tmp: tempfile.TemporaryDirectory | None = None

    async def __aenter__(self) -> Self:
        handler_cls = _make_api_handler(self.captured)
        self._api_server = ThreadingHTTPServer(
            ("127.0.0.1", self.api_port), handler_cls
        )
        threading.Thread(target=self._api_server.serve_forever, daemon=True).start()
        self._ws_server = await websockets.serve(
            self._ws_handle, "127.0.0.1", self.ws_port
        )

        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        tmp = Path(self._tmp.name)
        config = {
            "basic": {
                "log_level": "WARNING",
                "log_max_files": 3,
                "log_retention_days": 1,
                "superusers": ["100"],
            },
            "database": {"url": f"sqlite+aiosqlite:///{(tmp / 'bot.db').as_posix()}"},
            "web": {
                "host": "127.0.0.1",
                "port": self.web_port,
                "api_keys": [],
            },
            "transport": {
                "red": {
                    "enabled": True,
                    "host": "127.0.0.1",
                    "port": self.ws_port,
                    "token": "test-token",
                    "api_base": f"http://127.0.0.1:{self.api_port}",
                    "reconnect_interval": 3.0,
                }
            },
            "plugins": self.plugins,
            "plugin_configs": {
                "system": {"groups": ["200"]},
                **self.plugin_configs,
            },
            **self.config_extra,
        }
        config_path = tmp / "config.yaml"
        config_path.write_text(
            yaml.safe_dump(config, allow_unicode=True), encoding="utf-8"
        )
        self._process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(self.root / "main.py"),
            "--config",
            str(config_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        await self._wait_connected()
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._process is not None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=10)
            except (TimeoutError, ProcessLookupError):
                self._process.kill()
                await self._process.wait()
            await asyncio.sleep(0.5)
        if self._api_server is not None:
            self._api_server.shutdown()
        if self._ws_server is not None:
            self._ws_server.close()
            await self._ws_server.wait_closed()
        if self._tmp is not None:
            self._tmp.cleanup()

    async def _ws_handle(self, websocket) -> None:
        first = json.loads(await websocket.recv())
        if first.get("type") == "message::recv":
            for conn in list(self._connections):
                if conn is not websocket:
                    await conn.send(json.dumps(first))
            await websocket.close()
            return
        if first.get("type") != "meta::connect":
            await websocket.close()
            return
        await websocket.send(
            json.dumps(
                {
                    "type": "meta::connect",
                    "payload": {
                        "authData": {"uin": "123456"},
                        "version": "fake-chronocat",
                    },
                }
            )
        )
        self._connections.append(websocket)
        await websocket.wait_closed()

    async def _wait_connected(self, timeout: float = 30.0) -> None:
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            if self._process is not None and self._process.returncode is not None:
                raise RuntimeError("bot 进程在连接前退出")
            if self._connections:
                return
            await asyncio.sleep(0.1)
        raise TimeoutError("bot 未能在超时时间内连接假服务")

    async def _send(self, payload: dict) -> str:
        before = len(self.captured)
        async with websockets.connect(f"ws://127.0.0.1:{self.ws_port}") as ws:
            await ws.send(json.dumps(payload))
        for _ in range(100):
            if len(self.captured) > before:
                return extract_text(self.captured[-1])
            await asyncio.sleep(0.1)
        return ""

    async def send_group(self, group_id: str, message: str, seq: int = 1) -> str:
        """向群发送消息并等待回复文本。"""
        return await self._send(make_group_payload(str(group_id), message, seq))

    async def send_private(self, user_id: str, message: str, seq: int = 1) -> str:
        payload = make_group_payload(str(user_id), message, seq)
        payload["payload"][0]["chatType"] = 1
        payload["payload"][0]["peerUin"] = str(user_id)
        return await self._send(payload)

    def replies(self) -> list[str]:
        return [extract_text(body) for body in self.captured]


async def run_smoke() -> int:
    """自检：启动 harness 并验证 /ping 回复。"""
    async with FakeBotHarness() as bot:
        reply = await bot.send_group("200", "/ping")
        if "pong" in reply:
            print("PASS FakeBotHarness /ping")
            return 0
        print(f"FAIL /ping 未回复 pong：{reply!r}")
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run_smoke()))
