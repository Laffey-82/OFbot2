"""order_ledger 插件核心服务：北京时间、分账、订单仓储、统计/排行/账目、历史与导出。"""

from __future__ import annotations

import re
from collections.abc import Iterable
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from decimal import Decimal, getcontext
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select

from app.core.messages import MessageEvent
from app.core.plugin import PluginContext
from app.services.preset_utils import split_message

from .config import merged_config
from .models import OfbotCommissionHistory, OfbotOrder

getcontext().prec = 20

BJ_TZ = ZoneInfo("Asia/Shanghai")

_ctx: PluginContext | None = None

STATUS_ICONS = {
    "未接单": "【未完成】",
    "已接单": "【已接单】",
    "已完成": "【已完成】",
    "已取消": "【已取消】",
}


def init(ctx: PluginContext) -> None:
    global _ctx
    _ctx = ctx


def ctx() -> PluginContext:
    if _ctx is None:
        raise RuntimeError("order_ledger services not initialized")
    return _ctx


def config() -> dict[str, Any]:
    return merged_config(ctx().config)


@asynccontextmanager
async def session():
    db = ctx().db
    async with db()() as s:
        yield s


# ---------------------------------------------------------------- 时间工具

def now() -> datetime:
    return datetime.now(BJ_TZ)


def now_str() -> str:
    return now().strftime("%Y-%m-%d %H:%M:%S")


def today() -> str:
    return now().strftime("%Y-%m-%d")


def yesterday() -> str:
    return (now() - timedelta(days=1)).strftime("%Y-%m-%d")


def parse_date(value: str) -> str:
    value = str(value or "").strip()
    if len(value) == 8 and value.isdigit():
        return f"{value[:4]}-{value[4:6]}-{value[6:8]}"
    return value


def week_range(
    start_weekday: int = 5, test_date: datetime | None = None
) -> tuple[str, str]:
    """本周范围：以 start_weekday（0=周一…5=周六）为每周起始日，止于今天。"""
    now_dt = test_date or now()
    days_to_start = (now_dt.weekday() - start_weekday) % 7
    start = now_dt - timedelta(days=days_to_start)
    return start.strftime("%Y-%m-%d"), now_dt.strftime("%Y-%m-%d")


def last_week_range() -> tuple[str, str]:
    """上周范围（周一至周日）。"""
    now_dt = now()
    end = now_dt - timedelta(days=now_dt.weekday() + 1)
    start = end - timedelta(days=6)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def parse_time_param(text: str) -> tuple[str, str, str]:
    """把统计/导出/分账的时间参数解析为 (start_date, end_date, label)。"""
    text = str(text or "").strip()
    if text in ("本日", "今日"):
        return today(), today(), "本日"
    if text == "昨日":
        d = yesterday()
        return d, d, "昨日"
    if text == "本周":
        start, end = week_range(config().get("weekly_start_day", 5))
        return start, end, f"{start} 至 {end}"
    if text == "全部":
        return "", "", "全部"
    parts = text.split()
    if len(parts) == 1:
        d = parse_date(parts[0])
        if d:
            return d, d, d
    if len(parts) >= 2:
        start = parse_date(parts[0])
        end = parse_date(parts[1])
        if start and end:
            return start, end, f"{start} 至 {end}"
    return "", "", text


# ---------------------------------------------------------------- 文案工具

def money(value: float) -> str:
    return f"¥{float(value):.2f}"


def user_info(qq: str, nick: str = "") -> str:
    if qq:
        return f"{nick or '未知昵称'}（{qq}）"
    return "待接单"


def status_icon(status: str) -> str:
    return STATUS_ICONS.get(status, "【未知】")


