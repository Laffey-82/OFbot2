from __future__ import annotations

import argparse
import asyncio
import functools
import re
from datetime import UTC, datetime
from typing import Any

import uvicorn

from app.adapters.base import BotClient
from app.adapters.manager import ConnectionManager
from app.core.background import BackgroundWorker
from app.core.bus import get_bus
from app.core.cache import TTLCache
from app.core.capabilities import capability_registry
from app.core.commands import command_registry
from app.core.config import Settings, load_settings, save_settings
from app.core.events import (
    BotDisconnected,
    GroupMessageReceived,
    TaskAutoDisabled,
    TaskAutoReenabled,
    WebhookReceived,
    WorkflowAutoDisabled,
    WorkflowAutoReenabled,
    WorkflowRunFailed,
)
from app.core.logger import (
    get_logger,
    prune_log_files,
    set_log_level,
    setup_logging,
)
from app.core.observability import get_system_metrics
from app.core.paths import runtime_root
from app.core.permissions import permission_manager
from app.core.plugin import PluginManager
from app.core.plugin_tasks import PluginTaskRegistry
from app.core.rules import RuleRegistry
from app.core.scheduler import SchedulerService
from app.core.scopes import ScopePolicyService
from app.core.security import SecurityPolicy, audit_logger
from app.core.sessions import SessionManager
from app.core.subscriptions import EventSubscriptionRegistry
from app.core.whitelist import GroupWhitelistService
from app.db.base import (
    get_engine,
    init_db,
    reset_db_engine,
    resolve_sqlite_path,
    session_factory,
)
from app.db.migrations import MigrationRunner
from app.runtime import (
    _now,
    _persist_audit,
    _record_command_stat,
    auto_reenable_disabled,
    build_adapters,
    build_ai_service,
    infer_field_type,
    prune_audit_logs,
    restore_tasks,
)
from app.services.aggregation import AggregationService
from app.services.ai import AgentRunner
from app.services.alerts import AlertService
from app.services.audit_service import AuditService
from app.services.backup import BackupService
from app.services.capability_setup import register_builtin_capabilities
from app.services.export import ExportService
from app.services.files import FileService
from app.services.plugin_installer import PluginInstaller
from app.services.plugin_repo import PluginRepoService
from app.services.records import (
    FieldSchema,
    RecordService,
    RecordTypeSchema,
    SchemaRegistry,
    schema_from_dict,
)
from app.services.scaffold import ScaffoldService
from app.services.state_machine import StateMachineService
from app.services.textimg import TextImageService
from app.services.webhook import WebhookService
from app.services.workflow import WorkflowEngine
from app.services.workflow_templates import WorkflowTemplateService

ROOT = runtime_root()
logger = get_logger(__name__)

