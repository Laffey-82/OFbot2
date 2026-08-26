"""Webhook 页面与历史记录路由。"""

from __future__ import annotations

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
from sqlalchemy import func, select

from app.core.config import Settings, save_settings
from app.core.logger import get_logger
from app.core.security import audit_logger
from app.db.base import session_factory
from app.db.models import WebAccount, WebhookEvent
from app.web.deps import (
    get_csrf_token,
    get_current_user,
    require_admin,
    require_csrf,
)
from app.web.helpers import _parse_date_range, flash_redirect

logger = get_logger(__name__)


def build_router(*, app: FastAPI, settings: Settings, templates: Any) -> APIRouter:
    router = APIRouter()

    @router.get("/webhooks", response_class=HTMLResponse)
    async def webhooks_page(
        request: Request,
        user: WebAccount = Depends(get_current_user),
        csrf_token: str = Depends(get_csrf_token),
    ) -> HTMLResponse:
        service = app.state.services.get("webhook")
        webhooks = sorted(service.webhooks) if service else []
        filters = service.filters if service else {}
        last_triggered = service.last_triggered if service else {}

        history: dict[str, list[dict[str, Any]]] = {}
        async with session_factory()() as session:
            events = (
                await session.scalars(
                    select(WebhookEvent)
                    .order_by(WebhookEvent.created_at.desc())
                    .limit(200)
                )
            ).all()
        for event in events:
            history.setdefault(event.webhook_name, []).append(
                {
                    "time": (
                        event.created_at.isoformat()
                        if event.created_at
                        else ""
                    ),
                    "payload": event.payload,
                }
            )
        history = {name: entries[:10] for name, entries in history.items()}
        return templates.TemplateResponse(
            request,
            "webhooks.html",
            {
                "request": request,
                "user": user,
                "webhooks": webhooks,
                "filters": filters,
                "last_triggered": last_triggered,
                "history": history,
                "csrf_token": csrf_token,
            },
        )

    @router.post("/webhooks/add")
    async def webhooks_add(
        request: Request,
        user: WebAccount = Depends(require_admin),
        name: str = Form(...),
        filter_json: str = Form(""),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        service = app.state.services.get("webhook")
        if not (service and name):
            return flash_redirect("/webhooks", error="1")
        payload_filter: dict[str, Any] | None = None
        if filter_json.strip():
            try:
                import json

                parsed = json.loads(filter_json)
                if not isinstance(parsed, dict):
                    raise TypeError("filter must be an object")
                payload_filter = parsed
            except Exception:
                return flash_redirect("/webhooks", error="1")
        service.register(name, payload_filter)
        settings.plugin_configs.setdefault("webhooks", {})[name] = (
            payload_filter or {}
        )
        save_settings(settings)
        return flash_redirect("/webhooks", message=f"Webhook {name} 已注册")

    @router.get("/webhooks/{name}/history/export")
    async def webhooks_history_export(
        name: str,
        request: Request,
        user: WebAccount = Depends(require_admin),
        start: str = "",
        end: str = "",
        page: int = 0,
    ) -> Any:
        service = app.state.services.get("webhook")

        if service is None:
            raise HTTPException(status_code=404, detail="webhook history not found")
        import json

        start_dt, end_dt = _parse_date_range(start, end)
        where = [WebhookEvent.webhook_name == name]
        if start_dt is not None:
            where.append(WebhookEvent.created_at >= start_dt)
        if end_dt is not None:
            where.append(WebhookEvent.created_at <= end_dt)
        query = (
            select(WebhookEvent)
            .where(*where)
            .order_by(WebhookEvent.created_at.desc())
            .limit(100)
        )
        if page > 0:
            query = query.offset((page - 1) * 20).limit(20)
        async with session_factory()() as session:
            events = (await session.scalars(query)).all()
        if not events:
            raise HTTPException(status_code=404, detail="webhook history not found")
        entries = [
            {
                "time": event.created_at.isoformat() if event.created_at else "",
                "payload": event.payload,
            }
            for event in events
        ]
        range_part = ""
        if start or end:
            range_part = f"_{start or 'begin'}_{end or 'now'}"
        if page > 0:
            range_part += f"_p{page}"
        payload = json.dumps(
            entries,
            ensure_ascii=False,
            indent=2,
        ).encode("utf-8")
        return Response(
            payload,
            media_type="application/json",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="webhook_{name}_history'
                    f'{range_part}.json"'
                )
            },
        )

    @router.get("/webhooks/{name}/history", response_class=HTMLResponse)
    async def webhooks_history_page(
        name: str,
        request: Request,
        user: WebAccount = Depends(get_current_user),
        csrf_token: str = Depends(get_csrf_token),
        page: int = 1,
        start: str = "",
        end: str = "",
        page_size: int = 0,
    ) -> HTMLResponse:
        service = app.state.services.get("webhook")
        if service is None or name not in service.webhooks:
            raise HTTPException(status_code=404, detail="webhook not found")

        start_dt, end_dt = _parse_date_range(start, end)
        if page_size <= 0:
            page_size = settings.web.webhook_history_page_size
        page_size = max(5, min(page_size, 100))
        where = [WebhookEvent.webhook_name == name]
        if start_dt is not None:
            where.append(WebhookEvent.created_at >= start_dt)
        if end_dt is not None:
            where.append(WebhookEvent.created_at <= end_dt)
        async with session_factory()() as session:
            total = (
                await session.scalar(
                    select(func.count())
                    .select_from(WebhookEvent)
                    .where(*where)
                )
            ) or 0
            total_pages = max(1, (total + page_size - 1) // page_size)
            page = max(1, min(page, total_pages))
            events = (
                await session.scalars(
                    select(WebhookEvent)
                    .where(*where)
                    .order_by(WebhookEvent.created_at.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        return templates.TemplateResponse(
            request,
            "webhook_history.html",
            {
                "request": request,
                "user": user,
                "name": name,
                "events": events,
                "page": page,
                "total": total,
                "total_pages": total_pages,
                "start": start,
                "end": end,
                "page_size": page_size,
                "csrf_token": csrf_token,
            },
        )

    @router.post("/webhooks/{name}/history/clear")
    async def webhooks_history_clear(
        name: str,
        request: Request,
        user: WebAccount = Depends(require_admin),
        start: str = Form(""),
        end: str = Form(""),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        from sqlalchemy import delete

        start_dt, end_dt = _parse_date_range(start, end)
        delete_query = delete(WebhookEvent).where(
            WebhookEvent.webhook_name == name
        )
        if start_dt is not None:
            delete_query = delete_query.where(
                WebhookEvent.created_at >= start_dt
            )
        if end_dt is not None:
            delete_query = delete_query.where(WebhookEvent.created_at <= end_dt)
        async with session_factory()() as session:
            await session.execute(delete_query)
            await session.commit()
        audit_logger.record(
            "webhook.history_cleared", user.username, target=name, success=True
        )
        range_part = ""
        if start or end:
            range_part = f"（{start or '任意'} ~ {end or '现在'}）"
        return flash_redirect(
            f"/webhooks/{name}/history", message=f"历史已清空{range_part}"
        )

    @router.post("/webhooks/{name}/history/bulk-delete")
    async def webhooks_history_bulk_delete(
        name: str,
        request: Request,
        user: WebAccount = Depends(require_admin),
        ids: list[int] = Form(default=[]),
        start: str = Form(""),
        end: str = Form(""),
        scope: str = Form("selected"),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        from sqlalchemy import delete

        start_dt, end_dt = _parse_date_range(start, end)
        deleted = 0
        async with session_factory()() as session:
            if scope == "range":
                delete_query = delete(WebhookEvent).where(
                    WebhookEvent.webhook_name == name
                )
                if start_dt is not None:
                    delete_query = delete_query.where(
                        WebhookEvent.created_at >= start_dt
                    )
                if end_dt is not None:
                    delete_query = delete_query.where(
                        WebhookEvent.created_at <= end_dt
                    )
                result = await session.execute(delete_query)
                deleted = result.rowcount or 0
            elif ids:
                result = await session.execute(
                    delete(WebhookEvent).where(
                        WebhookEvent.id.in_(ids),
                        WebhookEvent.webhook_name == name,
                    )
                )
                deleted = result.rowcount or 0
            await session.commit()
        range_part = ""
        if scope == "range" and (start or end):
            range_part = f"（{start or '任意'} ~ {end or '现在'}）"
        kind = "筛选范围内全部" if scope == "range" else "选中"
        audit_logger.record(
            "webhook.history_deleted",
            user.username,
            target=f"{name}:{kind}{range_part}",
            success=True,
            detail={"count": deleted, "scope": scope, "start": start, "end": end},
        )
        return flash_redirect(
            f"/webhooks/{name}/history",
            message=f"已删除 {deleted} 条记录{range_part}",
        )

    @router.post("/webhooks/remove")
    async def webhooks_remove(
        request: Request,
        user: WebAccount = Depends(require_admin),
        name: str = Form(...),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        service = app.state.services.get("webhook")
        if service is None or not service.remove(name):
            return flash_redirect("/webhooks", error="Webhook 不存在")
        settings.plugin_configs.setdefault("webhooks", {}).pop(name, None)
        save_settings(settings)
        return flash_redirect("/webhooks", message="Webhook 已删除")

    @router.post("/webhooks/{name}/history/{event_id}/replay")
    async def webhooks_history_replay(
        name: str,
        event_id: int,
        request: Request,
        user: WebAccount = Depends(require_admin),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        """重放历史触发记录：用真实载荷再次触发该 Webhook。"""
        service = app.state.services.get("webhook")
        if service is None or name not in service.webhooks:
            return flash_redirect(
                f"/webhooks/{name}/history", error="Webhook 不存在"
            )
        async with session_factory()() as session:
            event = await session.get(WebhookEvent, event_id)
        if event is None or event.webhook_name != name:
            return flash_redirect(
                f"/webhooks/{name}/history", error="触发记录不存在"
            )
        matched = bool(service.matches(name, event.payload))
        await service.handle(name, event.payload)
        audit_logger.record(
            "webhook.replayed",
            user.username,
            target=f"{name}#{event_id}",
            success=True,
            detail={"matched": matched},
        )
        message = (
            "已重放并触发流程"
            if matched
            else "已重放（载荷与过滤器不匹配，未触发流程）"
        )
        return flash_redirect(f"/webhooks/{name}/history", message=message)

    return router
