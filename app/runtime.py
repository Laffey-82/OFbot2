"""机器人运行时装配辅助（任务恢复、命令统计、审计持久化、AI 与适配器构建）。"""

from __future__ import annotations

import functools
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select

from app.adapters.base import BotClient
from app.adapters.onebot import OneBotAdapter
from app.adapters.red import RedAdapter
from app.core.bus import get_bus
from app.core.config import Settings
from app.core.events import TaskAutoDisabled, TaskAutoReenabled, WorkflowAutoReenabled
from app.core.logger import get_logger
from app.core.observability import metrics
from app.core.scheduler import SchedulerService
from app.db.base import session_factory
from app.db.models import AuditLog, CommandStat, Task, TaskRun, User, Workflow
from app.services.ai import (
    AIService,
    AnthropicProvider,
    GeminiProvider,
    MockAIProvider,
    OllamaProvider,
    OpenAIChatProvider,
)

logger = get_logger(__name__)


def infer_field_type(value: Any) -> str:
    """根据载荷值推断记录字段类型（boolean / integer / number / string）。"""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    return "string"


def _now() -> datetime:
    return datetime.now(UTC)


async def prune_audit_logs(*, retention_days: int) -> int:
    """清理超过保留期的审计日志，返回删除条数（retention_days<=0 表示不清理）。"""
    if retention_days <= 0:
        return 0
    from datetime import timedelta

    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    async with session_factory()() as session:
        result = await session.execute(
            delete(AuditLog).where(AuditLog.timestamp < cutoff)
        )
        await session.commit()
        return result.rowcount or 0


async def _execute_task(
    task_id: str,
    *,
    bot_client: BotClient,
    scheduler: Any = None,
    auto_disable_after_failures: int = 0,
    message_override: str = "",
) -> None:
    async with session_factory()() as session:
        task = await session.scalar(
            select(Task).where(Task.task_id == task_id)
        )
        if task is None or not task.enabled:
            return
        task.last_run_time = _now()
        task.status = "running"
        await session.commit()
        try:
            group_id = task.params.get("group_id")
            message = message_override or task.params.get("message", "")
            if group_id and message and bot_client is not None:
                await bot_client.send_group_message(str(group_id), message)
            task.status = "succeeded"
            task.params = {k: v for k, v in task.params.items() if k != "last_error"}
            metrics.inc("tasks_completed_total")
        except Exception as exc:
            logger.exception("task execution failed: %s", task.name)
            task.status = "failed"
            task.params = {**task.params, "last_error": str(exc)}
            metrics.inc("tasks_failed_total")
        session.add(
            TaskRun(
                task_id=task.task_id,
                status=task.status,
                message=task.params.get("last_error", ""),
            )
        )
        await session.commit()
        if (
            task.status == "failed"
            and auto_disable_after_failures > 0
        ):
            runs = (
                await session.scalars(
                    select(TaskRun)
                    .where(TaskRun.task_id == task_id)
                    .order_by(TaskRun.created_at.desc())
                    .limit(auto_disable_after_failures)
                )
            ).all()
            consecutive = 0
            for run in runs:
                if run.status != "failed":
                    break
                consecutive += 1
            if consecutive >= auto_disable_after_failures:
                task = await session.get(Task, task.id)
                if task is not None and task.enabled:
                    now_iso = _now().isoformat(timespec="seconds")
                    cycles = list(task.params.get("self_heal_cycles") or [])
                    cycles.append(
                        {"disabled": now_iso, "reenabled": None}
                    )
                    task.enabled = False
                    task.params = {
                        **task.params,
                        "auto_disabled": now_iso,
                        "auto_disabled_reason": (
                            f"连续失败 {consecutive} 次，已自动停用"
                        ),
                        # 仅保留最近 9 个周期，避免 params 无限增长
                        "self_heal_cycles": cycles[-9:],
                    }
                    await session.commit()
                    try:
                        get_bus().dispatch(
                            TaskAutoDisabled(
                                task_id=task.task_id,
                                task_name=task.name,
                                reason=(
                                    f"连续失败 {consecutive} 次，已自动停用"
                                ),
                            )
                        )
                    except RuntimeError:
                        pass
                    logger.warning(
                        "task %s auto-disabled after %s consecutive failures",
                        task.name,
                        consecutive,
                    )


