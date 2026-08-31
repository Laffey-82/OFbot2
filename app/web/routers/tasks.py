"""定时任务与执行历史路由。"""

from __future__ import annotations

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

from app.core.config import Settings, save_settings
from app.core.logger import get_logger
from app.core.security import audit_logger
from app.db.base import session_factory
from app.db.models import Task, TaskRun, WebAccount
from app.web.deps import (
    get_csrf_token,
    get_current_user,
    require_admin,
    require_csrf,
)
from app.web.helpers import (
    _parse_date_range,
    _task_executor,
    flash_redirect,
)

logger = get_logger(__name__)


def build_router(*, app: FastAPI, settings: Settings, templates: Any) -> APIRouter:
    router = APIRouter()

    @router.get("/tasks", response_class=HTMLResponse)
    async def tasks_page(
        request: Request,
        user: WebAccount = Depends(get_current_user),
        csrf_token: str = Depends(get_csrf_token),
        runs_page: int = 1,
        runs_start: str = "",
        runs_end: str = "",
    ) -> HTMLResponse:
        runs_per_page = 30
        async with session_factory()() as session:
            tasks = (await session.scalars(select(Task).order_by(Task.created_at.desc()).limit(200))).all()
            runs_where = []
            start_dt, end_dt = _parse_date_range(runs_start, runs_end)
            if start_dt is not None:
                runs_where.append(TaskRun.created_at >= start_dt)
            if end_dt is not None:
                runs_where.append(TaskRun.created_at <= end_dt)
            runs_query = select(func.count()).select_from(TaskRun)
            if runs_where:
                runs_query = runs_query.where(*runs_where)
            total_runs = await session.scalar(runs_query) or 0
            succeeded_runs = (
                await session.scalar(
                    select(func.count())
                    .select_from(TaskRun)
                    .where(TaskRun.status == "succeeded")
                )
            ) or 0
            failed_runs_total = (
                await session.scalar(
                    select(func.count())
                    .select_from(TaskRun)
                    .where(TaskRun.status == "failed")
                )
            ) or 0
            total_runs_pages = max(1, (total_runs + runs_per_page - 1) // runs_per_page)
            runs_page = max(1, min(runs_page, total_runs_pages))
            runs_select = select(TaskRun)
            if runs_where:
                runs_select = runs_select.where(*runs_where)
            runs = (
                await session.scalars(
                    runs_select
                    .order_by(TaskRun.created_at.desc())
                    .offset((runs_page - 1) * runs_per_page)
                    .limit(runs_per_page)
                )
            ).all()
        manager = getattr(app.state, "plugin_manager", None)
        plugin_tasks = (
            manager.task_registry.list()
            if manager is not None and manager.task_registry is not None
            else []
        )
        return templates.TemplateResponse(
            request,
            "tasks.html",
            {
                "request": request,
                "user": user,
                "tasks": tasks,
                "runs": runs,
                "runs_page": runs_page,
                "total_runs": total_runs,
                "succeeded_runs": succeeded_runs,
                "failed_runs_total": failed_runs_total,
                "total_runs_pages": total_runs_pages,
                "runs_start": runs_start,
                "runs_end": runs_end,
                "plugin_tasks": plugin_tasks,
                "csrf_token": csrf_token,
            },
        )

    @router.post("/tasks/plugin/{plugin}/{task_id}/toggle")
    async def plugin_task_toggle(
        plugin: str,
        task_id: str,
        request: Request,
        user: WebAccount = Depends(require_admin),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        manager = getattr(app.state, "plugin_manager", None)
        if manager is None or manager.task_registry is None:
            return flash_redirect("/tasks", error="插件任务登记表不可用")
        entry = manager.task_registry.get(plugin, task_id)
        if entry is None:
            return flash_redirect("/tasks", error="插件任务不存在")
        enabled = not entry.enabled
        manager.task_registry.set_enabled(plugin, task_id, enabled)
        settings.runtime.plugin_tasks.setdefault(plugin, {})[task_id] = enabled
        save_settings(settings)
        audit_logger.record(
            "plugin_task.toggled",
            user.username,
            target=f"{plugin}.{task_id}",
            success=True,
        )
        return flash_redirect(
            "/tasks",
            message=f"插件任务 {plugin}.{task_id} 已{'启用' if enabled else '停用'}",
        )

    @router.post("/tasks/add")
    async def tasks_add(
        request: Request,
        user: WebAccount = Depends(require_admin),
        name: str = Form(...),
        task_type: str = Form(...),
        cron_expression: str = Form(""),
        interval_seconds: str = Form(""),
        group_id: str = Form(...),
        message: str = Form(...),
        params_json: str = Form(""),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        if task_type not in {"interval", "cron"}:
            return RedirectResponse("/tasks?error=1", status_code=303)
        if task_type == "interval" and not interval_seconds.isdigit():
            return RedirectResponse("/tasks?error=1", status_code=303)
        if task_type == "cron" and not cron_expression:
            return RedirectResponse("/tasks?error=1", status_code=303)
        import json

        params: dict[str, Any] = {"group_id": group_id, "message": message}
        if params_json.strip():
            try:
                extra = json.loads(params_json)
                if not isinstance(extra, dict):
                    raise TypeError("params must be an object")
                params.update(extra)
            except Exception:
                return RedirectResponse("/tasks?error=1", status_code=303)
        task_id = uuid4().hex
        async with session_factory()() as session:
            session.add(
                Task(
                    task_id=task_id,
                    name=name,
                    type=task_type,
                    cron_expression=cron_expression or None,
                    interval_seconds=int(interval_seconds) if interval_seconds.isdigit() else None,
                    params=params,
                    enabled=True,
                )
            )
            await session.commit()
        try:
            if app.state.scheduler:
                func = _task_executor(task_id, app)
                if task_type == "cron" and cron_expression:
                    app.state.scheduler.add_cron_job(
                        func,
                        job_id=task_id,
                        cron_expression=cron_expression,
                    )
                elif task_type == "interval":
                    app.state.scheduler.add_interval_job(
                        func,
                        job_id=task_id,
                        seconds=int(interval_seconds),
                    )
        except Exception:
            async with session_factory()() as session:
                task = await session.scalar(
                    select(Task).where(Task.task_id == task_id)
                )
                if task:
                    await session.delete(task)
                    await session.commit()
            return RedirectResponse("/tasks?error=1", status_code=303)
        audit_logger.record("task.created", user.username, target=name, success=True)
        return flash_redirect("/tasks", message=f"任务 {name} 已添加")

    @router.post("/tasks/{task_id}/toggle")
    async def tasks_toggle(
        task_id: str,
        request: Request,
        user: WebAccount = Depends(require_admin),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        async with session_factory()() as session:
            task = await session.scalar(
                select(Task).where(Task.task_id == task_id)
            )
            if task:
                task.enabled = not task.enabled
                if task.enabled and task.params.get("auto_disabled"):
                    task.params = {
                        key: value
                        for key, value in task.params.items()
                        if key
                        not in ("auto_disabled", "auto_disabled_reason")
                    }
                await session.commit()
        if app.state.scheduler:
            try:
                if task and not task.enabled:
                    app.state.scheduler.remove_job(task_id)
                elif task and task.enabled:
                    func = _task_executor(task_id, app)
                    if task.type == "cron" and task.cron_expression:
                        app.state.scheduler.add_cron_job(
                            func,
                            job_id=task_id,
                            cron_expression=task.cron_expression,
                        )
                    elif task.type == "interval" and task.interval_seconds:
                        app.state.scheduler.add_interval_job(
                            func,
                            job_id=task_id,
                            seconds=task.interval_seconds,
                        )
            except Exception:
                async with session_factory()() as session:
                    db_task = await session.scalar(
                        select(Task).where(Task.task_id == task_id)
                    )
                    if db_task:
                        db_task.enabled = False
                        await session.commit()
                return RedirectResponse("/tasks?error=1", status_code=303)
        return flash_redirect("/tasks", message="任务状态已更新")

    @router.post("/tasks/{task_id}/run")
    async def tasks_run_now(
        task_id: str,
        request: Request,
        user: WebAccount = Depends(require_admin),
        message: str = Form(""),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        async with session_factory()() as session:
            task = await session.scalar(
                select(Task).where(Task.task_id == task_id)
            )
            if task is None:
                return flash_redirect("/tasks", error="任务不存在")
            if not task.enabled:
                return flash_redirect(
                    "/tasks",
                    error=f"任务 {task.name} 已禁用，请先启用后再运行",
                )
        func = _task_executor(task_id, app, message_override=message)
        try:
            await func()
        except Exception:
            return flash_redirect("/tasks", error="1")
        return flash_redirect("/tasks", message="任务已执行")

    @router.post("/tasks/{task_id}/edit")
    async def tasks_edit(
        task_id: str,
        request: Request,
        user: WebAccount = Depends(require_admin),
        name: str = Form(...),
        task_type: str = Form("interval"),
        interval_seconds: str = Form(""),
        cron_expression: str = Form(""),
        group_id: str = Form(""),
        message: str = Form(""),
        params_json: str = Form(""),
        enabled: str = Form("on"),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        if task_type not in {"interval", "cron"}:
            return flash_redirect("/tasks", error="1")
        if task_type == "interval" and not interval_seconds.isdigit():
            return flash_redirect("/tasks", error="1")
        if task_type == "cron" and not cron_expression:
            return flash_redirect("/tasks", error="1")
        import json

        params: dict[str, Any] = {"group_id": group_id, "message": message}
        if params_json.strip():
            try:
                extra = json.loads(params_json)
                if not isinstance(extra, dict):
                    raise TypeError("params must be an object")
                params.update(extra)
            except Exception:
                return flash_redirect("/tasks", error="1")
        async with session_factory()() as session:
            task = await session.scalar(
                select(Task).where(Task.task_id == task_id)
            )
            if task is None:
                return flash_redirect("/tasks", error="1")
            task.name = name
            task.type = task_type
            task.cron_expression = cron_expression or None
            task.interval_seconds = (
                int(interval_seconds) if interval_seconds.isdigit() else None
            )
            task.params = params
            task.enabled = enabled == "on"
            await session.commit()
        scheduler = getattr(app.state, "scheduler", None)
        if scheduler:
            try:
                scheduler.remove_job(task_id)
            except Exception:
                pass
            if enabled == "on":
                func = _task_executor(task_id, app)
                try:
                    if task_type == "cron" and cron_expression:
                        scheduler.add_cron_job(
                            func,
                            job_id=task_id,
                            cron_expression=cron_expression,
                        )
                    elif task_type == "interval" and interval_seconds.isdigit():
                        scheduler.add_interval_job(
                            func,
                            job_id=task_id,
                            seconds=int(interval_seconds),
                        )
                except Exception:
                    return flash_redirect("/tasks", error="1")
        audit_logger.record(
            "task.updated", user.username, target=task_id, success=True
        )
        return flash_redirect("/tasks", message=f"任务 {name} 已更新")

    @router.post("/tasks/{task_id}/remove")
    async def tasks_remove(
        task_id: str,
        request: Request,
        user: WebAccount = Depends(require_admin),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        async with session_factory()() as session:
            task = await session.scalar(
                select(Task).where(Task.task_id == task_id)
            )
            if task is None:
                return flash_redirect("/tasks", error="任务不存在")
            await session.delete(task)
            await session.commit()
        if app.state.scheduler:
            app.state.scheduler.remove_job(task_id)
        return flash_redirect("/tasks", message="任务已删除")

    @router.post("/tasks/bulk")
    async def tasks_bulk(
        request: Request,
        user: WebAccount = Depends(require_admin),
        ids: list[str] = Form(default=[]),
        action: str = Form("enable"),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        if action not in {"enable", "disable", "delete"}:
            return flash_redirect("/tasks", error="1")
        if not ids:
            return flash_redirect("/tasks", message="未选择任务")
        changed = 0
        for task_id in ids[:200]:
            async with session_factory()() as session:
                task = await session.scalar(
                    select(Task).where(Task.task_id == task_id)
                )
                if task is None:
                    continue
                if action == "delete":
                    await session.delete(task)
                    await session.commit()
                    scheduler = getattr(app.state, "scheduler", None)
                    if scheduler:
                        scheduler.remove_job(task_id)
                    changed += 1
                    continue
                task.enabled = action == "enable"
                await session.commit()
            scheduler = getattr(app.state, "scheduler", None)
            if scheduler:
                if action == "disable":
                    scheduler.remove_job(task_id)
                elif action == "enable":
                    try:
                        async with session_factory()() as session:
                            task = await session.scalar(
                                select(Task).where(Task.task_id == task_id)
                            )
                        if task is None:
                            continue
                        func = _task_executor(task_id, app)
                        if task.type == "cron" and task.cron_expression:
                            scheduler.add_cron_job(
                                func,
                                job_id=task_id,
                                cron_expression=task.cron_expression,
                            )
                        elif task.type == "interval" and task.interval_seconds:
                            scheduler.add_interval_job(
                                func,
                                job_id=task_id,
                                seconds=task.interval_seconds,
                            )
                    except Exception:
                        async with session_factory()() as session:
                            db_task = await session.scalar(
                                select(Task).where(Task.task_id == task_id)
                            )
                            if db_task:
                                db_task.enabled = False
                                await session.commit()
            changed += 1
        audit_logger.record(
            "task.bulk_updated",
            user.username,
            target=f"{action}:{changed}",
            success=True,
            detail={"ids": ids[:200]},
        )
        label = {"enable": "启用", "disable": "禁用", "delete": "删除"}[action]
        return flash_redirect(
            "/tasks", message=f"批量{label}完成：{changed} 个任务"
        )

    @router.post("/tasks/runs/clear")
    async def tasks_runs_clear(
        request: Request,
        user: WebAccount = Depends(require_admin),
        start: str = Form(""),
        end: str = Form(""),
        status: str = Form(""),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        from sqlalchemy import delete

        start_dt, end_dt = _parse_date_range(start, end)
        clear_query = delete(TaskRun)
        if status in {"succeeded", "failed", "running"}:
            clear_query = clear_query.where(TaskRun.status == status)
        if start_dt is not None:
            clear_query = clear_query.where(TaskRun.created_at >= start_dt)
        if end_dt is not None:
            clear_query = clear_query.where(TaskRun.created_at <= end_dt)
        async with session_factory()() as session:
            result = await session.execute(clear_query)
            await session.commit()
            deleted = result.rowcount or 0
        audit_logger.record(
            "task.runs_cleared",
            user.username,
            target=f"runs:{deleted}",
            success=True,
            detail={"start": start, "end": end, "status": status},
        )
        range_part = ""
        if start or end or status:
            bits = []
            if start or end:
                bits.append(f"{start or '任意'} ~ {end or '现在'}")
            if status:
                bits.append({"succeeded": "成功", "failed": "失败", "running": "运行中"}[status])
            range_part = f"（{' / '.join(bits)}）"
        return flash_redirect(
            "/tasks", message=f"已清除 {deleted} 条执行历史{range_part}"
        )

    @router.get("/tasks/export")
    async def tasks_export(
        request: Request,
        user: WebAccount = Depends(require_admin),
        task_id: str = "",
        status: str = "",
        start: str = "",
        end: str = "",
    ) -> Response:
        import csv
        import io

        query = select(TaskRun)
        if task_id:
            query = query.where(TaskRun.task_id == task_id)
        if status:
            query = query.where(TaskRun.status == status)
        start_dt, end_dt = _parse_date_range(start, end)
        if start_dt is not None:
            query = query.where(TaskRun.created_at >= start_dt)
        if end_dt is not None:
            query = query.where(TaskRun.created_at <= end_dt)
        query = query.order_by(TaskRun.created_at.desc()).limit(2000)
        async with session_factory()() as session:
            runs = (await session.scalars(query)).all()
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["task_id", "status", "message", "created_at"])
        for run in runs:
            writer.writerow(
                [
                    run.task_id,
                    run.status,
                    run.message or "",
                    run.created_at.isoformat() if run.created_at else "",
                ]
            )
        return Response(
            buffer.getvalue().encode("utf-8-sig"),
            media_type="text/csv",
            headers={
                "Content-Disposition": 'attachment; filename="task_runs.csv"'
            },
        )

    return router
