"""审计日志页面与导出路由。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    Form,
    Request,
)
from fastapi.responses import (
    HTMLResponse,
    RedirectResponse,
    Response,
)
from sqlalchemy import func, select

from app.core.config import Settings
from app.core.logger import get_logger
from app.db.base import session_factory
from app.db.models import AuditLog, WebAccount
from app.web.deps import (
    get_csrf_token,
    require_admin,
    require_csrf,
)
from app.web.export_jobs import _persist_export_job, _run_audit_export_job
from app.web.helpers import (
    _parse_date_range,
    flash_redirect,
)

logger = get_logger(__name__)


def build_router(*, app: FastAPI, settings: Settings, templates: Any) -> APIRouter:
    router = APIRouter()

    @router.get("/audit", response_class=HTMLResponse)
    async def audit_page(
        request: Request,
        user: WebAccount = Depends(require_admin),
        csrf_token: str = Depends(get_csrf_token),
        actor: str = "",
        action: str = "",
        success: str = "",
        start: str = "",
        end: str = "",
        page: int = 1,
    ) -> HTMLResponse:
        start_dt, end_dt = _parse_date_range(start, end)
        async with session_factory()() as session:
            query = select(AuditLog)
            if actor.strip():
                query = query.where(AuditLog.actor.contains(actor.strip()))
            if action.strip():
                query = query.where(AuditLog.action.contains(action.strip()))
            if success in {"1", "0"}:
                query = query.where(AuditLog.success == (success == "1"))
            if start_dt is not None:
                query = query.where(AuditLog.timestamp >= start_dt)
            if end_dt is not None:
                query = query.where(AuditLog.timestamp <= end_dt)
            total_logs = (
                await session.scalar(
                    select(func.count()).select_from(query.subquery())
                )
            ) or 0
            page_size = 50
            total_log_pages = max(
                1, (total_logs + page_size - 1) // page_size
            )
            page = max(1, min(page, total_log_pages))
            query = (
                query.order_by(AuditLog.timestamp.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            logs = (await session.scalars(query)).all()
        return templates.TemplateResponse(
            request,
            "audit.html",
            {
                "request": request,
                "user": user,
                "logs": logs,
                "filter_actor": actor,
                "filter_action": action,
                "filter_success": success,
                "filter_start": start,
                "filter_end": end,
                "page": page,
                "total_logs": total_logs,
                "total_log_pages": total_log_pages,
                "csrf_token": csrf_token,
            },
        )

    @router.get("/audit/export")
    async def audit_export(
        request: Request,
        user: WebAccount = Depends(require_admin),
        actor: str = "",
        action: str = "",
        success: str = "",
        start: str = "",
        end: str = "",
    ) -> Response:
        import csv
        import io
        import json as json_module

        start_dt, end_dt = _parse_date_range(start, end)
        async with session_factory()() as session:
            query = select(AuditLog)
            if actor.strip():
                query = query.where(AuditLog.actor.contains(actor.strip()))
            if action.strip():
                query = query.where(AuditLog.action.contains(action.strip()))
            if success in {"1", "0"}:
                query = query.where(AuditLog.success == (success == "1"))
            if start_dt is not None:
                query = query.where(AuditLog.timestamp >= start_dt)
            if end_dt is not None:
                query = query.where(AuditLog.timestamp <= end_dt)
            total_logs = (
                await session.scalar(
                    select(func.count()).select_from(query.subquery())
                )
            ) or 0
            export_limit = 2000
            query = (
                query.order_by(AuditLog.timestamp.desc()).limit(export_limit)
            )
            logs = (await session.scalars(query)).all()
        range_part = ""
        if start or end:
            range_part = f"_{start or 'begin'}_{end or 'now'}"
        filename = (
            f"audit{range_part}_"
            f"{datetime.now(UTC).strftime('%Y%m%d_%H%M')}_{total_logs}.csv"
        )
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        if total_logs > export_limit:
            writer.writerow(
                [
                    (
                        f"# 提示：当前筛选共 {total_logs} 条，"
                        f"本文件仅包含最新 {len(logs)} 条，请缩小日期范围后再次导出"
                    )
                ]
            )
        writer.writerow(["timestamp", "action", "actor", "target", "success", "detail"])
        for log in logs:
            writer.writerow(
                [
                    log.timestamp.isoformat() if log.timestamp else "",
                    log.action,
                    log.actor,
                    log.target,
                    "1" if log.success else "0",
                    json_module.dumps(log.detail, ensure_ascii=False)
                    if log.detail
                    else "",
                ]
            )
        return Response(
            buffer.getvalue().encode("utf-8-sig"),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @router.post("/audit/export-job")
    async def audit_export_job(
        request: Request,
        user: WebAccount = Depends(require_admin),
        actor: str = Form(""),
        action: str = Form(""),
        success: str = Form(""),
        start: str = Form(""),
        end: str = Form(""),
        fmt: str = Form("csv"),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        export_service = app.state.services.get("export")
        if export_service is None:
            return flash_redirect("/audit", error="1")
        if fmt not in {"csv", "json", "excel"}:
            return flash_redirect("/audit", error="1")
        job_id = uuid4().hex[:12]
        job: dict[str, Any] = {
            "id": job_id,
            "record_type": "audit",
            "fmt": fmt,
            "status": "pending",
            "message": "排队中",
            "total": 0,
            "done": 0,
            "filename": None,
            "created_at": datetime.now(UTC).isoformat(),
            "actor": user.username,
            "attempts": 0,
            "retries": 0,
        }
        app.state.export_jobs[job_id] = job
        await _persist_export_job(job)
        background = getattr(app.state, "background_worker", None)
        run = _run_audit_export_job(
            job,
            fmt=fmt,
            export_service=export_service,
            actor=user.username,
            actor_filter=actor,
            action=action,
            success=success,
            start=start,
            end=end,
        )
        if background is not None:
            await background.submit(f"audit-export-{job_id}", run)
        else:
            await run
        return flash_redirect(
            "/exports", message="审计导出任务已创建，完成后可在导出中心下载"
        )

    return router
