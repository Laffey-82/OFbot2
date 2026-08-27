from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.adapters.base import BotClient
from app.core.bus import get_bus, reset_bus
from app.core.cache import TTLCache
from app.core.commands import CommandRegistry
from app.core.config import RuntimeSettings, ScopeEntry, Settings
from app.core.permissions import PermissionManager, permission_manager
from app.core.plugin import PluginManager
from app.core.scheduler import SchedulerService
from app.core.scopes import SCOPE_GLOBAL_GROUP, ScopePolicyService
from app.core.security import SecurityPolicy
from app.core.subscriptions import EventSubscriptionRegistry
from app.core.whitelist import GroupWhitelistService


@pytest.mark.asyncio
async def test_system_plugin_registers_commands() -> None:
    commands = CommandRegistry()
    permissions = PermissionManager()
    subscriptions = EventSubscriptionRegistry()
    scheduler = SchedulerService()
    manager = PluginManager(
        Path(__file__).resolve().parents[1] / "plugins",
        commands=commands,
        db=None,
        scheduler=scheduler,
        cache=TTLCache(),
        bot=BotClient(),
        permissions=permissions,
        services={"whitelist": GroupWhitelistService(["100"])},
        subscriptions=subscriptions,
    )
    loaded = manager.load_enabled({"system": True}, {"system": {"groups": ["100"]}})
    assert [item.name for item in loaded] == ["system"]
    for name in ("help", "whitelist", "plugins", "status", "task"):
        assert name in commands._commands
    assert await manager.unload_plugin("system") is True
    scheduler.shutdown()
    try:
        await asyncio.wait_for(get_bus().stop(clear=True), timeout=1)
    except Exception:
        pass
    reset_bus()


@pytest.mark.asyncio
async def test_help_lists_commands_dynamically() -> None:
    """/help 应动态展示注册命令（与命令注册中心互联），支持 /help <命令> 详情。"""
    commands = CommandRegistry()
    permissions = PermissionManager()
    subscriptions = EventSubscriptionRegistry()
    scheduler = SchedulerService()
    manager = PluginManager(
        Path(__file__).resolve().parents[1] / "plugins",
        commands=commands,
        db=None,
        scheduler=scheduler,
        cache=TTLCache(),
        bot=BotClient(),
        permissions=permissions,
        services={"whitelist": GroupWhitelistService([])},
        subscriptions=subscriptions,
    )
    manager.load_enabled(
        {"system": True}, {"system": {"groups": []}}
    )
    from app.core.messages import Message

    class FakeEvent:
        def __init__(self) -> None:
            self.replies: list[str] = []

        async def reply(self, content: str) -> None:
            self.replies.append(content)

    handler = commands._commands["help"].handler
    event = FakeEvent()
    await handler(event, Message(""), None)
    assert event.replies and "whitelist" in event.replies[0]
    assert "task" in event.replies[0]

    event2 = FakeEvent()
    await handler(event2, Message("whitelist"), None)
    assert event2.replies and "白名单管理" in event2.replies[0]
    assert "权限：system.status" in event2.replies[0]

    await manager.unload_plugin("system")
    scheduler.shutdown()
    try:
        await asyncio.wait_for(get_bus().stop(clear=True), timeout=1)
    except Exception:
        pass
    reset_bus()


@pytest.mark.asyncio
async def test_help_text_follows_custom_prefix() -> None:
    """非默认前缀下，帮助与用法文案应跟随实际前缀（无硬编码 /）。"""
    from app.core.messages import Message

    commands = CommandRegistry()
    commands.set_command_start(["#"])
    commands.set_security(SecurityPolicy())
    permissions = PermissionManager()
    subscriptions = EventSubscriptionRegistry()
    scheduler = SchedulerService()
    manager = PluginManager(
        Path(__file__).resolve().parents[1] / "plugins",
        commands=commands,
        db=None,
        scheduler=scheduler,
        cache=TTLCache(),
        bot=BotClient(),
        permissions=permissions,
        services={"whitelist": GroupWhitelistService([])},
        subscriptions=subscriptions,
    )
    manager.load_enabled({"system": True}, {"system": {"groups": []}})

    class FakeEvent:
        def __init__(self) -> None:
            self.replies: list[str] = []

        async def reply(self, content: str) -> None:
            self.replies.append(content)

    handler = commands._commands["help"].handler
    event = FakeEvent()
    await handler(event, Message("whitelist"), None)
    assert event.replies
    assert "#whitelist" in event.replies[0]
    assert "用法：#whitelist" in event.replies[0]

    event2 = FakeEvent()
    await handler(event2, Message(""), None)
    assert event2.replies
    assert "发送 #help" in event2.replies[0]

    await manager.unload_plugin("system")
    scheduler.shutdown()
    try:
        await asyncio.wait_for(get_bus().stop(clear=True), timeout=1)
    except Exception:
        pass
    reset_bus()