def format_order_card(order: dict[str, Any]) -> str:
    status_alias = {"已接单": "已接单（待完成）"}.get(
        order.get("status", ""), order.get("status", "未知")
    )
    lines = [
        f"订单【序号：{order.get('fixed_seq', '未知')}】{status_icon(order.get('status', ''))}",
        f"单子：{order.get('order_info', '无')}",
        f"价格：{money(float(order.get('price', 0) or 0))}",
        (
            f"控分：{order.get('control_score', '0')} | "
            f"控dx：{order.get('control_dx', '0')} | "
            f"成绩图：{order.get('need_score_img', '0')}"
        ),
        f"接单人：{user_info(order.get('creator_qq', ''), order.get('creator_nick', ''))}",
        f"打手：{user_info(order.get('player_qq', ''), order.get('player_nick', ''))}",
        f"状态：{status_alias}",
    ]
    if order.get("remark"):
        lines.append(f"备注：{order['remark']}")
    lines.append("————————————")
    return "\n".join(lines)


async def reply_multi(event: MessageEvent, text: str) -> None:
    """回复消息，超长自动分片（每片 ≤1800 字符）。"""
    chunks = split_message(str(text or ""), 1800) or [""]
    for chunk in chunks:
        await event.reply(chunk)


def at_user(user_id: str) -> str:
    return f"[@{user_id}]"


# ---------------------------------------------------------------- 分账计算

class Commission:
    """分账计算：比例来自插件配置，不写死任何固定比例。"""

    REQUIRED_KEYS = ("打手", "接单人", "OF", "应急公款")

    def __init__(self, ratio: dict[str, float] | None = None):
        cfg = config()
        self.ratio: dict[str, float] = {
            key: float((ratio or cfg.get("commission_ratio", {})).get(key, 0))
            for key in self.REQUIRED_KEYS
        }

    def validate_ratio(self) -> bool:
        total = sum(self.ratio.values())
        return 0.999 <= total <= 1.001

    def calculate(self, price: float) -> dict[str, float]:
        price_dec = Decimal(str(price))
        return {
            key: float(price_dec * Decimal(str(self.ratio[key])))
            for key in self.REQUIRED_KEYS
        }

    def pct(self, key: str) -> int:
        return round(self.ratio.get(key, 0) * 100)


# ---------------------------------------------------------------- 订单仓储

def _date_between(column, start: str, end: str):
    """按字符串日期范围过滤时间列（列值为 YYYY-MM-DD HH:MM:SS）。"""
    clauses = []
    if start:
        clauses.append(column >= f"{start} 00:00:00")
    if end:
        clauses.append(column <= f"{end} 23:59:59")
    return clauses


async def next_seq(group_id: str) -> int:
    async with session() as s:
        current = await s.scalar(
            select(func.max(OfbotOrder.fixed_seq)).where(
                OfbotOrder.group_id == group_id
            )
        )
        return int(current or 0) + 1


async def create_order(
    group_id: str,
    *,
    order_info: str,
    control_score: str,
    control_dx: str,
    need_score_img: str,
    price: float,
    creator_qq: str,
    creator_nick: str,
    remark: str = "",
    seq: int | None = None,
    extra: dict[str, Any] | None = None,
) -> OfbotOrder:
    """创建订单；fixed_seq 按群自增，冲突时重试。"""
    from sqlalchemy.exc import IntegrityError

    extra = extra or {}
    attempts = [seq] if seq else [None] * 5
    for candidate in attempts:
        current_seq = candidate or await next_seq(group_id)
        async with session() as s:
            order = OfbotOrder(
                group_id=group_id,
                fixed_seq=current_seq,
                order_id=extra.get("order_id") or f"{group_id}-{current_seq}",
                order_info=order_info,
                control_score=control_score,
                control_dx=control_dx,
                need_score_img=need_score_img,
                price=price,
                creator_qq=str(creator_qq),
                creator_nick=creator_nick,
                player_qq="",
                player_nick="",
                remark=remark,
                highlight=False,
                status="未接单",
                create_time=extra.get("create_time") or now_str(),
            )
            for key in (
                "status",
                "take_time",
                "complete_time",
                "cancel_take_time",
                "overdue_restore_time",
                "confirmer_qq",
                "confirmer_nick",
                "player_qq",
                "player_nick",
                "highlight",
            ):
                if key in extra:
                    setattr(order, key, extra[key])
            s.add(order)
            try:
                await s.commit()
                await s.refresh(order)
                return order
            except IntegrityError:
                await s.rollback()
                if seq is not None:
                    raise
    raise RuntimeError("订单序号分配失败，请重试")


