from __future__ import annotations

import hashlib
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import (
    FastAPI,
    HTTPException,
    Request,
    WebSocket,
)
from fastapi.responses import (
    JSONResponse,
    RedirectResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import __version__
from app.core.config import Settings
from app.core.logger import get_logger
from app.web.deps import (
    SessionManager,
)
from app.web.helpers import (
    ensure_default_admin,
    humanize_bytes,
    humanize_datetime,
    humanize_uptime,
    nav_active,
)

logger = get_logger(__name__)


def create_app(
    settings: Settings,
    *,
    plugin_manager: Any | None = None,
    reverse_routes: list[tuple[str, Any]] | None = None,
    http_routes: list[tuple[str, Any]] | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await ensure_default_admin(settings)
        yield

    app = FastAPI(title="OFbot 2", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.started_at = time.time()
    app.state.plugin_manager = plugin_manager
    app.state.session_manager = SessionManager(settings.web.session_ttl_seconds)
    app.state.services = {}
    app.state.export_jobs: dict[str, dict[str, Any]] = {}
    app.state.adapter_test_history: dict[str, list[dict[str, Any]]] = {}

    @app.exception_handler(HTTPException)
    async def http_exception_handler(
        request: Request, exc: HTTPException
    ) -> JSONResponse | RedirectResponse:
        accept = request.headers.get("accept", "")
        is_api_path = (
            request.url.path.startswith("/api/")
            or request.url.path.startswith("/health")
            or request.url.path == "/metrics"
        )
        if (
            exc.status_code in {401, 403}
            and request.url.path != "/login"
            and (not is_api_path or "text/html" in accept)
        ):
            return RedirectResponse("/login", status_code=303)
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )

    templates_dir = Path(__file__).parent / "templates"
    templates = Jinja2Templates(directory=str(templates_dir))

    templates.env.globals["humanize_uptime"] = humanize_uptime
    templates.env.globals["humanize_bytes"] = humanize_bytes
    templates.env.globals["humanize_datetime"] = humanize_datetime
    templates.env.globals["nav_active"] = nav_active
    templates.env.globals["APP_VERSION"] = __version__

    def static_version(path: str) -> str:
        """静态资源内容哈希，文件变更自动刷新缓存，无需手动递增版本号。"""
        try:
            data = (static_dir / path).read_bytes()
            return hashlib.md5(data).hexdigest()[:10]
        except OSError:
            return ""

    templates.env.globals["static_version"] = static_version
    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    from app.web.routers.ai_workflow import build_router as build_ai_workflow
    from app.web.routers.alerts import build_router as build_alerts
    from app.web.routers.audit_ops import build_router as build_audit_ops
    from app.web.routers.auth import build_router as build_auth
    from app.web.routers.backups import build_router as build_backups
    from app.web.routers.config_pages import build_router as build_config_pages
    from app.web.routers.connections import build_router as build_connections
    from app.web.routers.core import build_router as build_core
    from app.web.routers.data import build_router as build_data
    from app.web.routers.docs_pages import build_router as build_docs_pages
    from app.web.routers.executions_ops import build_router as build_executions_ops
    from app.web.routers.exports import build_router as build_exports
    from app.web.routers.files import build_router as build_files
    from app.web.routers.monitoring import build_router as build_monitoring
    from app.web.routers.plugins import build_router as build_plugins
    from app.web.routers.scopes import build_router as build_scopes
    from app.web.routers.stats import build_router as build_stats
    from app.web.routers.tasks import build_router as build_tasks
    from app.web.routers.webhooks import build_router as build_webhooks
    app.include_router(build_auth(app=app, settings=settings, templates=templates))
    app.include_router(build_core(app=app, settings=settings, templates=templates))
    app.include_router(build_plugins(app=app, settings=settings, templates=templates))
    app.include_router(build_connections(app=app, settings=settings, templates=templates))
    app.include_router(build_scopes(app=app, settings=settings, templates=templates))
    app.include_router(build_stats(app=app, settings=settings, templates=templates))
    app.include_router(build_config_pages(app=app, settings=settings, templates=templates))
    app.include_router(build_docs_pages(app=app, settings=settings, templates=templates))
    app.include_router(build_data(app=app, settings=settings, templates=templates))
    app.include_router(build_webhooks(app=app, settings=settings, templates=templates))
    app.include_router(build_alerts(app=app, settings=settings, templates=templates))
    app.include_router(build_exports(app=app, settings=settings, templates=templates))
    app.include_router(build_files(app=app, settings=settings, templates=templates))
    app.include_router(build_backups(app=app, settings=settings, templates=templates))
    app.include_router(build_ai_workflow(app=app, settings=settings, templates=templates))
    app.include_router(build_tasks(app=app, settings=settings, templates=templates))
    app.include_router(build_monitoring(app=app, settings=settings, templates=templates))
    app.include_router(build_audit_ops(app=app, settings=settings, templates=templates))
    app.include_router(build_executions_ops(app=app, settings=settings, templates=templates))
    from app.web.routers.api import router as api_router

    app.include_router(api_router)

    if plugin_manager:
        for plugin_router in plugin_manager.collect_routers():
            app.include_router(plugin_router)

    for reverse_path, reverse_handler in reverse_routes or []:

        @app.websocket(reverse_path)
        async def reverse_ws(
            websocket: WebSocket, _handler: Any = reverse_handler
        ) -> None:
            await _handler(websocket)

    for http_path, http_handler in http_routes or []:

        @app.post(http_path)
        async def http_event(
            request: Request, _handler: Any = http_handler
        ) -> JSONResponse:
            try:
                payload = await request.json()
            except Exception:
                return JSONResponse(status_code=400, content={"status": "bad json"})
            await _handler.handle_http_event(payload)
            return JSONResponse(status_code=200, content={"status": "ok"})

    return app
