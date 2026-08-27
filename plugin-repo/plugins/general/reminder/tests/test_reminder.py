from __future__ import annotations

import sys
import importlib.util
from datetime import datetime
from pathlib import Path

_handlers_path = Path(__file__).resolve().parents[1] / "handlers.py"
_spec = importlib.util.spec_from_file_location(
    "reminder_handlers_test", _handlers_path
)
handlers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(handlers)

from app.core.messages import Message  # noqa: E402
remind_command = handlers.remind_command
setup = handlers.setup


class FakeEvent:
    def __init__(self, group_id: str = "100") -> None:
        self.group_id = group_id
        self.replies: list[str] = []

    async def reply(self, content: str) -> None:
        self.replies.append(content)


class FakeScheduler:
    def __init__(self) -> None:
        self.jobs: list[tuple[str, object]] = []

    def add_date_job(self, func, *, job_id: str, run_date: object) -> None:
        self.jobs.append((job_id, run_date))


async def test_remind_schedules_job(tmp_path) -> None:
    scheduler = FakeScheduler()
    ctx = type("Ctx", (), {})()
    ctx.scheduler = scheduler
    ctx.config = {}
    ctx.now = lambda: datetime(2026, 8, 27, 10, 0, 0)
    ctx.send_group = lambda *a, **k: None
    setup(ctx)
    event = FakeEvent()
    await remind_command(event, Message("60 该喝水了"), None)
    assert event.replies and "60 秒后" in event.replies[0]
    assert len(scheduler.jobs) == 1
    job_id, run_date = scheduler.jobs[0]
    assert job_id
    assert run_date.hour == 10 and run_date.minute == 1
