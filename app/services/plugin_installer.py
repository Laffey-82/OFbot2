from __future__ import annotations

import json
import re
import shutil
import time
import zipfile
from pathlib import Path
from typing import Any

from app.core.logger import get_logger
from app.core.plugin import PLUGIN_API_VERSION

logger = get_logger(__name__)

_PLUGIN_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_NETWORK_IMPORTS = (
    "httpx",
    "aiohttp",
    "requests",
    "urllib",
    "socket",
    "websockets",
    "http.client",
    "fastapi",
)
_EXEC_PATTERNS = (
    "eval(",
    "exec(",
    "subprocess",
    "os.system",
    "os.popen",
    "os.spawn",
    "pty.spawn",
    "ctypes",
    "shutil.rmtree",
    "__import__",
    "compile(",
    "marshal.loads",
    "pickle.loads",
    "yaml.load(",
)
_FS_MUTATION_PATTERNS = (
    "os.remove",
    "os.unlink",
    "os.rmdir",
    "os.rename",
    "shutil.move",
    ".write_text(",
    ".write_bytes(",
    ".unlink(",
)
_SECRET_PATTERNS = ("api_key", "access_token", "secret", "password")
_SEND_METHODS = ("send_group_message", "send_private_message", "send_message")
_ALLOWED_EXTENSIONS = {
    ".py",
    ".json",
    ".yml",
    ".yaml",
    ".md",
    ".txt",
    ".html",
    ".svg",
    ".css",
    ".js",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".csv",
}
_DEPENDENCY_ALLOWLIST = {
    "app",
    "pydantic",
    "httpx",
    "yaml",
    "jinja2",
    "sqlalchemy",
    "apscheduler",
    "openpyxl",
    "docx",
    "qrcode",
    "PIL",
    "asyncio",
    "datetime",
    "json",
    "re",
    "pathlib",
    "typing",
    "collections",
    "time",
    "random",
    "math",
    "uuid",
    "base64",
    "hashlib",
    "hmac",
    "logging",
    "os",
    "sys",
}


def validate_plugin_name(name: str) -> str:
    """校验插件名：小写字母开头，仅含小写字母/数字/下划线，长度 1-64。"""
    name = (name or "").strip()
    if not _PLUGIN_NAME_RE.match(name):
        raise ValueError(
            "插件名仅允许小写字母开头，包含小写字母/数字/下划线（1-64 字符）"
        )
    return name


def audit_plugin_dir(plugin_dir: str | Path) -> list[dict[str, Any]]:
    """静态扫描插件目录 .py 源码中的高危 API 与敏感模式（供 plugin check 使用）。"""
    plugin_dir = Path(plugin_dir)
    checks: list[dict[str, Any]] = []
    for path in sorted(plugin_dir.rglob("*.py")):
        if ".audit" in path.parts or "__pycache__" in path.parts:
            continue
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.warning("读取插件源码失败 %s：%s", path, exc)
            continue
        lowered = source.lower()
        rel = str(path.relative_to(plugin_dir))
        for module in _NETWORK_IMPORTS:
            if re.search(
                rf"^\s*(import|from)\s+{re.escape(module)}",
                source,
                re.MULTILINE,
            ):
                checks.append(
                    {
                        "level": "info",
                        "check": "network.access",
                        "detail": f"{rel} 引用了网络库 {module}",
                    }
                )
        for pattern in _EXEC_PATTERNS:
            if pattern in lowered:
                checks.append(
                    {
                        "level": "warn",
                        "check": "code.execution",
                        "detail": f"{rel} 包含 {pattern}",
                    }
                )
        for pattern in _FS_MUTATION_PATTERNS:
            if pattern in lowered:
                checks.append(
                    {
                        "level": "warn",
                        "check": "filesystem.mutation",
                        "detail": f"{rel} 包含 {pattern}",
                    }
                )
        for pattern in _SECRET_PATTERNS:
            if pattern in lowered and re.search(
                rf"\b{re.escape(pattern)}\b\s*[=:]\s*['\"\d{{]",
                source,
            ):
                checks.append(
                    {
                        "level": "info",
                        "check": "secret.handling",
                        "detail": (
                            f"{rel} 直接赋值 {pattern}，"
                            "建议改用 config_schema 配置"
                        ),
                    }
                )
    return checks


