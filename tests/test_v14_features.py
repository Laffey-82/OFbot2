"""v1.4 新特性测试：rest 参数、点分命令、max_arg_length、ctx 注入、权限映射、
指令冲突解决、任务模板/受管任务、target 列表、records 过滤、配置校验、文本转图。"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from app.adapters.base import BotClient
from app.core.bus import get_bus, reset_bus
from app.core.cache import TTLCache
from app.core.commands import CommandRegistry
from app.core.config import Settings
from app.core.messages import GroupMessageEvent, Message, Sender
from app.core.parsing import ParamSpec, SubcommandSpec, bind_params, build_usage
from app.core.permissions import PermissionManager
from app.core.plugin import PluginContext, PluginManager
from app.core.plugin_tasks import PluginTaskEntry, PluginTaskRegistry
from app.core.rules import RuleRegistry
from app.core.scheduler import SchedulerService
from app.core.scopes import ScopePolicyService
from app.core.subscriptions import EventSubscriptionRegistry
from app.db.base import get_engine, init_db, reset_db_engine
from app.services.records import (
    FieldSchema,
    RecordService,
    RecordTypeSchema,
    SchemaRegistry,
)
from app.web.routers.plugins import _validate_config_schema

# ---------------------------------------------------------------- rest 参数

def test_rest_param_binding() -> None:
    params = [
        ParamSpec(name="head", type="string", required=True),
        ParamSpec(name="content", type="rest"),
    ]
    bound, err = bind_params("hello a b c", params)
    assert err is None
    assert bound == {"head": "hello", "content": "a b c"}
    bound2, err = bind_params('hello "x y" z', params)
    assert bound2 == {"head": "hello", "content": "x y z"}
    usage = build_usage("echo", params, [])
    assert "content…" in usage


def test_rest_param_missing_required() -> None:
    params = [ParamSpec(name="content", type="rest", required=True)]
    _bound, err = bind_params("", params)
    assert err is not None and "缺少必填参数" in err


# ---------------------------------------------------------------- 命令注册

def test_dotted_command_name_lookup() -> None:
    registry = CommandRegistry()

    async def handler(event, args, command_ctx) -> None:
        pass

    registry.register("order_ledger.分账", handler, plugin_name="order_ledger")
    assert registry.parse("/order_ledger.分账 3") == ("order_ledger.分账", "3")
    # 未注册点分名时回退到分段命令
    registry.register(
        "order",
        handler,
        plugin_name="order",
        subcommands=[SubcommandSpec(name="add")],
    )
    assert registry.parse("/order.add info 50") == ("order", "add info 50")


async def test_max_arg_length_rejects_long_args() -> None:
    registry = CommandRegistry()

    async def handler(event, args, command_ctx) -> None:
        pass

    registry.register("echo", handler, plugin_name="test", max_arg_length=10)
    replies: list[str] = []

    async def reply(text) -> None:
        replies.append(str(text))

    event = GroupMessageEvent(
        bot_id="b",
        self_id="1",
        raw_event={},
        message_id="1",
        user_id="100",
        sender=Sender("100", "u"),
        message=Message("/echo " + "a" * 20),
        group_id="200",
    )
    event.reply = reply
    assert await registry.handle_message(event) is True
    assert replies and "参数过长" in replies[-1]


async def test_handler_ctx_injection() -> None:
    registry = CommandRegistry()
    seen: list = []

    async def handler(event, args, command_ctx, ctx=None) -> None:
        seen.append(ctx)

    registry.register("inject", handler, plugin_name="test")
    registry.set_plugin_context_resolver(lambda name: "CTX" if name == "test" else None)

    async def reply(text) -> None:
        pass

    event = GroupMessageEvent(
        bot_id="b",
        self_id="1",
        raw_event={},
        message_id="1",
        user_id="100",
        sender=Sender("100", "u"),
        message=Message("/inject"),
        group_id="200",
    )
    event.reply = reply
    await registry.handle_message(event)
    assert seen == ["CTX"]


# ---------------------------------------------------------------- 插件管理

def _make_plugin_dir(
    base: Path,
    name: str,
    *,
    commands: list[dict],
    permissions: list[str] | None = None,
    permission_roles: dict | None = None,
    conflicts: dict | None = None,
    tasks: list[dict] | None = None,
) -> None:
    (base / name).mkdir(parents=True)
    manifest: dict = {
        "name": name,
        "api_version": 1,
        "version": "1.0.0",
        "features": [{"id": "main", "commands": commands}],
    }
    if permissions is not None:
        manifest["permissions"] = permissions
    if permission_roles is not None:
        manifest["permission_roles"] = permission_roles
    if conflicts is not None:
        manifest["conflicts"] = conflicts
    if tasks is not None:
        manifest["features"][0]["tasks"] = tasks
    (base / name / "plugin.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    (base / name / "__init__.py").write_text(
        "from app.core.plugin import Plugin\n"
        "from . import handlers\n"
        f"class P{name}(Plugin):\n"
        "    def setup(self, ctx):\n"
        "        handlers.setup(ctx)\n"
        f"def create_plugin():\n    return P{name}()\n",
        encoding="utf-8",
    )
    (base / name / "handlers.py").write_text(
        "from app.core.plugin import PluginContext\n"
        "_ctx = None\n"
        "def setup(ctx):\n"
        "    global _ctx\n    _ctx = ctx\n"
        "async def cmd(event, args, command_ctx):\n"
        "    pass\n"
        "async def task_handler():\n"
        "    pass\n",
        encoding="utf-8",
    )


def _manager(plugins_dir: Path, *, permissions: PermissionManager | None = None):
    return PluginManager(
        plugins_dir,
        commands=CommandRegistry(),
        db=None,
        scheduler=SchedulerService(),
        cache=TTLCache(),
        bot=BotClient(),
        permissions=permissions or PermissionManager(),
        services={},
        subscriptions=EventSubscriptionRegistry(),
        task_registry=PluginTaskRegistry(SchedulerService()),
        rules=RuleRegistry(),
    )


@pytest.mark.asyncio
async def test_permission_roles_mapping() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        base = Path(tmp)
        _make_plugin_dir(
            base,
            "admin_plugin",
            commands=[{"name": "admin_cmd", "handler": "handlers.cmd", "permission": "admin_plugin.admin"}],
            permissions=["admin_plugin.admin"],
            permission_roles={"admin_plugin.admin": ["admin"]},
        )
        permissions = PermissionManager()
        manager = _manager(base, permissions=permissions)
        manager.load_enabled({"admin_plugin": True}, {})
        assert permissions.has_permission("u1", "admin_plugin.admin") is False
        permissions.upsert_principal("u2", role="admin", scopes={"*"})
        assert permissions.has_permission("u2", "admin_plugin.admin") is True
        await get_bus().stop(clear=True)
        await reset_bus()


@pytest.mark.asyncio
async def test_conflict_resolution_rename_and_skip() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        base = Path(tmp)
        _make_plugin_dir(base, "aa", commands=[{"name": "x", "handler": "handlers.cmd"}])
        _make_plugin_dir(
            base,
            "bb",
            commands=[{"name": "x", "handler": "handlers.cmd"}],
            conflicts={"x": "rename"},
        )
        _make_plugin_dir(
            base,
            "cc",
            commands=[{"name": "x", "handler": "handlers.cmd"}],
            conflicts={"x": "skip"},
        )
        manager = _manager(base)
        loaded = manager.load_enabled({"aa": True, "bb": True, "cc": True}, {})
        assert [item.name for item in loaded] == ["aa", "bb", "cc"]
        commands = manager.commands
        assert "x" in commands._commands and commands._commands["x"].plugin_name == "aa"
        assert "bb.x" in commands._commands
        assert "cc.x" not in commands._commands
        bb_log = manager.loaded["bb"].conflicts
        assert any(
            item.get("command") == "x" and item.get("action") == "rename"
            for item in bb_log
        )
        cc_log = manager.loaded["cc"].conflicts
        assert any(
            item.get("command") == "x" and item.get("action") == "skip"
            for item in cc_log
        )
        await get_bus().stop(clear=True)
        await reset_bus()


@pytest.mark.asyncio
async def test_conflict_resolution_system_reserved() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        base = Path(tmp)
        _make_plugin_dir(base, "plugin_x", commands=[{"name": "help", "handler": "handlers.cmd"}])
        _make_plugin_dir(base, "system", commands=[{"name": "help", "handler": "handlers.cmd"}])
        manager = _manager(base)
        loaded = manager.load_enabled({"plugin_x": True, "system": True}, {})
        assert [item.name for item in loaded] == ["plugin_x", "system"]
        commands = manager.commands
        assert commands._commands["help"].plugin_name == "system"
        assert "plugin_x.help" in commands._commands
        await get_bus().stop(clear=True)
        await reset_bus()


@pytest.mark.asyncio
async def test_templated_task_params() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        base = Path(tmp)
        _make_plugin_dir(
            base,
            "task_plugin",
            commands=[],
            tasks=[
                {
                    "id": "daily",
                    "kind": "cron",
                    "params": {"cron": "${tasks.daily.cron}"},
                    "handler": "handlers.task_handler",
                    "target": "all",
                }
            ],
        )
        manager = _manager(base)
        config = {"tasks": {"daily": {"cron": "0 2 * * *"}}}
        manager.load_enabled({"task_plugin": True}, {"task_plugin": config})
        entry = manager.task_registry.get("task_plugin", "daily")
        assert entry is not None and entry.params["cron"] == "0 2 * * *"
        assert manager.scheduler.scheduler.get_job(entry.job_id) is not None
        await get_bus().stop(clear=True)
        await reset_bus()


def _fake_context(db, scheduler, task_registry, config=None) -> PluginContext:
    return PluginContext(
        name="test_plugin",
        config=config or {},
        bus=None,
        commands=CommandRegistry(),
        db=db,
        scheduler=scheduler,
        cache=TTLCache(),
        bot=BotClient(),
        permissions=PermissionManager(),
        services={},
        subscriptions=EventSubscriptionRegistry(),
        task_registry=task_registry,
    )


def test_register_managed_task() -> None:
    scheduler = SchedulerService()
    registry = PluginTaskRegistry(scheduler)
    ctx = _fake_context(None, scheduler, registry)
    calls: list = []

    async def handler(ctx=None) -> None:
        calls.append(ctx)

    entry = ctx.register_managed_task(
        "t1",
        "interval",
        {"seconds": 999999},
        handler,
        description="测试任务",
    )
    assert registry.get("test_plugin", "t1") is not None
    assert scheduler.scheduler.get_job(entry.job_id) is not None
    assert registry.set_enabled("test_plugin", "t1", False) is True
    job = scheduler.scheduler.get_job(entry.job_id)
    assert job is not None and job.next_run_time is None  # paused


async def test_task_target_list_gating() -> None:
    settings = Settings()
    policy = ScopePolicyService(settings)
    policy.set_feature("group:100", "order_ledger.tasks", False)
    from app.core.plugin import PluginManager as PM

    scheduler = SchedulerService()
    task_registry = PluginTaskRegistry(scheduler)
    pm = PM(
        Path(tempfile.gettempdir()),
        commands=CommandRegistry(),
        db=None,
        scheduler=scheduler,
        cache=TTLCache(),
        bot=BotClient(),
        permissions=PermissionManager(),
        services={},
        subscriptions=EventSubscriptionRegistry(),
        task_registry=task_registry,
        scope_policy=policy,
    )
    calls: list[str] = []

    async def handler(ctx=None) -> None:
        calls.append("run")

    entry = PluginTaskEntry(
        plugin="order_ledger",
        task_id="t",
        feature_id="order_ledger.tasks",
        kind="interval",
        params={"seconds": 999999},
        handler=handler,
        target=["group:100", "group:200"],
    )
    task_registry.register(entry)
    await pm._run_manifest_task(entry)
    assert calls == ["run"]


# ---------------------------------------------------------------- records 过滤

@pytest.mark.asyncio
async def test_records_filters(tmp_path) -> None:
    url = f"sqlite+aiosqlite:///{tmp_path / 'records.db'}"
    get_engine(url)
    await init_db(url)
    try:
        schemas = SchemaRegistry()
        schemas.register(
            RecordTypeSchema(
                "ticket",
                [
                    FieldSchema("status", "string"),
                    FieldSchema("amount", "number"),
                    FieldSchema("owner", "string"),
                ],
            )
        )
        service = RecordService(schemas)
        await service.create("ticket", {"status": "done", "amount": 5, "owner": "a"})
        await service.create("ticket", {"status": "open", "amount": 15, "owner": "b"})
        await service.create("ticket", {"status": "done", "amount": 25, "owner": "a"})

        rows = await service.list(
            "ticket",
            filters={"status": "done", "amount": {"gte": 10}},
            sort_by="amount",
            order="asc",
        )
        assert [row.data["amount"] for row in rows] == [25]
        rows2 = await service.list(
            "ticket", filters={"owner": {"in": ["a"]}}
        )
        assert len(rows2) == 2
    finally:
        await reset_db_engine()


# ---------------------------------------------------------------- 配置校验

def test_config_schema_validation_and_defaults() -> None:
    schema = {
        "type": "object",
        "properties": {
            "ratio": {
                "type": "object",
                "properties": {
                    "打手": {"type": "number", "default": 0.69, "maximum": 1}
                },
            }
        },
    }
    normalized, err = _validate_config_schema(schema, {"ratio": {"打手": 1.5}})
    assert err and "打手" in err
    normalized, err = _validate_config_schema(schema, {"ratio": {}})
    assert err == ""
    assert normalized["ratio"]["打手"] == 0.69


# ---------------------------------------------------------------- 文本转图

def test_text_image_render(tmp_path) -> None:
    from app.services.textimg import render_text_image

    path = render_text_image("你好\n第二行", tmp_path, title="标题")
    assert path.exists() and path.suffix == ".png"
    from PIL import Image

    with Image.open(path) as image:
        assert image.format == "PNG"
