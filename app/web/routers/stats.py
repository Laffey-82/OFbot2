"""命令统计页面与导出路由。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    Query,
    Request,
)
from fastapi.responses import (
    HTMLResponse,
    Response,
)
from sqlalchemy import func, select

from app.core.config import Settings
from app.core.logger import get_logger
from app.db.base import session_factory
from app.db.models import CommandStat, WebAccount
from app.web.deps import get_current_user, require_admin

logger = get_logger(__name__)


def build_router(*, app: FastAPI, settings: Settings, templates: Any) -> APIRouter:
    router = APIRouter()

    @router.get("/stats", response_class=HTMLResponse)
    async def stats_page(
        request: Request,
        user: WebAccount = Depends(get_current_user),
        days: int = 0,
        command: str = "",
        day: str = "",
        filter_user: str = Query(default="", alias="user"),
    ) -> HTMLResponse:
        from datetime import timedelta

        if command:
            from datetime import timedelta

            time_filter = None
            if days > 0:
                time_filter = datetime.now(UTC) - timedelta(days=days)
            time_where = (
                CommandStat.timestamp >= time_filter
                if time_filter is not None
                else True
            )
            async with session_factory()() as session:
                total = (
                    await session.scalar(
                        select(func.count())
                        .select_from(CommandStat)
                        .where(CommandStat.command_name == command, time_where)
                    )
                ) or 0
                failed = (
                    await session.scalar(
                        select(func.count())
                        .select_from(CommandStat)
                        .where(
                            CommandStat.command_name == command,
                            CommandStat.success.is_(False),
                            time_where,
                        )
                    )
                ) or 0
                recent = (
                    await session.scalars(
                        select(CommandStat)
                        .where(CommandStat.command_name == command, time_where)
                        .order_by(CommandStat.timestamp.desc())
                        .limit(100)
                    )
                ).all()
                daily_rows = (
                    await session.execute(
                        select(
                            func.date(CommandStat.timestamp).label("day"),
                            func.count().label("cnt"),
                        )
                        .where(
                            CommandStat.command_name == command,
                            CommandStat.timestamp
                            >= datetime.now(UTC) - timedelta(days=30),
                        )
                        .group_by(func.date(CommandStat.timestamp))
                        .order_by(func.date(CommandStat.timestamp))
                    )
                ).all()
                hourly_rows: list[Any] = []
                if day:
                    try:
                        day_dt = datetime.fromisoformat(day)
                    except ValueError:
                        day_dt = None
                    if day_dt is not None:
                        hour_start = day_dt.replace(
                            hour=0, minute=0, second=0, microsecond=0
                        )
                        hour_end = hour_start + timedelta(days=1)
                        hourly_rows = (
                            await session.execute(
                                select(
                                    func.strftime(
                                        "%H", CommandStat.timestamp
                                    ).label("hour"),
                                    func.count().label("cnt"),
                                )
                                .where(
                                    CommandStat.command_name == command,
                                    CommandStat.timestamp >= hour_start,
                                    CommandStat.timestamp < hour_end,
                                )
                                .group_by(
                                    func.strftime(
                                        "%H", CommandStat.timestamp
                                    )
                                )
                                .order_by(
                                    func.strftime(
                                        "%H", CommandStat.timestamp
                                    )
                                )
                            )
                        ).all()
            command_trend = [
                {"date": str(day), "count": cnt} for day, cnt in daily_rows
            ]
            hourly = [
                {"hour": int(h or 0), "count": cnt}
                for h, cnt in hourly_rows
            ]
            return templates.TemplateResponse(
                request,
                "stats_command.html",
                {
                    "request": request,
                    "user": user,
                    "command": command,
                    "total": total,
                    "failed": failed,
                    "recent": recent,
                    "days": days,
                    "command_trend": command_trend,
                    "hourly": hourly,
                    "day": day,
                },
            )

        time_filter = None
        if days > 0:
            time_filter = datetime.now(UTC) - timedelta(days=days)
        user_where = (
            CommandStat.user_id == filter_user if filter_user else None
        )
        async with session_factory()() as session:
            base = select(CommandStat)
            if time_filter is not None:
                base = base.where(CommandStat.timestamp >= time_filter)
            if user_where is not None:
                base = base.where(user_where)
            total_commands = (
                await session.scalar(
                    select(func.count()).select_from(base.subquery())
                )
            ) or 0
            failed_query = (
                select(func.count())
                .select_from(CommandStat)
                .where(CommandStat.success.is_(False))
            )
            if time_filter is not None:
                failed_query = failed_query.where(
                    CommandStat.timestamp >= time_filter
                )
            if user_where is not None:
                failed_query = failed_query.where(user_where)
            failed_commands = (await session.scalar(failed_query)) or 0
            command_query = (
                select(CommandStat.command_name, func.count().label("cnt"))
                .group_by(CommandStat.command_name)
                .order_by(func.count().desc())
                .limit(20)
            )
            user_query = (
                select(CommandStat.user_id, func.count().label("cnt"))
                .group_by(CommandStat.user_id)
                .order_by(func.count().desc())
                .limit(20)
            )
            group_query = (
                select(CommandStat.group_id, func.count().label("cnt"))
                .where(CommandStat.group_id.isnot(None))
                .group_by(CommandStat.group_id)
                .order_by(func.count().desc())
                .limit(20)
            )
            if time_filter is not None:
                command_query = command_query.where(
                    CommandStat.timestamp >= time_filter
                )
                user_query = user_query.where(CommandStat.timestamp >= time_filter)
                group_query = group_query.where(CommandStat.timestamp >= time_filter)
            if user_where is not None:
                command_query = command_query.where(user_where)
                group_query = group_query.where(user_where)
            top_commands = (
                await session.execute(command_query)
            ).all()
            top_users = (
                await session.execute(user_query)
            ).all()
            top_groups = (
                await session.execute(group_query)
            ).all()
        return templates.TemplateResponse(
            request,
            "stats.html",
            {
                "request": request,
                "user": user,
                "total_commands": total_commands,
                "failed_commands": failed_commands,
                "top_commands": top_commands,
                "top_users": top_users,
                "top_groups": top_groups,
                "days": days,
                "filter_user": filter_user,
            },
        )

    @router.get("/stats/export")
    async def stats_export(
        request: Request,
        user: WebAccount = Depends(require_admin),
        days: int = 0,
        command: str = "",
        day: str = "",
    ) -> Response:
        from datetime import timedelta

        time_filter = None
        if days > 0:
            time_filter = datetime.now(UTC) - timedelta(days=days)
        import csv
        import io

        if command:
            where = [CommandStat.command_name == command]
            if time_filter is not None:
                where.append(CommandStat.timestamp >= time_filter)
            if day:
                try:
                    day_dt = datetime.fromisoformat(day)
                except ValueError:
                    day_dt = None
                if day_dt is not None:
                    hour_start = day_dt.replace(
                        hour=0, minute=0, second=0, microsecond=0
                    )
                    where = [
                        CommandStat.command_name == command,
                        CommandStat.timestamp >= hour_start,
                        CommandStat.timestamp < hour_start + timedelta(days=1),
                    ]
            group_col = (
                func.strftime("%H", CommandStat.timestamp)
                if day
                else func.date(CommandStat.timestamp)
            )
            query = select(group_col.label("bucket"), func.count())
            query = query.where(*where).group_by(group_col).order_by(group_col)
            async with session_factory()() as session:
                rows = (await session.execute(query)).all()
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow(["bucket", "count"])
            for bucket, cnt in rows:
                writer.writerow([bucket, cnt])
            suffix = f"_{day}" if day else f"_{days or 30}d"
            return Response(
                buffer.getvalue().encode("utf-8-sig"),
                media_type="text/csv",
                headers={
                    "Content-Disposition": (
                        f'attachment; filename="command_stats{suffix}.csv"'
                    )
                },
            )

        query = select(
            CommandStat.command_name,
            CommandStat.success,
            func.count().label("cnt"),
        ).group_by(CommandStat.command_name, CommandStat.success)
        if time_filter is not None:
            query = query.where(CommandStat.timestamp >= time_filter)
        query = query.order_by(func.count().desc()).limit(200)
        async with session_factory()() as session:
            rows = (await session.execute(query)).all()
        stats: dict[str, dict[str, int]] = {}
        for cmd_name, success, cnt in rows:
            entry = stats.setdefault(cmd_name, {"total": 0, "ok": 0, "fail": 0})
            entry["total"] += cnt
            if success:
                entry["ok"] += cnt
            else:
                entry["fail"] += cnt

        import csv
        import io

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["command", "total", "success", "failed", "success_rate"])
        for cmd_name, entry in sorted(
            stats.items(), key=lambda item: item[1]["total"], reverse=True
        ):
            rate = (
                round(entry["ok"] * 100 / entry["total"])
                if entry["total"]
                else 0
            )
            writer.writerow(
                [
                    cmd_name,
                    entry["total"],
                    entry["ok"],
                    entry["fail"],
                    f"{rate}%",
                ]
            )
        return Response(
            buffer.getvalue().encode("utf-8-sig"),
            media_type="text/csv",
            headers={
                "Content-Disposition": 'attachment; filename="command_stats.csv"'
            },
        )

    return router
