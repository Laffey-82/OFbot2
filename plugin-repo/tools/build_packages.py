"""打包 plugin-repo/plugins → plugin-repo/packages 并生成 registry.json。

用法：
    py plugin-repo/tools/build_packages.py                  # 全量构建（写入 packages/ 与 registry.json）
    py plugin-repo/tools/build_packages.py --check          # 仅校验：清单合法且产物与源码一致（不写入）
    py plugin-repo/tools/build_packages.py --owner X --repo Y --branch main

CI 流程：先运行全量构建，再 `git diff --exit-code -- plugin-repo` 确认产物已随源码提交。
"""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPO_DIR = ROOT / "plugin-repo"
SOURCES_DIR = REPO_DIR / "plugins"
PACKAGES_DIR = REPO_DIR / "packages"
REGISTRY_PATH = REPO_DIR / "registry.json"

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+")


def discover_plugins() -> list[tuple[str, Path]]:
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


def validate_manifest(category: str, plugin_dir: Path) -> dict:
    manifest = json.loads(
        (plugin_dir / "plugin.json").read_text(encoding="utf-8")
    )
    name = str(manifest.get("name", ""))
    if name != plugin_dir.name:
        raise ValueError(f"{plugin_dir}: 目录名与 name 不一致（{name}）")
    if manifest.get("api_version") != 1:
        raise ValueError(f"{plugin_dir}: api_version 必须为 1")
    version = str(manifest.get("version", ""))
    if not _SEMVER_RE.match(version):
        raise ValueError(f"{plugin_dir}: version 必须为 X.Y.Z（当前 {version!r}）")
    if not isinstance(manifest.get("dependencies", {}), dict):
        raise TypeError(f"{plugin_dir}: dependencies 必须是对象")
    if not (plugin_dir / "__init__.py").exists():
        raise ValueError(f"{plugin_dir}: 缺少 __init__.py")
    manifest["_category"] = category
    return manifest


def build_zip(category: str, plugin_dir: Path, owner: str, repo: str, branch: str) -> dict:
    manifest = validate_manifest(category, plugin_dir)
    name = plugin_dir.name
    PACKAGES_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = PACKAGES_DIR / f"{name}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for file_path in sorted(plugin_dir.rglob("*")):
            if file_path.is_dir():
                continue
            if any(
                part in {"__pycache__", ".pytest_cache", ".git"}
                for part in file_path.parts
            ):
                continue
            archive.write(file_path, f"{name}/{file_path.relative_to(plugin_dir).as_posix()}")
    return {
        "id": name,
        "name": name,
        "version": manifest["version"],
        "description": manifest.get("description", ""),
        "author": manifest.get("author", ""),
        "category": category,
        "zip_url": (
            f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}"
            f"/plugin-repo/packages/{name}.zip"
        ),
    }


def build_registry(owner: str, repo: str, branch: str) -> list[dict]:
    entries = [
        build_zip(category, plugin_dir, owner, repo, branch)
        for category, plugin_dir in discover_plugins()
    ]
    registry = {
        "format_version": 1,
        "updated_at": datetime.now(UTC).date().isoformat(),
        "plugins": entries,
    }
    REGISTRY_PATH.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return entries


def check_consistency(owner: str, repo: str, branch: str) -> int:
    """校验清单合法性，并核对已提交产物（packages/*.zip 与 registry.json）。"""
    errors: list[str] = []
    plugins = discover_plugins()
    if not plugins:
        errors.append("plugin-repo/plugins 下未发现插件")
    for category, plugin_dir in plugins:
        try:
            validate_manifest(category, plugin_dir)
        except (ValueError, json.JSONDecodeError) as exc:
            errors.append(str(exc))
    if not errors:
        expected = sorted(
            f"{plugin_dir.name}.zip" for _, plugin_dir in plugins
        )
        actual = sorted(
            path.name for path in PACKAGES_DIR.glob("*.zip")
        ) if PACKAGES_DIR.exists() else []
        if actual != expected:
            errors.append(
                f"packages 与源码不一致：期望 {expected}，实际 {actual}"
            )
        if REGISTRY_PATH.exists():
            try:
                registry = json.loads(
                    REGISTRY_PATH.read_text(encoding="utf-8")
                )
                ids = {entry.get("id") for entry in registry.get("plugins", [])}
                expected_ids = {plugin_dir.name for _, plugin_dir in plugins}
                if ids != expected_ids:
                    errors.append(
                        f"registry.json 插件列表与源码不一致：{ids} != {expected_ids}"
                    )
                for entry in registry.get("plugins", []):
                    if not entry.get("zip_url", "").startswith(
                        f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/plugin-repo/packages/"
                    ):
                        errors.append(
                            f"registry.json 中 {entry.get('id')} 的 zip_url 与当前 owner/repo/branch 不符"
                        )
            except (ValueError, json.JSONDecodeError) as exc:
                errors.append(f"registry.json 解析失败：{exc}")
        else:
            errors.append("缺少 registry.json（请先运行 build_packages.py）")
    for error in errors:
        print(f"[FAIL] {error}")
    return 1 if errors else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="仅校验，不写入")
    parser.add_argument("--owner", default="Laffey-82")
    parser.add_argument("--repo", default="OFbot2")
    parser.add_argument("--branch", default="main")
    args = parser.parse_args()
    if args.check:
        return check_consistency(args.owner, args.repo, args.branch)
    entries = build_registry(args.owner, args.repo, args.branch)
    print(f"已构建 {len(entries)} 个插件包 → {PACKAGES_DIR}")
    print(f"已刷新 {REGISTRY_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