async def get_order(group_id: str, seq: int) -> OfbotOrder | None:
    async with session() as s:
        return await s.scalar(
            select(OfbotOrder).where(
                OfbotOrder.group_id == group_id,
                OfbotOrder.fixed_seq == seq,
            )
        )


async def list_orders(
    group_id: str,
    *,
    statuses: list[str] | None = None,
    mine_qq: str | None = None,
    urgent: bool = False,
    create_start: str = "",
    create_end: str = "",
    complete_start: str = "",
    complete_end: str = "",
    creator_qq: str | None = None,
    player_qq: str | None = None,
) -> list[dict[str, Any]]:
    stmt = select(OfbotOrder).where(OfbotOrder.group_id == group_id)
    if statuses:
        stmt = stmt.where(OfbotOrder.status.in_(statuses))
    if mine_qq:
        stmt = stmt.where(OfbotOrder.player_qq == mine_qq)
    if urgent:
        stmt = stmt.where(OfbotOrder.highlight.is_(True))
    if creator_qq:
        stmt = stmt.where(OfbotOrder.creator_qq == creator_qq)
    if player_qq:
        stmt = stmt.where(OfbotOrder.player_qq == player_qq)
    stmt = stmt.where(*_date_between(OfbotOrder.create_time, create_start, create_end))
    stmt = stmt.where(
        *_date_between(OfbotOrder.complete_time, complete_start, complete_end)
    )
    stmt = stmt.order_by(OfbotOrder.fixed_seq.asc())
    async with session() as s:
        rows = (await s.scalars(stmt)).all()
    return [row.as_dict() for row in rows]


async def update_order(group_id: str, seq: int, **fields: Any) -> OfbotOrder | None:
    async with session() as s:
        order = await s.scalar(
            select(OfbotOrder).where(
                OfbotOrder.group_id == group_id,
                OfbotOrder.fixed_seq == seq,
            )
        )
        if order is None:
            return None
        for key, value in fields.items():
            if hasattr(order, key):
                setattr(order, key, value)
        await s.commit()
        await s.refresh(order)
        return order


async def take_order(
    group_id: str, seq: int, player_qq: str, player_nick: str
) -> tuple[bool, str, dict[str, Any] | None]:
    """原子接单：仅在状态为未接单时更新。"""
    async with session() as s:
        order = await s.scalar(
            select(OfbotOrder).where(
                OfbotOrder.group_id == group_id,
                OfbotOrder.fixed_seq == seq,
            )
        )
        if order is None:
            return False, "订单不存在", None
        if order.status != "未接单":
            return False, f"订单已被接单，当前状态：{order.status}", None
        order.status = "已接单"
        order.player_qq = str(player_qq)
        order.player_nick = player_nick
        order.take_time = now_str()
        await s.commit()
        await s.refresh(order)
        return True, "接单成功", order.as_dict()


async def delete_order(group_id: str, seq: int) -> bool:
    async with session() as s:
        order = await s.scalar(
            select(OfbotOrder).where(
                OfbotOrder.group_id == group_id,
                OfbotOrder.fixed_seq == seq,
            )
        )
        if order is None:
            return False
        await s.delete(order)
        await s.commit()
        return True


async def delete_orders_by_ids(ids: Iterable[int]) -> int:
    ids = [int(i) for i in ids]
    if not ids:
        return 0
    async with session() as s:
        result = await s.execute(
            delete(OfbotOrder).where(OfbotOrder.id.in_(ids))
        )
        await s.commit()
        return result.rowcount or 0


