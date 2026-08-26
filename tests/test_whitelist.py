from __future__ import annotations

import pytest

from app.adapters.base import BotClient
from app.core.messages import GroupMessageEvent, Message, Sender
from app.core.whitelist import GroupWhitelistService


@pytest.mark.asyncio
async def test_whitelist_filters_group_message() -> None:
    service = GroupWhitelistService(["100"])
    client = BotClient(whitelist_service=service)
    event = GroupMessageEvent(
        bot_id="test",
        self_id="10",
        raw_event={},
        message_id="1",
        user_id="1",
        sender=Sender("1", "tester"),
        message=Message("hello"),
        group_id="200",
    )
    assert await client.handle_bot_event(event) is False


@pytest.mark.asyncio
async def test_whitelist_empty_allows_all() -> None:
    service = GroupWhitelistService([])
    assert service.contains("200") is True
