from __future__ import annotations

import pytest

from app.core.bus import get_bus, reset_bus
from app.core.commands import CommandRegistry
from app.core.config import RuntimeSettings, ScopeEntry, Settings
from app.core.messages import GroupMessageEvent, Message, MessageSegment, Sender
from app.core.permissions import permission_manager
from app.core.scopes import SCOPE_GLOBAL_GROUP, ScopePolicyService
from app.core.security import SecurityPolicy


def make_event(
    text: str, user_id: str = "1", group_id: str = "2", at_self: bool = False
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


def _registry() -> tuple[CommandRegistry, ScopePolicyService, Settings]:
    registry = CommandRegistry()
    registry.set_command_start(["/"])
    registry.set_security(SecurityPolicy())
    settings = Settings()
    settings.runtime = RuntimeSettings(
        scopes={
            SCOPE_GLOBAL_GROUP: ScopeEntry(features={"demo.greet": True}),
        }
    )
    policy = ScopePolicyService(settings)
    registry.set_scope_policy(policy)

    async def handler(event, args, command_ctx) -> None:
        await event.reply("ok")

    registry.register(
        "greet",
        handler,
        permission="bot.command",
        plugin_name="demo",
        feature_id="demo.greet",
    )
    registry.register("secret", handler, permission="bot.command", plugin_name="demo")
    return registry, policy, settings


@pytest.mark.asyncio
async def test_feature_disabled_denies_with_hint() -> None:
    registry, policy, _ = _registry()
    policy.set_feature("group:2", "demo.greet", False)
    event = make_event("/greet")
    assert await registry.handle_message(event) is True
    assert event.replies and "未开启" in event.replies[0]
    await get_bus().stop(clear=True)
    await reset_bus()


@pytest.mark.asyncio
async def test_feature_disabled_silent_deny() -> None:
    registry, policy, _ = _registry()
    policy.set_feature("group:2", "demo.greet", False)
    policy.set_silent_deny("group:2", True)
    event = make_event("/greet")
    assert await registry.handle_message(event) is True
    assert event.replies == []
    await get_bus().stop(clear=True)
    await reset_bus()


@pytest.mark.asyncio
async def test_unknown_command_suggestion() -> None:
    registry, _, _ = _registry()
    event = make_event("/grete")
    assert await registry.handle_message(event) is False
    assert event.replies and "是否想用" in event.replies[0]
    assert "/greet" in event.replies[0]
    await get_bus().stop(clear=True)
    await reset_bus()


@pytest.mark.asyncio
async def test_scope_permission_override() -> None:
    registry, policy, _ = _registry()
    permission_manager.upsert_principal("1", role="user")
    policy.set_permission("group:2", "bot.command", False)
    event = make_event("/secret")
    assert await registry.handle_message(event) is True
    assert event.replies and "权限不足" in event.replies[0]
    await get_bus().stop(clear=True)
    await reset_bus()


@pytest.mark.asyncio
async def test_at_self_trigger() -> None:
    registry, _, _ = _registry()
    event = make_event("@10 /greet", at_self=True)
    assert await registry.handle_message(event) is True
    assert event.replies == ["ok"]
    await get_bus().stop(clear=True)
    await reset_bus()


@pytest.mark.asyncio
async def test_help_detail_shows_usage_and_examples() -> None:
    from pathlib import Path

    from app.adapters.base import BotClient
    from app.core.cache import TTLCache
    from app.core.messages import Message as Msg
    from app.core.permissions import PermissionManager
    from app.core.plugin import PluginManager
    from app.core.scheduler import SchedulerService
    from app.core.subscriptions import EventSubscriptionRegistry
    from app.core.whitelist import GroupWhitelistService

    commands = CommandRegistry()
    commands.set_command_start(["/"])
    commands.set_security(SecurityPolicy())
    manager = PluginManager(
        Path(__file__).resolve().parents[1] / "plugins",
        commands=commands,
        db=None,
        scheduler=SchedulerService(),
        cache=TTLCache(),
        bot=BotClient(),
        permissions=PermissionManager(),
        services={"whitelist": GroupWhitelistService([])},
        subscriptions=EventSubscriptionRegistry(),
    )
    manager.load_enabled({"system": True}, {"system": {"groups": []}})

    class FakeEvent:
        def __init__(self) -> None:
            self.replies: list[str] = []

        async def reply(self, content: str) -> None:
            self.replies.append(content)

    handler = commands._commands["help"].handler
    event = FakeEvent()
    await handler(event, Msg("whitelist"), None)
    assert "用法：" in event.replies[0]
    assert "示例：" in event.replies[0]
    await manager.unload_plugin("system")
    await get_bus().stop(clear=True)
    await reset_bus()