async def check_overdue(group_id: str) -> list[dict[str, Any]]:
    """检查超时订单：已接单超时还原为未接单；返回超时未接单需提醒的订单。"""
    cfg = config()
    overdue_days = int(cfg["order_settings"].get("overdue_days", 3))
    remind_hours = int(cfg["order_settings"].get("no_take_remind_hours", 2))
    orders = await list_orders(group_id)
    now_dt = now()
    remind: list[dict[str, Any]] = []

    for order in orders:
        status = order.get("status")
        if status == "已接单":
            take = order.get("take_time") or ""
            try:
                dt = datetime.strptime(take, "%Y-%m-%d %H:%M:%S").replace(
                    tzinfo=BJ_TZ
                )
            except (ValueError, TypeError):
                continue
            if (now_dt - dt).total_seconds() >= overdue_days * 86400:
                await update_order(
                    group_id,
                    order["fixed_seq"],
                    status="未接单",
                    player_qq="",
                    player_nick="",
                    overdue_restore_time=now_str(),
                )
        elif status == "未接单":
            create = order.get("create_time") or ""
            try:
                dt = datetime.strptime(create, "%Y-%m-%d %H:%M:%S").replace(
                    tzinfo=BJ_TZ
                )
            except (ValueError, TypeError):
                continue
            if (now_dt - dt).total_seconds() >= remind_hours * 3600:
                remind.append(order)
    return remind


# ---------------------------------------------------------------- 分账汇总/历史

def build_commission_data(
    orders: Iterable[dict[str, Any]], commission: Commission
) -> dict[str, Any]:
    """生成分账汇总数据（与旧 CommissionHistory.generate_commission_summary 对齐）。"""
    orders = list(orders)
    total_revenue = 0.0
    creator_summary: dict[str, dict[str, Any]] = {}
    player_summary: dict[str, dict[str, Any]] = {}
    order_details: list[dict[str, Any]] = []

    for order in orders:
        price = float(order.get("price", 0) or 0)
        fees = commission.calculate(price)
        total_revenue += price
        c_key = order.get("creator_qq") or ""
        if c_key:
            item = creator_summary.setdefault(
                c_key,
                {
                    "name": order.get("creator_nick") or c_key,
                    "amount": 0.0,
                    "count": 0,
                },
            )
            item["amount"] += fees["接单人"]
            item["count"] += 1
        p_key = order.get("player_qq") or ""
        if p_key:
            item = player_summary.setdefault(
                p_key,
                {
                    "name": order.get("player_nick") or p_key,
                    "amount": 0.0,
                    "count": 0,
                },
            )
            item["amount"] += fees["打手"]
            item["count"] += 1
        order_details.append(
            {
                "order_info": order.get("order_info", ""),
                "fixed_seq": order.get("fixed_seq", ""),
                "price": price,
                "commission": fees,
                "creator": order.get("creator_nick", ""),
                "player": order.get("player_nick", ""),
                "complete_time": order.get("complete_time", ""),
            }
        )

    commission_totals = {
        "打手": sum(item["amount"] for item in player_summary.values()),
        "接单人": sum(item["amount"] for item in creator_summary.values()),
        "OF": total_revenue * commission.ratio["OF"],
        "应急公款": total_revenue * commission.ratio["应急公款"],
    }
    total_commission = sum(commission_totals.values())
    difference = abs(total_revenue - total_commission)
    return {
        "total_revenue": total_revenue,
        "order_count": len(orders),
        "creator_summary": creator_summary,
        "player_summary": player_summary,
        "order_details": order_details,
        "commission_totals": commission_totals,
        "reconciliation": {
            "is_consistent": difference <= 0.01,
            "total_revenue": total_revenue,
            "total_commission": total_commission,
            "difference": difference,
            "message": (
                "对账一致" if difference <= 0.01 else f"对账不一致，差异金额：{money(difference)}"
            ),
        },
    }


