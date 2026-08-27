from __future__ import annotations

import json
import tempfile
import zipfile
from pathlib import Path

from app.services.plugin_installer import PluginInstaller


def _make_zip(path: Path, source: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "demo/plugin.json",
            json.dumps(
                {
                    "name": "demo",
                    "api_version": 1,
                    "version": "1.0.0",
                }
            ),
        )
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
                    "while True:\n"
                    "    send_group_message('1', 'hi')\n"
                ),
                "bad.py": "eval('1+1')\napi_key = 'sk-xxx'\n",
                "notes.exe": "MZ",
            },
        )
        installer = PluginInstaller(tmp / "plugins")
        report = installer.audit_zip(archive)
        checks = {item["check"]: item for item in report["checks"]}
        assert "network.access" in checks
        assert "code.execution" in checks
        assert "secret.handling" in checks
        assert "rate.risk" in checks
        assert "file.extension" in checks
        assert report["warnings"] >= 3


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
