from __future__ import annotations

import asyncio
import inspect
import json
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.bus import get_bus
from app.core.cache import TTLCache
from app.core.commands import CommandRegistry
from app.core.permissions import PermissionManager
from app.core.plugin import (
    PluginContext,
    PluginManager,
    PluginManifest,
)
from app.core.scheduler import SchedulerService
from app.core.subscriptions import EventSubscriptionRegistry


def _noop(*args: Any, **kwargs: Any) -> Any:
    return True


def _make_manager(
    tmp: Path | None = None,
) -> PluginManager:
    plugins_dir = tmp or Path(tempfile.mkdtemp())
    return PluginManager(
        plugins_dir,
        commands=CommandRegistry(),
        db=None,
        scheduler=SchedulerService(),
        cache=TTLCache(),
        bot=type("Bot", (), {"send_group_message": _noop, "send_private_message": _noop})(),
        permissions=PermissionManager(),
        services={},
        subscriptions=EventSubscriptionRegistry(),
    )


def _write_simple_plugin(root: Path, name: str = "testplugin") -> Path:
    plugin_dir = root / name
    plugin_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": name,
        "api_version": 1,
        "version": "1.0.0",
        "entry": "create_plugin",
        "commands": [
            {
                "name": "tping",
                "handler": "handle_ping",
                "permission": "bot.command",
            }
        ],
    }
    (plugin_dir / "plugin.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    (plugin_dir / "__init__.py").write_text(
        "from app.core.plugin import Plugin\n\n"
        "class _P(Plugin):\n"
        "    def setup(self, ctx): pass\n\n"
        "async def handle_ping(event, args, context):\n"
        "    await event.reply('pong')\n\n"
        "def create_plugin():\n"
        "    return _P()\n",
        encoding="utf-8",
    )
    return plugin_dir


def _write_failing_plugin(root: Path, name: str = "badplugin") -> Path:
    plugin_dir = root / name
    plugin_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": name,
        "api_version": 1,
        "version": "1.0.0",
        "entry": "create_plugin",
    }
    (plugin_dir / "plugin.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    (plugin_dir / "__init__.py").write_text(
        "from app.core.plugin import Plugin\n\n"
        "class _P(Plugin):\n"
        "    def setup(self, ctx): pass\n\n"
        "def create_plugin():\n"
        "    raise RuntimeError('intentional load failure')\n",
        encoding="utf-8",
    )
    return plugin_dir


def _write_setup_fail_plugin(root: Path, name: str = "setupfail") -> Path:
    plugin_dir = root / name
    plugin_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": name,
        "api_version": 1,
        "version": "1.0.0",
        "entry": "create_plugin",
    }
    (plugin_dir / "plugin.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    (plugin_dir / "__init__.py").write_text(
        "from app.core.plugin import Plugin\n\n"
        "class _P(Plugin):\n"
        "    def setup(self, ctx): raise RuntimeError('setup boom')\n\n"
        "def create_plugin():\n"
        "    return _P()\n",
        encoding="utf-8",
    )
    return plugin_dir


# ── Fix 1: reload_plugin rollback on failure ──────────────────────────────


@pytest.mark.asyncio
async def test_reload_plugin_rollback_on_load_failure() -> None:
    """reload_plugin 在 load 失败时应回滚到旧插件，旧插件仍可用。"""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = Path(tmp)
        plugin_dir = _write_simple_plugin(root)
        manager = _make_manager(root)

        loaded = manager.load_enabled(
            {"testplugin": True}, {"testplugin": {}}
        )
        assert len(loaded) == 1
        assert manager.commands._commands.get("tping") is not None

        (plugin_dir / "__init__.py").write_text(
            "from app.core.plugin import Plugin\n\n"
            "class _P(Plugin):\n"
            "    def setup(self, ctx): pass\n\n"
            "def create_plugin():\n"
            "    raise RuntimeError('new version broken')\n",
            encoding="utf-8",
        )

        result = await manager.reload_plugin("testplugin")
        assert result is False
        assert "testplugin" in manager.loaded
        assert manager.commands._commands.get("tping") is not None


# ── Fix 2: load_plugin cleanup on failure ────────────────────────────────


@pytest.mark.asyncio
async def test_load_plugin_cleanup_on_setup_failure() -> None:
    """setup 失败时不应残留 sys.modules 条目。"""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = Path(tmp)
        _write_setup_fail_plugin(root)
        manager = _make_manager(root)

        with pytest.raises(RuntimeError, match="setup boom"):
            manager.load_plugin("setupfail", root / "setupfail")

        assert "plugins.setupfail" not in sys.modules
        assert "setupfail" not in manager.loaded


