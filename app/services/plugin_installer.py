from __future__ import annotations

import json
import re
import shutil
import zipfile
from pathlib import Path

from app.core.logger import get_logger
from app.core.plugin import PLUGIN_API_VERSION

logger = get_logger(__name__)

_PLUGIN_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def validate_plugin_name(name: str) -> str:
    """校验插件名：小写字母开头，仅含小写字母/数字/下划线，长度 1-64。"""
    name = (name or "").strip()
    if not _PLUGIN_NAME_RE.match(name):
        raise ValueError(
            "插件名仅允许小写字母开头，包含小写字母/数字/下划线（1-64 字符）"
        )
    return name


class PluginInstaller:
    def __init__(self, plugins_dir: str | Path) -> None:
        self.plugins_dir = Path(plugins_dir)
        self.plugins_dir.mkdir(parents=True, exist_ok=True)

    def install_zip(self, archive_path: str | Path) -> Path:
        archive_path = Path(archive_path)
        with zipfile.ZipFile(archive_path) as archive:
            names = archive.namelist()
            manifest_name = next(
                (name for name in names if name.endswith("plugin.json")), None
            )
            if manifest_name is None:
                raise ValueError("zip archive has no plugin.json")
            manifest_data = json.loads(archive.read(manifest_name).decode("utf-8"))
            plugin_name = validate_plugin_name(manifest_data.get("name"))
            if manifest_data.get("api_version") != PLUGIN_API_VERSION:
                raise ValueError(
                    "plugin.json api_version 不支持："
                    f"当前框架要求 {PLUGIN_API_VERSION}"
                )
            version = manifest_data.get("version")
            if not isinstance(version, str) or not version.strip():
                raise ValueError("plugin.json 缺少 version")
            if "dependencies" in manifest_data and not isinstance(
                manifest_data["dependencies"], dict
            ):
                raise ValueError("plugin.json 的 dependencies 必须是对象")
            target = self.plugins_dir / plugin_name
            if target.exists():
                raise ValueError(f"plugin already exists: {plugin_name}")
            target.mkdir()
            try:
                root_dir = manifest_name.split("/")[0]
                for name in names:
                    relative = name
                    if name == root_dir or name.startswith(f"{root_dir}/"):
                        relative = name[len(root_dir) :].lstrip("/")
                    if not relative:
                        continue
                    resolved = (target / relative).resolve()
                    if not resolved.is_relative_to(target.resolve()):
                        raise ValueError("zip archive contains unsafe path")
                    if relative.endswith("/"):
                        resolved.mkdir(parents=True, exist_ok=True)
                    else:
                        resolved.parent.mkdir(parents=True, exist_ok=True)
                        resolved.write_bytes(archive.read(name))
            except Exception:
                shutil.rmtree(target)
                raise
        logger.info("plugin installed: %s", plugin_name)
        return target

    def create_scaffold(self, name: str) -> Path:
        name = validate_plugin_name(name)
        target = self.plugins_dir / name
        if target.exists():
            raise ValueError(f"plugin already exists: {name}")
        target.mkdir()
        manifest = {
            "name": name,
            "api_version": 1,
            "version": "0.1.0",
            "description": "new plugin",
            "author": "",
            "dependencies": {},
            "permissions": [],
            "config_schema": {"type": "object", "properties": {}},
            "web": False,
            "models": [],
            "migrations": [],
            "entry": "create_plugin",
        }
        (target / "plugin.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (target / "__init__.py").write_text(
            "from app.core.plugin import Plugin, PluginContext\n\n\n"
            "class ExamplePlugin(Plugin):\n"
            "    def setup(self, ctx: PluginContext) -> None:\n"
            "        pass\n\n\n"
            "def create_plugin() -> Plugin:\n"
            "    return ExamplePlugin()\n",
            encoding="utf-8",
        )
        return target
