"""一键发版：版本一致性校验、版本升级、打 tag 与 GitHub Release。

流程（非 dry-run）：
1. 校验 git 工作区干净。
2. 运行 scripts/check_release.py 做一致性门禁（版本号 / CHANGELOG / 提交信息）。
3. 可选 --bump 调用 scripts/sync_version.py 升级版本号。
4. 校验 docs/CHANGELOG.md 存在匹配的 ``## vX.Y.Z`` 小节，并提取为发布说明。
5. git commit / tag / push，并用 ``gh release create`` 创建发布。

用法：
    py scripts/release.py --version 1.6.0 --dry-run    # 只打印计划与校验结果
    py scripts/release.py --version 1.6.0 --bump        # 真实执行（升级版本并发布）
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


def read_app_version() -> str:
    init_py = (ROOT / "app" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', init_py)
    return match.group(1) if match else ""


def read_pyproject_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, flags=re.MULTILINE)
    return match.group(1) if match else ""


def latest_changelog_version() -> str | None:
    changelog = (ROOT / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(r"^## v(\d+\.\d+\.\d+)", changelog, flags=re.MULTILINE)
    return match.group(1) if match else None


def extract_changelog_section(version: str) -> str:
    changelog = (ROOT / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")
    lines = changelog.splitlines()
    marker = f"## v{version}"
    start: int | None = None
    for index, line in enumerate(lines):
        if line.startswith(marker):
            start = index
            break
    if start is None:
        return ""
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("## "):
            end = index
            break
    return "\n".join(lines[start:end]).strip() + "\n"


def consistency_issues(target_version: str) -> list[str]:
    issues: list[str] = []
    if not VERSION_RE.match(target_version):
        issues.append(f"目标版本格式非法：{target_version!r}")
        return issues
    app_version = read_app_version()
    pyproject_version = read_pyproject_version()
    changelog_version = latest_changelog_version()
    if app_version != target_version:
        issues.append(
            f"app/__init__.py 版本 {app_version!r} 与目标 {target_version!r} 不一致"
        )
    if pyproject_version != target_version:
        issues.append(
            f"pyproject.toml 版本 {pyproject_version!r} 与目标 {target_version!r} 不一致"
        )
    if changelog_version != target_version:
        issues.append(
            f"CHANGELOG 最新版本 {changelog_version!r} 与目标 {target_version!r} 不一致"
        )
    if not issues and not extract_changelog_section(target_version):
        issues.append(f"docs/CHANGELOG.md 缺少 ## v{target_version} 小节")
    return issues


def build_release_plan(target_version: str, bump: bool) -> list[str]:
    commands = [
        "python scripts/check_release.py",
    ]
    if bump:
        commands.append(f"python scripts/sync_version.py {target_version}")
    commands.extend(
        [
            "git add -A",
            f'git commit -m "chore(release): v{target_version}"',
            f"git tag v{target_version}",
            "git push origin HEAD",
            f"git push origin v{target_version}",
            (
                f"gh release create v{target_version} --title v{target_version} "
                "--notes-from-file .release_notes.md"
            ),
        ]
    )
    return commands


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )


def _git_tree_is_clean() -> bool:
    result = _run(["git", "status", "--porcelain"])
    return result.returncode == 0 and not result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", help="目标版本（默认读取 app.__version__）")
    parser.add_argument(
        "--bump",
        action="store_true",
        help="调用 scripts/sync_version.py 升级版本号",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印计划与校验结果，不做任何 git/gh 变更",
    )
    parser.add_argument(
        "--skip-checks",
        action="store_true",
        help="跳过一致性校验（不推荐）",
    )
    args = parser.parse_args()

    target = args.version or read_app_version()

    if args.dry_run:
        issues = [] if args.skip_checks else consistency_issues(target)
        print(f"目标版本：{target}")
        print("一致性校验：")
        if issues:
            for issue in issues:
                print(f"  [FAIL] {issue}")
        else:
            print("  [OK] 通过")
        print("\n将执行：")
        for command in build_release_plan(target, args.bump):
            print(f"  $ {command}")
        return 1 if issues else 0

    if not _git_tree_is_clean():
        print("发版中止：git 工作区不干净。", file=sys.stderr)
        return 1
    if args.bump:
        bump = _run(["python", "scripts/sync_version.py", target])
        if bump.returncode != 0:
            print(bump.stdout, end="")
            print(bump.stderr, end="", file=sys.stderr)
            return 1
    issues = [] if args.skip_checks else consistency_issues(target)
    if issues:
        for issue in issues:
            print(f"[FAIL] {issue}", file=sys.stderr)
        print("发版中止：一致性校验未通过。", file=sys.stderr)
        return 1
    if not args.skip_checks:
        gate = _run(["python", "scripts/check_release.py"])
        if gate.returncode != 0:
            print(gate.stdout, end="")
            print(gate.stderr, end="", file=sys.stderr)
            print("发版中止：check_release.py 未通过。", file=sys.stderr)
            return 1

    notes = extract_changelog_section(target)
    if not notes:
        print(f"发版中止：docs/CHANGELOG.md 缺少 ## v{target} 小节。", file=sys.stderr)
        return 1
    notes_path = Path(tempfile.gettempdir()) / f"ofbot2_release_{target}.md"
    notes_path.write_text(notes, encoding="utf-8")

    for command in (
        ["git", "add", "-A"],
        ["git", "commit", "-m", f"chore(release): v{target}"],
        ["git", "tag", f"v{target}"],
        ["git", "push", "origin", "HEAD"],
        ["git", "push", "origin", f"v{target}"],
        [
            "gh",
            "release",
            "create",
            f"v{target}",
            "--title",
            f"v{target}",
            "--notes-file",
            str(notes_path),
        ],
    ):
        result = _run(command)
        if result.returncode != 0:
            print(result.stdout, end="")
            print(result.stderr, end="", file=sys.stderr)
            print(f"命令失败：{' '.join(command)}", file=sys.stderr)
            return 1
    print(f"已发布 v{target}。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
