"""End-to-end smoke test using the fake Chronocat service.

Run:
    py scripts/e2e_smoke.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

import websockets

ROOT = Path(__file__).resolve().parents[1]


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


class ApiHandler(BaseHTTPRequestHandler):
    captured: ClassVar[list[str]] = []

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8", "replace")
        self.captured.append(body)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok": true}')

    def log_message(self, format: str, *args) -> None:
        pass


async def ws_handler(websocket, connections: list) -> None:
    first = json.loads(await websocket.recv())
    if first.get("type") == "message::recv":
        for conn in list(connections):
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
    connections.append(websocket)
    await websocket.wait_closed()


async def run() -> int:
    connections: list = []
    api_server = ThreadingHTTPServer(("127.0.0.1", 16531), ApiHandler)
    threading.Thread(target=api_server.serve_forever, daemon=True).start()

    async with websockets.serve(
        lambda ws: ws_handler(ws, connections),
        "127.0.0.1",
        16530,
    ):
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(ROOT / "main.py"),
            "--config",
            str(ROOT / "data" / "fake_config.yaml"),
        )
        try:
            for _ in range(150):
                if connections:
                    break
                await asyncio.sleep(0.1)
            if not connections:
                print("FAIL: bot did not connect")
                return 1

            payload = make_group_payload("200", "/ping", seq=1)
            async with websockets.connect("ws://127.0.0.1:16530") as ws:
                await ws.send(json.dumps(payload))

            for _ in range(50):
                if ApiHandler.captured:
                    break
                await asyncio.sleep(0.1)

            if ApiHandler.captured and "pong" in ApiHandler.captured[-1]:
                print("PASS: bot replied with pong")
                return 0
            print("FAIL: bot did not reply with pong")
            return 1
        finally:
            process.terminate()
            await asyncio.wait_for(process.wait(), timeout=5)
            api_server.shutdown()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