class PluginInstaller:
    def __init__(self, plugins_dir: str | Path) -> None:
        self.plugins_dir = Path(plugins_dir)
        self.plugins_dir.mkdir(parents=True, exist_ok=True)

    def audit_zip(self, archive_path: str | Path) -> dict[str, Any]:
        """安装前安全审计：文件白名单、网络访问、执行、文件变更、secret、
        发送频率与依赖白名单。"""
        archive_path = Path(archive_path)
        checks: list[dict[str, Any]] = []
        file_count = 0
        total_size = 0
        py_sources: list[str] = []
        manifest_data: dict[str, Any] | None = None
        with zipfile.ZipFile(archive_path) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                file_count += 1
                total_size += info.file_size
                name = info.filename.rsplit("/", 1)[-1]
                if name == "plugin.json":
                    try:
                        manifest_data = json.loads(
                            archive.read(info.filename).decode("utf-8")
                        )
                    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
                        manifest_data = None
                suffix = Path(name).suffix.lower()
                if suffix not in _ALLOWED_EXTENSIONS:
                    checks.append(
                        {
                            "level": "warn",
                            "check": "file.extension",
                            "detail": f"文件 {info.filename} 扩展名 {suffix or '(无)'} 不在白名单",
                        }
                    )
                if suffix == ".py":
                    py_sources.append(info.filename)
            if file_count > 200:
                checks.append(
                    {
                        "level": "warn",
                        "check": "file.count",
                        "detail": f"文件数量 {file_count} 超过 200，注意检查",
                    }
                )
            if total_size > 20 * 1024 * 1024:
                checks.append(
                    {
                        "level": "warn",
                        "check": "file.size",
                        "detail": f"包体积 {total_size // 1024} KB 超过 20 MB",
                    }
                )
            for name in py_sources:
                try:
                    source = archive.read(name).decode("utf-8", errors="replace")
                except Exception as exc:
                    logger.warning("读取插件源码失败 %s：%s", name, exc)
                    continue
                lowered = source.lower()
                for module in _NETWORK_IMPORTS:
                    if re.search(
                        rf"^\s*(import|from)\s+{re.escape(module)}",
                        source,
                        re.MULTILINE,
                    ):
                        checks.append(
                            {
                                "level": "info",
                                "check": "network.access",
                                "detail": f"{name} 引用了网络库 {module}",
                            }
                        )
                for pattern in _EXEC_PATTERNS:
                    if pattern in lowered:
                        checks.append(
                            {
                                "level": "warn",
                                "check": "code.execution",
                                "detail": f"{name} 包含 {pattern}",
                            }
                        )
                for pattern in _FS_MUTATION_PATTERNS:
                    if pattern in lowered:
                        checks.append(
                            {
                                "level": "warn",
                                "check": "filesystem.mutation",
                                "detail": f"{name} 包含 {pattern}",
                            }
                        )
                for pattern in _SECRET_PATTERNS:
                    if pattern in lowered and re.search(
                        rf"\b{re.escape(pattern)}\b\s*[=:]\s*['\"\d{{]",
                        source,
                    ):
                        checks.append(
                            {
                                "level": "info",
                                "check": "secret.handling",
                                "detail": f"{name} 直接赋值 {pattern}，建议改用 config_schema 配置",
                            }
                        )
                if any(method in source for method in _SEND_METHODS):
                    if re.search(r"(while\s+True|for\s+.*in\s+range)", source) and "sleep" not in lowered:
                        checks.append(
                            {
                                "level": "warn",
                                "check": "rate.risk",
                                "detail": f"{name} 存在循环发送且未发现 sleep，注意风控",
                            }
                        )
        dependencies = manifest_data.get("dependencies", []) if manifest_data else []
        if isinstance(dependencies, list):
            for dep in dependencies:
                dep_name = str(dep).split(".", 1)[0]
                if dep_name not in _DEPENDENCY_ALLOWLIST:
                    checks.append(
                        {
                            "level": "warn",
                            "check": "dependency.unknown",
                            "detail": f"依赖 {dep} 不在白名单，请确认来源可信",
                        }
                    )
        warnings = sum(1 for item in checks if item["level"] == "warn")
        infos = sum(1 for item in checks if item["level"] == "info")
        high_risk = any(
            item["check"] in {"code.execution", "filesystem.mutation"}
            for item in checks
        )
        return {
            "file_count": file_count,
            "total_size": total_size,
            "risk": "high" if high_risk else ("medium" if warnings else "low"),
            "warnings": warnings,
            "infos": infos,
            "checks": checks[:50],
        }

    def save_audit(self, name: str, report: dict[str, Any]) -> Path:
        audit_dir = self.plugins_dir / ".audit"
        audit_dir.mkdir(parents=True, exist_ok=True)
        path = audit_dir / f"{name}-{int(time.time())}.json"
        path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    def read_audits(self, name: str | None = None) -> list[dict[str, Any]]:
        audit_dir = self.plugins_dir / ".audit"
        if not audit_dir.exists():
            return []
        reports: list[dict[str, Any]] = []
        for path in sorted(audit_dir.glob("*.json"), reverse=True):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (ValueError, json.JSONDecodeError):
                logger.warning("跳过损坏的审计记录 %s", path.name)
                continue
            if name is None or data.get("plugin") == name:
                reports.append(data)
        return reports

    def install_zip(
        self, archive_path: str | Path, *, audit: bool = True
    ) -> Path:
        archive_path = Path(archive_path)
        audit_report: dict[str, Any] | None = None
        if audit:
            audit_report = self.audit_zip(archive_path)
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
        if audit_report is not None:
            audit_report["plugin"] = plugin_name
            audit_report["installed_at"] = time.time()
            self.save_audit(plugin_name, audit_report)
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
