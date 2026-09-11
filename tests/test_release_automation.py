from __future__ import annotations

from pathlib import Path

import pytest

from scripts import check_release, release


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _seed_repo(tmp_path: Path, version: str, changelog: str) -> None:
    _write(tmp_path / "app" / "__init__.py", f'__version__ = "{version}"\n')
    _write(
        tmp_path / "pyproject.toml",
        '[project]\nversion = "' + version + '"\n',
    )
    _write(tmp_path / "docs" / "CHANGELOG.md", changelog)


def test_read_app_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(release, "ROOT", tmp_path)
    _write(tmp_path / "app" / "__init__.py", '__version__ = "1.6.0"\n')
    assert release.read_app_version() == "1.6.0"


def test_latest_changelog_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(release, "ROOT", tmp_path)
    _write(
        tmp_path / "docs" / "CHANGELOG.md",
        "# Changelog\n\n## v1.6.0\n\n内容\n\n## v1.5.0\n\n旧内容\n",
    )
    assert release.latest_changelog_version() == "1.6.0"


def test_extract_changelog_section(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(release, "ROOT", tmp_path)
    changelog = (
        "# Changelog\n\n"
        "## v1.6.0\n\n- 新增 A\n\n"
        "## v1.5.0\n\n- 旧内容\n"
    )
    _write(tmp_path / "docs" / "CHANGELOG.md", changelog)
    section = release.extract_changelog_section("1.6.0")
    assert section.startswith("## v1.6.0")
    assert "- 新增 A" in section
    assert "v1.5.0" not in section


def test_consistency_issues_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(release, "ROOT", tmp_path)
    _seed_repo(
        tmp_path,
        "1.6.0",
        "# Changelog\n\n## v1.6.0\n\n- 内容\n",
    )
    assert release.consistency_issues("1.6.0") == []


def test_consistency_issues_detects_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(release, "ROOT", tmp_path)
    _seed_repo(
        tmp_path,
        "1.5.0",
        "# Changelog\n\n## v1.5.0\n\n- 内容\n",
    )
    issues = release.consistency_issues("1.6.0")
    assert any("app/__init__.py" in issue for issue in issues)
    assert any("pyproject.toml" in issue for issue in issues)
    assert any("CHANGELOG" in issue for issue in issues)


def test_build_release_plan_includes_bump() -> None:
    plan = release.build_release_plan("1.6.0", bump=True)
    assert "python scripts/sync_version.py 1.6.0" in plan
    assert "git tag v1.6.0" in plan
    assert any("gh release create" in item for item in plan)


def test_build_release_plan_without_bump() -> None:
    plan = release.build_release_plan("1.6.0", bump=False)
    assert not any("sync_version.py" in item for item in plan)


def test_check_release_passes_when_consistent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(check_release, "ROOT", tmp_path)
    _write(tmp_path / "app" / "__init__.py", '__version__ = "1.6.0"\n')
    _write(
        tmp_path / "pyproject.toml",
        '[project]\nversion = "1.6.0"\n',
    )
    _write(
        tmp_path / "docs" / "CHANGELOG.md",
        "# Changelog\n\n## v1.6.0\n\n- 内容\n",
    )
    monkeypatch.setattr(
        check_release, "_latest_commit_message", lambda: "feat: v1.6.0 发布"
    )
    assert check_release.main() == 0


def test_check_release_detects_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(check_release, "ROOT", tmp_path)
    _write(tmp_path / "app" / "__init__.py", '__version__ = "1.5.0"\n')
    _write(
        tmp_path / "pyproject.toml",
        '[project]\nversion = "1.5.0"\n',
    )
    _write(
        tmp_path / "docs" / "CHANGELOG.md",
        "# Changelog\n\n## v1.5.0\n\n- 内容\n",
    )
    monkeypatch.setattr(
        check_release, "_latest_commit_message", lambda: "feat: v1.6.0 发布"
    )
    assert check_release.main() == 1


def test_check_release_skips_without_semver(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(check_release, "ROOT", tmp_path)
    monkeypatch.setattr(check_release, "_latest_commit_message", lambda: "docs: 更新")
    assert check_release.main() == 0
