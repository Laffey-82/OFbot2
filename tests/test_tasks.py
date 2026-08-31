from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from sqlalchemy import select

from app.db.base import get_engine, init_db, reset_db_engine, session_factory
from app.db.models import Task, TaskRun
from app.runtime import _execute_task


class FakeBotClient:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send_group_message(self, group_id: str, message: str) -> bool:
        self.sent.append((group_id, message))
        return True


@pytest.mark.asyncio
async def test_execute_task_finds_record_by_task_id() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = Path(tmp_dir) / "tasks.db"
        url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
        await reset_db_engine()
        engine = get_engine(url)
        await init_db(url)
        async with session_factory()() as session:
            session.add(
                Task(
                    task_id="abc123",
                    name="test",
                    type="interval",
                    interval_seconds=60,
                    params={"group_id": "100", "message": "hello"},
                    enabled=True,
                )
            )
            await session.commit()

        client = FakeBotClient()
        await _execute_task("abc123", bot_client=client, scheduler=None)
        assert client.sent == [("100", "hello")]

        async with session_factory()() as session:
            task = await session.scalar(
                select(Task).where(Task.task_id == "abc123")
            )
            assert task is not None
            assert task.status == "succeeded"
            run = await session.scalar(
                select(TaskRun).where(TaskRun.task_id == "abc123")
            )
            assert run is not None
            assert run.status == "succeeded"
        await engine.dispose()
        await reset_db_engine()


@pytest.mark.asyncio
async def test_task_auto_disabled_after_consecutive_failures() -> None:
    """连续失败达到阈值后任务自动停用（电路断路器）。"""
    from app.core.bus import get_bus, reset_bus
    from app.core.events import TaskAutoDisabled
    from app.core.subscriptions import EventSubscriptionRegistry

    try:
        await get_bus().stop(clear=True)
    except Exception:
        pass
    await reset_bus()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = Path(tmp_dir) / "tasks.db"
        url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
        await reset_db_engine()
        engine = get_engine(url)
        await init_db(url)

        class FailingBotClient:
            async def send_group_message(self, group_id, message) -> bool:
                raise RuntimeError("boom")

        async with session_factory()() as session:
            session.add(
                Task(
                    task_id="flaky",
                    name="flaky-task",
                    type="interval",
                    interval_seconds=60,
                    params={"group_id": "1", "message": "x"},
                    enabled=True,
                )
            )
            session.add(TaskRun(task_id="flaky", status="failed"))
            await session.commit()

        received: list[TaskAutoDisabled] = []
        registry = EventSubscriptionRegistry()
        registry.subscribe(
            TaskAutoDisabled,
            lambda event: received.append(event),
            plugin_name="test",
        )
        client = FailingBotClient()
        await _execute_task(
            "flaky",
            bot_client=client,
            scheduler=None,
            auto_disable_after_failures=2,
        )
        async with session_factory()() as session:
            task = await session.scalar(
                select(Task).where(Task.task_id == "flaky")
            )
            assert task is not None
            assert task.enabled is False
            assert task.params.get("auto_disabled") is not None
            assert "自动停用" in task.params.get("auto_disabled_reason", "")
            cycles = task.params.get("self_heal_cycles") or []
            assert len(cycles) == 1
            assert cycles[0]["disabled"] is not None
            assert cycles[0]["reenabled"] is None
        assert received and received[0].task_id == "flaky"

        await engine.dispose()
        await reset_db_engine()
        await get_bus().stop(clear=True)
        await reset_bus()
