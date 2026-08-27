"""内置文档查看路由。"""

from __future__ import annotations

from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    HTTPException,
    Request,
)
from fastapi.responses import (
    HTMLResponse,
    PlainTextResponse,
)

from app.core.config import Settings
from app.web.deps import get_current_user
from app.web.helpers import PROJECT_ROOT, render_markdown_light


def build_router(*, app: FastAPI, settings: Settings, templates: Any) -> APIRouter:
    router = APIRouter()

    _DOC_MAPPING = {
        "readme": "readme.md",
        "quickstart": "docs/QUICKSTART.md",
        "install": "docs/INSTALL.md",
        "tutorial": "docs/TUTORIAL.md",
        "dev": "docs/DEVELOPMENT.md",
        "api": "docs/API.md",
        "presets": "docs/PRESETS.md",
        "connections": "docs/CONNECTIONS.md",
        "manifest": "docs/PLUGIN_MANIFEST.md",
        "architecture": "docs/ARCHITECTURE.md",
        "chronocat": "docs/CHRONOCAT.md",
        "goals": "docs/GOALS.md",
        "plugin-repo": "docs/PLUGIN_REPO.md",
        "license": "LICENSE",
        "changelog": "docs/CHANGELOG.md",
        "faq": "docs/FAQ.md",
    }

    @router.get("/docs/index", response_class=HTMLResponse)
    async def docs_page(
        request: Request, user: Any = Depends(get_current_user)
    ) -> HTMLResponse:
        return templates.TemplateResponse(
            request, "docs.html", {"request": request, "user": user}
        )

    @router.get("/docs/{name}", response_class=PlainTextResponse)
    async def docs_file(name: str) -> PlainTextResponse:
        path = PROJECT_ROOT / _DOC_MAPPING.get(name, "")
        if not path.exists():
            raise HTTPException(status_code=404, detail="document not found")
        return PlainTextResponse(path.read_text(encoding="utf-8"))

    @router.get("/docs/view/{name}", response_class=HTMLResponse)
    async def docs_view(
        name: str,
        request: Request,
        user: Any = Depends(get_current_user),
    ) -> HTMLResponse:
        path = PROJECT_ROOT / _DOC_MAPPING.get(name, "")
        if not path.exists():
            raise HTTPException(status_code=404, detail="document not found")
        content = render_markdown_light(path.read_text(encoding="utf-8"))
        return templates.TemplateResponse(
            request,
            "docs_view.html",
            {
                "request": request,
                "user": user,
                "content": content,
                "title": name,
            },
        )

    return router
