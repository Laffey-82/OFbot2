"""监听环境路由：功能开关矩阵、权限覆盖、黑名单、账号绑定与静默开关。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core.config import Settings, save_settings
from app.core.logger import get_logger
from app.core.scopes import SCOPE_GLOBAL_GROUP, SCOPE_PRIVATE, ScopePolicyService
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


def _scope_policy(app: FastAPI, settings: Settings) -> ScopePolicyService:
    policy = getattr(app.state, "scope_policy", None)
    if policy is None:
        policy = ScopePolicyService(settings)
        app.state.scope_policy = policy
    else:
        policy.reload(settings)
    return policy


def _collect_features(app: FastAPI) -> list[dict[str, Any]]:
    manager = getattr(app.state, "plugin_manager", None)
    features: list[dict[str, Any]] = []
    if manager is None:
        return features
    for name in sorted(manager.loaded):
        loaded = manager.loaded[name]
        for key, spec in loaded.features.items():
            features.append(
                {
                    "key": key,
                    "plugin": name,
                    "label": spec.label or spec.id,
                    "description": spec.description,
                    "enable_on_default": spec.enable_on_default,
                    "manage_permission": spec.manage_permission,
                    "commands": len(spec.commands),
                    "tasks": len(spec.tasks),
                    "listeners": len(spec.listeners),
                }
            )
    return features


def build_router(*, app: FastAPI, settings: Settings, templates: Any) -> APIRouter:
    router = APIRouter()

    @router.get("/scopes", response_class=HTMLResponse)
    async def scopes_page(
        request: Request,
        user: WebAccount = Depends(get_current_user),
        csrf_token: str = Depends(get_csrf_token),
    ) -> HTMLResponse:
        policy = _scope_policy(app, settings)
        policy.ensure_defaults()
        scopes = [
            {"key": key, "entry": entry}
            for key, entry in sorted(policy.runtime.scopes.items())
        ]
        features = _collect_features(app)
        connections = [
            {"id": conn.id, "protocol": conn.protocol, "enabled": conn.enabled}
            for conn in settings.transport.connections
        ]
        return templates.TemplateResponse(
            request,
            "scopes.html",
            {
                "request": request,
                "user": user,
                "scopes": scopes,
                "features": features,
                "connections": connections,
                "csrf_token": csrf_token,
                "global_group": SCOPE_GLOBAL_GROUP,
                "private_scope": SCOPE_PRIVATE,
            },
        )

    @router.post("/scopes/{scope}/feature")
    async def scopes_feature(
        scope: str,
        request: Request,
        user: WebAccount = Depends(require_admin),
        key: str = Form(...),
        value: str = Form(...),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        policy = _scope_policy(app, settings)
        if value == "on":
            policy.set_feature(scope, key, True)
        elif value == "off":
            policy.set_feature(scope, key, False)
        else:
            policy.set_feature(scope, key, None)
        save_settings(settings)
        audit_logger.record(
            "scope.feature",
            user.username,
            target=f"{scope}:{key}={value}",
            success=True,
        )
        return flash_redirect("/scopes", message=f"功能 {key} 已更新")

    @router.post("/scopes/{scope}/permission")
    async def scopes_permission(
        scope: str,
        request: Request,
        user: WebAccount = Depends(require_admin),
        permission: str = Form(...),
        value: str = Form(...),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        policy = _scope_policy(app, settings)
        if value == "allow":
            policy.set_permission(scope, permission, True)
        elif value == "deny":
            policy.set_permission(scope, permission, False)
        else:
            policy.set_permission(scope, permission, None)
        save_settings(settings)
        audit_logger.record(
            "scope.permission",
            user.username,
            target=f"{scope}:{permission}={value}",
            success=True,
        )
        return flash_redirect("/scopes", message="权限覆盖已更新")

    @router.post("/scopes/{scope}/blocked/add")
    async def scopes_blocked_add(
        scope: str,
        request: Request,
        user: WebAccount = Depends(require_admin),
        user_ids: str = Form(...),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        policy = _scope_policy(app, settings)
        added = 0
        for token in user_ids.replace("，", ",").replace(";", "\n").splitlines():
            for part in token.split(","):
                part = part.strip()
                if part and policy.add_blocked(scope, part):
                    added += 1
        if added:
            save_settings(settings)
        audit_logger.record(
            "scope.blocked_add",
            user.username,
            target=f"{scope}:{added}",
            success=True,
        )
        return flash_redirect(
            "/scopes", message=f"已添加 {added} 个黑名单 QQ"
        )

    @router.post("/scopes/{scope}/blocked/remove")
    async def scopes_blocked_remove(
        scope: str,
        request: Request,
        user: WebAccount = Depends(require_admin),
        user_id: str = Form(...),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        policy = _scope_policy(app, settings)
        if policy.remove_blocked(scope, user_id):
            save_settings(settings)
        audit_logger.record(
            "scope.blocked_remove",
            user.username,
            target=f"{scope}:{user_id}",
            success=True,
        )
        return flash_redirect("/scopes", message="已解除黑名单")

    @router.post("/scopes/{scope}/silent")
    async def scopes_silent(
        scope: str,
        request: Request,
        user: WebAccount = Depends(require_admin),
        value: str = Form("off"),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        policy = _scope_policy(app, settings)
        policy.set_silent_deny(scope, value == "on")
        save_settings(settings)
        audit_logger.record(
            "scope.silent",
            user.username,
            target=f"{scope}:{value}",
            success=True,
        )
        return flash_redirect("/scopes", message="静默模式已更新")

    @router.post("/scopes/{scope}/connection")
    async def scopes_connection(
        scope: str,
        request: Request,
        user: WebAccount = Depends(require_admin),
        connection_id: str = Form(""),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        policy = _scope_policy(app, settings)
        policy.set_connection(scope, connection_id)
        save_settings(settings)
        audit_logger.record(
            "scope.connection",
            user.username,
            target=f"{scope}:{connection_id}",
            success=True,
        )
        return flash_redirect("/scopes", message="账号绑定已更新")

    @router.post("/scopes/add")
    async def scopes_add(
        request: Request,
        user: WebAccount = Depends(require_admin),
        group_id: str = Form(...),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        policy = _scope_policy(app, settings)
        group_id = group_id.strip()
        if not group_id:
            return flash_redirect("/scopes", error="请填写群号")
        import re

        if not re.fullmatch(r"\d{1,20}", group_id):
            return flash_redirect("/scopes", error="群号格式无效（仅数字，1-20 位）")
        if len(settings.runtime.scopes) >= 1000:
            return flash_redirect("/scopes", error="监听环境数量已达上限（1000）")
        from app.core.scopes import scope_for_group

        policy.ensure_scope(scope_for_group(group_id))
        save_settings(settings)
        audit_logger.record(
            "scope.added", user.username, target=group_id, success=True
        )
        return flash_redirect("/scopes", message=f"已添加监听环境 群 {group_id}")

    @router.post("/scopes/{scope}/remove")
    async def scopes_remove(
        scope: str,
        request: Request,
        user: WebAccount = Depends(require_admin),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        if scope in {SCOPE_GLOBAL_GROUP, SCOPE_PRIVATE}:
            return flash_redirect("/scopes", error="默认环境不可删除")
        policy = _scope_policy(app, settings)
        policy.runtime.scopes.pop(scope, None)
        save_settings(settings)
        audit_logger.record(
            "scope.removed", user.username, target=scope, success=True
        )
        return flash_redirect("/scopes", message=f"已删除监听环境 {scope}")

    @router.post("/scopes/features/bulk")
    async def scopes_features_bulk(
        request: Request,
        user: WebAccount = Depends(require_admin),
        key: str = Form(...),
        value: str = Form(...),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        """批量：某功能在所有群环境一键开启/关闭/恢复默认。"""
        policy = _scope_policy(app, settings)
        updated = 0
        for scope_key, entry in list(policy.runtime.scopes.items()):
            if not scope_key.startswith("group:"):
                continue
            if value == "on":
                entry.features[key] = True
            elif value == "off":
                entry.features[key] = False
            else:
                entry.features.pop(key, None)
            updated += 1
        save_settings(settings)
        audit_logger.record(
            "scope.feature_bulk",
            user.username,
            target=f"{key}={value}:{updated}",
            success=True,
        )
        return flash_redirect(
            "/scopes", message=f"已批量更新 {updated} 个监听环境"
        )

    return router
