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
