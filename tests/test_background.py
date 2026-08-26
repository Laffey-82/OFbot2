from __future__ import annotations

import pytest

from app.core.background import BackgroundWorker


@pytest.mark.asyncio
async def test_background_worker_runs_task() -> None:
    worker = BackgroundWorker(queue_size=10, workers=2)
    results: list[int] = []

    async def task() -> None:
        results.append(1)

    await worker.start()
    await worker.submit("test", task())
    await worker.queue.join()
    await worker.stop()
    assert results == [1]