@pytest.mark.asyncio
async def test_feature_toggle_command_updates_scope() -> None:
    """群内 /功能禁用 应即时更新作用域开关（与 Web 同源）。"""
    from app.core.messages import GroupMessageEvent, Message, MessageSegment, Sender

    commands = CommandRegistry()
    commands.set_command_start(["/"])
    commands.set_security(SecurityPolicy())
    settings = Settings()
    settings.runtime = RuntimeSettings(
        scopes={SCOPE_GLOBAL_GROUP: ScopeEntry()}
    )
    policy = ScopePolicyService(settings)
    commands.set_scope_policy(policy)
    permissions = PermissionManager()
    permission_manager.upsert_principal("100", role="superadmin", scopes={"*"})
    subscriptions = EventSubscriptionRegistry()
    scheduler = SchedulerService()
    manager = PluginManager(
        Path(__file__).resolve().parents[1] / "plugins",
        commands=commands,
        db=None,
        scheduler=scheduler,
        cache=TTLCache(),
        bot=BotClient(),
        permissions=permissions,
        services={"whitelist": GroupWhitelistService([])},
        subscriptions=subscriptions,
        scope_policy=policy,
    )
    manager.load_enabled({"system": True}, {"system": {"groups": []}})
    assert "功能禁用" in commands._commands

    replies: list[str] = []
    event = GroupMessageEvent(
        bot_id="test",
        self_id="10",
        raw_event={},
        message_id="1",
        user_id="100",
        sender=Sender("100", "admin"),
        message=Message("/功能禁用 dice.roll"),
        group_id="200",
    )

    async def reply(content: str | Message | MessageSegment) -> None:
        replies.append(
            content.extract_plain_text()
            if isinstance(content, Message)
            else str(content)
        )

    event.reply = reply
    await commands.handle_message(event)
    assert policy.feature_value("group:200", "dice.roll") is False
    assert replies and "已在本群禁用功能 dice.roll" in replies[0]

    # 私聊应拒绝
    private_replies: list[str] = []
    private_event = GroupMessageEvent(
        bot_id="test",
        self_id="10",
        raw_event={},
        message_id="2",
        user_id="100",
        sender=Sender("100", "admin"),
        message=Message("/功能启用 dice.roll"),
        group_id="",
    )

    async def reply_private(content: str | Message | MessageSegment) -> None:
        private_replies.append(
            content.extract_plain_text()
            if isinstance(content, Message)
            else str(content)
        )

    private_event.reply = reply_private
    await commands.handle_message(private_event)
    assert private_replies and "仅群内可用" in private_replies[0]

    await manager.unload_plugin("system")
    scheduler.shutdown()
    try:
        await asyncio.wait_for(get_bus().stop(clear=True), timeout=1)
    except Exception:
        pass
    reset_bus()


@pytest.mark.asyncio
async def test_about_command_reports_version_and_capabilities() -> None:
    """/about 应展示框架版本与能力清单（与能力注册中心互联）。"""
    from app.core.capabilities import capability_registry

    commands = CommandRegistry()
    permissions = PermissionManager()
    subscriptions = EventSubscriptionRegistry()
    scheduler = SchedulerService()
    manager = PluginManager(
        Path(__file__).resolve().parents[1] / "plugins",
        commands=commands,
        db=None,
        scheduler=scheduler,
        cache=TTLCache(),
        bot=BotClient(),
        permissions=permissions,
        services={"whitelist": GroupWhitelistService([])},
        subscriptions=subscriptions,
        capabilities=capability_registry,
    )
    manager.load_enabled({"system": True}, {"system": {"groups": []}})
    from app import __version__
    from app.core.messages import Message

    class FakeEvent:
        def __init__(self) -> None:
            self.replies: list[str] = []

        async def reply(self, content: str) -> None:
            self.replies.append(content)

    handler = commands._commands["about"].handler
    event = FakeEvent()
    await handler(event, Message(""), None)
    assert event.replies
    assert f"OFbot 2 v{__version__}" in event.replies[0]
    assert "核心能力" in event.replies[0]
    assert "Red / OneBot" in event.replies[0]

    await manager.unload_plugin("system")
    scheduler.shutdown()
    try:
        await asyncio.wait_for(get_bus().stop(clear=True), timeout=1)
    except Exception:
        pass
    reset_bus()


