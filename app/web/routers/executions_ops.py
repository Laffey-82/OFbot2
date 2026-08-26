"""执行历史与自愈中心路由。"""

from __future__ import annotations

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
    Response,
)
from sqlalchemy import select

from app.core.config import Settings
from app.core.logger import get_logger
from app.db.base import session_factory
from app.db.models import (
    AlertEvent,
    Task,
    TaskRun,
    WebAccount,
    Workflow,
    WorkflowRun,
)
from app.web.deps import (
    get_csrf_token,
    get_current_user,
    require_admin,
)
from app.web.helpers import _parse_date_range, humanize_uptime

logger = get_logger(__name__)


async def _collect_executions(
    *,
    source: str = "",
    status: str = "",
    start: str = "",
    end: str = "",
    limit: int = 500,
) -> list[dict[str, Any]]:
    """合并定时任务运行与流程运行（统一执行历史数据源）。"""
    start_dt, end_dt = _parse_date_range(start, end)
    rows: list[dict[str, Any]] = []

    def _apply_filters(query: Any, model: Any) -> Any:
        if status:
            query = query.where(model.status == status)
        if start_dt is not None:
            query = query.where(model.created_at >= start_dt)
        if end_dt is not None:
            query = query.where(model.created_at <= end_dt)
        return query

    async with session_factory()() as session:
        task_flags: dict[str, bool] = {}
        workflow_flags: dict[int, bool] = {}
        if source in {"", "task"}:
            task_rows = (
                await session.scalars(
                    _apply_filters(select(TaskRun), TaskRun)
                    .order_by(TaskRun.created_at.desc())
                    .limit(limit)
                )
            ).all()
            task_ids = {item.task_id for item in task_rows}
            if task_ids:
                tasks = (
                    await session.scalars(
                        select(Task).where(Task.task_id.in_(task_ids))
                    )
                ).all()
                task_flags = {
                    item.task_id: bool(
                        item.params.get("auto_disabled")
                    )
                    for item in tasks
                }
            rows.extend(
                {
                    "time": item.created_at,
                    "source": "task",
                    "target": item.task_id,
                    "status": item.status,
                    "detail": item.message or "",
                    "link": "/tasks",
                    "task_id": item.task_id,
                    "workflow_id": "",
                    "auto_disabled": task_flags.get(item.task_id, False),
                }
                for item in task_rows
            )
        if source in {"", "workflow"}:
            wf_rows = (
                await session.scalars(
                    _apply_filters(select(WorkflowRun), WorkflowRun)
                    .order_by(WorkflowRun.created_at.desc())
                    .limit(limit)
                )
            ).all()
            wf_ids = {item.workflow_id for item in wf_rows}
            if wf_ids:
                workflows = (
                    await session.scalars(
                        select(Workflow).where(Workflow.id.in_(wf_ids))
                    )
                ).all()
                workflow_flags = {
                    item.id: bool(
                        item.definition.get("auto_disabled")
                    )
                    for item in workflows
                }
            rows.extend(
                {
                    "time": item.created_at,
                    "source": "workflow",
                    "target": f"#{item.workflow_id}",
                    "status": item.status,
                    "detail": (
                        item.result.get("error", "")
                        if isinstance(item.result, dict)
                        else ""
                    ),
                    "link": f"/workflows/runs/{item.id}",
                    "task_id": "",
                    "workflow_id": item.workflow_id,
                    "auto_disabled": workflow_flags.get(
                        item.workflow_id, False
                    ),
                }
                for item in wf_rows
            )
    rows.sort(
        key=lambda row: row["time"]
        or datetime(1970, 1, 1, tzinfo=UTC),
        reverse=True,
    )
    return rows