def build_summary_text(
    data: dict[str, Any], start_date: str, end_date: str, desc: str
) -> str:
    """由分账汇总数据生成人类可读的分账总结文本。"""
    commission = Commission()
    if not data["order_details"]:
        if start_date == end_date:
            return f"{start_date} {desc}无完成订单"
        return f"{start_date} 至 {end_date} 无完成订单"

    title = (
        f"{start_date} {desc}分账"
        if start_date == end_date
        else f"{start_date} 至 {end_date} 分账"
    )
    total_rev = data["total_revenue"]
    lines = [
        "=" * 40,
        title,
        "=" * 40,
        "",
        f"总订单：{data['order_count']} 单 | 总金额：{money(total_rev)}",
        "",
    ]

    # 转账统计（接单人订单总收入，不考虑分成）
    by_creator: dict[str, float] = {}
    for d in data["order_details"]:
        key = d.get("creator", "")
        by_creator[key] = by_creator.get(key, 0.0) + float(d["price"])
    if by_creator:
        lines.append("【转账统计】")
        lines.append("接单人需向公共账户转账金额（订单总收入）：")
        for key, amount in by_creator.items():
            lines.append(f"   {key} → {money(amount)}")
        lines.append(f"转账总额：{money(sum(by_creator.values()))}")
        lines.append("")

    lines.append("【分成统计】")
    c_name = f"接单人（{commission.pct('接单人')}%）"
    p_name = f"打手（{commission.pct('打手')}%）"
    lines.append(c_name + "：")
    for key, item in data["creator_summary"].items():
        lines.append(
            f"   {item['name']:<24} → {item['count']}单 → {money(item['amount'])}"
        )
    lines.append("")
    lines.append(p_name + "：")
    for key, item in data["player_summary"].items():
        lines.append(
            f"   {item['name']:<24} → {item['count']}单 → {money(item['amount'])}"
        )
    lines.append("")
    lines.append(f"OF（{commission.pct('OF')}%）：{money(data['commission_totals']['OF'])}")
    lines.append(
        f"应急公款（{commission.pct('应急公款')}%）："
        f"{money(data['commission_totals']['应急公款'])}"
    )
    lines.append("")
    lines.append("明细：")
    for i, d in enumerate(data["order_details"], 1):
        lines.extend(
            [
                f"\n[{i}] 序号{d['fixed_seq']} {d['order_info']} {money(d['price'])}",
                f"   接单人：{d['creator'] or '未知':<20} {money(d['commission']['接单人'])}",
                f"   打手：{d['player'] or '未知':<20} {money(d['commission']['打手'])}",
                (
                    f"   OF：{money(d['commission']['OF'])} | "
                    f"应急公款：{money(d['commission']['应急公款'])}"
                ),
            ]
        )
    totals = data["commission_totals"]
    lines.extend(
        [
            "\n" + "=" * 40,
            (
                f"总计：接单人{money(totals['接单人'])} "
                f"打手{money(totals['打手'])} "
                f"OF{money(totals['OF'])} 应急公款{money(totals['应急公款'])}"
            ),
            f"合计：{money(sum(totals.values()))}",
            "=" * 40,
        ]
    )
    return "\n".join(lines)


async def generate_commission(
    group_id: str, start_date: str, end_date: str, desc: str
) -> tuple[dict[str, Any], str]:
    """生成指定时间范围的分账汇总数据与总结文本。"""
    orders = await list_orders(
        group_id, complete_start=start_date, complete_end=end_date
    )
    orders = [o for o in orders if o.get("status") == "已完成"]
    data = build_commission_data(orders, Commission())
    summary = build_summary_text(data, start_date, end_date, desc)
    return data, summary


async def save_history(
    group_id: str,
    history_type: str,
    start_date: str,
    end_date: str,
    summary: str,
    data: dict[str, Any],
) -> None:
    async with session() as s:
        existing = await s.scalar(
            select(OfbotCommissionHistory).where(
                OfbotCommissionHistory.group_id == group_id,
                OfbotCommissionHistory.history_type == history_type,
                OfbotCommissionHistory.start_date == start_date,
                OfbotCommissionHistory.end_date == end_date,
            )
        )
        if existing is None:
            existing = OfbotCommissionHistory(
                group_id=group_id,
                history_type=history_type,
                start_date=start_date,
                end_date=end_date,
                summary=summary,
                data=data,
            )
            s.add(existing)
        else:
            existing.summary = summary
            existing.data = data
        await s.commit()


