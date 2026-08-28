from __future__ import annotations

import re
import tempfile
from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_roles_web_flow() -> None:
    from httpx import ASGITransport, AsyncClient

    from app.core.config import load_settings
    from app.db.base import get_engine, init_db, reset_db_engine
    from app.web.app import create_app, ensure_default_admin

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        settings = load_settings()
        settings.config_path = str(Path(tmp_dir) / "config.yaml")
        settings.database.url = (
            f"sqlite+aiosqlite:///{(Path(tmp_dir) / 'w.db').as_posix()}"
        )
        reset_db_engine()
        engine = get_engine(settings.database.url)
        await init_db(settings.database.url)
        await ensure_default_admin(settings)
        app = create_app(settings, plugin_manager=None)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t"
        ) as client:
            await client.post(
                "/login",
                data={"username": "admin", "password": "admin"},
            )
            page = await client.get("/roles")
            assert page.status_code == 200
            match = re.search(
                r'name="csrf_token" value="([^"]+)"', page.text
            )
            assert match
            csrf = match.group(1)
            response = await client.post(
                "/roles/set",
                data={"csrf_token": csrf, "user_id": "10001", "role": "admin"},
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert settings.runtime.user_roles.get("10001") == "admin"
            removed = await client.post(
                "/roles/remove",
                data={"csrf_token": csrf, "user_id": "10001"},
                follow_redirects=False,
            )
            assert removed.status_code == 303
            assert "10001" not in settings.runtime.user_roles
        await engine.dispose()
        reset_db_engine()


@pytest.mark.asyncio
async def test_plugin_state_roundtrip() -> None:
    import tempfile

    from app.db.base import get_engine, init_db, reset_db_engine
    from app.services.plugin_state import get_plugin_states, save_plugin_state

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        url = f"sqlite+aiosqlite:///{(Path(tmp_dir) / 's.db').as_posix()}"
        reset_db_engine()
        engine = get_engine(url)
        await init_db(url)
        await save_plugin_state("demo", "loaded", version="1.0.0")
        await save_plugin_state("demo", "error", error="boom")
        states = await get_plugin_states()
        assert states["demo"]["state"] == "error"
        assert states["demo"]["error"] == "boom"
        await engine.dispose()
        reset_db_engine()


def test_capability_setup_registers_builtins() -> None:
    from app.core.capabilities import capability_registry
    from app.services.capability_setup import register_builtin_capabilities

    register_builtin_capabilities()
    for name in (
        "records",
        "state_machine",
        "aggregation",
        "audit",
        "ai",
        "workflow",
        "webhook",
        "alerts",
        "export",
        "scheduler",
        "storage",
        "files",
    ):
        assert capability_registry.has(name), f"缺少能力 {name}"


@pytest.mark.asyncio
async def test_example_ai_plugin_declarative() -> None:
    from pathlib import Path

    from app.adapters.base import BotClient
    from app.core.bus import get_bus, reset_bus
    from app.core.cache import TTLCache
    from app.core.commands import CommandRegistry
    from app.core.permissions import PermissionManager
    from app.core.plugin import PluginManager
    from app.core.scheduler import SchedulerService
    from app.core.subscriptions import EventSubscriptionRegistry

    commands = CommandRegistry()
    manager = PluginManager(
        Path(__file__).resolve().parents[1] / "plugins",
        commands=commands,
        db=None,
        scheduler=SchedulerService(),
        cache=TTLCache(),
        bot=BotClient(),
        permissions=PermissionManager(),
        services={},
        subscriptions=EventSubscriptionRegistry(),
    )
    loaded = manager.load_enabled(
        {"example_ai": True}, {"example_ai": {}}
    )
    assert [item.name for item in loaded] == ["example_ai"]
    command = commands.get_commands("example_ai")
    assert command and command[0].name == "ask"
    assert command[0].feature_id == "example_ai.ask"
    await manager.unload_plugin("example_ai")
    try:
        await get_bus().stop(clear=True)
    except Exception:
        pass
    reset_bus()