@pytest.mark.asyncio
async def test_echo_command_echoes_with_sender() -> None:
    """/echo 应原样回复内容并附带发送者/群信息（开发调试用）。"""
    commands = CommandRegistry()
    permissions = PermissionManager()
    subscriptions = EventSubscriptionRegistry()
    scheduler = SchedulerService()
    manager = PluginManager(
        Path(__file__).resolve().parents[1] / "plugins",
        commands=commands,
        db=None,
        scheduler=scheduler,
        cache=TTLCache(),
        bot=BotClient(),
        permissions=permissions,
        services={"whitelist": GroupWhitelistService([])},
        subscriptions=subscriptions,
    )
    manager.load_enabled({"system": True}, {"system": {"groups": []}})
    from app.core.messages import Message

    class FakeEvent:
        user_id = "100"
        group_id = "2"

        def __init__(self) -> None:
            self.replies: list[str] = []

        async def reply(self, content: str) -> None:
            self.replies.append(content)

    handler = commands._commands["echo"].handler
    event = FakeEvent()
    await handler(event, Message("hello 世界"), None)
    assert event.replies
    assert "回声" in event.replies[0]
    assert "hello 世界" in event.replies[0]
    assert "来自：100（群 2）" in event.replies[0]

    await manager.unload_plugin("system")
    scheduler.shutdown()
    try:
        await asyncio.wait_for(get_bus().stop(clear=True), timeout=1)
    except Exception:
        pass
    reset_bus()


@pytest.mark.asyncio
async def test_plugin_context_developer_apis() -> None:
    """PluginContext 开发者接口：register_webhook / schedule_once / dispatch。"""
    from app.core.events import BotConnected
    from app.services.webhook import WebhookService

    try:
        await asyncio.wait_for(get_bus().stop(clear=True), timeout=1)
    except Exception:
        pass
    reset_bus()

    commands = CommandRegistry()
    permissions = PermissionManager()
    subscriptions = EventSubscriptionRegistry()
    scheduler = SchedulerService()
    webhooks = WebhookService()
    manager = PluginManager(
        Path(__file__).resolve().parents[1] / "plugins",
        commands=commands,
        db=None,
        scheduler=scheduler,
        cache=TTLCache(),
        bot=BotClient(),
        permissions=permissions,
        services={
            "whitelist": GroupWhitelistService([]),
            "webhook": webhooks,
        },
        subscriptions=subscriptions,
    )
    manager.load_enabled({"system": True}, {"system": {"groups": []}})
    ctx = manager.loaded["system"].context

    # register_webhook
    ctx.register_webhook("plugin_hook", {"event": "x"})
    assert "plugin_hook" in webhooks.webhooks
    assert webhooks.filters["plugin_hook"] == {"event": "x"}

    # schedule_once
    async def once_task() -> None:
        return None

    job_id = ctx.schedule_once(60, once_task)
    assert scheduler.scheduler.get_job(job_id) is not None
    assert job_id in scheduler._plugin_jobs.get("system", set())

    # dispatch → 订阅回调
    received: list[str] = []
    ctx.subscribe(BotConnected, lambda event: received.append(event.bot_id))
    ctx.dispatch(BotConnected(bot_id="b1"))
    await asyncio.sleep(0.15)
    assert received == ["b1"]

    await manager.unload_plugin("system")
    scheduler.shutdown()
    try:
        await asyncio.wait_for(get_bus().stop(clear=True), timeout=1)
    except Exception:
        pass
    reset_bus()
