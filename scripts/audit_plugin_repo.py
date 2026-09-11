"""插件市场制品与内置插件同步审计。

对 plugin-repo 中每个插件执行两类检查：
1. 制品健康：zip 只含预期文件，不含缓存/编译产物/编辑器备份/超大文件；
   测试文件与体积偏大的文件给出非阻断告警。
2. 内置同步：当 plugins/<name> 与市场插件同名时，校验 name/version/description/author
   一致，防止内置插件与市场插件悄悄分叉。

用法：
    py scripts/audit_plugin_repo.py              # 输出报告（告警不退出）
    py scripts/audit_plugin_repo.py --check      # 有 error 时非零退出
    py scripts/audit_plugin_repo.py --strict     # error 或 warning 都非零退出
"""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO_DIR = ROOT / "plugin-repo"
SOURCES_DIR = REPO_DIR / "plugins"
PACKAGES_DIR = REPO_DIR / "packages"
BUILTIN_DIR = ROOT / "plugins"

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+")
_IGNORED_PARTS = {
    "__pycache__",
    ".pytest_cache",
    ".git",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "node_modules",
}
_BINARY_SUFFIXES = {".pyc", ".pyo", ".exe", ".dll", ".so", ".dylib"}
_BACKUP_SUFFIXES = {".bak", ".orig", ".rej", ".swp", ".swo"}
_MAX_WARN_BYTES = 200_000
_MAX_ERROR_BYTES = 2_000_000


@dataclass(frozen=True)
class Finding:
    plugin: str
    severity: str  # "error" | "warning"
    message: str

    def line(self) -> str:
        return f"[{self.severity.upper()}] {self.plugin}: {self.message}"


def discover_marketplace_plugins() -> list[tuple[str, Path]]:
    plugins: list[tuple[str, Path]] = []
    if not SOURCES_DIR.exists():
        return plugins
    for category in sorted(SOURCES_DIR.iterdir()):
        if not category.is_dir():
            continue
        for plugin_dir in sorted(category.iterdir()):
            if (plugin_dir / "plugin.json").exists():
                plugins.append((category.name, plugin_dir))
    return plugins


def load_manifest(plugin_dir: Path) -> dict | None:
    manifest_path = plugin_dir / "plugin.json"
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def strip_archive_root(arcname: str, plugin_name: str) -> str:
    prefix = f"{plugin_name}/"
    if arcname.startswith(prefix):
        return arcname[len(prefix) :]
    return arcname


def classify_archive_entry(rel_path: str, size: int) -> list[tuple[str, str]]:
    """返回该文件的 (severity, message) 列表。"""
    findings: list[tuple[str, str]] = []
    parts = Path(rel_path).parts
    if any(part in _IGNORED_PARTS for part in parts):
        findings.append(("error", f"不应打包缓存/隐藏目录：{rel_path}"))
    suffix = Path(rel_path).suffix.lower()
    if suffix in _BINARY_SUFFIXES:
        findings.append(("error", f"不应打包二进制/编译产物：{rel_path}"))
    basename = Path(rel_path).name
    if basename.startswith(".") or basename.endswith("~"):
        findings.append(("warning", f"疑似隐藏或备份文件：{rel_path}"))
    if suffix in _BACKUP_SUFFIXES:
        findings.append(("warning", f"编辑器备份文件：{rel_path}"))
    if "tests" in parts or basename.startswith("test_") or basename.endswith("_test.py"):
        findings.append(("warning", f"发行包内含测试文件，可考虑排除：{rel_path}"))
    if size > _MAX_ERROR_BYTES:
        findings.append(
            ("error", f"文件过大（{size} 字节 > {_MAX_ERROR_BYTES}）：{rel_path}")
        )
    elif size > _MAX_WARN_BYTES:
        findings.append(
            ("warning", f"文件偏大（{size} 字节 > {_MAX_WARN_BYTES}）：{rel_path}")
        )
    return findings


def audit_package(category: str, plugin_dir: Path) -> list[Finding]:
    name = plugin_dir.name
    findings: list[Finding] = []
    manifest = load_manifest(plugin_dir)
    if manifest is None:
        return [Finding(name, "error", "plugin.json 不存在或无法解析")]
    if manifest.get("name") != name:
        findings.append(Finding(name, "error", "目录名与 manifest.name 不一致"))
    version = str(manifest.get("version", ""))
    if not _SEMVER_RE.match(version):
        findings.append(Finding(name, "error", f"version 非 X.Y.Z：{version!r}"))

    zip_path = PACKAGES_DIR / f"{name}.zip"
    if not zip_path.exists():
        findings.append(Finding(name, "error", f"缺少制品 {zip_path.relative_to(ROOT)}"))
        return findings

    try:
        with zipfile.ZipFile(zip_path) as archive:
            for info in archive.infolist():
                rel = strip_archive_root(info.filename, name)
                for severity, message in classify_archive_entry(rel, info.file_size):
                    findings.append(Finding(name, severity, message))
    except (zipfile.BadZipFile, OSError) as exc:
        findings.append(Finding(name, "error", f"zip 无法读取：{exc}"))
    return findings


def check_builtin_sync(category: str, plugin_dir: Path) -> list[Finding]:
    name = plugin_dir.name
    builtin_manifest_path = BUILTIN_DIR / name / "plugin.json"
    if not builtin_manifest_path.exists():
        return []
    market = load_manifest(plugin_dir)
    try:
        builtin = json.loads(builtin_manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [Finding(name, "error", f"内置 plugin.json 无法解析：{exc}")]

    findings: list[Finding] = []
    for field in ("name", "version", "description", "author"):
        if builtin.get(field) != market.get(field):
            findings.append(
                Finding(
                    name,
                    "error",
                    f"内置插件与市场插件 {field} 不一致："
                    f"{builtin.get(field)!r} != {market.get(field)!r}",
                )
            )
    return findings


def run_audit() -> list[Finding]:
    findings: list[Finding] = []
    for category, plugin_dir in discover_marketplace_plugins():
        findings.extend(audit_package(category, plugin_dir))
        findings.extend(check_builtin_sync(category, plugin_dir))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="error 时非零退出")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="error 或 warning 都非零退出",
    )
    args = parser.parse_args()

    findings = run_audit()
    if not findings:
        print("插件市场审计通过：未发现问题。")
        return 0
    for finding in findings:
        print(finding.line())

    errors = [f for f in findings if f.severity == "error"]
    warnings = [f for f in findings if f.severity == "warning"]
    print(
        f"\n共 {len(findings)} 项：{len(errors)} error，{len(warnings)} warning。"
    )
    if args.strict and findings:
        return 1
    if args.check and errors:
        return 1
    if not args.check and not args.strict:
        return 0
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
