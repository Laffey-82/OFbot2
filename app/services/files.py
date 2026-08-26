from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.logger import get_logger

logger = get_logger(__name__)


class FileService:
    def __init__(self, base_dir: str | Path, *, max_size: int = 50 * 1024 * 1024) -> None:
        self.base_dir = Path(base_dir).resolve()
        self.max_size = max_size
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def resolve(self, relative_path: str) -> Path:
        root = self.base_dir
        path = (root / relative_path).resolve()
        if not path.is_relative_to(root):
            raise ValueError("path escapes base directory")
        return path

    def save_bytes(self, data: bytes, *, suffix: str = "", subdir: str = "uploads") -> Path:
        if len(data) > self.max_size:
            raise ValueError("file too large")
        target_dir = self.base_dir / subdir
        target_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(data).hexdigest()
        path = target_dir / f"{digest}{suffix}"
        if not path.exists():
            path.write_bytes(data)
        return path

    def copy_file(self, source: str | Path, *, subdir: str = "imports") -> Path:
        source_path = Path(source).resolve()
        target = self.base_dir / subdir / f"{uuid4().hex}_{source_path.name}"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target)
        return target

    def list_files(self) -> list[dict[str, Any]]:
        files = []
        for path in self.base_dir.rglob("*"):
            if path.is_file():
                files.append(
                    {
                        "name": path.relative_to(self.base_dir).as_posix(),
                        "path": str(path),
                        "size": path.stat().st_size,
                        "modified": path.stat().st_mtime,
                    }
                )
        return sorted(files, key=lambda item: item["path"])

    def delete_file(self, relative_path: str) -> bool:
        path = self.resolve(relative_path)
        if not path.exists():
            return False
        path.unlink()
        return True
