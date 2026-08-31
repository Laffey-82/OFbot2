"""校验 readme / docs 内部相对链接、GitHub 锚点与截图资产存在性。

用法：py scripts/check_docs_links.py
任何损坏链接/锚点/缺失截图都会以非零退出码结束（CI docs-check 使用）。
"""

from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

MD_GLOB = ("readme.md", "docs/**/*.md", "docs/**/*.mdx")
SCREENSHOTS = (
    "docs/assets/screenshots/login.png",
    "docs/assets/screenshots/dashboard.png",
    "docs/assets/screenshots/connections.png",
    "docs/assets/screenshots/scopes.png",
    "docs/assets/screenshots/plugin_market.png",
    "docs/assets/screenshots/workflow.png",
)

_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+[^)]*)?\)")
_HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")


def _is_link_target(value: str) -> bool:
    lowered = value.lower()
    return lowered.startswith(("http://", "https://", "mailto:", "tel:"))


def slugify_heading(text: str) -> str:
    """近似 GitHub 的标题锚点规则（兼容中文）。"""
    text = text.strip().lower()
    # GitHub 会移除标点/特殊字符；保留字母、数字、CJK、下划线、连字符。
    chars: list[str] = []
    for ch in text:
        category = unicodedata.category(ch)
        if ch in "_-" or category.startswith(("L", "N")):
            chars.append(ch)
        elif ch.isspace():
            chars.append(" ")
    slug = re.sub(r"\s+", "-", "".join(chars)).strip("-")
    return re.sub(r"-{2,}", "-", slug)


def markdown_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for pattern in MD_GLOB:
        files.extend(
            path
            for path in root.glob(pattern)
            if path.is_file() and "_backup" not in path.parts
        )
    return sorted(set(files))


def headings(path: Path) -> set[str]:
    slugs: set[str] = set()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return slugs
    for line in text.splitlines():
        match = _HEADING_RE.match(line)
        if match:
            slugs.add(slugify_heading(match.group(1)))
    return slugs


def links_in(path: Path) -> list[tuple[int, str]]:
    """提取文件中的相对链接目标（跳过代码块）。"""
    found: list[tuple[int, str]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return found
    in_fence = False
    for lineno, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for match in _LINK_RE.finditer(line):
            target = match.group(1)
            if not _is_link_target(target):
                found.append((lineno, target))
    return found


def check(root: Path) -> list[str]:
    errors: list[str] = []
    files = markdown_files(root)
    heading_cache: dict[Path, set[str]] = {}
    for path in files:
        for lineno, target in links_in(path):
            target = target.strip()
            if target.startswith("#"):
                anchor = target[1:]
                slugs = heading_cache.setdefault(path, headings(path))
                if anchor and anchor not in slugs:
                    errors.append(
                        f"{path.relative_to(root)}:{lineno} 锚点缺失：{target}"
                    )
                continue
            file_part, _, anchor_part = target.partition("#")
            file_part = file_part.strip()
            rel = path.parent / file_part
            if file_part.startswith("/"):
                rel = root / file_part.lstrip("/")
            else:
                rel = rel.resolve()
            if not rel.exists():
                errors.append(
                    f"{path.relative_to(root)}:{lineno} 目标不存在：{target}"
                )
                continue
            if anchor_part:
                target_path = rel
                slugs = heading_cache.setdefault(target_path, headings(target_path))
                if anchor_part not in slugs:
                    errors.append(
                        f"{path.relative_to(root)}:{lineno} "
                        f"目标 {target} 的锚点缺失"
                    )
    for screenshot in SCREENSHOTS:
        if not (root / screenshot).exists():
            errors.append(f"截图资产缺失：{screenshot}")
    return errors


def main() -> int:
    errors = check(ROOT)
    if not errors:
        print(f"文档链接检查通过（{len(markdown_files(ROOT))} 个文件）")
        return 0
    print(f"发现 {len(errors)} 个问题：", file=sys.stderr)
    for error in errors:
        print(f"  - {error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
