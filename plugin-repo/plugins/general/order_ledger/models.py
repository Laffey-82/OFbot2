"""order_ledger 插件数据模型（注册到框架 SQLite）。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class OfbotOrder(Base):
    """代打单订单。时间字段统一存北京时间字符串（YYYY-MM-DD HH:MM:SS）。"""

    __tablename__ = "order_ledger_orders"
    __table_args__ = (
        UniqueConstraint(
            "group_id", "fixed_seq", name="uq_order_ledger_group_seq"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[str] = mapped_column(String(64), index=True)
    fixed_seq: Mapped[int] = mapped_column(Integer)
    order_id: Mapped[str] = mapped_column(String(64), default="")

    order_info: Mapped[str] = mapped_column(String(500), default="")
    control_score: Mapped[str] = mapped_column(String(8), default="1")
    control_dx: Mapped[str] = mapped_column(String(8), default="1")
    need_score_img: Mapped[str] = mapped_column(String(8), default="1")
    price: Mapped[float] = mapped_column(Float, default=0.0)

    creator_qq: Mapped[str] = mapped_column(String(64), index=True, default="")
    creator_nick: Mapped[str] = mapped_column(String(160), default="")
    player_qq: Mapped[str] = mapped_column(String(64), index=True, default="")
    player_nick: Mapped[str] = mapped_column(String(160), default="")
    remark: Mapped[str] = mapped_column(String(500), default="")
    highlight: Mapped[bool] = mapped_column(Boolean, default=False)

    # 未接单 / 已接单 / 已完成 / 已取消
    status: Mapped[str] = mapped_column(String(16), index=True, default="未接单")
    create_time: Mapped[str] = mapped_column(String(32), default="")
    take_time: Mapped[str] = mapped_column(String(32), default="")
    complete_time: Mapped[str] = mapped_column(String(32), default="")
    cancel_take_time: Mapped[str] = mapped_column(String(32), default="")
    overdue_restore_time: Mapped[str] = mapped_column(String(32), default="")
    confirmer_qq: Mapped[str] = mapped_column(String(64), default="")
    confirmer_nick: Mapped[str] = mapped_column(String(160), default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "group_id": self.group_id,
            "fixed_seq": self.fixed_seq,
            "order_id": self.order_id,
            "order_info": self.order_info,
            "control_score": self.control_score,
            "control_dx": self.control_dx,
            "need_score_img": self.need_score_img,
            "price": self.price,
            "creator_qq": self.creator_qq,
            "creator_nick": self.creator_nick,
            "player_qq": self.player_qq,
            "player_nick": self.player_nick,
            "remark": self.remark,
            "highlight": self.highlight,
            "status": self.status,
            "create_time": self.create_time,
            "take_time": self.take_time,
            "complete_time": self.complete_time,
            "cancel_take_time": self.cancel_take_time,
            "overdue_restore_time": self.overdue_restore_time,
            "confirmer_qq": self.confirmer_qq,
            "confirmer_nick": self.confirmer_nick,
        }


class OfbotCommissionHistory(Base):
    """分账历史（daily / weekly / range）。"""

    __tablename__ = "order_ledger_commission_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[str] = mapped_column(String(64), index=True)
    history_type: Mapped[str] = mapped_column(String(16), index=True)
    start_date: Mapped[str] = mapped_column(String(10), default="")
    end_date: Mapped[str] = mapped_column(String(10), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "group_id": self.group_id,
            "history_type": self.history_type,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "summary": self.summary,
            "data": self.data,
            "created_at": self.created_at,
        }
