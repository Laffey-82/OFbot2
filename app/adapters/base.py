from __future__ import annotations

import ssl
from abc import ABC, abstractmethod
from typing import Any

import httpx

from app.core.bus import get_bus
from app.core.commands import command_registry
from app.core.events import (
    GroupMessageReceived,
    PrivateMessageReceived,
)
from app.core.logger import get_logger
from app.core.messages import (
    GroupMessageEvent,
    Message,
    MessageEvent,
    MessageSegment,
    PrivateMessageEvent,
)

logger = get_logger(__name__)

_SHARED_SSL_CONTEXT = ssl.create_default_context()


def make_http_client(timeout: float = 15.0) -> httpx.AsyncClient:
    """构建带共享 SSL 上下文的异步客户端（避免重复加载系统证书）。"""
    return httpx.AsyncClient(timeout=timeout, verify=_SHARED_SSL_CONTEXT)


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
