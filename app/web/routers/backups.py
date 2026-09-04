"""数据备份与恢复路由。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

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
    RedirectResponse,
    Response,
)

from app.core.config import Settings, save_settings
from app.core.logger import get_logger
from app.core.security import audit_logger
from app.web.deps import (
    get_csrf_token,
    get_current_user,
    require_admin,
    require_csrf,
)
from app.web.helpers import PROJECT_ROOT, flash_redirect

logger = get_logger(__name__)


def _zip_directory(path: Path) -> bytes:
    """把备份目录同步打包为 zip 字节流（在线程池中执行，避免阻塞事件循环）。"""
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for file in path.rglob("*"):
            if file.is_file():
                archive.write(file, file.relative_to(path))
    return buffer.getvalue()


def build_router(*, app: FastAPI, settings: Settings, templates: Any) -> APIRouter:
    router = APIRouter()

    @router.get("/backups", response_class=HTMLResponse)
    async def backups_page(
        request: Request,
        user: Any = Depends(get_current_user),
        csrf_token: str = Depends(get_csrf_token),
    ) -> HTMLResponse:
        service = app.state.services.get("backup")
        backups = service.list_backups() if service else []
        last_auto_backup = settings.plugin_configs.get("backup", {}).get(
            "last_auto_backup", ""
        )
        return templates.TemplateResponse(
            request,
            "backups.html",
            {
                "request": request,
                "user": user,
                "backups": backups,
                "auto_backup_enabled": settings.scheduler.auto_backup_enabled,
                "backup_interval_hours": settings.scheduler.backup_interval_hours,
                "last_auto_backup": last_auto_backup,
                "csrf_token": csrf_token,
            },
        )

    @router.post("/backups/create")
    async def backups_create(
        request: Request,
        user: Any = Depends(require_admin),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        service = app.state.services.get("backup")
        if service is None:
            return RedirectResponse("/backups?error=1", status_code=303)
        root = PROJECT_ROOT
        await asyncio.to_thread(
            service.create_backup,
            root / "config.yaml",
            root / "data" / "ofbot2.db",
        )
        return flash_redirect("/backups", message="备份已创建")

    @router.post("/backups/auto-toggle")
    async def backups_auto_toggle(
        request: Request,
        user: Any = Depends(require_admin),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        settings.scheduler.auto_backup_enabled = (
            not settings.scheduler.auto_backup_enabled
        )
        save_settings(settings)
        enabled = settings.scheduler.auto_backup_enabled
        audit_logger.record(
            "backup.auto_toggled",
            user.username,
            target=str(enabled),
            success=True,
        )
        message = (
            f"自动备份已{'启用' if enabled else '关闭'}"
            "（每 "
            f"{settings.scheduler.backup_interval_hours} 小时执行，下一周期生效）"
        )
        return flash_redirect("/backups", message=message)

    @router.post("/backups/auto-interval")
    async def backups_auto_interval(
        request: Request,
        user: Any = Depends(require_admin),
        hours: int = Form(24),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        if not (1 <= hours <= 168):
            return flash_redirect("/backups", error="1")
        settings.scheduler.backup_interval_hours = hours
        save_settings(settings)
        audit_logger.record(
            "backup.interval_updated",
            user.username,
            target=str(hours),
            success=True,
        )
        return flash_redirect(
            "/backups", message=f"自动备份间隔已设为 {hours} 小时"
        )

    @router.get("/backups/{name}/download")
    async def backups_download(
        name: str,
        user: Any = Depends(get_current_user),
    ) -> Any:
        service = app.state.services.get("backup")
        if service is None:
            raise HTTPException(status_code=404, detail="backup service unavailable")
        try:
            path = service.resolve_backup(name)
        except Exception:
            raise HTTPException(status_code=404, detail="backup not found")
        data = await asyncio.to_thread(_zip_directory, path)
        return Response(
            data,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{name}.zip"'
            },
        )

    @router.get("/backups/{name}/file")
    async def backup_file_download(
        name: str,
        path: str = "",
        user: Any = Depends(require_admin),
    ) -> Any:
        from fastapi.responses import FileResponse

        service = app.state.services.get("backup")
        if service is None:
            raise HTTPException(status_code=404, detail="backup service unavailable")
        try:
            target = service.resolve_file(name, path)
        except Exception:
            raise HTTPException(status_code=404, detail="file not found")
        if not target.is_file():
            raise HTTPException(status_code=404, detail="file not found")
        return FileResponse(target)

    @router.post("/backups/{name}/delete")
    async def backups_delete(
        name: str,
        request: Request,
        user: Any = Depends(require_admin),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        service = app.state.services.get("backup")
        if service is None:
            return flash_redirect("/backups", error="1")
        try:
            service.delete_backup(name)
        except Exception:
            return flash_redirect("/backups", error="1")
        audit_logger.record(
            "backup.deleted", user.username, target=name, success=True
        )
        return flash_redirect("/backups", message=f"备份 {name} 已删除")

    @router.post("/backups/{name}/restore")
    async def backups_restore(
        name: str,
        request: Request,
        user: Any = Depends(require_admin),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        service = app.state.services.get("backup")
        if service is None:
            return flash_redirect("/backups", error="1")
        root = PROJECT_ROOT
        rollback_name = ""
        try:
            rollback = await asyncio.to_thread(
                service.create_backup,
                root / "config.yaml",
                root / "data" / "ofbot2.db",
            )
            rollback_name = rollback.name
        except Exception as exc:
            audit_logger.record(
                "backup.rollback_failed",
                user.username,
                target=name,
                success=False,
                detail={"error": str(exc)},
            )
        try:
            results = await asyncio.to_thread(
                service.restore,
                name,
                {
                    "config.yaml": root / "config.yaml",
                    "ofbot2.db": root / "data" / "ofbot2.db",
                },
            )
        except Exception:
            return flash_redirect("/backups", error="1")
        audit_logger.record(
            "backup.restored",
            user.username,
            target=name,
            success=True,
            detail=results,
        )
        staged = [key for key, value in results.items() if "暂存" in value]
        message = "备份已恢复，请重启服务生效"
        if rollback_name:
            message += f"；恢复前已自动创建回退点「{rollback_name}」"
        else:
            message += "；注意：回退点创建失败，请确认磁盘空间充足"
        if staged:
            message += f"；{len(staged)} 个文件被占用，已暂存待手动替换"
        return flash_redirect("/backups", message=message)

    @router.get("/backups/compare", response_class=HTMLResponse)
    async def backups_compare_page(
        request: Request,
        user: Any = Depends(get_current_user),
        a: str = "",
        b: str = "",
    ) -> HTMLResponse:
        service = app.state.services.get("backup")
        backups = service.list_backups() if service else []
        result = None
        if service is not None and a and b and a != b:
            try:
                result = service.compare(a, b)
            except Exception:
                result = None
        return templates.TemplateResponse(
            request,
            "backups_compare.html",
            {
                "request": request,
                "user": user,
                "backups": backups,
                "a": a,
                "b": b,
                "result": result,
            },
        )

    return router