async def restore_tasks(
    bot_client: BotClient,
    scheduler: SchedulerService,
    *,
    auto_disable_after_failures: int = 0,
) -> int:
    async with session_factory()() as session:
        tasks = (
            await session.scalars(select(Task).where(Task.enabled.is_(True)))
        ).all()
    restored = 0
    for task in tasks:
        func = functools.partial(
            _execute_task,
            task.task_id,
            bot_client=bot_client,
            scheduler=scheduler,
            auto_disable_after_failures=auto_disable_after_failures,
        )
        try:
            if task.type == "cron" and task.cron_expression:
                scheduler.add_cron_job(
                    func,
                    job_id=task.task_id,
                    cron_expression=task.cron_expression,
                    plugin_name=task.plugin_name or "",
                )
            elif task.type == "interval" and task.interval_seconds:
                scheduler.add_interval_job(
                    func,
                    job_id=task.task_id,
                    seconds=task.interval_seconds,
                    plugin_name=task.plugin_name or "",
                )
            elif task.type == "date" and task.run_date:
                scheduler.add_date_job(
                    func,
                    job_id=task.task_id,
                    run_date=task.run_date,
                    plugin_name=task.plugin_name or "",
                )
            else:
                continue
            restored += 1
        except Exception as exc:
            logger.warning("failed to restore task %s: %s", task.name, exc)
    logger.info("restored %s scheduled tasks", restored)
    return restored


async def auto_reenable_disabled(
    *,
    threshold_seconds: int,
    scheduler: Any = None,
    app: Any = None,
) -> dict[str, int]:
    """周期巡检：停用超过冷却期的自动停用任务 / 流程重新启用。"""
    from datetime import timedelta

    if threshold_seconds <= 0:
        return {"tasks": 0, "workflows": 0}
    cutoff = datetime.now(UTC) - timedelta(
        seconds=max(1, threshold_seconds)
    )
    reenabled = {"tasks": 0, "workflows": 0}
    async with session_factory()() as session:
        tasks = (
            await session.scalars(
                select(Task).where(Task.enabled.is_(False))
            )
        ).all()
        for task in tasks:
            stamp = task.params.get("auto_disabled")
            if not stamp:
                continue
            try:
                disabled_at = datetime.fromisoformat(str(stamp))
            except ValueError:
                continue
            if disabled_at and disabled_at <= cutoff:
                cycles = list(task.params.get("self_heal_cycles") or [])
                if cycles and cycles[-1].get("reenabled") is None:
                    cycles[-1] = {
                        **cycles[-1],
                        "reenabled": _now().isoformat(timespec="seconds"),
                    }
                task.enabled = True
                task.params = {
                    key: value
                    for key, value in task.params.items()
                    if key not in ("auto_disabled", "auto_disabled_reason")
                }
                if cycles:
                    task.params["self_heal_cycles"] = cycles
                await session.commit()
                reenabled["tasks"] += 1
                try:
                    get_bus().dispatch(
                        TaskAutoReenabled(
                            task_id=task.task_id,
                            task_name=task.name,
                            reason="停用冷却期结束，已自动恢复",
                        )
                    )
                except RuntimeError:
                    pass
                if scheduler is not None and app is not None:
                    from app.web.helpers import _task_executor

                    func = _task_executor(task.task_id, app)
                    if task.type == "cron" and task.cron_expression:
                        scheduler.add_cron_job(
                            func,
                            job_id=task.task_id,
                            cron_expression=task.cron_expression,
                        )
                    elif task.type == "interval" and task.interval_seconds:
                        scheduler.add_interval_job(
                            func,
                            job_id=task.task_id,
                            seconds=task.interval_seconds,
                        )
        workflows = (
            await session.scalars(
                select(Workflow).where(Workflow.enabled.is_(False))
            )
        ).all()
        for workflow in workflows:
            auto = workflow.definition.get("auto_disabled")
            if not auto or not isinstance(auto, dict):
                continue
            try:
                disabled_at = datetime.fromisoformat(str(auto.get("at", "")))
            except (ValueError, TypeError):
                continue
            if disabled_at and disabled_at <= cutoff:
                definition = dict(workflow.definition)
                cycles = list(definition.get("self_heal_cycles") or [])
                if cycles and cycles[-1].get("reenabled") is None:
                    cycles[-1] = {
                        **cycles[-1],
                        "reenabled": _now().isoformat(timespec="seconds"),
                    }
                definition.pop("auto_disabled", None)
                if cycles:
                    definition["self_heal_cycles"] = cycles
                workflow.enabled = True
                workflow.definition = definition
                await session.commit()
                reenabled["workflows"] += 1
                try:
                    get_bus().dispatch(
                        WorkflowAutoReenabled(
                            workflow_id=workflow.id,
                            workflow_name=workflow.name,
                            reason="停用冷却期结束，已自动恢复",
                        )
                    )
                except RuntimeError:
                    pass
    if reenabled["tasks"] or reenabled["workflows"]:
        logger.info(
            "auto re-enabled tasks=%s workflows=%s",
            reenabled["tasks"],
            reenabled["workflows"],
        )
    return reenabled


