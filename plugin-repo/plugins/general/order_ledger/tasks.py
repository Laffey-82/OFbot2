"""order_ledger 插件定时任务：未接单提醒、每日/每周分账、月度归档。"""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta

from app.core.messages import Message, MessageSegment
from app.core.paths import runtime_root
from app.core.plugin import PluginContext

from . import services

_ctx: PluginContext | None = None


def init(ctx: PluginContext) -> None:
    global _ctx
    _ctx = ctx


def ctx() -> PluginContext:
    if _ctx is None:
        raise RuntimeError("order_ledger tasks not initialized")
    return _ctx


def _task_enabled(name: str) -> bool:
    cfg = services.config()
    return bool(cfg.get("tasks", {}).get(name, {}).get("enabled", True))


async def no_take_remind() -> None:
    """每小时：检查超时还原与未接单提醒。"""
    if not _task_enabled("no_take_remind"):
        return
    cfg = services.config()
    hours = int(cfg["order_settings"].get("no_take_remind_hours", 2))
    for group_id in services.resolve_target_groups():
        try:
            remind = await services.check_overdue(group_id)
            if not remind:
                continue
            reminder = f"未接单提醒：以下订单超过{hours}小时未接单\n"
            for order in remind[:5]:
                reminder += "\n" + services.format_order_card(order)
            await services.send_to_groups(reminder, [group_id])
        except Exception as exc:
            ctx().logger.warning("group %s no-take remind failed: %s", group_id, exc)


async def daily_commission() -> None:
    """每日 01:00：生成昨日分账总结并保存历史。"""
    if not _task_enabled("daily_commission"):
        return
    yesterday = services.yesterday()
    for group_id in services.resolve_target_groups():
        try:
            data, summary = await services.generate_commission(
                group_id, yesterday, yesterday, "昨日"
            )
            await services.save_history(
                group_id, "daily", yesterday, yesterday, summary, data
            )
            await services.send_to_groups(summary, [group_id])
            cfg = services.config()
            if cfg.get("tasks", {}).get("daily_commission", {}).get("export"):
                await _send_export(group_id, yesterday, yesterday, "昨日")
        except Exception as exc:
            ctx().logger.warning("group %s daily commission failed: %s", group_id, exc)


async def weekly_commission() -> None:
    """每周六 01:00：生成上周分账总结并保存历史。"""
    if not _task_enabled("weekly_commission"):
        return
    start, end = services.last_week_range()
    for group_id in services.resolve_target_groups():
        try:
            data, summary = await services.generate_commission(
                group_id, start, end, "本周"
            )
            await services.save_history(
                group_id, "weekly", start, end, summary, data
            )
            await services.send_to_groups(summary, [group_id])
        except Exception as exc:
            ctx().logger.warning("group %s weekly commission failed: %s", group_id, exc)


async def monthly_archive() -> None:
    """每月 1 日 02:00：归档指定月份之前的已完成订单到 JSON 文件。"""
    if not _task_enabled("monthly_archive"):
        return
    cfg = services.config()
    months = int(cfg.get("archive", {}).get("months", 3))
    cutoff = (services.now() - timedelta(days=months * 30)).strftime("%Y-%m-%d")
    for group_id in services.resolve_target_groups():
        try:
            orders = await services.list_orders(group_id)
            old = [
                o
                for o in orders
                if o.get("status") == "已完成"
                and o.get("complete_time")
                and str(o["complete_time"])[:10] < cutoff
            ]
            if not old:
                continue
            archive_dir = runtime_root() / "data" / "archives"
            archive_dir.mkdir(parents=True, exist_ok=True)
            filename = (
                f"order_ledger_{group_id}_{services.now().strftime('%Y%m%d_%H%M%S')}.json"
            )
            payload = {
                "group_id": group_id,
                "archive_date": services.now().isoformat(),
                "archive_months": months,
                "orders": old,
            }
            await asyncio.to_thread(
                (archive_dir / filename).write_text,
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            await services.delete_orders_by_ids([o["id"] for o in old])
            ctx().logger.info(
                "group %s archived %s orders → %s", group_id, len(old), filename
            )
        except Exception as exc:
            ctx().logger.warning("group %s archive failed: %s", group_id, exc)


async def _send_export(
    group_id: str, start: str, end: str, desc: str
) -> None:
    export_service = ctx().services.get("export")
    if export_service is None:
        return
    orders = await services.list_orders(
        group_id, complete_start=start, complete_end=end
    )
    orders = [o for o in orders if o.get("status") == "已完成"]
    if not orders:
        return
    cfg = services.config()
    commission = services.Commission(cfg.get("commission_ratio"))
    rows = services.build_export_rows(orders, commission)
    path = export_service.export_excel(
        rows, services.safe_filename(f"导出_{desc}_{services.today()}")
    )
    await ctx().send_group(
        group_id,
        Message.text(f"【√】昨日导出：共{len(orders)}条数据\n文件：{path.name}")
        + MessageSegment.file(file=str(path), name=path.name),
    )
