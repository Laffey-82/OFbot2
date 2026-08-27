from __future__ import annotations

import hmac
from datetime import UTC, timedelta
from typing import Any

from fastapi import Depends, Header, HTTPException, Request, Response, status

from app.db.base import session_factory
from app.db.models import WebAccount, WebSession
from app.web.security import make_csrf_token, make_session_id, utcnow

SESSION_COOKIE = "ofbot2_session"


class SessionManager:
    def __init__(self, ttl_seconds: int, *, secure: bool = False) -> None:
        self.ttl_seconds = ttl_seconds
        self.secure = secure

    async def create_session(
        self, request: Request, response: Response, user_id: int
    ) -> str:
        session_id = make_session_id()
        csrf_token = make_csrf_token()
        expires_at = utcnow() + timedelta(seconds=self.ttl_seconds)
        async with session_factory()() as session:
            session.add(
                WebSession(
                    id=session_id,
                    user_id=user_id,
                    csrf_token=csrf_token,
                    expires_at=expires_at,
                )
            )
            await session.commit()
        response.set_cookie(
            SESSION_COOKIE,
            session_id,
            max_age=self.ttl_seconds,
            httponly=True,
            samesite="lax",
            secure=self.secure,
        )
        return csrf_token

    async def get_session(self, request: Request) -> dict[str, Any] | None:
        session_id = request.cookies.get(SESSION_COOKIE)
        if not session_id:
            return None
        async with session_factory()() as session:
            record = await session.get(WebSession, session_id)
            if record is None:
                return None
            expires_at = record.expires_at
            if expires_at is not None and expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at is None or expires_at <= utcnow():
                return None
            return {
                "session_id": record.id,
                "user_id": record.user_id,
                "csrf_token": record.csrf_token,
            }

    async def destroy_session(self, request: Request, response: Response) -> None:
        session_id = request.cookies.get(SESSION_COOKIE)
        if session_id:
            async with session_factory()() as session:
                record = await session.get(WebSession, session_id)
                if record:
                    await session.delete(record)
                    await session.commit()
        response.delete_cookie(SESSION_COOKIE)


def _get_session_manager(request: Request) -> SessionManager:
    return request.app.state.session_manager


async def get_current_user(request: Request) -> WebAccount:
    manager: SessionManager = _get_session_manager(request)
    session_data = await manager.get_session(request)
    if session_data is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")
    async with session_factory()() as session:
        user = await session.get(WebAccount, session_data["user_id"])
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")
    return user


async def require_csrf(request: Request) -> None:
    manager: SessionManager = _get_session_manager(request)
    session_data = await manager.get_session(request)
    if session_data is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")
    supplied = request.headers.get("x-csrf-token")
    if not supplied:
        form = await request.form()
        supplied = form.get("csrf_token", "")
    if not supplied or supplied != session_data["csrf_token"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="csrf")


async def require_admin(user: WebAccount = Depends(get_current_user)) -> WebAccount:
    if user.permission_level < 1:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    return user


async def require_superadmin(user: WebAccount = Depends(get_current_user)) -> WebAccount:
    if user.permission_level < 2:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    return user


async def get_csrf_token(request: Request) -> str:
    manager: SessionManager = _get_session_manager(request)
    session_data = await manager.get_session(request)
    if session_data is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")
    return session_data["csrf_token"]


async def require_api_key(
    request: Request,
    x_api_key: str | None = Header(default=None),
) -> None:
    settings = request.app.state.settings
    allowed = settings.web.api_keys or []
    if not allowed:
        return
    if x_api_key is None or not any(
        hmac.compare_digest(x_api_key, key) for key in allowed
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid api key")
