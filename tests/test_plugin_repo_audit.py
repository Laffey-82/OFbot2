from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

import scripts.audit_plugin_repo as audit


def test_strip_archive_root() -> None:
    assert audit.strip_archive_root("calc/__init__.py", "calc") == "__init__.py"
    assert audit.strip_archive_root("calc/__init__.py", "other") == "calc/__init__.py"


def test_classify_archive_entry_catches_cached_and_binary() -> None:
    findings = audit.classify_archive_entry("calc/__pycache__/x.pyc", 10)
    assert any(severity == "error" for severity, _ in findings)
    assert len([f for f in findings if f[0] == "error"]) >= 1
    findings = audit.classify_archive_entry("calc/module.pyc", 10)
    assert any(severity == "error" for severity, _ in findings)


def test_classify_archive_entry_warns_on_tests_and_large_file() -> None:
    findings = audit.classify_archive_entry("calc/tests/test_x.py", 10)
    assert any(severity == "warning" for severity, _ in findings)
    findings = audit.classify_archive_entry("calc/handlers.py", 300_000)
    assert any(severity == "warning" for severity, _ in findings)
    findings = audit.classify_archive_entry("calc/data.bin", 3_000_000)
    assert any(severity == "error" for severity, _ in findings)


def _write_manifest(path: Path, manifest: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")


def _write_zip(path: Path, entries: dict[str, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)


def test_audit_package_ok(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    plugin_dir = tmp_path / "calc"
    _write_manifest(
        plugin_dir / "plugin.json",
        {"name": "calc", "version": "1.0.0", "description": "计算器"},
    )
    packages = tmp_path / "packages"
    monkeypatch.setattr(audit, "PACKAGES_DIR", packages)
    _write_zip(
        packages / "calc.zip",
        {
            "calc/__init__.py": b"",
            "calc/plugin.json": b'{"name": "calc"}',
        },
    )
    assert audit.audit_package("general", plugin_dir) == []


def test_audit_package_flags_bad_entries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    plugin_dir = tmp_path / "calc"
    _write_manifest(
        plugin_dir / "plugin.json",
        {"name": "calc", "version": "1.0.0"},
    )
    packages = tmp_path / "packages"
    monkeypatch.setattr(audit, "PACKAGES_DIR", packages)
    _write_zip(
        packages / "calc.zip",
        {
            "calc/__init__.py": b"",
            "calc/__pycache__/x.pyc": b"",
            "calc/tests/test_x.py": b"",
        },
    )
    findings = audit.audit_package("general", plugin_dir)
    severities = {f.severity for f in findings}
    assert "error" in severities
    assert "warning" in severities


def test_builtin_sync_mismatch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    plugin_dir = tmp_path / "order_ledger"
    _write_manifest(
        plugin_dir / "plugin.json",
        {"name": "order_ledger", "version": "1.0.0", "description": "市场描述"},
    )
    builtin_dir = tmp_path / "builtin"
    monkeypatch.setattr(audit, "BUILTIN_DIR", builtin_dir)
    _write_manifest(
        builtin_dir / "order_ledger" / "plugin.json",
        {"name": "order_ledger", "version": "1.0.0", "description": "内置描述"},
    )
    findings = audit.check_builtin_sync("general", plugin_dir)
    assert any("description" in f.message for f in findings)


def test_builtin_sync_missing_builtin_is_ok(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    plugin_dir = tmp_path / "calc"
    _write_manifest(plugin_dir / "plugin.json", {"name": "calc", "version": "1.0.0"})
    monkeypatch.setattr(audit, "BUILTIN_DIR", tmp_path / "no-builtin")
    assert audit.check_builtin_sync("general", plugin_dir) == []
