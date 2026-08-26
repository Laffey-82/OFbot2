from __future__ import annotations

import pytest

from app.core.bus import get_bus, reset_bus
from app.core.commands import CommandRegistry
from app.core.messages import GroupMessageEvent, Message, MessageSegment, Sender
from app.core.permissions import permission_manager
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


def test_command_parse_with_separator() -> None:
    registry = CommandRegistry()
    registry.set_command_start(["/"])
    registry.set_command_sep(["."])
    assert registry.parse("/ping") == ("ping", "")
    assert registry.parse("/ping.x") == ("ping", "x")
    assert registry.parse("/ping.x y") == ("ping", "x y")
    assert registry.parse("/ping  arg") == ("ping", "arg")
    # 分隔符不在命令名中时不影响普通解析
    registry.set_command_sep([";"])
    assert registry.parse("/ping.x") == ("ping.x", "")


@pytest.mark.asyncio
async def test_command_registry_runs_handler() -> None:
    registry = CommandRegistry()
    registry.set_command_start(["/"])
    registry.set_security(SecurityPolicy())
    permission_manager.upsert_principal("1", role="superadmin", scopes={"*"})

    async def handler(event, args, context) -> None:
        await event.reply("ok")

    registry.register("ping", handler, permission="bot.command", plugin_name="test")
    event = make_event("/ping")
    handled = await registry.handle_message(event)
    assert handled is True
    assert event.replies == ["ok"]
    await get_bus().stop(clear=True)
    reset_bus()


@pytest.mark.asyncio
async def test_command_registry_rejects_unknown() -> None:
    registry = CommandRegistry()
    registry.set_command_start(["/"])
    event = make_event("hello")
    assert await registry.handle_message(event) is False


@pytest.mark.asyncio
async def test_normal_user_can_run_plugin_permission_command() -> None:
    registry = CommandRegistry()
    registry.set_command_start(["/"])
    registry.set_security(SecurityPolicy())
    permission_manager.upsert_principal("user-1", role="user")
    permission_manager.grant_role_permission("user", "template.ping")

    async def handler(event, args, context) -> None:
        await event.reply("pong")

    registry.register(
        "ping", handler, permission="template.ping", plugin_name="template"
    )
    event = make_event("/ping", user_id="user-1")
    assert await registry.handle_message(event) is True
    assert event.replies == ["pong"]
    await get_bus().stop(clear=True)
    reset_bus()
