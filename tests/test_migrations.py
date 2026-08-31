from __future__ import annotations

import tempfile
from pathlib import Path

from app.db.migrations import MigrationRunner


async def test_migration_runner_executes_upgrade() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        path = Path(tmp_dir) / "0001_test.py"
        path.write_text(
            "async def upgrade():\n    pass\n",
            encoding="utf-8",
        )
        runner = MigrationRunner()
        await runner.run([str(path)])
        assert str(path) in runner._applied


async def test_migration_runner_persists_and_skips() -> None:
    """迁移记录持久化到表：重建 runner 后不重复执行。"""
    import tempfile
    from pathlib import Path

    from sqlalchemy import select

    from app.db.base import get_engine, init_db, reset_db_engine, session_factory
    from app.db.models import MigrationRecord

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        path = Path(tmp_dir) / "0002_test.py"
        marker = Path(tmp_dir) / "ran.txt"
        path.write_text(
            "import pathlib\n"
            "async def upgrade():\n"
            "    pathlib.Path(r'" + str(marker) + "').write_text('ran')\n",
            encoding="utf-8",
        )
        url = f"sqlite+aiosqlite:///{(Path(tmp_dir) / 'm.db').as_posix()}"
        await reset_db_engine()
        engine = get_engine(url)
        await init_db(url)

        runner = MigrationRunner()
        await runner.run([str(path)])
        assert marker.exists()

        async with session_factory()() as session:
            rows = (await session.scalars(select(MigrationRecord.name))).all()
        assert str(path) in rows

        # 重建 runner（模拟重启）：不重复执行
        marker.unlink()
        runner2 = MigrationRunner()
        await runner2.run([str(path)])
        assert not marker.exists()

        await engine.dispose()
        await reset_db_engine()


async def test_migration_runner_failure_not_recorded() -> None:
    """upgrade 抛错时不应写入迁移记录。"""
    import tempfile
    from pathlib import Path

    import pytest
    from sqlalchemy import select

    from app.db.base import get_engine, init_db, reset_db_engine, session_factory
    from app.db.models import MigrationRecord

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        path = Path(tmp_dir) / "0003_bad.py"
        path.write_text(
            "async def upgrade():\n"
            "    raise RuntimeError('boom')\n",
            encoding="utf-8",
        )
        url = f"sqlite+aiosqlite:///{(Path(tmp_dir) / 'm.db').as_posix()}"
        await reset_db_engine()
        engine = get_engine(url)
        await init_db(url)

        with pytest.raises(RuntimeError, match="boom"):
            await MigrationRunner().run([str(path)])

        async with session_factory()() as session:
            rows = (await session.scalars(select(MigrationRecord.name))).all()
        assert str(path) not in rows

        await engine.dispose()
        await reset_db_engine()
