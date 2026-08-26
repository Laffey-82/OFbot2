"""导出任务编排：记录/审计后台导出、任务持久化与失败重试。"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from sqlalchemy import select

from app.core.logger import get_logger
from app.core.security import audit_logger
from app.db.base import session_factory
from app.db.models import AuditLog, ExportJob
from app.web.helpers import _parse_date_range

logger = get_logger(__name__)


def _export_job_from_row(row: Any) -> dict[str, Any]:
    """从数据库导出任务行还原为任务字典（用于重试）。"""
    return {
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
        "attempts": 0,
        "retries": 0,
    }


async def _run_export_job(
    job: dict[str, Any],
    *,
    record_type: str,
    fmt: str,
    export_service: Any,
    records_service: Any,
    actor: str,
) -> None:
    job["status"] = "running"
    job["message"] = "读取记录…"
    try:
        items = await records_service.list(record_type=record_type, limit=10000)
        rows: list[dict[str, Any]] = []
        for item in items:
            row: dict[str, Any] = {
                "id": item.id,
                "status": item.status,
                "created_at": str(item.created_at),
            }
            row.update(item.data or {})
            rows.append(row)
        job["total"] = len(rows)
        job["done"] = len(rows)
        job["message"] = "写入文件…"
        name = f"records_{record_type}_{int(time.time())}"
        if fmt == "json":
            export_service.export_json(rows, name)
        elif fmt == "csv":
            export_service.export_csv(rows, name)
        elif fmt == "excel":
            export_service.export_excel(rows, name)
        else:
            export_service.export_docx(rows, name, title=record_type)
        ext = {"csv": "csv", "json": "json", "excel": "xlsx", "docx": "docx"}[fmt]
        job["filename"] = f"{name}.{ext}"
        job["status"] = "done"
        job["message"] = f"完成，共 {len(rows)} 条"
        audit_logger.record(
            "export.created",
            actor,
            target=f"{record_type}.{fmt}",
            success=True,
            detail={"rows": len(rows)},
        )
    except Exception as exc:
        job["status"] = "failed"
        job["message"] = str(exc)
        logger.exception("background export failed: %s", job.get("id"))
    await _persist_export_job(job)


async def _persist_export_job(job: dict[str, Any]) -> None:
    """将导出任务写入数据库，保证重启后历史保留。"""
    try:
        async with session_factory()() as session:
            row = await session.scalar(
                select(ExportJob).where(ExportJob.job_id == job["id"])
            )
            if row is None:
                session.add(
                    ExportJob(
                        job_id=job["id"],
                        record_type=job.get("record_type", ""),
                        fmt=job.get("fmt", "csv"),
                        status=job.get("status", "pending"),
                        message=job.get("message", ""),
                        filename=job.get("filename"),
                        actor=job.get("actor", ""),
                    )
                )
            else:
                row.status = job.get("status", row.status)
                row.message = job.get("message", row.message)
                row.filename = job.get("filename")
            await session.commit()
    except Exception:
        logger.exception("failed to persist export job")


async def _submit_export_retry(
    app: Any,
    job: dict[str, Any],
    actor: str,
    *,
    settings: Any,
) -> None:
    """将失败的导出任务重新排队执行（仅记录类型导出，审计任务需在审计页重建）。"""
    export_service = app.state.services.get("export")
    records_service = app.state.services.get("records")
    if export_service is None or records_service is None:
        job["status"] = "failed"
        job["message"] = "导出服务不可用，无法重试"
        return
    retries = max(0, int(job.get("retries", settings.web.export_retries)))

    async def run_export() -> None:
        for attempt in range(retries + 1):
            job["attempts"] = attempt
            await _run_export_job(
                job,
                record_type=job["record_type"],
                fmt=job["fmt"],
                export_service=export_service,
                records_service=records_service,
                actor=actor,
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
        await background.submit(f"export-{job['id']}", run_export())
    else:
        await run_export()


async def _run_audit_export_job(
    job: dict[str, Any],
    *,
    fmt: str,
    export_service: Any,
    actor: str,
    actor_filter: str = "",
    action: str = "",
    success: str = "",
    start: str = "",
    end: str = "",
) -> None:
    """后台导出审计日志，避免大结果集阻塞请求。"""
    import json as json_module

    job["status"] = "running"
    job["message"] = "查询审计记录…"
    try:
        start_dt, end_dt = _parse_date_range(start, end)
        async with session_factory()() as session:
            query = select(AuditLog)
            if actor_filter.strip():
                query = query.where(AuditLog.actor.contains(actor_filter.strip()))
            if action.strip():
                query = query.where(AuditLog.action.contains(action.strip()))
            if success in {"1", "0"}:
                query = query.where(AuditLog.success == (success == "1"))
            if start_dt is not None:
                query = query.where(AuditLog.timestamp >= start_dt)
            if end_dt is not None:
                query = query.where(AuditLog.timestamp <= end_dt)
            query = query.order_by(AuditLog.timestamp.desc()).limit(50000)
            logs = (await session.scalars(query)).all()
        rows: list[dict[str, Any]] = []
        for log in logs:
            rows.append(
                {
                    "timestamp": log.timestamp.isoformat() if log.timestamp else "",
                    "action": log.action,
                    "actor": log.actor,
                    "target": log.target,
                    "success": "1" if log.success else "0",
                    "detail": (
                        json_module.dumps(log.detail, ensure_ascii=False)
                        if log.detail
                        else ""
                    ),
                }
            )
        job["total"] = len(rows)
        job["done"] = len(rows)
        job["message"] = "写入文件…"
        name = f"audit_{int(time.time())}"
        if fmt == "json":
            export_service.export_json(rows, name)
        elif fmt == "excel":
            export_service.export_excel(rows, name)
        else:
            export_service.export_csv(rows, name)
        ext = {"csv": "csv", "json": "json", "excel": "xlsx"}[fmt]
        job["filename"] = f"{name}.{ext}"
        job["status"] = "done"
        job["message"] = f"完成，共 {len(rows)} 条"
        audit_logger.record(
            "audit.exported",
            actor,
            target=f"audit.{fmt}",
            success=True,
            detail={"rows": len(rows)},
        )
    except Exception as exc:
        job["status"] = "failed"
        job["message"] = str(exc)
        logger.exception("background audit export failed: %s", job.get("id"))
    await _persist_export_job(job)
