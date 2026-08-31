from __future__ import annotations

import json
import tempfile
import zipfile
from pathlib import Path

from app.services.plugin_installer import PluginInstaller, audit_plugin_dir


def _make_zip(
    path: Path, source: dict[str, str], manifest: dict[str, object] | None = None
) -> None:
    manifest_data: dict[str, object] = {
        "name": "demo",
        "api_version": 1,
        "version": "1.0.0",
    }
    if manifest:
        manifest_data.update(manifest)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("demo/plugin.json", json.dumps(manifest_data))
        for name, content in source.items():
            archive.writestr(f"demo/{name}", content)


def test_audit_zip_detects_risks() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        tmp = Path(tmp_dir)
        archive = tmp / "demo.zip"
        _make_zip(
            archive,
            {
                "handlers.py": (
                    "import httpx\n"
                    "import socket\n"
                    "import shutil\n"
                    "while True:\n"
                    "    send_group_message('1', 'hi')\n"
                ),
                "bad.py": (
                    "eval('1+1')\n"
                    "subprocess.run(['ls'])\n"
                    "os.remove('/tmp/x')\n"
                    "api_key = 'sk-xxx'\n"
                ),
                "notes.exe": "MZ",
            },
        )
        installer = PluginInstaller(tmp / "plugins")
        report = installer.audit_zip(archive)
        checks = {item["check"]: item for item in report["checks"]}
        assert "network.access" in checks
        assert "code.execution" in checks
        assert "filesystem.mutation" in checks
        assert "secret.handling" in checks
        assert "rate.risk" in checks
        assert "file.extension" in checks
        assert report["warnings"] >= 3
        assert report["risk"] == "high"


def test_audit_zip_dependency_whitelist() -> None:
    """依赖白名单：未知第三方依赖告警，白名单内依赖不告警。"""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        tmp = Path(tmp_dir)
        archive = tmp / "demo.zip"
        _make_zip(
            archive,
            {"__init__.py": "from app.core.plugin import Plugin\n"},
            manifest={"dependencies": ["pydantic", "requests"]},
        )
        installer = PluginInstaller(tmp / "plugins")
        report = installer.audit_zip(archive)
        unknown = [
            item for item in report["checks"] if item["check"] == "dependency.unknown"
        ]
        assert len(unknown) == 1
        assert "requests" in unknown[0]["detail"]


def test_audit_plugin_dir_scans_source(tmp_path) -> None:
    """plugin check 使用的目录级静态扫描可发现高危 API。"""
    plugin_dir = tmp_path / "demo"
    plugin_dir.mkdir()
    (plugin_dir / "handlers.py").write_text(
        "import httpx\nimport subprocess\nos.remove('/tmp/x')\n",
        encoding="utf-8",
    )
    (plugin_dir / "safe.py").write_text(
        "from app.core.plugin import Plugin\n",
        encoding="utf-8",
    )
    checks = audit_plugin_dir(plugin_dir)
    by_check = {item["check"] for item in checks}
    assert "network.access" in by_check
    assert "code.execution" in by_check
    assert "filesystem.mutation" in by_check


def test_install_persists_audit() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        tmp = Path(tmp_dir)
        archive = tmp / "demo.zip"
        _make_zip(archive, {"__init__.py": "from app.core.plugin import Plugin\n"})
        installer = PluginInstaller(tmp / "plugins")
        target = installer.install_zip(archive)
        assert (target / "plugin.json").exists()
        audits = installer.read_audits("demo")
        assert audits
        assert audits[-1]["plugin"] == "demo"