@pytest.mark.asyncio
async def test_load_plugin_cleanup_on_factory_failure() -> None:
    """factory 失败时不应残留 sys.modules 条目。"""
    import sys

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = Path(tmp)
        _write_failing_plugin(root)
        manager = _make_manager(root)

        with pytest.raises(RuntimeError, match="intentional load failure"):
            manager.load_plugin("badplugin", root / "badplugin")

        assert "plugins.badplugin" not in sys.modules
        assert "badplugin" not in manager.loaded


# ── Fix 3a: IPC stop() sends shutdown before _closed ────────────────────


@pytest.mark.asyncio
async def test_ipc_stop_sends_shutdown_before_terminating() -> None:
    """stop() 应在设置 _closed 前发送 shutdown。"""
    from app.core.plugin_ipc import PluginProcessBridge

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = Path(tmp)
        bridge = PluginProcessBridge(
            name="test",
            plugin_dir=root,
            manifest=PluginManifest(name="test", api_version=1),
            config={},
            context=MagicMock(),
            request_timeout=1.0,
        )
        mock_proc = AsyncMock()
        mock_proc.returncode = None
        mock_proc.stdin = AsyncMock()
        mock_proc.stdout = AsyncMock()
        mock_proc.wait = AsyncMock(return_value=0)
        bridge._proc = mock_proc
        bridge._writer = mock_proc.stdin

        with patch.object(bridge, "request", new_callable=AsyncMock) as mock_req:
            await bridge.stop()
            mock_req.assert_called_with("shutdown", timeout=3.0)

        assert bridge._closed is True


# ── Fix 3b: worker json.loads tolerance ─────────────────────────────────


@pytest.mark.asyncio
async def test_worker_read_loop_handles_malformed_json() -> None:
    """worker _read_loop 不因坏 JSON 崩溃。"""
    import app.core.plugin_worker as pw

    pw._pending.clear()
    pw._MODULE = MagicMock()
    pw._SHUTDOWN = asyncio.Event()

    lines = [
        b'{"id": 1, "result": {"ok": true}}\n',
        b'NOT_JSON\n',
        b'{"id": 2, "result": {"ok": true}}\n',
    ]

    import concurrent.futures

    def fake_run_in_executor(executor, func, *args):
        fut = concurrent.futures.Future()
        try:
            result = func(*args) if args else func()
            fut.set_result(result)
        except Exception as e:
            fut.set_exception(e)
        return asyncio.ensure_future(asyncio.wrap_future(fut))

    f1: asyncio.Future[Any] = asyncio.get_event_loop().create_future()
    f2: asyncio.Future[Any] = asyncio.get_event_loop().create_future()
    pw._pending[1] = f1
    pw._pending[2] = f2

    loop = asyncio.get_event_loop()
    original_run_in_executor = loop.run_in_executor

    call_count = 0

    def patched_run_in_executor(executor, func, *args):
        nonlocal call_count
        if call_count < len(lines):
            line = lines[call_count]
            call_count += 1
            fut = concurrent.futures.Future()
            fut.set_result(line)
            return asyncio.ensure_future(asyncio.wrap_future(fut))
        fut = concurrent.futures.Future()
        fut.set_result(b"")
        return asyncio.ensure_future(asyncio.wrap_future(fut))

    loop.run_in_executor = patched_run_in_executor
    try:
        await pw._read_loop()
    finally:
        loop.run_in_executor = original_run_in_executor

    assert f1.result() == {"ok": True}
    assert f2.result() == {"ok": True}


# ── Fix 3c: worker ctx handler signature check ──────────────────────────


@pytest.mark.asyncio
async def test_worker_resolve_and_run_injects_ctx() -> None:
    """handler 声明 ctx 参数时，worker 应注入 RemoteContext。"""
    import app.core.plugin_worker as pw
    from app.core.plugin_worker import RemoteContext

    captured: dict[str, Any] = {}

    class FakeModule:
        @staticmethod
        async def handler_with_ctx(event, args_msg, context, *, ctx=None):
            captured["ctx"] = ctx
            captured["event"] = event

    pw._MODULE = FakeModule
    params = {
        "handler": "handler_with_ctx",
        "args": [{"__message__": None}, "plain_text", {}],
    }
    await pw._resolve_and_run(FakeModule, params)
    assert isinstance(captured.get("ctx"), RemoteContext)


