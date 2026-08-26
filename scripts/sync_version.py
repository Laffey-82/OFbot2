"""同步框架版本号到全部出处（app/__init__.py 与 pyproject.toml）。

用法：py scripts/sync_version.py 2.140.0
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    if len(sys.argv) != 2:
        print("用法：py scripts/sync_version.py <版本号>")
        return 2
    version = sys.argv[1].strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        print(f"版本号格式无效：{version}（应为 X.Y.Z）")
        return 2

    init_py = ROOT / "app" / "__init__.py"
    text = init_py.read_text(encoding="utf-8")
    text = re.sub(
        r'__version__ = ".*"',
        f'__version__ = "{version}"',
        text,
        count=1,
    )
    init_py.write_text(text, encoding="utf-8")

    pyproject = ROOT / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    text = re.sub(
        r'^version = ".*"',
        f'version = "{version}"',
        text,
        count=1,
        flags=re.MULTILINE,
    )
    pyproject.write_text(text, encoding="utf-8")

    print(f"已同步版本号：{version}")
    print("提示：请在 docs/CHANGELOG.md 顶部补充对应条目。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
