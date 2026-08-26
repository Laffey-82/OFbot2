from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from app.core.config import load_settings
from app.db.base import get_engine, init_db, reset_db_engine
from app.services.doctor import run_environment_checks


@pytest.mark.asyncio
async def test_doctor_reports_disk_and_plugins() -> None:
    """环境自检包含磁盘空间与插件目录检查，能识别异常插件。"""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        root = Path(tmp_dir)
        (root / "data").mkdir()
        plugins_dir = root / "plugins"
        plugins_dir.mkdir()
        (plugins_dir / "good").mkdir()
        (plugins_dir / "good" / "plugin.json").write_text(
            json.dumps(
                {
                    "name": "good",
                    "api_version": 1,
                    "version": "1.0.0",
                    "description": "ok",
                    "author": "",
                }
            ),
            encoding="utf-8",
        )
        (plugins_dir / "bad_name").mkdir()
        (plugins_dir / "bad_name" / "plugin.json").write_text(
            json.dumps({"name": "other", "api_version": 1}),
            encoding="utf-8",
        )
        (plugins_dir / "no_manifest").mkdir()
        (plugins_dir / "needs_missing").mkdir()
        (plugins_dir / "needs_missing" / "plugin.json").write_text(
            json.dumps(
                {
                    "name": "needs_missing",
                    "api_version": 1,
                    "version": "1.0.0",
                    "description": "dep on missing",
                    "author": "",
                    "dependencies": {"ghost": "1.0.0"},
                }
            ),
            encoding="utf-8",
        )
        (plugins_dir / "needs_disabled").mkdir()
        (plugins_dir / "needs_disabled" / "plugin.json").write_text(
            json.dumps(
                {
                    "name": "needs_disabled",
                    "api_version": 1,
                    "version": "1.0.0",
                    "description": "dep on disabled",
                    "author": "",
                    "dependencies": {"good": "1.0.0"},
                }
            ),
            encoding="utf-8",
        )

        settings = load_settings()
        settings.config_path = str(root / "config.yaml")
        settings.database.url = f"sqlite+aiosqlite:///{root.as_posix()}/test.db"
        reset_db_engine()
        engine = get_engine(settings.database.url)
        await init_db(settings.database.url)

        checks = await run_environment_checks(
            settings, app_state=None, root=root
        )
        by_name = {item["name"]: item for item in checks}

        disk = by_name.get("磁盘空间")
        assert disk is not None
        assert disk["status"] in {"pass", "warn", "info"}
        assert "剩余" in disk["detail"]

        plugins = by_name.get("插件目录")
        assert plugins is not None
        assert plugins["status"] == "warn"
        assert "3 个合法插件" in plugins["detail"]
        assert "bad_name" in plugins["detail"]
        assert "no_manifest" in plugins["detail"]
        assert "缺少依赖 ghost" in plugins["detail"]
        assert "依赖 good 未启用" in plugins["detail"]
        assert plugins.get("href") == "/plugins"

        await engine.dispose()
        reset_db_engine()