async def list_history(
    group_id: str,
    history_type: str | None = None,
    start_date: str = "",
    end_date: str = "",
) -> list[dict[str, Any]]:
    stmt = select(OfbotCommissionHistory).where(
        OfbotCommissionHistory.group_id == group_id
    )
    if history_type:
        stmt = stmt.where(OfbotCommissionHistory.history_type == history_type)
    if start_date:
        stmt = stmt.where(OfbotCommissionHistory.end_date >= start_date)
    if end_date:
        stmt = stmt.where(OfbotCommissionHistory.start_date <= end_date)
    stmt = stmt.order_by(OfbotCommissionHistory.start_date.desc())
    async with session() as s:
        rows = (await s.scalars(stmt)).all()
    return [row.as_dict() for row in rows]


# ---------------------------------------------------------------- 统计/排行/账目

def build_stats(
    orders: list[dict[str, Any]], commission: Commission
) -> dict[str, Any]:
    completed = [o for o in orders if o.get("status") == "已完成"]
    revenue = sum(float(o.get("price", 0) or 0) for o in completed)
    creator_detail: dict[str, dict[str, Any]] = {}
    player_detail: dict[str, dict[str, Any]] = {}
    for order in completed:
        price = float(order.get("price", 0) or 0)
        c_key = f"{order.get('creator_qq') or '未知'}（{order.get('creator_nick') or '未知'}）"
        item = creator_detail.setdefault(c_key, {"count": 0, "amount": 0.0})
        item["count"] += 1
        item["amount"] += price * commission.ratio["接单人"]
        p_key = f"{order.get('player_qq') or '未知'}（{order.get('player_nick') or '未知'}）"
        item = player_detail.setdefault(p_key, {"count": 0, "amount": 0.0})
        item["count"] += 1
        item["amount"] += price * commission.ratio["打手"]
    return {
        "completed": len(completed),
        "revenue": revenue,
        "creator_detail": creator_detail,
        "player_detail": player_detail,
        "of": revenue * commission.ratio["OF"],
        "emergency": revenue * commission.ratio["应急公款"],
    }


def build_rank(orders: list[dict[str, Any]], commission: Commission) -> dict[str, list[dict[str, Any]]]:
    take_stats: dict[str, dict[str, Any]] = {}
    create_stats: dict[str, dict[str, Any]] = {}
    income_stats: dict[str, dict[str, Any]] = {}
    for order in orders:
        player_qq = order.get("player_qq") or ""
        if player_qq:
            item = take_stats.setdefault(
                player_qq,
                {"qq": player_qq, "nick": order.get("player_nick") or "未知", "count": 0},
            )
            item["count"] += 1
        creator_qq = order.get("creator_qq") or ""
        if creator_qq:
            item = create_stats.setdefault(
                creator_qq,
                {"qq": creator_qq, "nick": order.get("creator_nick") or "未知", "count": 0},
            )
            item["count"] += 1
        if order.get("status") == "已完成":
            price = float(order.get("price", 0) or 0)
            fees = commission.calculate(price)
            if player_qq:
                item = income_stats.setdefault(
                    player_qq,
                    {"qq": player_qq, "nick": order.get("player_nick") or "未知", "income": 0.0},
                )
                item["income"] += fees["打手"]
            if creator_qq:
                item = income_stats.setdefault(
                    creator_qq,
                    {"qq": creator_qq, "nick": order.get("creator_nick") or "未知", "income": 0.0},
                )
                item["income"] += fees["接单人"]
    return {
        "take": sorted(take_stats.values(), key=lambda x: x["count"], reverse=True)[:10],
        "create": sorted(create_stats.values(), key=lambda x: x["count"], reverse=True)[:10],
        "income": sorted(income_stats.values(), key=lambda x: x["income"], reverse=True)[:10],
    }


