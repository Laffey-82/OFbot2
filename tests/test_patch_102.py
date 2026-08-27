from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.commands import CommandRegistry
from app.core.parsing import (
    ParamSpec,
    SubcommandSpec,
    resolve_subcommand,
    tokenize_args,
)


def test_tokenize_preserves_windows_backslashes() -> None:
    assert tokenize_args(r"C:\Users\a\b.txt") == [r"C:\Users\a\b.txt"]
    assert tokenize_args(r"路径 C:\temp") == ["路径", r"C:\temp"]


def test_tokenize_quotes_still_group() -> None:
    assert tokenize_args('a "b c" d="e f"') == ["a", "b c", "d=e f"]
    assert tokenize_args("'x y' z") == ["x y", "z"]
    assert tokenize_args("") == []


def test_subcommand_dotted_token() -> None:
    subs = [
        SubcommandSpec(
            name="add",
            aliases=["新增"],
            params=[ParamSpec(name="n", type="int", required=True)],
        )
    ]
    name, rest, err = resolve_subcommand("add.info 50", subs)
    assert (name, rest, err) == ("add", "info 50", None)
    name, rest, err = resolve_subcommand("新增.info", subs)
    assert name == "add" and err is None
    name, rest, err = resolve_subcommand("add 5", subs)
    assert (name, rest, err) == ("add", "5", None)
    name, _, err = resolve_subcommand("del 5", subs)
    assert name is None and "未知子命令" in err


def test_command_conflict_detection() -> None:
    registry = CommandRegistry()

    async def handler(event, args, ctx) -> None:
        pass

    registry.register("demo", handler, plugin_name="plugin_a")
    registry.register("demo2", handler, plugin_name="plugin_a", aliases={"d2"})
    assert registry.check_conflict("demo", set(), "plugin_b") == "plugin_a"
    assert registry.check_conflict("d2", set(), "plugin_b") == "plugin_a"
    assert registry.check_conflict("demo3", {"d3"}, "plugin_b") is None
    # 同插件自身不算冲突
    assert registry.check_conflict("demo", set(), "plugin_a") is None


@pytest.mark.asyncio
async def test_plugin_load_conflict_fails_plugin() -> None:
    import tempfile

    from app.adapters.base import BotClient
    from app.core.bus import get_bus, reset_bus
    from app.core.cache import TTLCache
    from app.core.plugin import PluginManager
    from app.core.scheduler import SchedulerService
    from app.core.subscriptions import EventSubscriptionRegistry

    def make_plugin(dir_path: Path, name: str) -> None:
        (dir_path / name).mkdir(parents=True)
        (dir_path / name / "plugin.json").write_text(
            json.dumps(
                {
                    "name": name,
                    "api_version": 1,
                    "version": "1.0.0",
                    "features": [
                        {
                            "id": "main",
                            "commands": [
                                {
                                    "name": "conflict_cmd",
                                    "handler": "handlers.cmd",
                                }
                            ],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (dir_path / name / "__init__.py").write_text(
            "from app.core.plugin import Plugin\n"
            "from . import handlers\n"
            f"class P{name}(Plugin):\n"
            "    def setup(self, ctx):\n"
            "        handlers.setup(ctx)\n"
            f"def create_plugin():\n    return P{name}()\n",
            encoding="utf-8",
        )
        (dir_path / name / "handlers.py").write_text(
            "from app.core.plugin import PluginContext\n"
            "_ctx = None\n"
            "def setup(ctx):\n"
            "    global _ctx\n    _ctx = ctx\n"
            "async def cmd(event, args, command_ctx):\n"
            "    pass\n",
            encoding="utf-8",
        )

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        plugins_dir = Path(tmp_dir)
        make_plugin(plugins_dir, "plugin_a")
        make_plugin(plugins_dir, "plugin_b")
        commands = CommandRegistry()
        manager = PluginManager(
            plugins_dir,
            commands=commands,
            db=None,
            scheduler=SchedulerService(),
            cache=TTLCache(),
            bot=BotClient(),
            permissions=__import__(
                "app.core.permissions", fromlist=["PermissionManager"]
            ).PermissionManager(),
            services={},
            subscriptions=EventSubscriptionRegistry(),
        )
        loaded = manager.load_enabled(
            {"plugin_a": True, "plugin_b": True}, {}
        )
        assert [item.name for item in loaded] == ["plugin_a"]
        assert manager.loaded["plugin_a"].state == "loaded"
        try:
            await get_bus().stop(clear=True)
        except Exception:
            pass
        reset_bus()


@pytest.mark.asyncio
async def test_safe_reply_unbound_event() -> None:
    from app.core.commands import _safe_reply
    from app.core.messages import GroupMessageEvent, Message, Sender

    event = GroupMessageEvent(
        bot_id="t",
        self_id="10",
        raw_event={},
        message_id="1",
        user_id="1",
        sender=Sender("1", "u"),
        message=Message("x"),
        group_id="1",
    )
    # reply 未绑定：不抛异常
    await _safe_reply(event, "hello")

    replies: list[str] = []

    async def reply(text: str) -> None:
        replies.append(text)

    event.reply = reply
    await _safe_reply(event, "hi")
    assert replies == ["hi"]
