"""Tests for core defect fixes: rate limit, cooldown, keyword, rest params."""
from __future__ import annotations

import pytest

from app.core.bus import get_bus, reset_bus
from app.core.commands import CommandRegistry
from app.core.messages import GroupMessageEvent, Message, MessageSegment, Sender
from app.core.parsing import ParamSpec, bind_params
from app.core.permissions import permission_manager
from app.core.rules import _rule_keyword
from app.core.security import SecurityPolicy


def make_event(text: str, user_id: str = "1", group_id: str = "2") -> GroupMessageEvent:
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
    )

    async def reply(message: str | Message | MessageSegment) -> None:
        replies.append(
            message.extract_plain_text() if isinstance(message, Message) else str(message)
        )

    event.reply = reply
    event.replies = replies
    return event


@pytest.mark.asyncio
async def test_rate_limit_rejects_on_exceed():
    """Defect 1: rate_limit 命令超限被拒。"""
    registry = CommandRegistry()
    registry.set_command_start(["/"])
    policy = SecurityPolicy(rate_limit_default="2/minute")
    registry.set_security(policy)
    permission_manager.upsert_principal("1", role="superadmin", scopes={"*"})

    async def handler(event, args, context):
        await event.reply("ok")

    registry.register(
        "rltest",
        handler,
        permission="bot.command",
        plugin_name="test",
        rate_limit="2/minute",
    )

    for _ in range(2):
        event = make_event("/rltest")
        await registry.handle_message(event)

    event = make_event("/rltest")
    await registry.handle_message(event)
    assert event.replies and "触发频率限制" in event.replies[0]
    await get_bus().stop(clear=True)
    await reset_bus()


@pytest.mark.asyncio
async def test_rate_limit_default_works():
    """Defect 2: rate_limit_default 生效。"""
    registry = CommandRegistry()
    registry.set_command_start(["/"])
    policy = SecurityPolicy(rate_limit_default="2/minute")
    registry.set_security(policy)
    permission_manager.upsert_principal("1", role="superadmin", scopes={"*"})

    async def handler(event, args, context):
        await event.reply("ok")

    registry.register(
        "norate",
        handler,
        permission="bot.command",
        plugin_name="test",
    )

    for _ in range(2):
        event = make_event("/norate")
        await registry.handle_message(event)

    event = make_event("/norate")
    await registry.handle_message(event)
    assert event.replies and "触发频率限制" in event.replies[0]
    await get_bus().stop(clear=True)
    await reset_bus()


@pytest.mark.asyncio
async def test_cooldown_eviction_preserves_keys():
    """Defect 3: 冷却表注入 1 万+条目后既有冷却键不被清零。"""
    policy = SecurityPolicy(default_cooldown_seconds=60.0)

    for i in range(10_001):
        policy.check_cooldown(f"cooldown:fake:{i}", 60.0)

    key = "cooldown:1:mycmd"
    assert policy.check_cooldown(key, 60.0) is True
    assert key in policy._last_command
    assert policy.check_cooldown(key, 60.0) is False


@pytest.mark.asyncio
async def test_keyword_numeric_list():
    """Defect 4: keyword 数字规则不再抛错。"""
    event = make_event("12345")
    result = await _rule_keyword(event, {"value": [123, 456]})
    assert result is True

    result2 = await _rule_keyword(event, {"value": [999]})
    assert result2 is False


@pytest.mark.asyncio
async def test_rest_param_missing_required_after():
    """Defect 5: rest 参数后必填缺失报用法错误。"""
    params = [
        ParamSpec(name="msg", type="rest", required=True),
        ParamSpec(name="extra", type="string", required=True),
    ]
    _, error = bind_params("hello", params)
    assert error is not None
    assert "缺少必填参数：extra" in error
