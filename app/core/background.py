from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import Any

from app.core.logger import get_logger

logger = get_logger(__name__)


class BackgroundWorker:
    def __init__(self, queue_size: int = 256, workers: int = 2) -> None:
        self.queue: asyncio.Queue[tuple[str, Awaitable[Any]]] = asyncio.Queue(
            maxsize=queue_size
        )
        self.worker_count = workers
        self._workers: list[asyncio.Task[None]] = []
        self._active: dict[str, asyncio.Task[Any]] = {}

    async def start(self) -> None:
        self._workers = [
            asyncio.create_task(self._worker(index), name=f"ofbot-worker-{index}")
            for index in range(self.worker_count)
        ]

    async def stop(self) -> None:
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        for task in self._active.values():
            task.cancel()
        if self._active:
            await asyncio.gather(*self._active.values(), return_exceptions=True)
        self._active.clear()

    async def submit(
        self, name: str, coroutine: Awaitable[Any]
    ) -> asyncio.Task[Any] | None:
        """提交后台任务；同名任务已在运行时返回已有 task，不重复提交。

        去重防止重连路径重复提交同一适配器的 start()，避免双连接。
        队列中允许同名不同协程（如 benchmark 场景）。
        """
        if name in self._active:
            logger.info(
                "background task %s already running, skip duplicate submit", name
            )
            self._discard_coroutine(coroutine)
            return self._active[name]
        await self.queue.put((name, coroutine))
        return None

    @staticmethod
    def _discard_coroutine(coroutine: Awaitable[Any]) -> None:
        """关闭被跳过的协程，避免 "coroutine was never awaited" 警告。"""
        close = getattr(coroutine, "close", None)
        if callable(close):
            close()

    async def _worker(self, index: int) -> None:
        while True:
            name, coroutine = await self.queue.get()
            task = asyncio.create_task(coroutine, name=f"ofbot-bg-{name}")
            self._active[name] = task
            try:
                await task
            except asyncio.CancelledError:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                raise
            except Exception:
                logger.exception("background task failed: %s", name)
            finally:
                self.queue.task_done()
                if self._active.get(name) is task:
                    self._active.pop(name, None)

