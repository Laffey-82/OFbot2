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
async def test_custom_command_prefix_applies_live() -> None:
    """Web 配置把前缀改为 # 后，解析即时生效且旧前缀失效。"""
    registry = CommandRegistry()
    registry.set_command_start(["#"])
    registry.set_security(SecurityPolicy())
    permission_manager.upsert_principal("1", role="superadmin", scopes={"*"})

    async def handler(event, args, context) -> None:
        await event.reply("ok")

    registry.register("ping", handler, permission="bot.command", plugin_name="test")
    event = make_event("#ping")
    assert await registry.handle_message(event) is True
    assert event.replies == ["ok"]

    event_old = make_event("/ping")
    assert await registry.handle_message(event_old) is False
    assert event_old.replies == []
    await get_bus().stop(clear=True)
    reset_bus()


@pytest.mark.asyncio
async def test_unknown_command_hint_uses_active_prefix() -> None:
    """未知命令提示跟随当前前缀（不再硬编码 /）。"""
    registry = CommandRegistry()
    registry.set_command_start(["#"])
    registry.set_security(SecurityPolicy())

    async def handler(event, args, context) -> None:
        await event.reply("ok")

    registry.register("ping", handler, permission="bot.command", plugin_name="test")
    event = make_event("#pin")
    assert await registry.handle_message(event) is False
    assert event.replies and "未找到命令 #pin" in event.replies[0]
    assert "#ping" in event.replies[0]
    await get_bus().stop(clear=True)
    reset_bus()


@pytest.mark.asyncio
async def test_declared_params_parsed_and_validated() -> None:
    """声明参数后，框架自动解析类型/必填/命名参数，错误时回复用法。"""
    registry = CommandRegistry()
    registry.set_command_start(["/"])
    registry.set_security(SecurityPolicy())
    permission_manager.upsert_principal("1", role="superadmin", scopes={"*"})

    captured: dict = {}

    async def handler(event, args, command_ctx) -> None:
        captured["params"] = command_ctx.params
        await event.reply("ok")

    registry.register(
        "add",
        handler,
        permission="bot.command",
        plugin_name="test",
        params=[
            {
                "name": "count",
                "type": "int",
                "required": True,
            },
            {
                "name": "label",
                "type": "string",
                "default": "x",
            },
        ],
    )

    event = make_event("/add 5 你好")
    assert await registry.handle_message(event) is True
    assert captured["params"] == {"count": 5, "label": "你好"}

    event_bad = make_event("/add abc")
    assert await registry.handle_message(event_bad) is True
    assert event_bad.replies and "参数错误" in event_bad.replies[0]
    assert "需要整数" in event_bad.replies[0]
    assert "用法" in event_bad.replies[0]

    event_missing = make_event("/add")
    assert await registry.handle_message(event_missing) is True
    assert event_missing.replies and "缺少必填参数" in event_missing.replies[0]
    await get_bus().stop(clear=True)
    reset_bus()


@pytest.mark.asyncio
async def test_subcommand_dispatch() -> None:
    """分段命令：第一段作为子命令，其余参数绑定到子命令参数。"""
    registry = CommandRegistry()
    registry.set_command_start(["/"])
    registry.set_security(SecurityPolicy())
    permission_manager.upsert_principal("1", role="superadmin", scopes={"*"})

    captured: dict = {}

    async def handler(event, args, command_ctx) -> None:
        captured["sub"] = command_ctx.subcommand
        captured["params"] = command_ctx.params
        await event.reply("ok")

    registry.register(
        "greet",
        handler,
        permission="bot.command",
        plugin_name="test",
        subcommands=[
            {
                "name": "hello",
                "aliases": ["你好"],
                "params": [
                    {"name": "target", "type": "string", "default": "世界"}
                ],
            },
            {
                "name": "world",
                "params": [
                    {"name": "count", "type": "int", "default": 1}
                ],
            },
        ],
    )

    event = make_event("/greet 你好 小明")
    assert await registry.handle_message(event) is True
    assert captured["sub"] == "hello"
    assert captured["params"] == {"target": "小明"}

    event2 = make_event("/greet world 3")
    assert await registry.handle_message(event2) is True
    assert captured["sub"] == "world"
    assert captured["params"] == {"count": 3}

    event3 = make_event("/greet nope")
    assert await registry.handle_message(event3) is True
    assert event3.replies and "未知子命令" in event3.replies[0]
    await get_bus().stop(clear=True)
    reset_bus()


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
