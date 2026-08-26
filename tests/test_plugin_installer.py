from __future__ import annotations

import json
import tempfile
import zipfile
from pathlib import Path

import pytest

from app.services.plugin_installer import PluginInstaller, validate_plugin_name


def _manifest(**overrides: object) -> str:
    data = {
        "name": "good",
        "api_version": 1,
        "version": "1.0.0",
        "description": "ok",
        "author": "me",
        "dependencies": {},
    }
    data.update(overrides)
    return json.dumps(data)


def test_create_scaffold_and_install_zip() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        plugins_dir = Path(tmp_dir) / "plugins"
        source_dir = Path(tmp_dir) / "source"
        scaffold = PluginInstaller(source_dir).create_scaffold("hello")
        assert (scaffold / "plugin.json").exists()

        archive = Path(tmp_dir) / "hello.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("hello/plugin.json", (scaffold / "plugin.json").read_text(encoding="utf-8"))
            zf.writestr("hello/__init__.py", (scaffold / "__init__.py").read_text(encoding="utf-8"))

        installed = PluginInstaller(plugins_dir).install_zip(archive)
        manifest = json.loads(
            (installed / "plugin.json").read_text(encoding="utf-8")
        )
        assert manifest["name"] == "hello"


def test_install_zip_rejects_unsafe_path() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        installer = PluginInstaller(Path(tmp_dir) / "plugins")
        archive = Path(tmp_dir) / "bad.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("bad/plugin.json", _manifest(name="bad"))
            zf.writestr("../evil.txt", "x")
        try:
            installer.install_zip(archive)
        except ValueError:
            return
        raise AssertionError("unsafe zip should be rejected")


def test_install_zip_rejects_bad_manifest() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        installer = PluginInstaller(Path(tmp_dir) / "plugins")

        # 路径穿越型插件名
        archive = Path(tmp_dir) / "traversal.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("x/plugin.json", _manifest(name="../evil"))
        with pytest.raises(ValueError, match="插件名"):
            installer.install_zip(archive)

        # api_version 不兼容
        archive = Path(tmp_dir) / "api.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("x/plugin.json", _manifest(api_version=99))
        with pytest.raises(ValueError, match="api_version"):
            installer.install_zip(archive)

        # 缺少 version
        archive = Path(tmp_dir) / "ver.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("x/plugin.json", _manifest(version=""))
        with pytest.raises(ValueError, match="version"):
            installer.install_zip(archive)

        # 越界文件不应被写出
        outside = Path(tmp_dir) / "evil.txt"
        assert not outside.exists()


def test_validate_plugin_name_edges() -> None:
    assert validate_plugin_name("hello") == "hello"
    assert validate_plugin_name("my_plugin2") == "my_plugin2"
    for bad in ["", "  ", "MyPlugin", "1abc", "a b", "../x", "a/b", "a.b"]:
        with pytest.raises(ValueError):
            validate_plugin_name(bad)


def test_scaffold_rejects_bad_name() -> None:
    from app.services.scaffold import ScaffoldService

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        root = Path(tmp_dir)
        service = ScaffoldService(root / "examples", root / "plugins")
        with pytest.raises(ValueError, match="插件名"):
            service.create_from_template("dice", "../evil")
