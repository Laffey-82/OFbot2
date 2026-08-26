from __future__ import annotations

import asyncio

from app.adapters.base import BotClient
from app.adapters.onebot import OneBotAdapter
from app.adapters.red import RedAdapter
from app.core.config import OneBotSettings, RedSettings


def test_onebot_parses_cq_message() -> None:
    adapter = OneBotAdapter(OneBotSettings(), "test", BotClient())
    message = adapter._parse_message("[CQ:at,qq=123] hello [CQ:image,file=a.png]")
    assert message.segments[0].type == "at"
    assert "hello" in message.extract_plain_text()


def test_red_parses_text_and_image_segments() -> None:
    adapter = RedAdapter(RedSettings(), "test", BotClient())
    segments = adapter._parse_segments(
        [
            {"elementType": 1, "textElement": {"content": "hello"}},
            {"elementType": 2, "picElement": {"sourcePath": "x.png", "md5HexStr": "abc"}},
        ]
    )
    assert segments[0].type == "text"
    assert segments[1].type == "image"


def test_bot_client_counts_messages() -> None:
    client = BotClient()

    class FakeAdapter:
        async def send_group_message(self, group_id: str, message: str) -> bool:
            return True

        async def send_private_message(self, user_id: str, message: str) -> bool:
            return True

    client.register("fake", FakeAdapter())
    assert asyncio.run(client.send_group_message("1", "hi")) is True
    assert asyncio.run(client.send_private_message("2", "hi")) is True
    assert client.counters["fake"]["sent"] == 2


def test_adapter_tracks_heartbeat() -> None:
    client = BotClient()
    adapter = RedAdapter(RedSettings(), "red", client)
    assert adapter._reconnects == 0
    client.details["red"] = {"self_id": "1", "connected_at": 0}
    asyncio.run(adapter._handle_raw('{"type": "keepalive"}'))
    assert client.details["red"]["last_heartbeat"] > 0
