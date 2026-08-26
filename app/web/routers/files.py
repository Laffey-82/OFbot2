"""文件中心路由。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)

from app.core.config import Settings
from app.core.logger import get_logger
from app.core.security import audit_logger
from app.db.models import WebAccount
from app.web.deps import (
    get_csrf_token,
    get_current_user,
    require_admin,
    require_csrf,
)
from app.web.helpers import flash_redirect, render_markdown_light

logger = get_logger(__name__)


def build_router(*, app: FastAPI, settings: Settings, templates: Any) -> APIRouter:
    router = APIRouter()

    @router.get("/files", response_class=HTMLResponse)
    async def files_page(
        request: Request,
        user: Any = Depends(get_current_user),
        csrf_token: str = Depends(get_csrf_token),
    ) -> HTMLResponse:
        service = app.state.services.get("files")
        files = service.list_files() if service else []
        return templates.TemplateResponse(
            request,
            "files.html",
            {
                "request": request,
                "user": user,
                "files": files,
                "csrf_token": csrf_token,
            },
        )

    @router.post("/files/upload")
    async def files_upload(
        request: Request,
        user: Any = Depends(require_admin),
        file: UploadFile = File(...),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        service = app.state.services.get("files")
        if service:
            service.save_bytes(await file.read(), suffix=Path(file.filename or ".bin").suffix)
        return flash_redirect("/files", message="文件已上传")

    @router.get("/files/{name}/download")
    async def files_download(
        name: str,
        user: Any = Depends(get_current_user),
    ) -> Any:
        from fastapi.responses import FileResponse

        service = app.state.services.get("files")
        if service is None:
            raise HTTPException(status_code=404, detail="file service unavailable")
        path = service.resolve(name)
        if not path.exists():
            raise HTTPException(status_code=404, detail="file not found")
        return FileResponse(path)

    @router.get("/files/{name:path}/preview")
    async def files_preview(
        name: str,
        request: Request,
        user: Any = Depends(get_current_user),
    ) -> JSONResponse:
        service = app.state.services.get("files")
        if service is None:
            raise HTTPException(status_code=404, detail="files unavailable")
        path = service.resolve(name)
        if not path.exists():
            raise HTTPException(status_code=404, detail="file not found")
        try:
            data = path.read_bytes()[:50 * 1024]
            if b"\x00" in data[:1024]:
                return JSONResponse(
                    {"ok": False, "detail": "二进制文件无法预览"}
                )
            content = data.decode("utf-8", errors="replace")
        except Exception as exc:
            return JSONResponse({"ok": False, "detail": str(exc)})
        html_content = ""
        if path.name.lower().endswith(".md"):
            html_content = render_markdown_light(content)
        return JSONResponse(
            {
                "ok": True,
                "content": content,
                "html": html_content,
                "truncated": path.stat().st_size > 50 * 1024,
            }
        )

    @router.post("/files/{name:path}/delete")
    async def files_delete(
        name: str,
        request: Request,
        user: Any = Depends(require_admin),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        service = app.state.services.get("files")
        if service is None or not service.delete_file(name):
            return flash_redirect("/files", error="1")
        audit_logger.record(
            "file.deleted", user.username, target=name, success=True
        )
        return flash_redirect("/files", message=f"文件 {name} 已删除")

    @router.post("/files/bulk-delete")
    async def files_bulk_delete(
        request: Request,
        user: Any = Depends(require_admin),
        names: list[str] = Form(default=[]),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        service = app.state.services.get("files")
        if service is None:
            return flash_redirect("/files", error="1")
        deleted = 0
        for name in names:
            if service.delete_file(name):
                deleted += 1
        audit_logger.record(
            "files.bulk_deleted", user.username, target=str(deleted), success=True
        )
        return flash_redirect("/files", message=f"已删除 {deleted} 个文件")

    @router.post("/files/bulk-download")
    async def files_bulk_download(
        request: Request,
        user: WebAccount = Depends(require_admin),
        names: list[str] = Form(default=[]),
        csrf: None = Depends(require_csrf),
    ) -> Any:
        from io import BytesIO
        from zipfile import ZIP_DEFLATED, ZipFile

        service = app.state.services.get("files")
        if service is None:
            return flash_redirect("/files", error="1")
        names = names[:200]
        resolved = []
        for name in names:
            try:
                path = service.resolve(name)
            except Exception as exc:
                logger.warning("skip invalid file path %s: %s", name, exc)
                continue
            if path.is_file():
                resolved.append((name, path))
        if not resolved:
            return flash_redirect("/files", error="请选择要下载的文件")
        buffer = BytesIO()
        with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
            for name, path in resolved:
                archive.write(path, arcname=name)
        audit_logger.record(
            "files.bulk_downloaded",
            user.username,
            target=f"files:{len(resolved)}",
            success=True,
        )
        stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M")
        return Response(
            buffer.getvalue(),
            media_type="application/zip",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="files_{stamp}_{len(resolved)}.zip"'
                )
            },
        )

    return router
