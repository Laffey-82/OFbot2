"""order_ledger 插件端到端冒烟：假 Chronocat + 完整订单/统计/分账流程。

用法（项目根目录）：
    py scripts/e2e_order_ledger_smoke.py
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


async def send_and_wait(
    ws_url: str, group_id: str, message: str, seq: int, captured: list[str], before: int
) -> str:
    async with websockets.connect(ws_url) as ws:
        await ws.send(json.dumps(make_group_payload(group_id, message, seq)))
    for _ in range(80):
        if len(captured) > before:
            return extract_text(captured[-1])
        await asyncio.sleep(0.1)
    return ""


async def run() -> int:
    ApiHandler.captured = []
    connections: list = []
    api_server = ThreadingHTTPServer(("127.0.0.1", 16531), ApiHandler)
    threading.Thread(target=api_server.serve_forever, daemon=True).start()

    # 清理上一次冒烟测试的假数据库，保证从零开始
    fake_db = ROOT / "data" / "fake_bot.db"
    if fake_db.exists():
        fake_db.unlink()

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
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            for _ in range(150):
                if connections:
                    break
                await asyncio.sleep(0.1)
            if not connections:
                print("FAIL: bot did not connect")
                return 1

            ws_url = "ws://127.0.0.1:16530"
            cases = [
                ("/录入 白系理论 1 0 1 100 官机打", ["订单录入成功", "白系理论"]),
                ("/查询 未接单", ["订单列表"]),
                ("/接单 1", ["接单成功"]),
                ("/完成 1", ["订单已完成"]),
                ("/统计 全部", ["总营收"]),
                ("/排行 全部 全部", ["排行"]),
                ("/账目", ["个人账目中心"]),
                ("/我的订单", ["我的订单"]),
                ("/分账 昨日", ["分账操作已执行完成"]),
                ("/分账历史 昨日", ["分账历史"]),
                ("/导出订单 全部", ["导出成功"]),
                ("/订单状态", ["订单统计"]),
            ]
            failed = []
            for i, (command, keywords) in enumerate(cases, 1):
                before = len(ApiHandler.captured)
                reply = await send_and_wait(
                    ws_url, "200", command, i, ApiHandler.captured, before
                )
                if not reply:
                    failed.append((command, "无回复"))
                    continue
                missing = [kw for kw in keywords if kw not in reply]
                if missing:
                    failed.append((command, f"缺少关键词 {missing}，回复：{reply[:120]}"))
                else:
                    print(f"PASS {command}")

            if failed:
                for command, reason in failed:
                    print(f"FAIL {command}: {reason}")
                return 1

            print("PASS: order_ledger 端到端冒烟全部通过")
            return 0
        finally:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=10)
            except (TimeoutError, ProcessLookupError):
                process.kill()
                await process.wait()
            try:
                rest = await asyncio.wait_for(process.stdout.read(), timeout=5)
            except Exception:
                rest = b""
            log_text = rest.decode("utf-8", "replace")
            if "plugin loaded: order_ledger" in log_text:
                print("PASS plugin loaded: order_ledger")
            else:
                print("WARN 未在日志中看到 order_ledger 插件加载记录")
            api_server.shutdown()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
