from __future__ import annotations

from app.core import paths


def test_runtime_root_env_override(monkeypatch, tmp_path) -> None:
    target = tmp_path / "custom"
    target.mkdir()
    monkeypatch.setenv(paths.ENV_VAR, str(target))
    assert paths.runtime_root() == target.resolve()


def test_runtime_root_cwd_marker(monkeypatch, tmp_path) -> None:
    (tmp_path / "config.yaml").write_text("{}", encoding="utf-8")
    monkeypatch.delenv(paths.ENV_VAR, raising=False)
    monkeypatch.chdir(tmp_path)
    assert paths.runtime_root() == tmp_path.resolve()


def test_runtime_root_fallback_package(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv(paths.ENV_VAR, raising=False)
    monkeypatch.chdir(tmp_path)  # 空目录，无标记
    assert paths.runtime_root() == paths._package_root()