async def _record_command_stat(
    *,
    user_id: str,
    group_id: str | None,
    command_name: str,
    success: bool,
) -> None:
    metrics.inc("commands_total")
    if not success:
        metrics.inc("commands_failed_total")
    try:
        async with session_factory()() as session:
            session.add(
                CommandStat(
                    user_id=user_id,
                    group_id=group_id,
                    command_name=command_name,
                    success=success,
                )
            )
            user = await session.get(User, user_id)
            if user is None:
                session.add(
                    User(
                        user_id=user_id,
                        command_count=1,
                    )
                )
            else:
                user.command_count += 1
                user.last_active = _now()
            await session.commit()
    except Exception:
        logger.exception("failed to record command stat")


async def _persist_audit(
    *,
    action: str,
    actor: str,
    target: str,
    success: bool,
    detail: dict[str, Any],
) -> None:
    try:
        async with session_factory()() as session:
            session.add(
                AuditLog(
                    action=action,
                    actor=actor,
                    target=target,
                    success=success,
                    detail=detail,
                )
            )
            await session.commit()
    except Exception:
        logger.exception("failed to persist audit log")


def build_ai_service(settings: Settings) -> AIService:
    """根据配置注册 AI Provider 并返回服务实例。"""
    ai_service = AIService()
    ai_service.register(MockAIProvider())
    real_providers: list[str] = []
    openai_cfg = settings.plugin_configs.get("ai", {}).get("openai", {})
    if openai_cfg.get("api_key"):
        ai_service.register(
            OpenAIChatProvider(
                base_url=openai_cfg.get("base_url", "https://api.openai.com/v1"),
                api_key=openai_cfg["api_key"],
                model=openai_cfg.get("model", "gpt-4o-mini"),
            )
        )
        real_providers.append("openai")
    anthropic_cfg = settings.plugin_configs.get("ai", {}).get("anthropic", {})
    if anthropic_cfg.get("api_key"):
        ai_service.register(
            AnthropicProvider(
                api_key=anthropic_cfg["api_key"],
                model=anthropic_cfg.get("model", "claude-3-5-sonnet-latest"),
            )
        )
        real_providers.append("anthropic")
    gemini_cfg = settings.plugin_configs.get("ai", {}).get("gemini", {})
    if gemini_cfg.get("api_key"):
        ai_service.register(
            GeminiProvider(
                api_key=gemini_cfg["api_key"],
                model=gemini_cfg.get("model", "gemini-1.5-flash"),
            )
        )
        real_providers.append("gemini")
    ollama_cfg = settings.plugin_configs.get("ai", {}).get("ollama", {})
    if ollama_cfg.get("base_url"):
        ai_service.register(
            OllamaProvider(
                base_url=ollama_cfg.get("base_url", "http://127.0.0.1:11434"),
                model=ollama_cfg.get("model", "qwen2.5:7b"),
            )
        )
        real_providers.append("ollama")
    if real_providers:
        ai_service.set_active(real_providers[-1])

    return ai_service


def build_adapters(
    settings: Settings,
    bot_client: BotClient,
    existing_onebot: OneBotAdapter | None = None,
) -> tuple[list[Any], list[tuple[str, Any]]]:
    """按连接配置列表构建适配器；返回 (需自启动的适配器, 反向 WS 路由列表)。"""
    from app.adapters.mirai import MiraiAdapter
    from app.adapters.onebot_v12 import OneBotV12Adapter
    from app.adapters.qq_official import OfficialQQAdapter
    from app.adapters.satori import SatoriAdapter

    adapters: list[Any] = []
    reverse_routes: list[tuple[str, Any]] = []
    for conn in settings.transport.connections:
        if not conn.enabled:
            continue
        if conn.protocol == "red":
            if not conn.token:
                logger.warning(
                    "red connection %s enabled but token is empty; adapter will not start",
                    conn.id,
                )
                continue
            adapter = RedAdapter(conn, bot_id=conn.id, bot_client=bot_client)
        elif conn.protocol == "onebot" and conn.version == "v12":
            adapter = OneBotV12Adapter(conn, bot_id=conn.id, bot_client=bot_client)
        elif conn.protocol == "onebot":
            adapter = OneBotAdapter(conn, bot_id=conn.id, bot_client=bot_client)
        elif conn.protocol == "satori":
            adapter = SatoriAdapter(conn, bot_id=conn.id, bot_client=bot_client)
        elif conn.protocol == "mirai":
            adapter = MiraiAdapter(conn, bot_id=conn.id, bot_client=bot_client)
        elif conn.protocol == "qq_official":
            adapter = OfficialQQAdapter(conn, bot_id=conn.id, bot_client=bot_client)
        else:
            logger.warning("unknown connection protocol: %s", conn.protocol)
            continue
        bot_client.register(conn.id, adapter)
        if (
            getattr(adapter, "handle_reverse_ws", None)
            and conn.mode in {"reverse", "reverse_ws"}
        ):
            reverse_routes.append((conn.path or "/onebot/v11/ws", adapter))
        else:
            adapters.append(adapter)
    return adapters, reverse_routes

