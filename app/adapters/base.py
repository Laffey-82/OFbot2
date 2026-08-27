from __future__ import annotations

import asyncio
import random
import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.core.bus import get_bus
from app.core.commands import command_registry
from app.core.events import (
    GroupMessageReceived,
    PrivateMessageReceived,
)
from app.core.http import make_http_client
from app.core.logger import get_logger, set_trace_id
from app.core.messages import (
    GroupMessageEvent,
    Message,
    MessageEvent,
    MessageSegment,
    PrivateMessageEvent,
)

logger = get_logger(__name__)

__all__ = ["BotClient", "ProtocolAdapter", "make_http_client"]


@dataclass
class ConnectionHealth:
    """单连接健康度快照（供监控页与告警使用）。"""

    name: str
    status: str = "unknown"
    connected: bool = False
    score: int = 0
    last_heartbeat: float = 0.0
    heartbeat_stale: bool = False
    messages_received: int = 0
    messages_sent: int = 0
    reconnects: int = 0
    detail: dict[str, Any] = field(default_factory=dict)


class ProtocolAdapter(ABC):
    bot_id: str = ""

    @abstractmethod
    async def start(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def stop(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def send_group_message(self, group_id: str, message: str | Message | MessageSegment) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def send_private_message(self, user_id: str, message: str | Message | MessageSegment) -> bool:
        raise NotImplementedError

    async def test(self) -> tuple[bool, str]:
        """轻量连接探针，返回 (是否成功, 详情)。"""
        raise NotImplementedError


class BaseAdapter(ProtocolAdapter):
    """提供指数退避 + 抖动重连与心跳超时收包的基础类。"""

    def __init__(
        self,
        settings: Any | None = None,
        bot_client: Any | None = None,
    ) -> None:
        self._running = False
        self._reconnects = 0
        self.bot_client = bot_client
        self.reconnect_interval = float(
            getattr(settings, "reconnect_interval", 3.0) or 3.0
        )
        self.reconnect_max_seconds = float(
            getattr(settings, "reconnect_max_seconds", 60.0) or 60.0
        )
        self.reconnect_max_attempts = int(
            getattr(settings, "reconnect_max_attempts", 0) or 0
        )

    async def run_reconnect_loop(
        self,
        connect: Callable[[], Awaitable[None]],
        bot_id: str,
    ) -> None:
        """指数退避 + 抖动重连；达到 max_attempts 后进入 disabled 状态。"""
        self._running = True
        attempt = 0
        while self._running:
            try:
                await connect()
                attempt = 0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("adapter %s connection failed: %s", bot_id, exc)
                if self.bot_client is not None:
                    self.bot_client.status[bot_id] = "disconnected"
                    self.bot_client._bump(bot_id, "reconnects")
            if not self._running:
                break
            attempt += 1
            if (
                self.reconnect_max_attempts > 0
                and attempt > self.reconnect_max_attempts
            ):
                logger.error(
                    "adapter %s 超过最大重连次数（%s），已停用",
                    bot_id,
                    self.reconnect_max_attempts,
                )
                if self.bot_client is not None:
                    self.bot_client.status[bot_id] = "disabled"
                self._running = False
                break
            delay = min(
                self.reconnect_interval * (2 ** (attempt - 1)),
                self.reconnect_max_seconds,
            )
            delay *= random.uniform(0.8, 1.2)
            await asyncio.sleep(max(0.1, delay))

    async def recv_loop(
        self,
        ws: Any,
        handler: Callable[[str], Awaitable[None]],
        bot_id: str,
        stale_seconds: float = 300.0,
    ) -> None:
        """收包循环：超时未收到任何数据视为心跳过期，抛错触发重连。"""
        while True:
            try:
                raw = await asyncio.wait_for(
                    ws.recv(), timeout=max(5.0, stale_seconds)
                )
            except TimeoutError as exc:
                raise ConnectionError(
                    f"adapter {bot_id} heartbeat stale"
                ) from exc
            await handler(raw)


class BotClient:
    def __init__(
        self,
        whitelist_service: Any | None = None,
        scope_policy: Any | None = None,
    ) -> None:
        self.adapters: dict[str, ProtocolAdapter] = {}
        self.active_adapter = ""
        self.whitelist_service = whitelist_service
        self.scope_policy = scope_policy
        self.status: dict[str, str] = {}
        self.details: dict[str, dict[str, Any]] = {}
        self.counters: dict[str, dict[str, int]] = {}
        self.reconnect_limits: dict[str, int] = {}
        self.stale_seconds: float = 300.0

    def _bump(self, name: str, key: str, amount: int = 1) -> None:
        self.counters.setdefault(name, {})
        self.counters[name][key] = self.counters[name].get(key, 0) + amount

    def register(self, name: str, adapter: ProtocolAdapter) -> None:
        self.adapters[name] = adapter
        self.status[name] = "registered"
        if not self.active_adapter:
            self.active_adapter = name

    def set_active(self, name: str) -> None:
        if name not in self.adapters:
            raise KeyError(name)
        self.active_adapter = name

    def resolve_connection(self, group_id: str | None = None, user_id: str | None = None) -> str:
        """按作用域账号绑定解析出站连接；未绑定时回退第一个启用的连接。"""
        scope = ""
        if group_id:
            scope = f"group:{group_id}"
        elif user_id:
            scope = "private:*"
        if scope and self.scope_policy is not None:
            bound = self.scope_policy.connection_for(scope)
            if bound and bound in self.adapters:
                return bound
        for name in self.adapters:
            if self.status.get(name) == "connected":
                return name
        if self.active_adapter in self.adapters:
            return self.active_adapter
        for name in self.adapters:
            return name
        return ""

    def health(self, stale_seconds: float | None = None) -> list[ConnectionHealth]:
        """计算所有连接的健康度评分（0-100）。"""
        stale_seconds = stale_seconds or self.stale_seconds
        result: list[ConnectionHealth] = []
        now = time.time()
        for name in self.adapters:
            status = self.status.get(name, "registered")
            detail = dict(self.details.get(name, {}))
            counters = self.counters.get(name, {})
            heartbeat = detail.get("last_heartbeat", 0.0) or 0.0
            connected = status == "connected"
            score = 0
            if connected:
                score += 50
            if heartbeat and (now - heartbeat) <= stale_seconds:
                score += 25
            received = int(counters.get("received", 0))
            sent = int(counters.get("sent", 0))
            if received:
                score += min(15, received)
            if sent:
                score += min(10, sent)
            if detail.get("error"):
                score = max(0, score - 20)
            result.append(
                ConnectionHealth(
                    name=name,
                    status=status,
                    connected=connected,
                    score=min(100, score),
                    last_heartbeat=heartbeat,
                    heartbeat_stale=bool(heartbeat) and (now - heartbeat) > stale_seconds,
                    messages_received=received,
                    messages_sent=sent,
                    reconnects=int(counters.get("reconnects", 0)),
                    detail=detail,
                )
            )
        return sorted(result, key=lambda item: item.name)

    async def send_group_message(
        self,
        group_id: str,
        message: str | Message | MessageSegment,
        connection_id: str = "",
    ) -> bool:
        connection_id = connection_id or self.resolve_connection(group_id=group_id)
        adapter = self.adapters.get(connection_id or self.active_adapter)
        if adapter is None:
            return False
        ok = await adapter.send_group_message(group_id, message)
        if ok:
            self._bump(connection_id or self.active_adapter, "sent")
        return ok

    async def send_private_message(
        self,
        user_id: str,
        message: str | Message | MessageSegment,
        connection_id: str = "",
    ) -> bool:
        connection_id = connection_id or self.resolve_connection(user_id=user_id)
        adapter = self.adapters.get(connection_id or self.active_adapter)
        if adapter is None:
            return False
        ok = await adapter.send_private_message(user_id, message)
        if ok:
            self._bump(connection_id or self.active_adapter, "sent")
        return ok

    async def handle_bot_event(self, event: MessageEvent) -> bool:
        trace_id = set_trace_id()
        try:
            event.trace_id = trace_id
            self._bump(event.bot_id, "received")
            if isinstance(event, GroupMessageEvent) and self.whitelist_service is not None:
                if not self.whitelist_service.contains(event.group_id):
                    logger.debug("group message filtered by whitelist: %s", event.group_id)
                    return False
            if isinstance(event, GroupMessageEvent):
                get_bus().dispatch(
                    GroupMessageReceived(
                        bot_id=event.bot_id,
                        self_id=event.self_id,
                        message_id=event.message_id,
                        user_id=event.user_id,
                        group_id=event.group_id,
                        message=event.message.extract_plain_text(),
                        raw_event=event.raw_event,
                    )
                )
            elif isinstance(event, PrivateMessageEvent):
                get_bus().dispatch(
                    PrivateMessageReceived(
                        bot_id=event.bot_id,
                        self_id=event.self_id,
                        message_id=event.message_id,
                        user_id=event.user_id,
                        message=event.message.extract_plain_text(),
                        raw_event=event.raw_event,
                    )
                )
            return await command_registry.handle_message(event)
        finally:
            set_trace_id("")
