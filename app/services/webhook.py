from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
from typing import Any

from app.core.bus import get_bus
from app.core.capabilities import Capability
from app.core.events import WebhookReceived
from app.core.logger import get_logger
from app.db.base import session_factory
from app.db.models import WebhookEvent

logger = get_logger(__name__)


class WebhookService:
    def __init__(self, retention: int = 200) -> None:
        self.webhooks: set[str] = set()
        self.filters: dict[str, dict[str, Any]] = {}
        self.last_triggered: dict[str, str] = {}
        self.history: dict[str, deque[dict[str, Any]]] = {}
        self.history_size = 10
        self.retention = max(1, retention)

    def register(self, name: str, payload_filter: dict[str, Any] | None = None) -> None:
        self.webhooks.add(name)
        if payload_filter:
            self.filters[name] = payload_filter
        else:
            self.filters.pop(name, None)

    def remove(self, name: str) -> bool:
        if name not in self.webhooks:
            return False
        self.webhooks.remove(name)
        self.filters.pop(name, None)
        return True

    @staticmethod
    def _deep_get(data: dict[str, Any], path: str) -> Any:
        current: Any = data
        for part in path.split("."):
            if not isinstance(current, dict):
                return None
            current = current.get(part)
        return current

    def matches(self, name: str, payload: dict[str, Any]) -> bool:
        payload_filter = self.filters.get(name)
        if not payload_filter:
            return True
        return all(
            self._deep_get(payload, key) == value
            for key, value in payload_filter.items()
        )

    async def handle(self, name: str, payload: dict[str, Any]) -> bool:
        if name not in self.webhooks:
            return False
        if not self.matches(name, payload):
            return True  # 已注册但载荷不匹配，静默忽略
        try:
            get_bus().dispatch(WebhookReceived(name=name, payload=payload))
        except RuntimeError:
            pass
        self.last_triggered[name] = datetime.now(UTC).isoformat(timespec="seconds")
        self.history.setdefault(name, deque(maxlen=self.history_size)).append(
            {
                "time": self.last_triggered[name],
                "payload": payload,
            }
        )
        try:
            async with session_factory()() as session:
                session.add(
                    WebhookEvent(webhook_name=name, payload=payload)
                )
                await session.commit()
        except Exception:
            logger.exception("failed to persist webhook event")
        await self._prune(name)
        return True

    async def _prune(self, name: str) -> None:
        """按保留条数清理该 Webhook 的数据库历史。"""
        from sqlalchemy import delete, func, select

        try:
            async with session_factory()() as session:
                count = await session.scalar(
                    select(func.count())
                    .select_from(WebhookEvent)
                    .where(WebhookEvent.webhook_name == name)
                )
                if count and count > self.retention:
                    ids = (
                        await session.scalars(
                            select(WebhookEvent.id)
                            .where(WebhookEvent.webhook_name == name)
                            .order_by(WebhookEvent.created_at.asc())
                            .limit(count - self.retention)
                        )
                    ).all()
                    if ids:
                        await session.execute(
                            delete(WebhookEvent).where(WebhookEvent.id.in_(ids))
                        )
                        await session.commit()
        except Exception:
            logger.exception("failed to prune webhook history")


def register_webhook_capability() -> Capability:
    return Capability(
        name="webhook",
        description="外部 Webhook 接收与事件转发",
        methods=["register", "handle"],
    )
