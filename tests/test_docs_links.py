from __future__ import annotations

from pathlib import Path

from scripts.check_docs_links import (
    check,
    links_in,
    slugify_heading,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_check_passes_on_valid_tree(tmp_path) -> None:
    _write(
        tmp_path / "readme.md",
        "[快速上手](docs/QUICKSTART.md)\n"
        "[架构](docs/ARCHITECTURE.md#架构说明)\n",
    )
    _write(tmp_path / "docs/QUICKSTART.md", "# 快速上手\n正文\n")
    _write(
        tmp_path / "docs/ARCHITECTURE.md",
        "# 架构说明\n## 消息流\n正文\n",
    )
    for name in (
        "login",
        "dashboard",
        "connections",
        "scopes",
        "plugin_market",
        "workflow",
    ):
        _write(tmp_path / "docs/assets/screenshots" / f"{name}.png", "x")
    assert check(tmp_path) == []


def test_check_reports_missing_target_and_anchor(tmp_path) -> None:
    _write(
        tmp_path / "readme.md",
        "[不存在](docs/missing.md)\n"
        "[坏锚点](docs/A.md#不存在的标题)\n",
    )
    _write(tmp_path / "docs/A.md", "# 存在的标题\n")
    errors = check(tmp_path)
    assert any("docs/missing.md" in error for error in errors)
    assert any("不存在的标题" in error for error in errors)


def test_links_inside_code_fence_are_ignored(tmp_path) -> None:
    _write(
        tmp_path / "readme.md",
        "```text\n[x](docs/nope.md)\n```\n",
    )
    _write(tmp_path / "docs/a.md", "# a\n")
    for name in (
        "login",
        "dashboard",
        "connections",
        "scopes",
        "plugin_market",
        "workflow",
    ):
        _write(tmp_path / "docs/assets/screenshots" / f"{name}.png", "x")
    assert links_in(tmp_path / "readme.md") == []
    assert check(tmp_path) == []


def test_slugify_heading_handles_chinese_and_punctuation() -> None:
    assert slugify_heading("连接与协议（HTTP/WS）") == "连接与协议httpws"
    assert slugify_heading("Hello, World!") == "hello-world"
    assert slugify_heading("作用域与功能开关") == "作用域与功能开关"
