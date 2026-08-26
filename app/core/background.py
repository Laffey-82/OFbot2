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

    async def submit(self, name: str, coroutine: Awaitable[Any]) -> None:
        await self.queue.put((name, coroutine))

    async def _worker(self, index: int) -> None:
        while True:
            name, coroutine = await self.queue.get()
            try:
                await coroutine
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("background task failed: %s", name)
            finally:
                self.queue.task_done()

