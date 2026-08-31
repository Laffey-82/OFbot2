from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.adapters.base import BotClient
from app.core.bus import get_bus, reset_bus
from app.core.cache import TTLCache
from app.core.commands import CommandRegistry
from app.core.permissions import PermissionManager
from app.core.plugin import PluginManager
from app.core.scheduler import SchedulerService
from app.core.subscriptions import EventSubscriptionRegistry


@pytest.mark.asyncio
async def test_plugin_load_and_unload_cleans_commands() -> None:
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
        services={},
        subscriptions=subscriptions,
    )

    loaded = manager.load_enabled({"template": True}, {"template": {}})
    assert [item.name for item in loaded] == ["template"]
    assert commands._commands.get("ping") is not None

    assert await manager.reload_plugin("template") is True
    assert commands._commands.get("ping") is not None
    active_subscriptions = [
        entry
        for entries in subscriptions._entries.values()
        for entry in entries
        if entry.active
    ]
    assert len(active_subscriptions) == 1

    assert await manager.unload_plugin("template") is True
    assert commands._commands.get("ping") is None
    assert all(
        not entry.active
        for entries in subscriptions._entries.values()
        for entry in entries
    )
    scheduler.shutdown()
    try:
        await asyncio.wait_for(get_bus().stop(clear=True), timeout=1)
    except Exception:
        pass
    await reset_bus()
