"""角色分配路由：按 QQ 授予 user/operator/admin/superadmin。"""

from __future__ import annotations

from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    Form,
    Request,
)
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core.config import Settings, save_settings
from app.core.logger import get_logger
from app.core.permissions import permission_manager
from app.core.security import audit_logger
from app.db.models import WebAccount
from app.web.deps import (
    get_csrf_token,
    get_current_user,
    require_admin,
    require_csrf,
)
from app.web.helpers import flash_redirect

logger = get_logger(__name__)

ROLE_OPTIONS = ("user", "operator", "admin", "superadmin")


def build_router(*, app: FastAPI, settings: Settings, templates: Any) -> APIRouter:
    router = APIRouter()

    @router.get("/roles", response_class=HTMLResponse)
    async def roles_page(
        request: Request,
        user: WebAccount = Depends(get_current_user),
        csrf_token: str = Depends(get_csrf_token),
    ) -> HTMLResponse:
        roles = dict(settings.runtime.user_roles)
        return templates.TemplateResponse(
            request,
            "roles.html",
            {
                "request": request,
                "user": user,
                "roles": roles,
                "role_options": ROLE_OPTIONS,
                "csrf_token": csrf_token,
            },
        )

    @router.post("/roles/set")
    async def roles_set(
        request: Request,
        user: WebAccount = Depends(require_admin),
        user_id: str = Form(...),
        role: str = Form("user"),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        user_id = user_id.strip()
        if not user_id:
            return flash_redirect("/roles", error="QQ 号不能为空")
        if role not in ROLE_OPTIONS:
            return flash_redirect("/roles", error=f"未知角色：{role}")
        settings.runtime.user_roles[user_id] = role
        save_settings(settings)
        permission_manager.upsert_principal(
            user_id,
            role=role,
            scopes={"*"} if role == "superadmin" else set(),
        )
        audit_logger.record(
            "role.assigned",
            user.username,
            target=user_id,
            success=True,
            detail={"role": role},
        )
        return flash_redirect(
            "/roles", message=f"已将 QQ {user_id} 设为 {role}"
        )

    @router.post("/roles/remove")
    async def roles_remove(
        request: Request,
        user: WebAccount = Depends(require_admin),
        user_id: str = Form(...),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        user_id = user_id.strip()
        if user_id in settings.runtime.user_roles:
            del settings.runtime.user_roles[user_id]
            save_settings(settings)
        audit_logger.record(
            "role.removed",
            user.username,
            target=user_id,
            success=True,
        )
        return flash_redirect("/roles", message=f"已移除 QQ {user_id} 的角色")

    return router