async def _self_heal_data() -> dict[str, Any]:
    """自愈中心数据：当前停用实体、近 7 天事件与统计。"""
    from datetime import timedelta

    events_filter = [
        "task.auto_disabled",
        "workflow.auto_disabled",
        "task.auto_reenabled",
        "workflow.auto_reenabled",
    ]
    cutoff = datetime.now(UTC) - timedelta(days=7)
    closed_durations: list[float] = []

    def _closed_cycle_seconds(cycle: Any) -> float | None:
        """已恢复周期的停用时长（秒），未闭合或非法周期返回 None。"""
        if not isinstance(cycle, dict):
            return None
        disabled = cycle.get("disabled")
        reenabled = cycle.get("reenabled")
        if not disabled or not reenabled:
            return None
        try:
            start = datetime.fromisoformat(str(disabled))
            end = datetime.fromisoformat(str(reenabled))
        except (ValueError, TypeError):
            return None
        seconds = (end - start).total_seconds()
        return seconds if seconds >= 0 else None

    async with session_factory()() as session:
        disabled_tasks = (
            await session.scalars(
                select(Task).where(Task.enabled.is_(False))
            )
        ).all()
        disabled_tasks = [
            task
            for task in disabled_tasks
            if task.params.get("auto_disabled")
        ]
        disabled_workflows = (
            await session.scalars(
                select(Workflow).where(Workflow.enabled.is_(False))
            )
        ).all()
        disabled_workflows = [
            workflow
            for workflow in disabled_workflows
            if workflow.definition.get("auto_disabled")
        ]
        all_tasks = (await session.scalars(select(Task))).all()
        all_workflows = (await session.scalars(select(Workflow))).all()
        events = (
            await session.scalars(
                select(AlertEvent)
                .where(
                    AlertEvent.event.in_(events_filter),
                    AlertEvent.created_at >= cutoff,
                )
                .order_by(AlertEvent.created_at.desc())
                .limit(50)
            )
        ).all()
    for item in all_tasks:
        for cycle in item.params.get("self_heal_cycles") or []:
            seconds = _closed_cycle_seconds(cycle)
            if seconds is not None:
                closed_durations.append(seconds)
    for item in all_workflows:
        for cycle in item.definition.get("self_heal_cycles") or []:
            seconds = _closed_cycle_seconds(cycle)
            if seconds is not None:
                closed_durations.append(seconds)
    disabled_events = sum(
        1
        for item in events
        if item.event in ("task.auto_disabled", "workflow.auto_disabled")
    )
    reenabled_events = sum(
        1
        for item in events
        if item.event in ("task.auto_reenabled", "workflow.auto_reenabled")
    )
    total_events = disabled_events + reenabled_events
    recovery_rate = (
        round((reenabled_events / total_events) * 100)
        if total_events
        else 0
    )
    avg_seconds = (
        round(sum(closed_durations) / len(closed_durations))
        if closed_durations
        else 0
    )
    return {
        "disabled_tasks": list(disabled_tasks),
        "disabled_workflows": list(disabled_workflows),
        "events": list(events),
        "stats": {
            "disabled_tasks": len(disabled_tasks),
            "disabled_workflows": len(disabled_workflows),
            "disabled_events": disabled_events,
            "reenabled_events": reenabled_events,
            "recovery_rate": recovery_rate,
            "closed_cycles": len(closed_durations),
            "avg_downtime_seconds": avg_seconds,
            "avg_downtime_text": (
                humanize_uptime(avg_seconds) if avg_seconds else "—"
            ),
        },
    }


def build_router(*, app: FastAPI, settings: Settings, templates: Any) -> APIRouter:
    router = APIRouter()

    @router.get("/executions", response_class=HTMLResponse)
    async def executions_page(
        request: Request,
        user: WebAccount = Depends(get_current_user),
        csrf_token: str = Depends(get_csrf_token),
        source: str = "",
        status: str = "",
        start: str = "",
        end: str = "",
        page: int = 1,
    ) -> HTMLResponse:
        """统一执行历史：定时任务运行与流程运行合并视图。"""
        page_size = 50
        rows = await _collect_executions(
            source=source,
            status=status,
            start=start,
            end=end,
        )
        total = len(rows)
        total_pages = max(1, (total + page_size - 1) // page_size)
        page = max(1, min(page, total_pages))
        visible = rows[(page - 1) * page_size : page * page_size]
        return templates.TemplateResponse(
            request,
            "executions.html",
            {
                "request": request,
                "user": user,
                "rows": visible,
                "source": source,
                "status": status,
                "filter_start": start,
                "filter_end": end,
                "page": page,
                "total": total,
                "total_pages": total_pages,
                "csrf_token": csrf_token,
            },
        )

    @router.get("/executions/export")
    async def executions_export(
        request: Request,
        user: WebAccount = Depends(require_admin),
        source: str = "",
        status: str = "",
        start: str = "",
        end: str = "",
    ) -> Response:
        import csv
        import io

        rows = await _collect_executions(
            source=source,
            status=status,
            start=start,
            end=end,
        )
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["timestamp", "source", "target", "status", "detail"])
        for row in rows:
            writer.writerow(
                [
                    row["time"].isoformat() if row["time"] else "",
                    row["source"],
                    row["target"],
                    row["status"],
                    row["detail"],
                ]
            )
        range_part = ""
        if start or end:
            range_part = f"_{start or 'begin'}_{end or 'now'}"
        filename = (
            f"executions{range_part}_"
            f"{datetime.now(UTC).strftime('%Y%m%d_%H%M')}_{len(rows)}.csv"
        )
        return Response(
            buffer.getvalue().encode("utf-8-sig"),
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            },
        )

    @router.get("/self-heal", response_class=HTMLResponse)
    async def self_heal_page(
        request: Request,
        user: WebAccount = Depends(get_current_user),
        csrf_token: str = Depends(get_csrf_token),
    ) -> HTMLResponse:
        data = await _self_heal_data()
        return templates.TemplateResponse(
            request,
            "self_heal.html",
            {
                "request": request,
                "user": user,
                "disabled_tasks": data["disabled_tasks"],
                "disabled_workflows": data["disabled_workflows"],
                "events": data["events"],
                "stats": data["stats"],
                "csrf_token": csrf_token,
            },
        )

    return router