# ── Fix 4: background tasks started and cancelled ────────────────────────


@pytest.mark.asyncio
async def test_register_task_started_and_cancelled() -> None:
    """ctx.register_task 注册的协程应在 load 后启动，unload 时 cancel。"""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = Path(tmp)
        plugin_dir = root / "taskplugin"
        plugin_dir.mkdir()
        manifest = {
            "name": "taskplugin",
            "api_version": 1,
            "version": "1.0.0",
            "entry": "create_plugin",
        }
        (plugin_dir / "plugin.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )
        (plugin_dir / "__init__.py").write_text(
            "import asyncio\n"
            "from app.core.plugin import Plugin\n\n"
            "_started = False\n"
            "_stopped = False\n\n"
            "class _P(Plugin):\n"
            "    def setup(self, ctx):\n"
            "        async def bg():\n"
            "            global _started\n"
            "            _started = True\n"
            "            await asyncio.sleep(3600)\n"
            "        ctx.register_task(bg)\n\n"
            "def create_plugin():\n"
            "    return _P()\n",
            encoding="utf-8",
        )
        manager = _make_manager(root)
        manager.load_enabled({"taskplugin": True}, {"taskplugin": {}})

        assert len(manager.loaded["taskplugin"].background_tasks) == 1
        task = manager.loaded["taskplugin"].background_tasks[0]
        assert not task.done()

        await manager.unload_plugin("taskplugin")
        assert task.cancelled()
        assert "taskplugin" not in manager.loaded


# ── Fix 5: unsubscribe_plugin deletes entries ────────────────────────────


def test_unsubscribe_plugin_removes_entries() -> None:
    """unsubscribe_plugin 应删除条目而非仅置 active=False。"""
    from app.core.subscriptions import EventSubscriptionRegistry

    reg = EventSubscriptionRegistry()

    class DummyEvent:
        pass

    reg.subscribe(DummyEvent, lambda e: None, "pluginA")
    reg.subscribe(DummyEvent, lambda e: None, "pluginB")
    reg.subscribe(DummyEvent, lambda e: None, "pluginA")

    removed = reg.unsubscribe_plugin("pluginA")
    assert removed == 2
    assert DummyEvent not in reg._entries or not any(
        e.plugin_name == "pluginA"
        for e in reg._entries.get(DummyEvent, [])
    )
    remaining = reg._entries.get(DummyEvent, [])
    assert len(remaining) == 1
    assert remaining[0].plugin_name == "pluginB"


# ── Fix 6: schedule_once uniqueness ─────────────────────────────────────


def test_schedule_once_job_id_unique() -> None:
    """schedule_once 应生成唯一 job_id（含 uuid4 后缀）。"""
    ctx = PluginContext(
        name="test",
        config={},
        bus=get_bus(),
        commands=CommandRegistry(),
        db=None,
        scheduler=SchedulerService(),
        cache=TTLCache(),
        bot=None,
        permissions=PermissionManager(),
        services={},
        subscriptions=EventSubscriptionRegistry(),
    )
    id1 = ctx.schedule_once(10, lambda: None)
    id2 = ctx.schedule_once(10, lambda: None)
    assert id1 != id2
    assert len(id1.split(".")) >= 4


# ── Fix 7: field_validator raises ValueError ────────────────────────────


@pytest.mark.asyncio
async def test_declared_task_target_validator_raises_valueerror() -> None:
    """DeclaredTask.target 验证应抛出 ValueError 而非 TypeError。"""
    from pydantic import ValidationError

    from app.core.plugin import DeclaredTask

    with pytest.raises(ValidationError) as exc_info:
        DeclaredTask(id="t1", handler="h", target="invalid_target")
    errors = str(exc_info.value)
    assert "validation error" in errors.lower()
    assert "task target" in errors.lower() or "取值非法" in errors


# ── Fix 8: render_text_image is async ──────────────────────────────────


@pytest.mark.asyncio
async def test_render_text_image_is_async() -> None:
    """render_text_image 应是 async 方法。"""
    ctx = PluginContext(
        name="test",
        config={},
        bus=get_bus(),
        commands=CommandRegistry(),
        db=None,
        scheduler=SchedulerService(),
        cache=TTLCache(),
        bot=None,
        permissions=PermissionManager(),
        services={},
        subscriptions=EventSubscriptionRegistry(),
    )
    assert inspect.iscoroutinefunction(ctx.render_text_image)
