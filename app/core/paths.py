"""运行时根目录解析：支持 pip 安装后在任意工作目录运行。"""

from __future__ import annotations

import os
from pathlib import Path

ENV_VAR = "OFBOT2_ROOT"


def _package_root() -> Path:
    """仓库/包安装根目录（app/core/paths.py 的上级三级）。"""
    return Path(__file__).resolve().parents[2]


def runtime_root() -> Path:
    """解析运行时根目录：OFBOT2_ROOT → 当前工作目录（含 config.yaml/plugins 时）→ 包根目录。"""
    env = os.environ.get(ENV_VAR, "").strip()
    if env:
        return Path(env).resolve()
    cwd = Path.cwd()
    if (cwd / "config.yaml").exists() or (cwd / "plugins").is_dir():
        return cwd
    return _package_root()
