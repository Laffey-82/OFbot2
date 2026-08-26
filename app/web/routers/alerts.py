"""告警规则与历史记录路由。"""

from __future__ import annotations

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
    Response,
)
from sqlalchemy import func, select

from app.core.config import Settings
from app.core.logger import get_logger
from app.core.security import audit_logger
from app.db.base import session_factory
from app.db.models import AlertEvent, WebAccount
from app.services.alerts import persist_alert_rules
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

    @router.get("/alerts", response_class=HTMLResponse)
    async def alerts_page(
        request: Request,
        user: WebAccount = Depends(get_current_user),
        csrf_token: str = Depends(get_csrf_token),
        rule: str = "",
        event: str = "",
        start: str = "",
        end: str = "",
        page: int = 1,
        stats_days: int = 0,
    ) -> HTMLResponse:
        service = app.state.services.get("alerts")
        rules = service.rules if service else []
        start_dt, end_dt = _parse_date_range(start, end)
        async with session_factory()() as session:
            query = select(AlertEvent)
            if rule.strip():
                query = query.where(
                    AlertEvent.rule_name.contains(rule.strip())
                )
            if event.strip():
                query = query.where(AlertEvent.event.contains(event.strip()))
            if start_dt is not None:
                query = query.where(AlertEvent.created_at >= start_dt)
            if end_dt is not None:
                query = query.where(AlertEvent.created_at <= end_dt)
            total_events = (
                await session.scalar(
                    select(func.count()).select_from(query.subquery())
                )
            ) or 0
            page_size = 50
            total_pages = max(1, (total_events + page_size - 1) // page_size)
            page = max(1, min(page, total_pages))
            events = (
                await session.scalars(
                    query.order_by(AlertEvent.created_at.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
            from datetime import timedelta

            stats_cutoff = None
            if stats_days > 0:
                stats_cutoff = datetime.now(UTC) - timedelta(
                    days=min(stats_days, 365)
                )
            stats_query = select(func.count()).select_from(AlertEvent)
            if stats_cutoff is not None:
                stats_query = stats_query.where(
                    AlertEvent.created_at >= stats_cutoff
                )
            total_alerts = (
                await session.scalar(stats_query)
            ) or 0
            today_start = datetime.now(UTC).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            today_alerts = (
                await session.scalar(
                    select(func.count())
                    .select_from(AlertEvent)
                    .where(AlertEvent.created_at >= today_start)
                )
            ) or 0
            top_rule_rows = (
                await session.execute(
                    select(
                        AlertEvent.rule_name,
                        func.count().label("count"),
                    )
                    .where(
                        AlertEvent.created_at >= stats_cutoff
                        if stats_cutoff is not None
                        else True
                    )
                    .group_by(AlertEvent.rule_name)
                    .order_by(func.count().desc())
                    .limit(3)
                )
            ).all()
            top_event_rows = (
                await session.execute(
                    select(
                        AlertEvent.event,
                        func.count().label("count"),
                    )
                    .where(
                        AlertEvent.created_at >= stats_cutoff
                        if stats_cutoff is not None
                        else True
                    )
                    .group_by(AlertEvent.event)
                    .order_by(func.count().desc())
                    .limit(3)
                )
            ).all()
            top_rules = [
                {"name": row.rule_name, "count": row.count}
                for row in top_rule_rows
            ]
            top_events = [
                {"name": row.event, "count": row.count}
                for row in top_event_rows
            ]
        import re as _re

        event_rows: list[dict[str, Any]] = []
        for item in events:
            run_link = ""
            if item.event == "workflow.failed":
                run_match = _re.search(r"run #(\d+)", item.detail or "")
                if run_match:
                    run_link = f"/workflows/runs/{run_match.group(1)}"
            event_rows.append(
                {
                    "rule_name": item.rule_name,
                    "event": item.event,
                    "detail": item.detail,
                    "created_at": item.created_at,
                    "run_link": run_link,
                }
            )
        return templates.TemplateResponse(
            request,
            "alerts.html",
            {
                "request": request,
                "user": user,
                "rules": rules,
                "events": event_rows,
                "filter_rule": rule,
                "filter_event": event,
                "filter_start": start,
                "filter_end": end,
                "page": page,
                "total_events": total_events,
                "total_pages": total_pages,
                "alert_history_retention_days": (
                    settings.web.alert_history_retention_days
                ),
                "alert_min_interval_seconds": (
                    settings.web.alert_min_interval_seconds
                ),
                "total_alerts": total_alerts,
                "today_alerts": today_alerts,
                "top_rules": top_rules,
                "top_events": top_events,
                "stats_days": stats_days,
                "csrf_token": csrf_token,
            },
        )

    @router.get("/alerts/export")
    async def alerts_export(
        request: Request,
        user: WebAccount = Depends(require_admin),
        rule: str = "",
        event: str = "",
        start: str = "",
        end: str = "",
    ) -> Response:
        import csv
        import io

        start_dt, end_dt = _parse_date_range(start, end)
        async with session_factory()() as session:
            query = select(AlertEvent)
            if rule.strip():
                query = query.where(
                    AlertEvent.rule_name.contains(rule.strip())
                )
            if event.strip():
                query = query.where(AlertEvent.event.contains(event.strip()))
            if start_dt is not None:
                query = query.where(AlertEvent.created_at >= start_dt)
            if end_dt is not None:
                query = query.where(AlertEvent.created_at <= end_dt)
            events = (
                await session.scalars(
                    query.order_by(AlertEvent.created_at.desc()).limit(5000)
                )
            ).all()
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["created_at", "rule_name", "event", "detail"])
        for item in events:
            writer.writerow(
                [
                    item.created_at.isoformat() if item.created_at else "",
                    item.rule_name,
                    item.event,
                    item.detail,
                ]
            )
        range_part = ""
        if start or end:
            range_part = f"_{start or 'begin'}_{end or 'now'}"
        filename = (
            f"alerts{range_part}_"
            f"{datetime.now(UTC).strftime('%Y%m%d_%H%M')}_{len(events)}.csv"
        )
        return Response(
            buffer.getvalue().encode("utf-8-sig"),
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            },
        )

    @router.post("/alerts/history/clear")
    async def alerts_history_clear(
        request: Request,
        user: WebAccount = Depends(require_admin),
        start: str = Form(""),
        end: str = Form(""),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        from sqlalchemy import delete

        start_dt, end_dt = _parse_date_range(start, end)
        delete_query = delete(AlertEvent)
        if start_dt is not None:
            delete_query = delete_query.where(
                AlertEvent.created_at >= start_dt
            )
        if end_dt is not None:
            delete_query = delete_query.where(
                AlertEvent.created_at <= end_dt
            )
        async with session_factory()() as session:
            result = await session.execute(delete_query)
            await session.commit()
            deleted = result.rowcount or 0
        audit_logger.record(
            "alert.history_cleared",
            user.username,
            target=f"alerts:{deleted}",
            success=True,
            detail={"start": start, "end": end},
        )
        range_part = ""
        if start or end:
            range_part = f"（{start or '任意'} ~ {end or '现在'}）"
        return flash_redirect(
            "/alerts", message=f"已清除 {deleted} 条告警历史{range_part}"
        )

    @router.post("/alerts/add")
    async def alerts_add(
        request: Request,
        user: WebAccount = Depends(require_admin),
        name: str = Form(...),
        event: str = Form("*"),
        target_group: str = Form(""),
        target_private: str = Form(""),
        keyword: str = Form(""),
        min_interval_seconds: int = Form(0),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        service = app.state.services.get("alerts")
        if service and name:
            service.add_rule(
                name,
                event,
                target_group,
                target_private,
                keyword,
                min_interval_seconds,
            )
            persist_alert_rules(settings, service)
        return flash_redirect("/alerts", message=f"告警规则 {name} 已添加")

    @router.post("/alerts/remove")
    async def alerts_remove(
        request: Request,
        user: WebAccount = Depends(require_admin),
        name: str = Form(...),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        service = app.state.services.get("alerts")
        if service is None or not service.remove_rule(name):
            return flash_redirect("/alerts", error="规则不存在")
        persist_alert_rules(settings, service)
        return flash_redirect("/alerts", message="告警规则已删除")

    @router.post("/alerts/toggle")
    async def alerts_toggle(
        request: Request,
        user: WebAccount = Depends(require_admin),
        name: str = Form(...),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        service = app.state.services.get("alerts")
        if service is None:
            return flash_redirect("/alerts", error="1")
        rule = next((r for r in service.rules if r.name == name), None)
        if rule is None:
            return flash_redirect("/alerts", error="规则不存在")
        enabled = service.toggle_rule(name)
        persist_alert_rules(settings, service)
        return flash_redirect(
            "/alerts", message=f"规则 {name} 已{'启用' if enabled else '禁用'}"
        )

    @router.post("/alerts/{name}/edit")
    async def alerts_edit(
        name: str,
        request: Request,
        user: WebAccount = Depends(require_admin),
        event: str = Form("*"),
        target_group: str = Form(""),
        target_private: str = Form(""),
        keyword: str = Form(""),
        min_interval_seconds: int = Form(0),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        service = app.state.services.get("alerts")
        if service is None:
            return flash_redirect("/alerts", error="1")
        rule = next((r for r in service.rules if r.name == name), None)
        if rule is None:
            return flash_redirect("/alerts", error="1")
        rule.event = event
        rule.target_group = target_group
        rule.target_private = target_private
        rule.keyword = keyword
        rule.min_interval_seconds = max(0, min_interval_seconds)
        persist_alert_rules(settings, service)
        audit_logger.record(
            "alert.updated", user.username, target=name, success=True
        )
        return flash_redirect("/alerts", message=f"规则 {name} 已更新")

    @router.post("/alerts/{name}/test")
    async def alerts_test(
        name: str,
        request: Request,
        user: WebAccount = Depends(require_admin),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        service = app.state.services.get("alerts")
        if service is None:
            return flash_redirect("/alerts", error="1")
        rule = next((r for r in service.rules if r.name == name), None)
        if rule is None:
            return flash_redirect("/alerts", error="1")
        notifier = getattr(service, "notifier", None)
        if notifier is None:
            return flash_redirect(
                "/alerts",
                error="通知通道未配置（服务未运行），请启动后重试",
            )
        detail = f"测试通知：规则 {name}（事件 {rule.event}）"
        try:
            await notifier(rule, detail)
        except Exception as exc:
            audit_logger.record(
                "alert.test_failed",
                user.username,
                target=name,
                success=False,
                detail={"error": str(exc)},
            )
            return flash_redirect("/alerts", error=f"测试发送失败：{exc}")
        audit_logger.record(
            "alert.test_sent", user.username, target=name, success=True
        )
        return flash_redirect(
            "/alerts", message=f"已向规则 {name} 发送测试通知"
        )

    return router
