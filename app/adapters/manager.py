"""ConnectionManager：多适配器生命周期统一管理，单连接故障不影响其他。"""

from __future__ import annotations

import asyncio
from typing import Any

from app.core.logger import get_logger

logger = get_logger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self.adapters: list[Any] = []
        self.tasks: dict[str, asyncio.Task] = {}
        self.reverse_routes: list[tuple[str, Any]] = []
        self.bot_client: Any = None

    def attach(self, bot_client: Any) -> None:
        self.bot_client = bot_client
        bot_client.connection_manager = self

    def adopt(self, adapters: list[Any]) -> None:
        self.adapters = list(adapters)
        for adapter in self.adapters:
            bot_id = getattr(adapter, "bot_id", "")
            if self.bot_client is not None:
                self.bot_client.register(bot_id, adapter)

    def collect_reverse_routes(self) -> list[tuple[str, Any]]:
        routes: list[tuple[str, Any]] = []
        for adapter in self.adapters:
            handler = getattr(adapter, "handle_reverse_ws", None)
            if handler is None:
                continue
            path = getattr(adapter, "reverse_path", "") or "/onebot/v11/ws"
            routes.append((path, handler))
        self.reverse_routes = routes
        return routes

    def start_all(self) -> None:
        for adapter in self.adapters:
            self.start_connection(getattr(adapter, "bot_id", ""))

    def start_connection(self, bot_id: str) -> asyncio.Task | None:
        adapter = next(
            (item for item in self.adapters if getattr(item, "bot_id", "") == bot_id),
            None,
        )
        if adapter is None:
            return None
        task = asyncio.create_task(
            adapter.start(), name=f"adapter-{bot_id}"
        )
        self.tasks[bot_id] = task
        return task

    async def stop_connection(self, bot_id: str) -> None:
        adapter = next(
            (item for item in self.adapters if getattr(item, "bot_id", "") == bot_id),
            None,
        )
        task = self.tasks.pop(bot_id, None)
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        if adapter is not None:
            try:
                await adapter.stop()
            except Exception:
                logger.exception("adapter stop failed: %s", bot_id)
        if self.bot_client is not None:
            self.bot_client.status[bot_id] = "disconnected"

    async def stop_all(self) -> None:
        for bot_id in list(self.tasks):
            await self.stop_connection(bot_id)
        for adapter in self.adapters:
            try:
                await adapter.stop()
            except Exception:
                logger.exception("adapter stop failed: %s", getattr(adapter, "bot_id", "?"))

    async def reconfigure(self, adapters: list[Any]) -> None:
        """停止旧连接并按新适配器列表重启（连接配置热更新）。"""
        await self.stop_all()
        if self.bot_client is not None:
            for name in list(self.bot_client.adapters):
                self.bot_client.adapters.pop(name, None)
                self.bot_client.status.pop(name, None)
                self.bot_client.details.pop(name, None)
        self.adapters = []
        self.tasks = {}
        self.adopt(adapters)
        self.start_all()

    def connected_ids(self) -> list[str]:
        return [
            bot_id
            for bot_id in self.tasks
            if self.bot_client is not None
            and self.bot_client.status.get(bot_id) == "connected"
        ]
