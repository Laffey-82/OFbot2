"""系统监控与运行日志路由。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

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
)

from app.core.config import Settings, save_settings
from app.core.logger import get_logger
from app.core.observability import get_system_metrics
from app.core.security import audit_logger
from app.db.models import WebAccount
from app.web.deps import (
    get_csrf_token,
    get_current_user,
    require_admin,
    require_csrf,
)
from app.web.helpers import PROJECT_ROOT, _tail_lines, flash_redirect

logger = get_logger(__name__)


def build_router(*, app: FastAPI, settings: Settings, templates: Any) -> APIRouter:
    router = APIRouter()

    @router.get("/monitor", response_class=HTMLResponse)
    async def monitor_page(
        request: Request,
        user: WebAccount = Depends(get_current_user),
        csrf_token: str = Depends(get_csrf_token),
    ) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "monitor.html",
            {
                "request": request,
                "user": user,
                "metrics": get_system_metrics(),
                "cpu_threshold": settings.web.cpu_threshold,
                "memory_threshold": settings.web.memory_threshold,
                "csrf_token": csrf_token,
                "audit": [],
            },
        )

    @router.post("/monitor/thresholds")
    async def monitor_thresholds(
        request: Request,
        user: WebAccount = Depends(require_admin),
        cpu_threshold: int = Form(80),
        memory_threshold: int = Form(85),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        cpu_threshold = max(1, min(100, cpu_threshold))
        memory_threshold = max(1, min(100, memory_threshold))
        settings.web.cpu_threshold = cpu_threshold
        settings.web.memory_threshold = memory_threshold
        try:
            save_settings(settings)
        except Exception:
            return flash_redirect("/monitor", error="1")
        audit_logger.record(
            "monitor.thresholds_updated",
            user.username,
            target=f"cpu={cpu_threshold}% memory={memory_threshold}%",
            success=True,
        )
        return flash_redirect(
            "/monitor",
            message=(
                f"阈值已更新：CPU {cpu_threshold}% / 内存 {memory_threshold}%"
            ),
        )

    @router.get("/logs", response_class=HTMLResponse)
    async def logs_page(
        request: Request,
        user: WebAccount = Depends(require_admin),
        csrf_token: str = Depends(get_csrf_token),
        file: str = "",
        lines: int = 200,
    ) -> HTMLResponse:
        root = PROJECT_ROOT
        logs_dir = root / "logs"
        log_files: list[dict[str, Any]] = []
        if logs_dir.is_dir():
            paths = [
                path
                for path in logs_dir.glob("*.log")
                if path.is_file()
            ]
            paths.sort(key=lambda path: path.stat().st_mtime, reverse=True)
            for path in paths[:50]:
                stat = path.stat()
                log_files.append(
                    {
                        "name": path.name,
                        "size": stat.st_size,
                        "modified": datetime.fromtimestamp(
                            stat.st_mtime
                        ).isoformat(),
                    }
                )
        lines = max(50, min(2000, lines))
        selected = ""
        content = ""
        if log_files:
            selected = (
                file
                if any(item["name"] == file for item in log_files)
                else log_files[0]["name"]
            )
            target = (logs_dir / selected).resolve()
            if target.is_relative_to(logs_dir.resolve()):
                content = _tail_lines(target, lines)
        return templates.TemplateResponse(
            request,
            "logs.html",
            {
                "request": request,
                "user": user,
                "files": log_files,
                "selected": selected,
                "lines": lines,
                "content": content,
                "log_retention_days": settings.basic.log_retention_days,
                "log_max_files": settings.basic.log_max_files,
                "csrf_token": csrf_token,
            },
        )

    return router
