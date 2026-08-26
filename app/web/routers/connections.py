"""连接中心路由：适配器状态、重连、测试与试发消息。"""

from __future__ import annotations

import time
from datetime import UTC, datetime
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

from app.core.config import ConnectionSettings, Settings, save_settings
from app.core.logger import get_logger
from app.core.security import audit_logger
from app.db.base import session_factory
from app.db.models import AdapterTestLog, WebAccount
from app.web.deps import (
    get_csrf_token,
    get_current_user,
    require_admin,
    require_csrf,
)
from app.web.helpers import flash_redirect

logger = get_logger(__name__)


def _default_path(protocol: str, version: str, mode: str) -> str:
    if mode in {"reverse_ws", "reverse"}:
        if protocol == "onebot" and version == "v12":
            return "/onebot/v12/ws"
        return "/onebot/v11/ws"
    if protocol == "satori":
        return "/"
    return "/onebot/v11/ws"


async def _apply_connections(app: FastAPI, settings: Settings) -> None:
    """连接热重载（服务运行时可用）。"""
    reconfigure = getattr(app.state, "reconfigure_adapters", None)
    if reconfigure is not None:
        try:
            await reconfigure()
        except Exception:
            logger.exception("connection reconfigure failed")


def build_router(*, app: FastAPI, settings: Settings, templates: Any) -> APIRouter:
    router = APIRouter()

    @router.get("/connections", response_class=HTMLResponse)
    async def connections_page(
        request: Request,
        user: WebAccount = Depends(get_current_user),
        csrf_token: str = Depends(get_csrf_token),
    ) -> HTMLResponse:
        bot_client = getattr(app.state, "bot_client", None)
        adapters = getattr(bot_client, "status", {})
        details = getattr(bot_client, "details", {})
        counters = getattr(bot_client, "counters", {})
        merged: dict[str, Any] = {}
        for name in set(details) | set(counters):
            merged[name] = {**details.get(name, {}), **counters.get(name, {})}
        for info in merged.values():
            heartbeat = info.get("last_heartbeat")
            if isinstance(heartbeat, (int, float)):
                stale_after = settings.security.heartbeat_stale_seconds
                info["heartbeat_stale"] = (time.time() - heartbeat) > stale_after
            for key in ("connected_at", "last_heartbeat"):
                value = info.get(key)
                if isinstance(value, (int, float)):
                    info[key] = datetime.fromtimestamp(
                        value, tz=UTC
                    ).strftime("%Y-%m-%d %H:%M:%S")
        test_history: dict[str, list[dict[str, Any]]] = {}
        for name, entries in app.state.adapter_test_history.items():
            test_history[name] = list(reversed(entries))
        async with session_factory()() as session:
            test_rows = (
                await session.scalars(
                    select(AdapterTestLog)
                    .order_by(AdapterTestLog.created_at.desc())
                    .limit(100)
                )
            ).all()
        for row in test_rows:
            test_history.setdefault(row.adapter_name, []).append(
                {
                    "time": (
                        row.created_at.isoformat() if row.created_at else ""
                    ),
                    "ok": row.ok,
                    "detail": row.detail,
                }
            )
        test_history = {
            name: entries[-5:] for name, entries in test_history.items()
        }
        return templates.TemplateResponse(
            request,
            "connections.html",
            {
                "request": request,
                "user": user,
                "adapters": adapters,
                "details": merged,
                "config": settings.model_dump(mode="json"),
                "last_reconfigured": getattr(
                    app.state, "last_reconfigured", ""
                ),
                "connections": settings.transport.connections,
                "test_history": test_history,
                "csrf_token": csrf_token,
            },
        )

    @router.post("/connections/add")
    async def connections_add(
        request: Request,
        user: WebAccount = Depends(require_admin),
        conn_id: str = Form(...),
        protocol: str = Form("onebot"),
        version: str = Form("v11"),
        mode: str = Form("reverse_ws"),
        host: str = Form("127.0.0.1"),
        port: int = Form(8080),
        path: str = Form(""),
        access_token: str = Form(""),
        token: str = Form(""),
        api_base: str = Form(""),
        app_id: str = Form(""),
        secret: str = Form(""),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        conn_id = conn_id.strip()
        if not conn_id or any(
            item.id == conn_id for item in settings.transport.connections
        ):
            return flash_redirect("/connections", error="连接 ID 为空或已存在")
        try:
            connection = ConnectionSettings(
                id=conn_id,
                protocol=protocol,
                version=version,
                mode=mode,
                host=host,
                port=port,
                path=path or _default_path(protocol, version, mode),
                access_token=access_token,
                token=token,
                api_base=api_base,
                app_id=app_id,
                secret=secret,
            )
        except Exception as exc:
            return flash_redirect("/connections", error=f"配置无效：{exc}")
        settings.transport.connections.append(connection)
        save_settings(settings)
        await _apply_connections(app, settings)
        audit_logger.record(
            "adapter.added", user.username, target=conn_id, success=True
        )
        return flash_redirect("/connections", message=f"已新增连接 {conn_id}")

    @router.post("/connections/{conn_id}/toggle")
    async def connections_toggle(
        conn_id: str,
        request: Request,
        user: WebAccount = Depends(require_admin),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        for connection in settings.transport.connections:
            if connection.id == conn_id:
                connection.enabled = not connection.enabled
                save_settings(settings)
                await _apply_connections(app, settings)
                audit_logger.record(
                    "adapter.toggled",
                    user.username,
                    target=conn_id,
                    success=True,
                )
                state = "启用" if connection.enabled else "停用"
                return flash_redirect(
                    "/connections", message=f"连接 {conn_id} 已{state}"
                )
        return flash_redirect("/connections", error="连接不存在")

    @router.post("/connections/{conn_id}/delete")
    async def connections_delete(
        conn_id: str,
        request: Request,
        user: WebAccount = Depends(require_admin),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        before = len(settings.transport.connections)
        settings.transport.connections = [
            item
            for item in settings.transport.connections
            if item.id != conn_id
        ]
        if len(settings.transport.connections) == before:
            return flash_redirect("/connections", error="连接不存在")
        save_settings(settings)
        await _apply_connections(app, settings)
        audit_logger.record(
            "adapter.deleted", user.username, target=conn_id, success=True
        )
        return flash_redirect("/connections", message=f"已删除连接 {conn_id}")

    @router.post("/connections/{name}/reconnect")
    async def connections_reconnect(
        name: str,
        request: Request,
        user: WebAccount = Depends(require_admin),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        adapters = getattr(app.state, "adapters", [])
        adapter = next((item for item in adapters if getattr(item, "bot_id", "") == name), None)
        if adapter is None:
            return flash_redirect("/connections", error="1")
        try:
            await adapter.stop()
        except Exception:
            pass
        logger.info("reconnecting adapter %s", name)
        background = getattr(app.state, "background_worker", None)
        if background is not None:
            await background.submit(f"adapter-{name}", adapter.start())
        else:
            await adapter.start()
        audit_logger.record(
            "adapter.reconnected", user.username, target=name, success=True
        )
        return flash_redirect("/connections", message=f"适配器 {name} 已重连")

    @router.post("/connections/{name}/test")
    async def connections_test(
        name: str,
        request: Request,
        user: WebAccount = Depends(require_admin),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        adapters = getattr(app.state, "adapters", [])
        adapter = next(
            (item for item in adapters if getattr(item, "bot_id", "") == name),
            None,
        )
        if adapter is None or not hasattr(adapter, "test"):
            return flash_redirect("/connections", error="1")
        try:
            ok, detail = await adapter.test()
        except Exception as exc:
            ok, detail = False, str(exc)
        audit_logger.record(
            "adapter.tested", user.username, target=name, success=ok
        )
        history = app.state.adapter_test_history.setdefault(name, [])
        history.append(
            {
                "time": datetime.now(UTC).isoformat(timespec="seconds"),
                "ok": ok,
                "detail": detail,
            }
        )
        app.state.adapter_test_history[name] = history[-5:]
        try:
            async with session_factory()() as session:
                session.add(
                    AdapterTestLog(
                        adapter_name=name,
                        ok=ok,
                        detail=detail[:1000],
                    )
                )
                await session.commit()
        except Exception:
            logger.exception("failed to persist adapter test log")
        if ok:
            return flash_redirect(
                "/connections", message=f"{name} 测试成功：{detail}"
            )
        return flash_redirect(
            "/connections", error=f"{name} 测试失败：{detail}"
        )

    @router.post("/connections/reconnect-all")
    async def connections_reconnect_all(
        request: Request,
        user: WebAccount = Depends(require_admin),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        adapters = getattr(app.state, "adapters", [])
        background = getattr(app.state, "background_worker", None)
        count = 0
        for adapter in adapters:
            name = getattr(adapter, "bot_id", "?")
            try:
                await adapter.stop()
            except Exception:
                pass
            if background is not None:
                await background.submit(f"adapter-{name}", adapter.start())
            else:
                await adapter.start()
            count += 1
        audit_logger.record(
            "adapter.reconnect_all",
            user.username,
            target=str(count),
            success=True,
        )
        return flash_redirect("/connections", message=f"已重连 {count} 个适配器")

    @router.post("/connections/test-all")
    async def connections_test_all(
        request: Request,
        user: WebAccount = Depends(require_admin),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        adapters = getattr(app.state, "adapters", [])
        ok_count = 0
        fail_count = 0
        for adapter in adapters:
            name = getattr(adapter, "bot_id", "?")
            test = getattr(adapter, "test", None)
            if test is None:
                continue
            try:
                ok, detail = await test()
            except Exception as exc:
                ok, detail = False, str(exc)
            if ok:
                ok_count += 1
            else:
                fail_count += 1
            history = app.state.adapter_test_history.setdefault(name, [])
            history.append(
                {
                    "time": datetime.now(UTC).isoformat(timespec="seconds"),
                    "ok": ok,
                    "detail": detail,
                }
            )
            app.state.adapter_test_history[name] = history[-5:]
            try:
                async with session_factory()() as session:
                    session.add(
                        AdapterTestLog(
                            adapter_name=name,
                            ok=ok,
                            detail=detail[:1000],
                        )
                    )
                    await session.commit()
            except Exception:
                logger.exception("failed to persist adapter test log")
        audit_logger.record(
            "adapter.test_all",
            user.username,
            target=f"ok={ok_count},fail={fail_count}",
            success=True,
        )
        return flash_redirect(
            "/connections", message=f"测试完成：成功 {ok_count} / 失败 {fail_count}"
        )

    @router.post("/connections/send-test")
    async def connections_send_test(
        request: Request,
        user: WebAccount = Depends(require_admin),
        group_id: str = Form(""),
        message: str = Form(""),
        target_type: str = Form("group"),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        bot_client = getattr(app.state, "bot_client", None)
        if bot_client is None:
            return flash_redirect("/connections", error="1")
        targets = []
        for part in group_id.replace("，", ",").replace(";", "\n").splitlines():
            for token in part.split(","):
                token = token.strip()
                if token and token not in targets:
                    targets.append(token)
        targets = targets[:50]
        if not targets:
            return flash_redirect("/connections", error="请至少填写一个目标 QQ / 群号")
        results = []
        ok_count = fail_count = 0
        for target in targets:
            ok = False
            detail = ""
            try:
                if target_type == "private":
                    ok = await bot_client.send_private_message(target, message)
                else:
                    ok = await bot_client.send_group_message(target, message)
            except Exception as exc:
                detail = str(exc)
            if ok:
                ok_count += 1
            else:
                fail_count += 1
            results.append(
                {"target": target, "ok": ok, "detail": detail or ""}
            )
        audit_logger.record(
            "adapter.send_test",
            user.username,
            target=target_type,
            success=fail_count == 0,
            detail={"results": results, "message": message},
        )
        kind = "私聊" if target_type == "private" else "群聊"
        if fail_count == 0:
            return flash_redirect(
                "/connections",
                message=f"已向 {ok_count} 个{kind}目标发送测试消息",
            )
        failed_preview = "、".join(
            r["target"] for r in results if not r["ok"]
        )[:120]
        return flash_redirect(
            "/connections",
            error=(
                f"发送完成：成功 {ok_count} / 失败 {fail_count}"
                + (f"（失败目标：{failed_preview}）" if failed_preview else "")
            ),
        )

    return router
