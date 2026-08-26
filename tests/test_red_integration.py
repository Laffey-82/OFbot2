from __future__ import annotations

import asyncio
import json

import httpx
import pytest
import websockets

from app.adapters.base import BotClient
from app.adapters.red import RedAdapter
from app.core.bus import get_bus, reset_bus
from app.core.config import RedSettings
from app.core.messages import GroupMessageEvent


class RecordingClient(BotClient):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[GroupMessageEvent] = []

    async def handle_bot_event(self, event):
        self.events.append(event)
        return True


def make_group_payload() -> dict:
    return {
        "type": "message::recv",
        "payload": [
            {
                "msgId": "msg-1",
                "chatType": 2,
                "subMsgType": 0,
                "sendType": 1,
                "senderUid": "u-100",
                "senderUin": "100",
                "peerUid": "u-200",
                "peerUin": "200",
                "msgTime": "0",
                "msgSeq": "1",
                "cntSeq": "1",
                "elements": [{"elementType": 1, "textElement": {"content": "/ping"}}],
                "sendMemberName": "tester",
                "sendNickName": "tester",
                "peerName": "group",
                "records": [],
                "emojiLikesList": [],
            }
        ],
    }


@pytest.mark.asyncio
async def test_red_adapter_connects_and_sends() -> None:
    captured: list[httpx.Request] = []

    def http_handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"ok": True})

    async def ws_handler(websocket) -> None:
        connect = json.loads(await websocket.recv())
        assert connect["type"] == "meta::connect"
        await websocket.send(
            json.dumps(
                {
                    "type": "meta::connect",
                    "payload": {
                        "authData": {"uin": "123"},
                        "version": "test",
                    },
                }
            )
        )
        await websocket.send(json.dumps(make_group_payload()))
        await asyncio.sleep(0.2)

    async with websockets.serve(ws_handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        client = RecordingClient()
        adapter = RedAdapter(
            RedSettings(
                host="127.0.0.1",
                port=port,
                token="test-token",
                api_base="http://127.0.0.1",
            ),
            "test",
            client,
        )
        adapter._http = httpx.AsyncClient(transport=httpx.MockTransport(http_handler))
        task = asyncio.create_task(adapter.start())
        try:
            for _ in range(50):
                if client.events:
                    break
                await asyncio.sleep(0.1)
            assert client.events, "red adapter did not receive group message"
            assert client.events[0].group_id == "200"
            assert client.events[0].message.extract_plain_text() == "/ping"

            assert await adapter.send_group_message("200", "hello") is True
            assert captured
            assert captured[0].url.path == "/message/send"
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await adapter.stop()
            try:
                await get_bus().stop(clear=True)
            except Exception:
                pass
            reset_bus()
