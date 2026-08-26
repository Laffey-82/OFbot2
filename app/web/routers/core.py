"""核心页面路由：健康检查、监控指标、仪表盘。"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    Request,
)
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
)
from sqlalchemy import func, select, text

from app.core.config import Settings
from app.core.logger import get_logger
from app.core.observability import get_system_metrics, metrics
from app.db.base import session_factory
from app.db.models import (
    AlertEvent,
    AuditLog,
    CommandStat,
    Group,
    Record,
    Task,
    User,
    WebAccount,
    WebhookEvent,
    Workflow,
    WorkflowRun,
)
from app.web.deps import get_current_user
from app.web.helpers import admin_uses_default_password

logger = get_logger(__name__)


def build_router(*, app: FastAPI, settings: Settings, templates: Any) -> APIRouter:
    router = APIRouter()

    @router.get("/health/live")
    async def health_live() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/health/ready")
    async def health_ready() -> Any:
        try:
            async with session_factory()() as session:
                await session.execute(text("SELECT 1"))
        except Exception:
            return JSONResponse(status_code=503, content={"status": "unavailable"})
        return {"status": "ready", "database": "ok"}

    @router.get("/metrics")
    async def metrics_endpoint() -> Any:
        for key, value in get_system_metrics().items():
            metrics.set_gauge(key, value)
        return PlainTextResponse(metrics.prometheus_text())

    @router.get("/favicon.ico", include_in_schema=False)
    async def favicon() -> Any:
        return RedirectResponse("/static/favicon.svg")

    @router.get("/", response_class=HTMLResponse)
    async def dashboard(
        request: Request, user: WebAccount = Depends(get_current_user)
    ) -> HTMLResponse:
        async with session_factory()() as session:
            total_users = await session.scalar(select(func.count()).select_from(User))
            total_groups = await session.scalar(select(func.count()).select_from(Group))
            total_commands = await session.scalar(select(func.count()).select_from(CommandStat))
            total_tasks = await session.scalar(select(func.count()).select_from(Task))
            failed_tasks = (
                await session.scalar(
                    select(func.count())
                    .select_from(Task)
                    .where(Task.status == "failed")
                )
            ) or 0
            running_tasks = (
                await session.scalar(
                    select(func.count())
                    .select_from(Task)
                    .where(Task.status == "running")
                )
            ) or 0
            total_records = await session.scalar(select(func.count()).select_from(Record))
            total_workflows = await session.scalar(
                select(func.count()).select_from(Workflow)
            )
            failed_runs = await session.scalar(
                select(func.count())
                .select_from(WorkflowRun)
                .where(WorkflowRun.status == "failed")
            )
            recent_audit = (
                await session.scalars(
                    select(AuditLog)
                    .order_by(AuditLog.timestamp.desc())
                    .limit(8)
                )
            ).all()
            recent_runs = (
                await session.scalars(
                    select(WorkflowRun)
                    .order_by(WorkflowRun.created_at.desc())
                    .limit(8)
                )
            ).all()
            recent_alerts = (
                await session.scalars(
                    select(AlertEvent)
                    .order_by(AlertEvent.created_at.desc())
                    .limit(8)
                )
            ).all()
            recent_webhooks = (
                await session.scalars(
                    select(WebhookEvent)
                    .order_by(WebhookEvent.created_at.desc())
                    .limit(8)
                )
            ).all()
            from datetime import timedelta

            trend_cutoff = datetime.now(UTC) - timedelta(days=30)
            trend_rows = (
                await session.execute(
                    select(
                        func.date(CommandStat.timestamp).label("day"),
                        func.count().label("cnt"),
                    )
                    .where(CommandStat.timestamp >= trend_cutoff)
                    .group_by(func.date(CommandStat.timestamp))
                    .order_by(func.date(CommandStat.timestamp))
                )
            ).all()
            command_trend = [
                {"date": str(day), "count": cnt} for day, cnt in trend_rows
            ]
            today_start = datetime.now(UTC).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            today_commands = (
                await session.scalar(
                    select(func.count())
                    .select_from(CommandStat)
                    .where(CommandStat.timestamp >= today_start)
                )
            ) or 0
            yesterday_start = today_start - timedelta(days=1)
            yesterday_commands = (
                await session.scalar(
                    select(func.count())
                    .select_from(CommandStat)
                    .where(
                        CommandStat.timestamp >= yesterday_start,
                        CommandStat.timestamp < today_start,
                    )
                )
            ) or 0
        bot_client = getattr(app.state, "bot_client", None)
        adapters = getattr(bot_client, "status", {})
        plugins = (
            app.state.plugin_manager.get_loaded_plugins()
            if app.state.plugin_manager
            else []
        )
        scope_count = len(settings.runtime.scopes) if settings.runtime else 0
        needs_setup = await admin_uses_default_password()
        import platform
        import sys

        system_info = {
            "version": app.version,
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "database": settings.database.url,
            "uptime": time.time() - getattr(app.state, "started_at", time.time()),
        }
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "request": request,
                "user": user,
                "total_users": total_users,
                "scope_count": scope_count,
                "total_groups": total_groups,
                "total_commands": total_commands,
                "total_tasks": total_tasks,
                "failed_tasks": failed_tasks,
                "running_tasks": running_tasks,
                "total_records": total_records,
                "total_workflows": total_workflows,
                "failed_runs": failed_runs,
                "plugins": plugins,
                "adapters": adapters,
                "recent_audit": recent_audit,
                "recent_runs": recent_runs,
                "recent_alerts": recent_alerts,
                "recent_webhooks": recent_webhooks,
                "needs_setup": needs_setup,
                "system_info": system_info,
                "command_trend": command_trend,
                "today_commands": today_commands,
                "yesterday_commands": yesterday_commands,
            },
        )

    return router
