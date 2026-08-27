"""认证与账户路由：登录、登出、修改密码。"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
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
from sqlalchemy import select

from app.core.config import Settings
from app.core.logger import get_logger
from app.core.security import audit_logger
from app.db.base import session_factory
from app.db.models import WebAccount
from app.web.deps import get_csrf_token, get_current_user, require_csrf
from app.web.helpers import flash_redirect
from app.web.security import password_hasher

logger = get_logger(__name__)


@dataclass
class _LoginState:
    failures: int = 0
    locked_until: float = 0.0


# 进程内登录失败状态（单进程 Web 部署）；锁定策略由 security.* 配置驱动
_login_states: dict[str, _LoginState] = {}


def clear_login_states() -> None:
    """清空登录失败状态（供测试与运维重置）。"""
    _login_states.clear()


def build_router(*, app: FastAPI, settings: Settings, templates: Any) -> APIRouter:
    router = APIRouter()

    @router.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request) -> HTMLResponse:
        error_code = request.query_params.get("error")
        error = {
            "1": "用户名或密码错误",
            "2": "失败次数过多，请稍后再试",
        }.get(error_code or "")
        session_ttl_hours = settings.web.session_ttl_seconds / 3600
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "request": request,
                "error": error,
                "session_ttl_hours": session_ttl_hours,
            },
        )

    @router.post("/login")
    async def login(
        request: Request,
        username: str = Form(...),
        password: str = Form(...),
    ) -> RedirectResponse:
        max_attempts = max(0, int(settings.security.max_login_attempts))
        lock_seconds = max(0, float(settings.security.login_lock_seconds))
        delay = min(
            5.0, max(0.0, float(settings.security.login_failure_delay_seconds))
        )
        state = _login_states.setdefault(username, _LoginState())
        if len(_login_states) > 10000:
            _login_states.pop(next(iter(_login_states)), None)
        now = time.time()
        if state.locked_until and now < state.locked_until:
            audit_logger.record(
                "web.login_locked",
                username,
                success=False,
                detail={"reason": "too_many_attempts"},
            )
            return RedirectResponse("/login?error=2", status_code=303)
        async with session_factory()() as session:
            user = await session.scalar(select(WebAccount).where(WebAccount.username == username))
        verified = user is not None and password_hasher.verify_password(
            password, user.password_hash
        )
        if verified and user is not None and password_hasher.needs_upgrade(
            user.password_hash
        ):
            user.password_hash = password_hasher.hash_password(password)
            async with session_factory()() as session:
                account = await session.get(WebAccount, user.id)
                if account is not None:
                    account.password_hash = user.password_hash
                    await session.commit()
        if not verified:
            if delay > 0:
                await asyncio.sleep(delay)
            state.failures += 1
            if (
                max_attempts > 0
                and lock_seconds > 0
                and state.failures >= max_attempts
            ):
                state.locked_until = now + lock_seconds
                state.failures = 0
            audit_logger.record(
                "web.login_failed",
                username,
                success=False,
                detail={"reason": "invalid_credentials"},
            )
            return RedirectResponse("/login?error=1", status_code=303)
        state.failures = 0
        state.locked_until = 0.0
        audit_logger.record("web.login", username, target=str(user.id), success=True)
        if (
            user.username == "admin"
            and password_hasher.verify_password("admin", user.password_hash)
        ):
            response = RedirectResponse("/setup", status_code=303)
        else:
            response = RedirectResponse("/", status_code=303)
        await app.state.session_manager.create_session(request, response, user.id)
        return response

    @router.get("/logout")
    async def logout(request: Request) -> RedirectResponse:
        response = RedirectResponse("/login", status_code=303)
        await app.state.session_manager.destroy_session(request, response)
        return response

    @router.get("/account", response_class=HTMLResponse)
    async def account_page(
        request: Request,
        user: WebAccount = Depends(get_current_user),
        csrf_token: str = Depends(get_csrf_token),
    ) -> HTMLResponse:
        accounts: list[WebAccount] = []
        if user.can_manage_users:
            async with session_factory()() as session:
                accounts = (
                    await session.scalars(
                        select(WebAccount).order_by(WebAccount.username)
                    )
                ).all()
        return templates.TemplateResponse(
            request,
            "account.html",
            {
                "request": request,
                "user": user,
                "csrf_token": csrf_token,
                "accounts": accounts,
                "error": request.query_params.get("error", ""),
            },
        )

    @router.post("/account")
    async def account_update(
        request: Request,
        user: WebAccount = Depends(get_current_user),
        current_password: str = Form(...),
        new_password: str = Form(...),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        if len(new_password) < 6:
            return RedirectResponse("/account?error=1", status_code=303)
        async with session_factory()() as session:
            account = await session.get(WebAccount, user.id)
            if account is None or not password_hasher.verify_password(
                current_password, account.password_hash
            ):
                return RedirectResponse("/account?error=2", status_code=303)
            account.password_hash = password_hasher.hash_password(new_password)
            await session.commit()
        audit_logger.record(
            "web.password_changed", user.username, target=str(user.id), success=True
        )
        return flash_redirect("/account", message="密码已修改")

    @router.post("/account/accounts/add")
    async def account_add(
        request: Request,
        user: WebAccount = Depends(get_current_user),
        username: str = Form(...),
        password: str = Form(...),
        permission_level: str = Form("0"),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        if not user.can_manage_users:
            return RedirectResponse("/account?error=1", status_code=303)
        username = username.strip()
        if len(username) < 3 or len(password) < 6:
            return RedirectResponse("/account?error=1", status_code=303)
        try:
            level = int(permission_level)
        except ValueError:
            return RedirectResponse("/account?error=1", status_code=303)
        if level not in {0, 1, 2} or (level >= 2 and user.permission_level < 2):
            return RedirectResponse("/account?error=1", status_code=303)
        async with session_factory()() as session:
            existing = await session.scalar(
                select(WebAccount).where(WebAccount.username == username)
            )
            if existing:
                return RedirectResponse("/account?error=1", status_code=303)
            session.add(
                WebAccount(
                    username=username,
                    password_hash=password_hasher.hash_password(password),
                    permission_level=level,
                    can_manage_users=level >= 1,
                    can_manage_plugins=level >= 1,
                    can_manage_tasks=level >= 1,
                    can_view_monitor=level >= 0,
                )
            )
            await session.commit()
        audit_logger.record(
            "web.account_added", user.username, target=username, success=True
        )
        return flash_redirect("/account", message=f"已添加后台账户 {username}")

    @router.post("/account/accounts/remove")
    async def account_remove(
        request: Request,
        user: WebAccount = Depends(get_current_user),
        account_id: int = Form(...),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        if not user.can_manage_users:
            return RedirectResponse("/account?error=1", status_code=303)
        async with session_factory()() as session:
            target = await session.get(WebAccount, account_id)
            if target is None:
                return RedirectResponse("/account?error=1", status_code=303)
            if target.permission_level >= 2 and user.permission_level < 2:
                return RedirectResponse("/account?error=1", status_code=303)
            if target.username == user.username:
                return RedirectResponse("/account?error=1", status_code=303)
            await session.delete(target)
            await session.commit()
            target_name = target.username
        audit_logger.record(
            "web.account_removed", user.username, target=target_name, success=True
        )
        return flash_redirect("/account", message=f"已删除后台账户 {target_name}")

    return router
