from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from app.web.export_jobs import _export_job_from_row
from app.web.helpers import (
    _parse_date_range,
    _tail_lines,
    _task_executor,
    nav_active,
    render_markdown_light,
)


class _FakeRequest:
    def __init__(self, path: str) -> None:
        self.url = type("URL", (), {"path": path})()


def test_nav_active() -> None:
    """侧边栏菜单高亮：精确匹配与子页面前缀匹配。"""
    assert nav_active(_FakeRequest("/workflows"), "/workflows") == "active"
    assert (
        nav_active(_FakeRequest("/workflows/5/edit"), "/workflows")
        == "active"
    )
    assert (
        nav_active(_FakeRequest("/webhooks/abc/history"), "/webhooks")
        == "active"
    )
    assert nav_active(_FakeRequest("/backups/compare"), "/backups") == "active"
    # 根路径只精确匹配，避免任意子路径误高亮
    assert nav_active(_FakeRequest("/"), "/") == "active"
    assert nav_active(_FakeRequest("/login"), "/") == ""
    # 相似前缀不误判
    assert nav_active(_FakeRequest("/exports/jobs"), "/exports") == "active"
    assert nav_active(_FakeRequest("/exporters"), "/exports") == ""
    assert nav_active(_FakeRequest("/config"), "/plugins") == ""


@pytest.mark.asyncio
async def test_web_task_executor_delegates_to_runtime() -> None:
    """Web 触发任务与调度器共用 runtime._execute_task（统一断路器与 message_override）。"""
    from types import SimpleNamespace

    from sqlalchemy import select

    from app.core.bus import get_bus, reset_bus
    from app.core.config import load_settings
    from app.db.base import get_engine, init_db, reset_db_engine, session_factory
    from app.db.models import Task, TaskRun

    try:
        await get_bus().stop(clear=True)
    except Exception:
        pass
    await reset_bus()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = Path(tmp_dir) / "tasks.db"
        settings = load_settings()
        settings.config_path = str(Path(tmp_dir) / "config.yaml")
        settings.database.url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
        settings.scheduler.auto_disable_after_failures = 2
        await reset_db_engine()
        engine = get_engine(settings.database.url)
        await init_db(settings.database.url)

        class CapturingBot:
            def __init__(self) -> None:
                self.sent: list[tuple[str, str]] = []
                self.fail = False

            async def send_group_message(self, group_id, message) -> bool:
                if self.fail:
                    raise RuntimeError("boom")
                self.sent.append((str(group_id), str(message)))
                return True

        bot = CapturingBot()
        app = SimpleNamespace(state=SimpleNamespace(settings=settings, bot_client=bot))
        async with session_factory()() as session:
            session.add(
                Task(
                    task_id="web_ok",
                    name="web-ok",
                    type="interval",
                    interval_seconds=60,
                    params={"group_id": "1"},
                    enabled=True,
                )
            )
            session.add(
                Task(
                    task_id="web_flaky",
                    name="web-flaky",
                    type="interval",
                    interval_seconds=60,
                    params={"group_id": "1", "message": "x"},
                    enabled=True,
                )
            )
            session.add(TaskRun(task_id="web_flaky", status="failed"))
            await session.commit()

        # message_override 生效
        await _task_executor("web_ok", app, message_override="hello")()
        assert bot.sent == [("1", "hello")]

        # 连续失败触发自动停用（与调度器路径一致）
        bot.fail = True
        await _task_executor("web_flaky", app)()
        await _task_executor("web_flaky", app)()
        async with session_factory()() as session:
            task = await session.scalar(
                select(Task).where(Task.task_id == "web_flaky")
            )
            assert task is not None and task.enabled is False
            assert task.params.get("auto_disabled") is not None

        await engine.dispose()
        await reset_db_engine()
        await get_bus().stop(clear=True)
        await reset_bus()


def test_parse_date_range() -> None:
    start, end = _parse_date_range("2026-08-01", "2026-08-31")
    assert start == datetime.fromisoformat("2026-08-01")
    assert end == datetime.fromisoformat("2026-08-31T23:59:59")

    start, end = _parse_date_range("", "")
    assert start is None and end is None

    start, end = _parse_date_range("not-a-date", "2026-08-31")
    assert start is None
    assert end == datetime.fromisoformat("2026-08-31T23:59:59")


def test_tail_lines() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        sample = Path(tmp_dir) / "sample.log"
        sample.write_text(
            "\n".join(f"line{i}" for i in range(300)),
            encoding="utf-8",
        )
        tail = _tail_lines(sample, 50)
        assert len(tail.splitlines()) == 50
        assert tail.splitlines()[0] == "line250"
        assert _tail_lines(sample, 5000) == sample.read_text(
            encoding="utf-8"
        )
        assert _tail_lines(sample, 0) == "line299"
        assert _tail_lines(Path(tmp_dir) / "missing.log", 10) == ""

        binary = Path(tmp_dir) / "binary.log"
        binary.write_bytes(b"ok\xff\xfe\nnext")
        tail_binary = _tail_lines(binary, 5)
        assert "next" in tail_binary


def test_render_markdown_light() -> None:
    text = (
        "# 标题\n\n"
        "段落 `code` 与 **加粗**\n\n"
        "- 列表项\n\n"
        "```\nprint(1)\n```\n"
    )
    html = render_markdown_light(text)
    assert "<h1>标题</h1>" in html
    assert "<code>code</code>" in html
    assert "<strong>加粗</strong>" in html
    assert "<li>列表项</li>" in html
    assert 'class="code-block"' in html
    assert "print(1)" in html

    escaped = render_markdown_light("<script>alert(1)</script>")
    assert "<script>" not in escaped
    assert "&lt;script&gt;" in escaped


def test_export_job_from_row() -> None:
    class Row:
        job_id = "j1"
        record_type = "order"
        fmt = "csv"
        status = "failed"
        message = "x"
        filename = None
        actor = "admin"
        created_at = datetime.fromisoformat("2026-08-01T12:00:00")

    job = _export_job_from_row(Row())
    assert job["id"] == "j1"
    assert job["record_type"] == "order"
    assert job["status"] == "failed"
    assert job["created_at"] == "2026-08-01T12:00:00"
