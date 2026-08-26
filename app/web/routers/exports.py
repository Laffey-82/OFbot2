"""导出中心页面与任务路由。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    Form,
    HTTPException,
    Request,
)
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)
from sqlalchemy import select

from app.core.config import Settings
from app.core.logger import get_logger
from app.core.security import audit_logger
from app.db.base import session_factory
from app.db.models import ExportJob, WebAccount
from app.web.deps import (
    get_csrf_token,
    get_current_user,
    require_admin,
    require_csrf,
)
from app.web.export_jobs import (
    _export_job_from_row,
    _persist_export_job,
    _run_export_job,
    _submit_export_retry,
)
from app.web.helpers import (
    flash_redirect,
)

logger = get_logger(__name__)


def build_router(*, app: FastAPI, settings: Settings, templates: Any) -> APIRouter:
    router = APIRouter()

    @router.get("/exports", response_class=HTMLResponse)
    async def exports_page(
        request: Request,
        user: WebAccount = Depends(get_current_user),
        csrf_token: str = Depends(get_csrf_token),
    ) -> HTMLResponse:
        service = app.state.services.get("export")
        files = service.list_files() if service else []
        schemas = app.state.services.get("schema_registry")
        types = schemas.list() if schemas else []
        jobs = sorted(
            app.state.export_jobs.values(),
            key=lambda job: job.get("created_at", ""),
            reverse=True,
        )[:20]
        live_jobs = {job["id"]: job for job in app.state.export_jobs.values()}
        async with session_factory()() as session:
            rows = (
                await session.scalars(
                    select(ExportJob)
                    .order_by(ExportJob.created_at.desc())
                    .limit(50)
                )
            ).all()
        merged: dict[str, dict[str, Any]] = {}
        for row in rows:
            merged[row.job_id] = {
                "id": row.job_id,
                "record_type": row.record_type,
                "fmt": row.fmt,
                "status": row.status,
                "message": row.message,
                "filename": row.filename,
                "actor": row.actor,
                "created_at": (
                    row.created_at.isoformat() if row.created_at else ""
                ),
            }
        merged.update(live_jobs)
        jobs = sorted(
            merged.values(), key=lambda job: job.get("created_at", ""), reverse=True
        )[:20]
        return templates.TemplateResponse(
            request,
            "exports.html",
            {
                "request": request,
                "user": user,
                "files": files,
                "types": types,
                "jobs": jobs,
                "csrf_token": csrf_token,
            },
        )

    @router.post("/exports/create")
    async def exports_create(
        request: Request,
        user: WebAccount = Depends(require_admin),
        record_type: str = Form(...),
        fmt: str = Form("csv"),
        retries: int = Form(-1),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        export_service = app.state.services.get("export")
        records_service = app.state.services.get("records")
        if export_service is None or records_service is None:
            return flash_redirect("/exports", error="1")
        if fmt not in {"csv", "json", "excel", "docx"}:
            return flash_redirect("/exports", error="1")
        job_id = uuid4().hex[:12]
        job: dict[str, Any] = {
            "id": job_id,
            "record_type": record_type,
            "fmt": fmt,
            "status": "pending",
            "message": "排队中",
            "total": 0,
            "done": 0,
            "filename": None,
            "created_at": datetime.now(UTC).isoformat(),
            "actor": user.username,
            "attempts": 0,
            "retries": retries if retries >= 0 else settings.web.export_retries,
        }
        app.state.export_jobs[job_id] = job
        await _persist_export_job(job)
        finished = [
            key
            for key, item in app.state.export_jobs.items()
            if item.get("status") in {"done", "failed"}
        ]
        retention = settings.web.export_job_retention
        if len(finished) > retention:
            for key in finished[: len(finished) - retention]:
                app.state.export_jobs.pop(key, None)

        retries = max(0, int(job.get("retries", settings.web.export_retries)))

        async def run_export() -> None:
            for attempt in range(retries + 1):
                job["attempts"] = attempt
                await _run_export_job(
                    job,
                    record_type=record_type,
                    fmt=fmt,
                    export_service=export_service,
                    records_service=records_service,
                    actor=user.username,
                )
                if job["status"] != "failed":
                    break
                if attempt < retries:
                    job["status"] = "pending"
                    job["message"] = f"失败，自动重试 {attempt + 1}/{retries}…"
                    await _persist_export_job(job)
                    await asyncio.sleep(0.5)
            if job["status"] == "pending":
                job["status"] = "failed"
                job["message"] = "重试次数用尽"
                await _persist_export_job(job)

        background = getattr(app.state, "background_worker", None)
        if background is not None:
            await background.submit(f"export-{job_id}", run_export())
        else:
            await run_export()
        return flash_redirect("/exports", message="导出任务已创建")

    @router.post("/exports/jobs/clear")
    async def exports_jobs_clear(
        request: Request,
        user: WebAccount = Depends(require_admin),
        keep_failed: str = Form("off"),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        from datetime import timedelta

        retention_days = settings.web.export_job_retention_days
        cutoff = None
        if retention_days > 0:
            cutoff = datetime.now(UTC) - timedelta(days=retention_days)

        def is_old(job: dict[str, Any]) -> bool:
            if cutoff is None:
                return True
            try:
                created = datetime.fromisoformat(str(job.get("created_at", "")))
                return created < cutoff
            except ValueError:
                return True

        for key in list(app.state.export_jobs):
            status = app.state.export_jobs[key].get("status")
            if (
                status == "done"
                or (status == "failed" and keep_failed != "on")
            ) and is_old(app.state.export_jobs[key]):
                app.state.export_jobs.pop(key, None)
        async with session_factory()() as session:
            from sqlalchemy import delete

            delete_query = delete(ExportJob)
            if keep_failed == "on":
                delete_query = delete_query.where(ExportJob.status == "done")
            if cutoff is not None:
                delete_query = delete_query.where(
                    ExportJob.created_at < cutoff
                )
            if keep_failed == "on" or cutoff is not None:
                await session.execute(
                    delete_query
                )
            else:
                await session.execute(delete(ExportJob))
            await session.commit()
        message = "已完成任务已清除"
        if cutoff is not None:
            message += f"（保留近 {retention_days} 天）"
        return flash_redirect("/exports", message=message)

    @router.post("/exports/jobs/{job_id}/retry")
    async def exports_jobs_retry(
        job_id: str,
        request: Request,
        user: WebAccount = Depends(require_admin),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        job = app.state.export_jobs.get(job_id)
        if job is None:
            async with session_factory()() as session:
                row = await session.scalar(
                    select(ExportJob).where(ExportJob.job_id == job_id)
                )
            if row is None:
                return flash_redirect("/exports", error="1")
            job = _export_job_from_row(row)
            app.state.export_jobs[job_id] = job
        if job.get("status") != "failed":
            return flash_redirect("/exports", message="仅失败任务可重试")
        if job.get("record_type") == "audit":
            return flash_redirect(
                "/exports", message="审计导出任务请在审计页重新创建"
            )
        await _submit_export_retry(
            app, job, user.username, settings=settings
        )
        return flash_redirect("/exports", message="导出任务已重新排队")

    @router.post("/exports/jobs/retry-failed")
    async def exports_jobs_retry_failed(
        request: Request,
        user: WebAccount = Depends(require_admin),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        queued = 0
        skipped = 0
        seen: set[str] = set()
        for job in list(app.state.export_jobs.values()):
            if job.get("status") != "failed":
                continue
            if job.get("record_type") == "audit":
                skipped += 1
                continue
            seen.add(job["id"])
            await _submit_export_retry(
                app, job, user.username, settings=settings
            )
            queued += 1
        async with session_factory()() as session:
            rows = (
                await session.scalars(
                    select(ExportJob).where(ExportJob.status == "failed")
                )
            ).all()
        for row in rows:
            if row.job_id in seen or row.job_id in app.state.export_jobs:
                continue
            job = _export_job_from_row(row)
            if job["record_type"] == "audit":
                skipped += 1
                continue
            app.state.export_jobs[job["id"]] = job
            await _submit_export_retry(
                app, job, user.username, settings=settings
            )
            queued += 1
        audit_logger.record(
            "export.jobs_bulk_retried",
            user.username,
            target=f"queued={queued} skipped={skipped}",
            success=queued > 0,
        )
        message = f"已重新排队 {queued} 个失败任务"
        if skipped:
            message += f"，跳过 {skipped} 个审计导出（请在审计页重新创建）"
        return flash_redirect("/exports", message=message)

    @router.get("/exports/jobs")
    async def exports_jobs(
        request: Request,
        user: WebAccount = Depends(get_current_user),
        actor: str = "",
    ) -> JSONResponse:
        live_jobs = {job["id"]: job for job in app.state.export_jobs.values()}
        query = select(ExportJob)
        if actor:
            query = query.where(ExportJob.actor == actor)
        async with session_factory()() as session:
            rows = (
                await session.scalars(
                    query
                    .order_by(ExportJob.created_at.desc())
                    .limit(50)
                )
            ).all()
        merged: dict[str, dict[str, Any]] = {}
        for row in rows:
            merged[row.job_id] = {
                "id": row.job_id,
                "record_type": row.record_type,
                "fmt": row.fmt,
                "status": row.status,
                "message": row.message,
                "filename": row.filename,
                "actor": row.actor,
                "created_at": (
                    row.created_at.isoformat() if row.created_at else ""
                ),
            }
        merged.update(live_jobs)
        if actor:
            merged = {
                key: job
                for key, job in merged.items()
                if job.get("actor") == actor
            }
        jobs = sorted(
            merged.values(), key=lambda job: job.get("created_at", ""), reverse=True
        )[:20]
        return JSONResponse({"jobs": jobs})

    @router.get("/exports/{name}/download")
    async def exports_download(
        name: str,
        user: WebAccount = Depends(get_current_user),
    ) -> Any:
        from fastapi.responses import FileResponse

        service = app.state.services.get("export")
        if service is None:
            raise HTTPException(status_code=404, detail="export service unavailable")
        path = service.resolve_path(name)
        if not path.exists():
            raise HTTPException(status_code=404, detail="file not found")
        return FileResponse(path)

    @router.post("/exports/{name}/delete")
    async def exports_delete(
        name: str,
        request: Request,
        user: WebAccount = Depends(require_admin),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        service = app.state.services.get("export")
        if service is None or not service.delete_file(name):
            return flash_redirect("/exports", error="1")
        audit_logger.record(
            "export.deleted", user.username, target=name, success=True
        )
        return flash_redirect("/exports", message=f"导出文件 {name} 已删除")

    @router.post("/exports/bulk-download")
    async def exports_bulk_download(
        request: Request,
        user: WebAccount = Depends(require_admin),
        names: list[str] = Form(default=[]),
        all_files: str = Form("off"),
        csrf: None = Depends(require_csrf),
    ) -> Any:
        from io import BytesIO
        from zipfile import ZIP_DEFLATED, ZipFile

        service = app.state.services.get("export")
        if service is None:
            return flash_redirect("/exports", error="1")
        if all_files == "on":
            names = [file["name"] for file in service.list_files()]
        names = names[:200]
        resolved = []
        for name in names:
            try:
                path = service.resolve_path(name)
            except Exception as exc:
                logger.warning("skip invalid export path %s: %s", name, exc)
                continue
            if path.exists():
                resolved.append((name, path))
        if not resolved:
            return flash_redirect("/exports", error="1")
        buffer = BytesIO()
        with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
            for name, path in resolved:
                archive.write(path, arcname=name)
        audit_logger.record(
            "export.bulk_downloaded",
            user.username,
            target=f"exports:{len(resolved)}",
            success=True,
        )
        stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M")
        return Response(
            buffer.getvalue(),
            media_type="application/zip",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="exports_{stamp}_{len(resolved)}.zip"'
                )
            },
        )

    @router.post("/exports/bulk-delete")
    async def exports_bulk_delete(
        request: Request,
        user: WebAccount = Depends(require_admin),
        names: list[str] = Form(default=[]),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        service = app.state.services.get("export")
        if service is None:
            return flash_redirect("/exports", error="1")
        deleted = 0
        for name in names[:200]:
            if service.delete_file(name):
                deleted += 1
        audit_logger.record(
            "export.bulk_deleted",
            user.username,
            target=f"exports:{deleted}",
            success=True,
        )
        return flash_redirect(
            "/exports", message=f"已删除 {deleted} 个导出文件"
        )

    return router
