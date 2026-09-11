"""发版一致性门禁：提交信息版本与版本号/CHANGELOG 同步校验。

用法：
    py scripts/check_release.py

退出码：
    0  全部一致（或最近提交不含 vX.Y.Z 语义版本，视为普通提交）
    1  存在不一致
"""

from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_RE = re.compile(r"\bv(\d+\.\d+\.\d+)\b")


def _read_app_version() -> str:
    text = (ROOT / "app" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    return match.group(1) if match else ""


def _read_pyproject_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as file:
        return str(tomllib.load(file)["project"]["version"])


def _latest_commit_message() -> str:
    result = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def main() -> int:
    message = _latest_commit_message()
    match = VERSION_RE.search(message)
    if not match:
        print("最近提交不含 vX.Y.Z 语义版本，跳过一致性门禁。")
        return 0
    version = match.group(1)
    errors: list[str] = []
    app_version = _read_app_version()
    pyproject_version = _read_pyproject_version()
    if app_version != version:
        errors.append(
            f"提交信息声明 v{version}，但 app/__init__.py 为 {app_version!r}"
        )
    if pyproject_version != version:
        errors.append(
            f"提交信息声明 v{version}，但 pyproject.toml 为 {pyproject_version!r}"
        )
    changelog = (ROOT / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")
    if not re.search(rf"^## v{re.escape(version)}\b", changelog, re.MULTILINE):
        errors.append(f"docs/CHANGELOG.md 缺少 ## v{version} 小节")
    if errors:
        for error in errors:
            print(f"[FAIL] {error}", file=sys.stderr)
        return 1
    print(f"[OK] v{version} 版本号与 CHANGELOG 一致。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
