"""Local fake Chronocat service for developing without a real QQ client.

Usage:
    py scripts/fake_chronocat.py

Configure config.yaml:
    transport.red.host: 127.0.0.1
    transport.red.port: 16530
    transport.red.token: test-token
    transport.red.api_base: http://127.0.0.1:16531

After the bot connects, type:
    group <group_id> <message>
to simulate a group message sent to the bot.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import websockets


class ApiHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8", "replace")
        print(f"[API] {self.path} {body}")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok": true}')

    def log_message(self, format: str, *args) -> None:
        pass


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
    token = first.get("payload", {}).get("token", "")
    print(f"[WS] connect token={token}")
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
    print("[WS] bot connected; type `group <id> <message>` to simulate a message")
    try:
        await websocket.wait_closed()
    finally:
        connections.remove(websocket)


async def console_loop(connections: list) -> None:
    seq = 0
    while True:
        try:
            line = await asyncio.to_thread(input, "send> ")
        except EOFError:
            await asyncio.sleep(0.5)
            continue
        parts = line.strip().split(maxsplit=2)
        if not line.strip():
            continue
        if parts[0].lower() == "quit":
            break
        if len(parts) < 3 or parts[0].lower() != "group":
            print("usage: group <group_id> <message>")
            continue
        group_id, message = parts[1], parts[2]
        seq += 1
        payload = make_group_payload(group_id, message, seq)
        for websocket in list(connections):
            await websocket.send(json.dumps(payload))
        print(f"[WS] sent group={group_id} message={message}")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ws-port", type=int, default=16530)
    parser.add_argument("--api-port", type=int, default=16531)
    args = parser.parse_args()

    connections: list = []
    api_server = ThreadingHTTPServer(("127.0.0.1", args.api_port), ApiHandler)
    threading.Thread(target=api_server.serve_forever, daemon=True).start()
    print(f"[HTTP] fake Red API on http://127.0.0.1:{args.api_port}")

    async with websockets.serve(
        lambda ws: ws_handler(ws, connections),
        "127.0.0.1",
        args.ws_port,
    ):
        print(f"[WS] fake Chronocat on ws://127.0.0.1:{args.ws_port}")
        try:
            if sys.stdin.isatty():
                await console_loop(connections)
            else:
                print("[WS] non-interactive mode; inject messages via a websocket client")
                await asyncio.Future()
        finally:
            api_server.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