def build_account(
    user_qq: str, orders: list[dict[str, Any]], commission: Commission
) -> dict[str, Any]:
    completed = [o for o in orders if o.get("status") == "已完成"]
    creator_earnings = 0.0
    player_earnings = 0.0
    records: list[dict[str, Any]] = []
    for order in completed:
        price = float(order.get("price", 0) or 0)
        fees = commission.calculate(price)
        if order.get("creator_qq") == user_qq:
            creator_earnings += fees["接单人"]
            records.append(
                {
                    "order_id": order.get("order_id", ""),
                    "order_info": order.get("order_info", ""),
                    "price": price,
                    "role": "接单人",
                    "earnings": fees["接单人"],
                    "complete_time": order.get("complete_time", ""),
                }
            )
        if order.get("player_qq") == user_qq:
            player_earnings += fees["打手"]
            records.append(
                {
                    "order_id": order.get("order_id", ""),
                    "order_info": order.get("order_info", ""),
                    "price": price,
                    "role": "打手",
                    "earnings": fees["打手"],
                    "complete_time": order.get("complete_time", ""),
                }
            )
    records.sort(key=lambda x: x.get("complete_time", ""), reverse=True)
    return {
        "qq": user_qq,
        "total_orders": len(records),
        "total_earnings": creator_earnings + player_earnings,
        "creator_earnings": creator_earnings,
        "player_earnings": player_earnings,
        "order_records": records,
    }


# ---------------------------------------------------------------- 导出

def build_export_rows(
    orders: list[dict[str, Any]], commission: Commission
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for order in orders:
        price = float(order.get("price", 0) or 0)
        fees = commission.calculate(price)
        rows.append(
            {
                "订单固定序号": order.get("fixed_seq", ""),
                "订单ID": order.get("order_id", ""),
                "单子": order.get("order_info", ""),
                "控分": order.get("control_score", ""),
                "控dx": order.get("control_dx", ""),
                "成绩图": order.get("need_score_img", ""),
                "价格": price,
                "接单人QQ": order.get("creator_qq", ""),
                "接单人昵称": order.get("creator_nick", ""),
                f"接单人分成({commission.pct('接单人')}%)": fees["接单人"],
                "打手QQ": order.get("player_qq", ""),
                "打手昵称": order.get("player_nick", ""),
                f"打手分成({commission.pct('打手')}%)": fees["打手"],
                f"OF分成({commission.pct('OF')}%)": fees["OF"],
                f"应急公款({commission.pct('应急公款')}%)": fees["应急公款"],
                "备注": order.get("remark", ""),
                "状态": order.get("status", ""),
                "创建时间": order.get("create_time", ""),
                "完成时间": order.get("complete_time", ""),
            }
        )
    return rows


def safe_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", str(name)).strip() or "export"


# ---------------------------------------------------------------- 群组解析

def resolve_target_groups() -> list[str]:
    """定时任务发送目标群：优先 notify_groups，否则所有启用了 tasks 功能的群。"""
    cfg = config()
    notify = [str(g) for g in (cfg.get("notify_groups") or []) if str(g).strip()]
    if notify:
        return notify
    groups: list[str] = []
    policy = ctx().scope_policy
    if policy is None:
        return groups
    for key in policy.scope_keys():
        if not key.startswith("group:") or key == "group:*":
            continue
        group_id = key.split(":", 1)[1]
        if policy.feature_enabled("order_ledger", "tasks", key, default=True):
            groups.append(group_id)
    return groups


async def send_to_groups(text: str, groups: Iterable[str]) -> int:
    """向多个群发送消息（自动分片），返回成功发送的群数。"""
    sent = 0
    for group_id in groups:
        chunks = split_message(str(text or ""), 1800) or [""]
        for chunk in chunks:
            ok = await ctx().send_group(str(group_id), chunk)
            if not ok:
                break
        else:
            sent += 1
    return sent
