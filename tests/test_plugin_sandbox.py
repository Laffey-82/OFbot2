from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from app.core.bus import get_bus, reset_bus
from app.core.cache import TTLCache
from app.core.commands import CommandRegistry
from app.core.messages import GroupMessageEvent, Message, MessageSegment, Sender
from app.core.permissions import permission_manager
from app.core.plugin import PluginManager
from app.core.scheduler import SchedulerService
from app.core.security import SecurityPolicy
from app.core.subscriptions import EventSubscriptionRegistry
from app.db.base import get_engine, init_db, reset_db_engine
from app.services.records import (
    FieldSchema,
    RecordService,
    RecordTypeSchema,
    SchemaRegistry,
)


def _write_plugin(root: Path, *, gated_call: bool = False) -> Path:
    plugin_dir = root / "sandbox_demo"
    plugin_dir.mkdir()
    manifest = {
        "name": "sandbox_demo",
        "api_version": 1,
        "version": "1.0.0",
        "sandbox": "process",
        "sandbox_policy": {"allow_services": ["records"]},
        "features": [
            {
                "id": "ping",
                "label": "沙箱 ping",
                "enable_on_default": True,
                "commands": [
                    {
                        "name": "sping",
                        "handler": "handlers.ping_command",
                        "permission": "bot.command",
                        "description": "沙箱回复",
                    }
                ],
            }
        ],
    }
    (plugin_dir / "plugin.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    (plugin_dir / "__init__.py").write_text(
        "from . import handlers  # noqa: F401\n"
        "from app.core.plugin import Plugin\n\n"
        "_CTX = None\n\n"
        "class SandboxDemoPlugin(Plugin):\n"
        "    def setup(self, ctx):\n"
        "        global _CTX\n"
        "        _CTX = ctx\n"
        "\n"
        "def create_plugin():\n"
        "    return SandboxDemoPlugin()\n",
        encoding="utf-8",
    )
    handler_body = (
        "import plugins.sandbox_demo as plugin_mod\n"
        "import json\n"
        "\n"
        "async def ping_command(event, args, context):\n"
        "    text = args.extract_plain_text().strip()\n"
        "    created = await plugin_mod._CTX.records.create(\n"
        "        'note', {'title': text or 'empty'}\n"
        "    )\n"
        "    await event.reply(f'pong:{text}:{created.id}')\n"
        + (
            "    try:\n"
            "        await plugin_mod._CTX.files.list()\n"
            "        await event.reply('files:allowed')\n"
            "    except Exception as exc:\n"
            "        await event.reply('files:denied')\n"
            if gated_call
            else ""
        )
    )
    (plugin_dir / "handlers.py").write_text(handler_body, encoding="utf-8")
    return plugin_dir


def _make_event(text: str) -> GroupMessageEvent:
    replies: list[str] = []
    event = GroupMessageEvent(
        bot_id="test",
        self_id="10",
        raw_event={},
        message_id="1",
        user_id="1",
        sender=Sender("1", "tester"),
        message=Message(text),
        group_id="2",
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


def _build_manager(root: Path) -> PluginManager:
    commands = CommandRegistry()
    commands.set_command_start(["/"])
    commands.set_security(SecurityPolicy())
    permission_manager.upsert_principal("1", role="superadmin", scopes={"*"})
    schemas = SchemaRegistry()
    schemas.register(
        RecordTypeSchema("note", [FieldSchema("title", "string", True)])
    )
    return PluginManager(
        root,
        commands=commands,
        db=None,
        scheduler=SchedulerService(),
        cache=TTLCache(),
        bot=type("Bot", (), {"send_group_message": _noop, "send_private_message": _noop})(),
        permissions=permission_manager,
        services={},
        subscriptions=EventSubscriptionRegistry(),
        records=RecordService(schemas),
    ), commands


async def _noop(*args, **kwargs):
    return True


@pytest.mark.asyncio
async def test_process_sandbox_plugin_command_and_capability() -> None:
    """process 插件可加载、收命令、回执，且能力调用经白名单执行。"""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        root = Path(tmp_dir)
        _write_plugin(root)
        await reset_db_engine()
        engine = get_engine(f"sqlite+aiosqlite:///{(root / 's.db').as_posix()}")
        await init_db(f"sqlite+aiosqlite:///{(root / 's.db').as_posix()}")
        manager, commands = _build_manager(root)
        loaded = manager.load_enabled({"sandbox_demo": True}, {"sandbox_demo": {}})
        assert [item.name for item in loaded] == ["sandbox_demo"]
        await manager.start_plugin("sandbox_demo")

        event = _make_event("/sping hello")
        assert await commands.handle_message(event) is True
        assert event.replies and event.replies[0].startswith("pong:hello:")

        await manager.unload_plugin("sandbox_demo")
        await engine.dispose()
        await reset_db_engine()
        try:
            await get_bus().stop(clear=True)
        except Exception:
            pass
        await reset_bus()


@pytest.mark.asyncio
async def test_process_sandbox_denies_gated_capability() -> None:
    """白名单外能力（files）被拒绝，异常可回传插件侧。"""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        root = Path(tmp_dir)
        _write_plugin(root, gated_call=True)
        await reset_db_engine()
        engine = get_engine(f"sqlite+aiosqlite:///{(root / 's.db').as_posix()}")
        await init_db(f"sqlite+aiosqlite:///{(root / 's.db').as_posix()}")
        manager, commands = _build_manager(root)
        manager.load_enabled({"sandbox_demo": True}, {"sandbox_demo": {}})
        await manager.start_plugin("sandbox_demo")

        event = _make_event("/sping hello")
        assert await commands.handle_message(event) is True
        assert any("files:denied" in r for r in event.replies)

        await manager.unload_plugin("sandbox_demo")
        await engine.dispose()
        await reset_db_engine()
        try:
            await get_bus().stop(clear=True)
        except Exception:
            pass
        await reset_bus()
