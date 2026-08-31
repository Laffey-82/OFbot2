"""轻量自研事件总线（替代 bubus）。

设计目标：
- 依赖面为零（仅 pydantic），移除 bubus 的队列竞态与 stop() 阻塞问题。
- `on(event_type, handler)` 按 `isinstance` 匹配，父类订阅可收到子类事件
  （如 `GroupPoke` 同时派发给 `NoticeReceived` 订阅者）。
- `dispatch(event)` 为每个匹配 handler 创建独立任务，单个 handler 异常不影响其他。
- `stop(timeout, clear)` 优雅排空 pending 任务，超时强制取消，不阻塞事件循环，
  不再需要 `os._exit` 兜底。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger("app.core.bus")


class BaseEvent(BaseModel):
    """事件基类（pydantic 兼容，替代 bubus.BaseEvent）。"""


EventHandler = Callable[[BaseEvent], Any | Awaitable[Any]]


class EventBus:
    """异步发布/订阅总线。"""

    def __init__(
        self,
        name: str = "OFbot2",
        max_history_size: int | None = 500,
    ) -> None:
        self.name = name
        self.max_history_size = max_history_size
        self._handlers: dict[type[BaseEvent], list[EventHandler]] = {}
        self._history: list[BaseEvent] = []
        self._tasks: set[asyncio.Task[Any]] = set()
        self._stopped = False

    def on(self, event_type: type[BaseEvent], handler: EventHandler) -> None:
        """注册事件处理器（按类型匹配，含父类）。"""
        self._handlers.setdefault(event_type, []).append(handler)

    def dispatch(self, event: BaseEvent) -> BaseEvent:
        """派发事件：为每个匹配 handler 创建后台任务并立即返回。"""
        if self._stopped:
            return event
        if self.max_history_size is not None:
            self._history.append(event)
            if len(self._history) > self.max_history_size:
                del self._history[: len(self._history) - self.max_history_size]
        for handler in self._matching_handlers(event):
            try:
                task = asyncio.create_task(self._run_handler(handler, event))
            except RuntimeError:
                # 事件循环不可用（如关闭过程中）：忽略本次派发。
                continue
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        return event

    def _matching_handlers(self, event: BaseEvent) -> list[EventHandler]:
        handlers: list[EventHandler] = []
        for event_cls, registered in self._handlers.items():
            if isinstance(event, event_cls):
                handlers.extend(registered)
        return handlers

    async def _run_handler(
        self, handler: EventHandler, event: BaseEvent
    ) -> None:
        try:
            result = handler(event)
            if hasattr(result, "__await__"):
                await result
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "event handler failed event=%s", event.__class__.__name__
            )

    async def stop(
        self, timeout: float | None = None, clear: bool = False
    ) -> None:
        """停止总线：等待 pending 任务完成，超时则取消，不阻塞事件循环。"""
        if clear:
            self._history.clear()
        self._stopped = True
        await self.wait_until_idle(timeout=timeout)

    async def wait_until_idle(self, timeout: float | None = None) -> None:
        """等待所有 pending 任务完成（超时则取消，不阻塞事件循环）。"""
        tasks = list(self._tasks)
        if not tasks:
            return
        if timeout is None or timeout <= 0:
            await asyncio.gather(*tasks, return_exceptions=True)
            return
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=timeout,
            )
        except TimeoutError:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    @property
    def pending_count(self) -> int:
        """仍在排空中的任务数量（测试与健康检查用）。"""
        return len(self._tasks)


_bus = EventBus(name="OFbot2", max_history_size=500)


def get_bus() -> EventBus:
    return _bus


async def reset_bus() -> EventBus:
    """停止旧总线（排空 pending 任务）后重建单例。"""
    global _bus
    old = _bus
    _bus = EventBus(name="OFbot2", max_history_size=500)
    if old is not None:
        try:
            await asyncio.wait_for(old.stop(clear=True), timeout=2.0)
        except Exception:
            pass
    return _bus