async def run(settings: Settings) -> None:
    set_log_level(settings.basic.log_level)
    get_engine(settings.database.url)
    scope_policy = ScopePolicyService(settings)

    def persist_whitelist(groups: list[str]) -> None:
        settings.plugin_configs.setdefault("system", {})["groups"] = groups
        save_settings(settings)

    whitelist_service = GroupWhitelistService(
        settings.plugin_configs.get("system", {}).get("groups", []),
        on_change=persist_whitelist,
    )
    bot_client = BotClient(
        whitelist_service=whitelist_service, scope_policy=scope_policy
    )
    scheduler = SchedulerService(
        timezone=settings.scheduler.timezone,
        max_instances=settings.scheduler.max_instances,
        coalesce=settings.scheduler.coalesce,
    )
    background = BackgroundWorker()
    cache: TTLCache[Any] = TTLCache(max_size=2048, default_ttl=300)
    security = SecurityPolicy(
        max_message_length=settings.security.max_message_length,
        max_arg_length=settings.security.max_arg_length,
        default_cooldown_seconds=settings.security.default_cooldown_seconds,
        rate_limit_default=settings.security.rate_limit_default,
        sensitive_words=settings.security.sensitive_words,
        blocked_users=settings.security.blocked_users,
    )
    command_registry.set_command_start(settings.basic.command_start)
    command_registry.set_command_sep(settings.basic.command_sep)
    command_registry.set_security(security)
    command_registry.set_scope_policy(scope_policy)
    rule_registry = RuleRegistry()
    session_manager = SessionManager(
        ttl_seconds=settings.runtime.session_ttl_seconds,
        max_sessions=settings.runtime.session_max_sessions,
    )
    command_registry.set_rule_registry(rule_registry)
    command_registry.set_session_manager(session_manager)
    command_registry.unknown_command_hint = (
        settings.security.unknown_command_hint
    )
    command_registry.set_stat_callback(_record_command_stat)
    audit_logger.set_persist_callback(_persist_audit)

    schema_registry = SchemaRegistry()
    for saved_type in settings.plugin_configs.get("records", {}).get("types", []):
        try:
            schema_registry.register(schema_from_dict(saved_type))
        except Exception as exc:
            logger.warning("failed to restore record type: %s", exc)
    record_service = RecordService(schema_registry)
    state_machine = StateMachineService()
    aggregation = AggregationService()
    audit_service = AuditService()
    ai_service = build_ai_service(settings)
    agent_runner = AgentRunner(
        ai_service,
        max_memory_turns=settings.runtime.agent_max_memory_turns,
    )

    async def agent_send_group(group_id: str, message: str) -> str:
        ok = await bot_client.send_group_message(str(group_id), message)
        return "已发送" if ok else "发送失败（连接不可用）"

    async def agent_send_private(user_id: str, message: str) -> str:
        ok = await bot_client.send_private_message(str(user_id), message)
        return "已发送" if ok else "发送失败（连接不可用）"

    async def agent_records_create(record_type: str, data: str = "{}") -> str:
        import json

        try:
            payload = json.loads(data) if data.strip() else {}
        except json.JSONDecodeError:
            return "数据 JSON 无效"
        if not isinstance(payload, dict):
            return "数据必须是 JSON 对象"
        try:
            record = await record_service.create(record_type, payload)
        except Exception as exc:
            return f"创建失败：{exc}"
        return f"已创建记录 #{record.id}"

    async def agent_records_list(record_type: str, limit: int = 20) -> str:
        try:
            records = await record_service.list(record_type, limit=limit)
        except Exception as exc:
            return f"查询失败：{exc}"
        if not records:
            return f"记录类型 {record_type} 暂无数据"
        lines = [f"记录 #{item.id}：{item.data}" for item in records[:limit]]
        return "\n".join(lines)

    async def agent_ai_chat(prompt: str) -> str:
        return await ai_service.chat(
            [
                {"role": "system", "content": "你是 OFbot 2 助手。"},
                {"role": "user", "content": prompt},
            ]
        )

    agent_runner.register_tool(
        "send_group",
        agent_send_group,
        description="向指定群发送一条消息",
        sensitive=True,
        permission="bot.message",
    )
    agent_runner.register_tool(
        "send_private",
        agent_send_private,
        description="向指定用户发送一条私聊消息",
        sensitive=True,
        permission="bot.message",
    )
    agent_runner.register_tool(
        "records_create",
        agent_records_create,
        description="在记录中心创建一条记录",
        sensitive=True,
        permission="record.manage",
    )
    agent_runner.register_tool(
        "records_list",
        agent_records_list,
        description="查询记录中心某类型的记录",
        permission="record.read",
    )
    agent_runner.register_tool(
        "ai_chat",
        agent_ai_chat,
        description="调用 AI 完成一次独立的单轮对话",
    )

    workflow_engine = WorkflowEngine(
        auto_disable_after_failures=(
            settings.web.auto_disable_workflows_after_failures
        )
    )

    async def wf_echo(context: dict[str, Any], text: str = "") -> str:
        return text

    async def wf_send_group(
        context: dict[str, Any], group_id: str, message: str
    ) -> bool:
        return await bot_client.send_group_message(group_id, message)

    async def wf_ai_chat(context: dict[str, Any], prompt: str) -> str:
        return await ai_service.chat(
            [
                {"role": "system", "content": "你是 OFbot 流程引擎助手。"},
                {"role": "user", "content": prompt},
            ]
        )

    async def wf_create_record(
        context: dict[str, Any], record_type: str, data: str = "{}"
    ) -> str:
        """流程动作：写入一条通用记录（联动记录中心）。"""
        import json

        try:
            payload = json.loads(data) if data.strip() else {}
        except json.JSONDecodeError:
            return "数据 JSON 无效"
        if not isinstance(payload, dict):
            return "数据必须是 JSON 对象"
        try:
            schema_registry.get(record_type)
        except KeyError:
            schema_registry.register(
                RecordTypeSchema(
                    record_type,
                    [
                        FieldSchema(
                            str(key),
                            infer_field_type(payload[key]),
                            required=False,
                        )
                        for key in payload
                    ],
                    description="由流程自动创建",
                )
            )
            try:
                from app.web.helpers import persist_record_type

                persist_record_type(
                    settings, schema_registry.get(record_type)
                )
            except Exception:
                pass
        try:
            record = await record_service.create(record_type, payload)
        except Exception as exc:
            return f"创建失败：{exc}"
        return f"已创建记录 #{record.id}"

    workflow_engine.register_action("echo", wf_echo)
    workflow_engine.register_action("send_group", wf_send_group)
    workflow_engine.register_action("ai_chat", wf_ai_chat)
    workflow_engine.register_action("create_record", wf_create_record)
    webhook_service = WebhookService(
        retention=settings.web.webhook_history_retention
    )
    webhook_service.register("default")
    for wh_name, wh_filter in settings.plugin_configs.get("webhooks", {}).items():
        try:
            webhook_service.register(wh_name, wh_filter or None)
        except Exception as exc:
            logger.warning("failed to restore webhook %s: %s", wh_name, exc)
    alert_service = AlertService(
        retention_days=settings.web.alert_history_retention_days,
        min_interval_seconds=settings.web.alert_min_interval_seconds,
    )
    for saved_rule in settings.plugin_configs.get("alerts", {}).get("rules", []):
        try:
            alert_service.add_rule(
                str(saved_rule.get("name", "")),
                str(saved_rule.get("event", "*")),
                str(saved_rule.get("target_group", "")),
                str(saved_rule.get("target_private", "")),
                str(saved_rule.get("keyword", "")),
                int(saved_rule.get("min_interval_seconds", 0) or 0),
            )
            if not saved_rule.get("enabled", True):
                alert_service.toggle_rule(str(saved_rule.get("name", "")))
        except Exception as exc:
            logger.warning("failed to restore alert rule: %s", exc)

    async def alert_notifier(rule: Any, detail: str) -> None:
        if rule.target_group:
            for group in re.split(r"[,，\s]+", rule.target_group.strip()):
                if not group:
                    continue
                await bot_client.send_group_message(
                    group, f"告警 {rule.name}: {detail}"
                )
        if getattr(rule, "target_private", ""):
            for user_id in re.split(
                r"[,，\s]+", rule.target_private.strip()
            ):
                if not user_id:
                    continue
                await bot_client.send_private_message(
                    user_id, f"告警 {rule.name}: {detail}"
                )
        try:
            await workflow_engine.trigger(
                "alert",
                {"rule": rule.name, "event": rule.event, "detail": detail},
            )
        except Exception:
            logger.exception("alert workflow trigger failed")

    alert_service.set_notifier(alert_notifier)

    register_builtin_capabilities()

    services: dict[str, Any] = {
        "export": ExportService(ROOT / "data" / "exports"),
        "files": FileService(ROOT / "data" / "files"),
        "backup": BackupService(ROOT / "data" / "backups"),
        "whitelist": whitelist_service,
        "installer": PluginInstaller(ROOT / "plugins"),
        "plugin_repo": PluginRepoService(
            ROOT / "plugins",
            ROOT / "plugin-repo",
            repo_url=settings.web.plugin_repo_url,
            token=settings.web.plugin_repo_token,
        ),
        "scaffold": ScaffoldService(ROOT / "examples" / "plugins", ROOT / "plugins"),
        "schema_registry": schema_registry,
        "records": record_service,
        "state_machine": state_machine,
        "aggregation": aggregation,
        "audit": audit_service,
        "ai": ai_service,
        "workflow": workflow_engine,
        "workflow_templates": WorkflowTemplateService(
            ROOT / "data" / "workflow_templates"
        ),
        "webhook": webhook_service,
        "alerts": alert_service,
        "capabilities": capability_registry,
        "agent": agent_runner,
        "agent_permission": permission_manager.has_permission,
        "rules": rule_registry,
        "session": session_manager,
        "textimg": TextImageService(ROOT / "data" / "textimg"),
    }
    subscriptions = EventSubscriptionRegistry()

    async def on_bot_disconnected(event: BotDisconnected) -> None:
        await alert_service.check("adapter_disconnected", event.bot_id)

    subscriptions.subscribe(BotDisconnected, on_bot_disconnected, plugin_name="core")

    async def on_workflow_failed(event: WorkflowRunFailed) -> None:
        await alert_service.check(
            "workflow.failed",
            (
                f"{event.workflow_name}（#{event.workflow_id}，"
                f"run #{event.run_id}）：{event.error}"
            ),
        )

    subscriptions.subscribe(
        WorkflowRunFailed, on_workflow_failed, plugin_name="core"
    )

    async def on_task_auto_disabled(event: TaskAutoDisabled) -> None:
        await alert_service.check(
            "task.auto_disabled",
            f"{event.task_name}（{event.task_id}）：{event.reason}",
        )

    subscriptions.subscribe(
        TaskAutoDisabled, on_task_auto_disabled, plugin_name="core"
    )

    async def on_workflow_auto_disabled(
        event: WorkflowAutoDisabled,
    ) -> None:
        await alert_service.check(
            "workflow.auto_disabled",
            f"{event.workflow_name}（#{event.workflow_id}）：{event.reason}",
        )

    subscriptions.subscribe(
        WorkflowAutoDisabled, on_workflow_auto_disabled, plugin_name="core"
    )

    async def on_task_auto_reenabled(event: TaskAutoReenabled) -> None:
        await alert_service.check(
            "task.auto_reenabled",
            f"{event.task_name}（{event.task_id}）：{event.reason}",
        )

    subscriptions.subscribe(
        TaskAutoReenabled, on_task_auto_reenabled, plugin_name="core"
    )

    async def on_workflow_auto_reenabled(
        event: WorkflowAutoReenabled,
    ) -> None:
        await alert_service.check(
            "workflow.auto_reenabled",
            f"{event.workflow_name}（#{event.workflow_id}）：{event.reason}",
        )

    subscriptions.subscribe(
        WorkflowAutoReenabled,
        on_workflow_auto_reenabled,
        plugin_name="core",
    )

    async def on_webhook_received(event: WebhookReceived) -> None:
        await workflow_engine.trigger("webhook", {"webhook": event.name, "payload": event.payload})

    subscriptions.subscribe(WebhookReceived, on_webhook_received, plugin_name="core")

    async def on_group_message_received(event: GroupMessageReceived) -> None:
        await workflow_engine.trigger(
            "message",
            {
                "group_id": event.group_id,
                "user_id": event.user_id,
                "message": event.message,
            },
        )

    subscriptions.subscribe(
        GroupMessageReceived, on_group_message_received, plugin_name="core"
    )

    plugin_manager = PluginManager(
        ROOT / "plugins",
        commands=command_registry,
        db=session_factory,
        scheduler=scheduler,
        cache=cache,
        bot=bot_client,
        permissions=permission_manager,
        services=services,
        subscriptions=subscriptions,
        capabilities=capability_registry,
        records=record_service,
        state_machine=state_machine,
        aggregation=aggregation,
        audit=audit_service,
        ai=ai_service,
        workflow=workflow_engine,
        scope_policy=scope_policy,
        task_registry=PluginTaskRegistry(scheduler),
        rules=rule_registry,
        session=session_manager,
    )
    plugin_manager.set_runtime_task_states(
        settings.runtime.plugin_tasks
    )
    services["plugin_manager"] = plugin_manager
    command_registry.set_plugin_context_resolver(plugin_manager.get_context)
    plugin_manager.load_enabled(settings.plugins, settings.plugin_configs)

    plugin_models = [
        model
        for loaded in plugin_manager.loaded.values()
        for model in loaded.context._models
    ]
    await init_db(settings.database.url, extra_models=plugin_models)
    migration_paths = [
        migration
        for loaded in plugin_manager.loaded.values()
        for migration in loaded.context._migrations
    ]
    if migration_paths:
        await MigrationRunner().run(migration_paths)

    for user_id in settings.basic.superusers:
        permission_manager.upsert_principal(
            str(user_id), role="superadmin", scopes={"*"}
        )
    superuser_set = {str(uid) for uid in settings.basic.superusers}
    for user_id, role in settings.runtime.user_roles.items():
        if str(user_id) in superuser_set:
            logger.warning(
                "user_roles 中的 %s 与 superusers 重叠，superusers 的 superadmin 角色将被覆盖",
                user_id,
            )
        permission_manager.upsert_principal(
            str(user_id),
            role=str(role or "user"),
            scopes={"*"} if role == "superadmin" else set(),
        )

    await background.start()
    scheduler.start()
    await plugin_manager.start_all()
    for loaded in plugin_manager.loaded.values():
        for factory in loaded.context._background_tasks:
            try:
                await background.submit(loaded.name, factory())
            except Exception as exc:
                logger.warning("failed to submit plugin background task: %s", exc)

    backup_service = services["backup"]

    async def auto_backup_loop() -> None:
        while True:
            interval = max(1, settings.scheduler.backup_interval_hours) * 3600
            await asyncio.sleep(interval)
            if not settings.scheduler.auto_backup_enabled:
                continue
            try:
                db_path = resolve_sqlite_path(settings.database.url)
                await asyncio.to_thread(
                    backup_service.create_backup,
                    ROOT / "config.yaml",
                    db_path,
                )
                logger.info("auto backup completed")
                settings.plugin_configs.setdefault("backup", {})[
                    "last_auto_backup"
                ] = _now().isoformat(timespec="seconds")
                save_settings(settings)
            except Exception:
                logger.exception("auto backup failed")

    await background.submit("auto-backup", auto_backup_loop())

    alert_service = services["alerts"]

    async def metric_threshold_loop() -> None:
        crossed = {"cpu": False, "memory": False}
        from datetime import timedelta

        from sqlalchemy import delete

        from app.db.base import session_factory
        from app.db.models import MetricsSample

        while True:
            await asyncio.sleep(30)
            try:
                snapshot = get_system_metrics()
                cpu = float(snapshot.get("cpu_percent", 0))
                memory = float(snapshot.get("memory_percent", 0))
                active_tasks = int(snapshot.get("active_tasks", 0))
                threads = int(snapshot.get("thread_count", 0))
                processes = int(snapshot.get("process_count", 0))
                try:
                    async with session_factory()() as session:
                        session.add(
                            MetricsSample(
                                cpu_percent=cpu,
                                memory_percent=memory,
                                active_tasks=active_tasks,
                                threads=threads,
                                processes=processes,
                            )
                        )
                        cutoff = datetime.now(UTC) - timedelta(days=7)
                        await session.execute(
                            delete(MetricsSample).where(
                                MetricsSample.created_at < cutoff
                            )
                        )
                        await session.commit()
                except Exception:
                    logger.exception("failed to persist metrics sample")
                cpu_th = max(1, int(settings.web.cpu_threshold))
                mem_th = max(1, int(settings.web.memory_threshold))
                if cpu >= cpu_th and not crossed["cpu"]:
                    crossed["cpu"] = True
                    await alert_service.check(
                        "metric.cpu_high",
                        f"CPU 使用率 {cpu:.1f}% 超过阈值 {cpu_th}%",
                    )
                elif cpu < cpu_th - 5:
                    crossed["cpu"] = False
                if memory >= mem_th and not crossed["memory"]:
                    crossed["memory"] = True
                    await alert_service.check(
                        "metric.memory_high",
                        f"内存使用率 {memory:.1f}% 超过阈值 {mem_th}%",
                    )
                elif memory < mem_th - 5:
                    crossed["memory"] = False
            except Exception:
                logger.exception("metric threshold check failed")

    await background.submit("metric-threshold", metric_threshold_loop())

    async def auto_reenable_loop() -> None:
        while True:
            await asyncio.sleep(
                max(10, settings.scheduler.auto_reenable_interval_seconds)
            )
            try:
                await auto_reenable_disabled(
                    threshold_seconds=(
                        settings.scheduler.auto_reenable_after_seconds
                    ),
                    scheduler=scheduler,
                    app=web_app,
                )
            except Exception:
                logger.exception("auto re-enable loop failed")

    await background.submit("auto-reenable", auto_reenable_loop())

    async def audit_retention_loop() -> None:
        while True:
            await asyncio.sleep(3600)
            try:
                await prune_audit_logs(
                    retention_days=settings.security.audit_retention_days
                )
            except Exception:
                logger.exception("audit retention pruning failed")

    await background.submit("audit-prune", audit_retention_loop())

    adapters, reverse_routes = build_adapters(settings, bot_client)

    await restore_tasks(
        bot_client,
        scheduler,
        auto_disable_after_failures=(
            settings.scheduler.auto_disable_after_failures
        ),
    )

    workflows = await workflow_engine.list()
    for workflow in workflows:
        trigger = workflow.definition.get("trigger", {})
        if trigger.get("type") == "schedule" and trigger.get("cron"):
            scheduler.add_cron_job(
                functools.partial(workflow_engine.execute, workflow.id),
                job_id=f"workflow-{workflow.id}",
                cron_expression=trigger["cron"],
            )

    from app.web.app import create_app

    http_routes = [
        (getattr(adapter, "http_path", "/onebot/v11/http"), adapter)
        for adapter in adapters
        if hasattr(adapter, "handle_http_event")
    ]
    web_app = create_app(
        settings,
        plugin_manager=plugin_manager,
        reverse_routes=reverse_routes,
        http_routes=http_routes,
    )
    web_app.state.background_worker = background
    web_app.state.bot_client = bot_client
    web_app.state.scheduler = scheduler
    web_app.state.services = services
    web_app.state.scope_policy = scope_policy
    web_app.state.plugin_repo_service = services.get("plugin_repo")

    connection_manager = ConnectionManager()
    connection_manager.attach(bot_client)
    connection_manager.adopt(adapters)
    connection_manager.collect_reverse_routes()
    connection_manager.start_all()
    web_app.state.adapters = adapters
    web_app.state.connection_manager = connection_manager

    async def reconfigure_adapters() -> dict[str, Any]:
        """停止当前适配器并按最新配置重建、重启，实现协议热重载。"""
        new_adapters, _ = build_adapters(settings, bot_client)
        await connection_manager.reconfigure(new_adapters)
        adapters.clear()
        adapters.extend(new_adapters)

        new_http_routes = [
            (getattr(a, "http_path", "/onebot/v11/http"), a)
            for a in new_adapters
            if hasattr(a, "handle_http_event")
        ]
        web_app.state.http_handlers.clear()
        web_app.state.http_handlers.extend(new_http_routes)
        register_http = web_app.state._register_http_event_route
        for new_path, _handler in new_http_routes:
            register_http(new_path)

        web_app.state.last_reconfigured = _now().isoformat(timespec="seconds")
        return {
            "adapters": [getattr(a, "bot_id", "?") for a in new_adapters]
        }

    web_app.state.reconfigure_adapters = reconfigure_adapters

    if (
        settings.web.host not in ("127.0.0.1", "localhost", "::1")
        and not settings.web.api_keys
    ):
        logger.warning(
            "Web 服务绑定非本机地址 %s 且未配置 web.api_keys，"
            "/api/v1/* 管理接口将要求后台登录会话；"
            "程序化调用请配置 API Key（见 FAQ）",
            settings.web.host,
        )

    config = uvicorn.Config(
        web_app,
        host=settings.web.host,
        port=settings.web.port,
        log_level=settings.basic.log_level.lower(),
    )
    server = uvicorn.Server(config)
    try:
        await server.serve()
    finally:
        try:
            await connection_manager.stop_all()
        except Exception:
            logger.exception("connection cleanup failed")
        for plugin_name in list(plugin_manager.loaded):
            try:
                await plugin_manager.unload_plugin(plugin_name)
            except Exception:
                logger.exception("plugin unload failed: %s", plugin_name)
        scheduler.shutdown(wait=False)
        try:
            await background.stop()
        except Exception:
            logger.exception("background worker stop failed")
        try:
            await get_bus().stop(timeout=4, clear=True)
        except Exception:
            logger.warning("event bus did not stop cleanly", exc_info=True)
        try:
            await reset_db_engine()
        except Exception:
            logger.exception("database engine disposal failed")


async def main(config_path: str | None = None) -> None:
    settings = load_settings(config_path or (ROOT / "config.yaml"))
    setup_logging(settings.basic.log_level)
    removed = prune_log_files(
        settings.basic.log_retention_days, settings.basic.log_max_files
    )
    if removed:
        logger.info("pruned %s outdated log files", removed)
    logger.info("starting OFbot 2")
    await run(settings)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=None, help="path to config.yaml")
    args = parser.parse_args()
    try:
        asyncio.run(main(args.config))
    except KeyboardInterrupt:
        logger.info("stopped by user")
