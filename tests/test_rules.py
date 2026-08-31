from __future__ import annotations

import pytest

from app.core.bus import get_bus, reset_bus
from app.core.commands import CommandRegistry
from app.core.config import RuntimeSettings, ScopeEntry, Settings
from app.core.messages import (
    GroupMessageEvent,
    Message,
    MessageSegment,
    Sender,
)
from app.core.rules import RuleRegistry, RuleSpec
from app.core.scopes import SCOPE_GLOBAL_GROUP, ScopePolicyService
from app.core.security import SecurityPolicy


def make_event(
    text: str,
    user_id: str = "1",
    group_id: str = "2",
    at_self: bool = False,
) -> GroupMessageEvent:
    replies: list[str] = []
    event = GroupMessageEvent(
        bot_id="test",
        self_id="10",
        raw_event={},
        message_id="1",
        user_id=user_id,
        sender=Sender(user_id, "tester"),
        message=Message(text),
        group_id=group_id,
        at_self=at_self,
    )

    async def reply(message: str | Message | MessageSegment) -> None:
        replies.append(
            message.extract_plain_text()
            if isinstance(message, Message)
            else str(message)
        )

    event.reply = reply
    event.replies = replies
    return event


def _registry(rules: list[RuleSpec]) -> CommandRegistry:
    registry = CommandRegistry()
    registry.set_command_start(["/"])
    registry.set_security(SecurityPolicy())
    registry.set_rule_registry(RuleRegistry())
    settings = Settings()
    settings.runtime = RuntimeSettings(
        scopes={SCOPE_GLOBAL_GROUP: ScopeEntry()}
    )
    registry.set_scope_policy(ScopePolicyService(settings))

    async def handler(event, args, command_ctx) -> None:
        await event.reply("ok")

    registry.register(
        "hello",
        handler,
        permission="bot.command",
        plugin_name="demo",
        rules=rules,
    )
    return registry


@pytest.mark.asyncio
async def test_keyword_rule_matches() -> None:
    registry = _registry(
        [RuleSpec(name="keyword", params={"value": "签到"})]
    )
    event = make_event("/hello 签到")
    assert await registry.handle_message(event) is True
    assert event.replies and event.replies[0] == "ok"
    await get_bus().stop(clear=True)
    await reset_bus()


@pytest.mark.asyncio
async def test_keyword_rule_mismatch_blocks() -> None:
    registry = _registry(
        [RuleSpec(name="keyword", params={"value": "签到"})]
    )
    event = make_event("/hello 其他")
    assert await registry.handle_message(event) is True
    assert not event.replies
    await get_bus().stop(clear=True)
    await reset_bus()


@pytest.mark.asyncio
async def test_to_me_rule_private_and_at() -> None:
    registry = _registry([RuleSpec(name="to_me")])
    event = make_event("/hello", group_id="", at_self=False)
    assert await registry.handle_message(event) is True
    assert event.replies and event.replies[0] == "ok"

    event2 = make_event("/hello", group_id="2", at_self=True)
    assert await registry.handle_message(event2) is True
    assert event2.replies
    await get_bus().stop(clear=True)
    await reset_bus()


@pytest.mark.asyncio
async def test_in_group_rule() -> None:
    registry = _registry(
        [RuleSpec(name="in_group", params={"groups": ["2"]})]
    )
    ok_event = make_event("/hello", group_id="2")
    assert await registry.handle_message(ok_event) is True
    assert ok_event.replies

    bad_event = make_event("/hello", group_id="99")
    assert await registry.handle_message(bad_event) is True
    assert not bad_event.replies
    await get_bus().stop(clear=True)
    await reset_bus()


@pytest.mark.asyncio
async def test_custom_rule_registration() -> None:
    registry = _registry([])
    registry.rules.register("even_user", lambda event, params: int(event.user_id) % 2 == 0)
    assert registry.rules.has("even_user")
    assert registry.rules.validate([RuleSpec(name="even_user")]) == []

    rule_registry = RuleRegistry()
    assert rule_registry.validate([RuleSpec(name="nope")]) == ["nope"]


@pytest.mark.asyncio
async def test_regex_rule() -> None:
    registry = _registry(
        [RuleSpec(name="regex", params={"pattern": r"^/hello\s+\d+$"})]
    )
    event = make_event("/hello 42")
    assert await registry.handle_message(event) is True
    assert event.replies
    await get_bus().stop(clear=True)
    await reset_bus()
