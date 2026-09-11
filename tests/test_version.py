from __future__ import annotations

import re
import subprocess
import tomllib
from pathlib import Path

import app

ROOT = Path(__file__).resolve().parents[1]


def test_version_single_source_consistent() -> None:
    with (ROOT / "pyproject.toml").open("rb") as file:
        pyproject = tomllib.load(file)
    assert pyproject["project"]["version"] == app.__version__


def test_version_format() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", app.__version__)


def test_pypi_metadata_present() -> None:
    with (ROOT / "pyproject.toml").open("rb") as file:
        pyproject = tomllib.load(file)
    project = pyproject["project"]
    assert project.get("readme")
    assert "license" in project
    assert project.get("authors")
    assert project.get("classifiers")
    assert "build-system" in pyproject


def test_semantic_commit_version_gate() -> None:
    """语义提交含 vX.Y.Z 时，版本号/CHANGELOG/本地 tag 必须同步。

    仅在本地 git 可用时校验；CI 环境（如 GitHub Actions checkout）可能未打 tag，
    因此 tag 检查仅在本仓库已存在至少一个本地 tag 时启用，避免误失败。
    """
    try:
        message = subprocess.run(
            ["git", "log", "-1", "--pretty=%s"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout.strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return
    match = re.search(r"\bv(\d+\.\d+\.\d+)\b", message)
    if not match:
        return
    version = match.group(1)
    assert app.__version__ == version, (
        f"提交信息声明 v{version}，但 app.__version__ = {app.__version__}"
    )
    changelog = (ROOT / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")
    assert re.search(rf"^## v{re.escape(version)}\b", changelog, re.MULTILINE), (
        f"docs/CHANGELOG.md 缺少 v{version} 小节"
    )
    try:
        current_tag = subprocess.run(
            ["git", "describe", "--tags", "--exact-match"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout.strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return
    if current_tag:
        assert current_tag == f"v{version}", (
            f"当前 HEAD 位于 tag {current_tag}，但提交信息声明 v{version}"
        )


def test_main_changelog_single_version_line() -> None:
    """主 CHANGELOG 只保留 1.x 版本线，3.x/2.x 标题不得回潮。"""
    changelog = (ROOT / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")
    headings = re.findall(r"^## v(\d+)\.", changelog, re.MULTILINE)
    assert headings and all(
        major == "1" for major in headings
    ), f"主 CHANGELOG 出现非 1.x 版本标题：{headings}"


def test_archived_v3_changelog_complete() -> None:
    archive = ROOT / "docs" / "archive" / "CHANGELOG_v3.md"
    assert archive.exists()
    text = archive.read_text(encoding="utf-8")
    for version in ("3.6.0", "3.5.0", "3.4.0", "3.3.0", "3.2.0", "3.1.0", "3.0.0"):
        assert f"## v{version}" in text, f"归档缺少 v{version} 小节"
    assert "CHANGELOG_v2.md" in text


def test_release_notes_extraction_matches_v1_only() -> None:
    """模拟 release.yml 的 awk：v1.0.0 小节不应包含归档说明。"""
    changelog = (ROOT / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")
    in_section = False
    lines: list[str] = []
    for line in changelog.splitlines():
        if line.startswith("## "):
            if in_section:
                break
            if line.startswith("## v1.0.0"):
                in_section = True
                lines.append(line)
            continue
        if in_section:
            lines.append(line)
    body = "\n".join(lines)
    assert body.startswith("## v1.0.0")
    assert "历史归档" not in body
    assert "## v3.6.0" not in body
