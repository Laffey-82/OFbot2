from __future__ import annotations

import tempfile
from pathlib import Path

import yaml

from app.core.config import load_settings, save_settings


def test_load_settings_defaults() -> None:
    settings = load_settings()
    assert settings.basic.command_start == ["/", "!"]
    assert settings.transport.protocol in {"red", "onebot"}
    assert settings.database.url.startswith("sqlite+aiosqlite")


def test_load_settings_merges_command_start_string() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        path = Path(tmp_dir) / "config.yaml"
        path.write_text(
            yaml.safe_dump(
                {"basic": {"command_start": "/", "log_level": "DEBUG"}},
                allow_unicode=True,
            ),
            encoding="utf-8",
        )
        settings = load_settings(path)
        assert settings.basic.command_start == ["/"]
        assert settings.basic.log_level == "DEBUG"


def test_save_settings_writes_to_configured_path_only() -> None:
    root_config = Path(__file__).resolve().parents[1] / "config.yaml"
    before = root_config.read_bytes()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        config_path = Path(tmp_dir) / "config.yaml"
        config_path.write_text(
            yaml.safe_dump({"basic": {"log_level": "INFO"}}),
            encoding="utf-8",
        )
        settings = load_settings(config_path)
        settings.basic.log_level = "DEBUG"
        save_settings(settings)
        assert config_path.exists()
        assert yaml.safe_load(config_path.read_text(encoding="utf-8"))["basic"][
            "log_level"
        ] == "DEBUG"
        assert root_config.read_bytes() == before


def test_load_settings_creates_defaults_for_missing_path() -> None:
    """install.bat 依赖：缺失 config.yaml 时加载默认值并可保存生成。"""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        path = Path(tmp_dir) / "config.yaml"
        settings = load_settings(path)
        assert settings.basic.log_retention_days == 14
        save_settings(settings)
        assert path.exists()
        reloaded = load_settings(path)
        assert reloaded.basic.command_start == settings.basic.command_start
