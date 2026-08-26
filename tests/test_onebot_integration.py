from __future__ import annotations

import asyncio
import json

import pytest
import websockets

from app.adapters.base import BotClient
from app.adapters.onebot import OneBotAdapter
from app.core.bus import get_bus, reset_bus
from app.core.config import OneBotSettings
from app.core.messages import GroupMessageEvent


class RecordingClient(BotClient):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[GroupMessageEvent] = []

    async def handle_bot_event(self, event):
        self.events.append(event)
        return True


@pytest.mark.asyncio
async def test_onebot_forward_connects_and_sends() -> None:
    received_actions: list[dict] = []

    async def ws_handler(websocket) -> None:
        await websocket.send(
            json.dumps(
                {
                    "post_type": "message",
                    "message_type": "group",
                    "group_id": 200,
                    "user_id": 100,
                    "message_id": 1,
                    "raw_message": "/ping",
                    "message": "/ping",
                    "sender": {"nickname": "tester", "card": None},
                }
            )
        )
        try:
            first = json.loads(await websocket.recv())
            received_actions.append(first)
        except Exception:
            pass

    async with websockets.serve(ws_handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        client = RecordingClient()
        adapter = OneBotAdapter(
            OneBotSettings(host="127.0.0.1", port=port, mode="forward"),
            "test",
            client,
        )
        task = asyncio.create_task(adapter.start())
        try:
            for _ in range(50):
                if client.events:
                    break
                await asyncio.sleep(0.1)
            assert client.events, "onebot adapter did not receive group message"
            assert client.events[0].group_id == "200"

            assert await adapter.send_group_message("200", "hello") is True
            for _ in range(50):
                if received_actions:
                    break
                await asyncio.sleep(0.1)
            assert received_actions
            assert received_actions[-1]["action"] == "send_group_msg"
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await adapter.stop()
            try:
                await get_bus().stop(clear=True)
            except Exception:
                pass
            reset_bus()
