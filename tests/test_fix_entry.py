"""回归测试：验证各缺陷修复的正确性。"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

# ── 缺陷 3：迁移记录新旧格式兼容 ──────────────────────────────────


async def test_migration_new_format_recorded() -> None:
    """新格式 record_name（relative/path/name.py）被正确记录。"""
    from sqlalchemy import select

    from app.db.base import get_engine, init_db, reset_db_engine, session_factory
    from app.db.migrations import MigrationRunner
    from app.db.models import MigrationRecord

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        subdir = Path(tmp_dir) / "mymodule"
        subdir.mkdir()
        path = subdir / "001_init.py"
        path.write_text("async def upgrade():\n    pass\n", encoding="utf-8")
        url = f"sqlite+aiosqlite:///{(Path(tmp_dir) / 'test.db').as_posix()}"
        await reset_db_engine()
        engine = get_engine(url)
        await init_db(url)

        runner = MigrationRunner()
        await runner.run([str(path)])

        async with session_factory()() as session:
            rows = (await session.scalars(select(MigrationRecord.name))).all()

        assert "mymodule/001_init.py" in rows

        await engine.dispose()
        await reset_db_engine()


async def test_migration_old_absolute_format_still_skipped() -> None:
    """旧格式绝对路径记录被识别，不重复执行。"""
    from datetime import UTC, datetime

    from app.db.base import get_engine, init_db, reset_db_engine, session_factory
    from app.db.migrations import MigrationRunner
    from app.db.models import MigrationRecord

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        subdir = Path(tmp_dir) / "mymodule"
        subdir.mkdir()
        path = subdir / "002_upgrade.py"
        path.write_text(
            "import pathlib\nasync def upgrade():\n    pathlib.Path(r'"
            + str(Path(tmp_dir) / "ran.txt")
            + "').write_text('ran')\n",
            encoding="utf-8",
        )
        marker = Path(tmp_dir) / "ran.txt"
        url = f"sqlite+aiosqlite:///{(Path(tmp_dir) / 'test.db').as_posix()}"
        await reset_db_engine()
        engine = get_engine(url)
        await init_db(url)

        # 先用旧绝对路径格式写入记录
        async with session_factory()() as session:
            session.add(
                MigrationRecord(
                    name=str(path),
                    applied_at=datetime.now(UTC),
                )
            )
            await session.commit()

        runner = MigrationRunner()
        await runner.run([str(path)])
        assert not marker.exists()

        await engine.dispose()
        await reset_db_engine()


# ── 缺陷 4：get_engine URL 变化时换引擎 ───────────────────────────


async def test_get_engine_url_change_replaces_engine() -> None:
    """URL 变化时旧引擎被 dispose，新引擎指向新数据库。"""
    import app.db.base as base_mod
    from app.db.base import get_engine, reset_db_engine

    await reset_db_engine()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        url1 = f"sqlite+aiosqlite:///{(Path(tmp_dir) / 'a.db').as_posix()}"
        url2 = f"sqlite+aiosqlite:///{(Path(tmp_dir) / 'b.db').as_posix()}"
        engine_a = get_engine(url1)
        assert base_mod._engine_url is not None
        engine_b = get_engine(url2)
        assert engine_a is not engine_b
        assert base_mod._engine_url is not None
        await engine_b.dispose()
        await reset_db_engine()


# ── 缺陷 2：DB 路径推导 ─────────────────────────────────────────


def test_resolve_sqlite_path_relative() -> None:
    """相对路径被解析为项目根目录下的绝对路径。"""
    from app.db.base import resolve_sqlite_path

    result = resolve_sqlite_path("sqlite+aiosqlite:///data/test.db")
    assert result.is_absolute()
    assert result.name == "test.db"


def test_resolve_sqlite_path_absolute() -> None:
    """绝对路径保持不变（不拼接项目根）。"""
    import sys

    from app.db.base import resolve_sqlite_path

    if sys.platform == "win32":
        # Windows 上 /tmp/test.db 不被视为绝对路径，用 drive 字母路径
        raw = "C:/tmp/test.db"
        expected = Path(raw)
    else:
        raw = "/tmp/test.db"
        expected = Path(raw)
    result = resolve_sqlite_path(f"sqlite+aiosqlite:///{raw}")
    assert result == expected


def test_resolve_sqlite_path_non_sqlite_raises() -> None:
    """非 SQLite URL 抛出 ValueError。"""
    from app.db.base import resolve_sqlite_path

    with pytest.raises(ValueError, match="not a sqlite URL"):
        resolve_sqlite_path("postgresql://localhost/db")


# ── 缺陷 6：成功运行清除 last_error ─────────────────────────────


async def test_task_success_clears_last_error() -> None:
    """任务成功后 last_error 从 params 中移除。"""

    from sqlalchemy import select

    from app.db.base import get_engine, init_db, reset_db_engine, session_factory
    from app.db.models import Task

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        url = f"sqlite+aiosqlite:///{(Path(tmp_dir) / 'test.db').as_posix()}"
        await reset_db_engine()
        engine = get_engine(url)
        await init_db(url)

        async with session_factory()() as session:
            session.add(
                Task(
                    task_id="task_with_error",
                    name="test",
                    type="interval",
                    interval_seconds=60,
                    params={"last_error": "old error", "group_id": "123"},
                    enabled=True,
                )
            )
            await session.commit()

        from app.adapters.base import BotClient
        from app.runtime import _execute_task

        bot_client = BotClient()
        await _execute_task(
            "task_with_error",
            bot_client=bot_client,
            auto_disable_after_failures=0,
        )

        async with session_factory()() as session:
            task = await session.scalar(
                select(Task).where(Task.task_id == "task_with_error")
            )
            assert task is not None
            assert task.status == "succeeded"
            assert "last_error" not in task.params

        await engine.dispose()
        await reset_db_engine()
