from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.logger import get_logger

logger = get_logger(__name__)


class BackupService:
    def __init__(self, backup_dir: str | Path, *, keep: int = 10) -> None:
        self.backup_dir = Path(backup_dir)
        self.keep = keep
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def create_backup(self, *sources: str | Path) -> Path:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        target = self.backup_dir / stamp
        counter = 1
        while target.exists():
            target = self.backup_dir / f"{stamp}_{counter}"
            counter += 1
        target.mkdir(parents=True, exist_ok=False)
        for source in sources:
            source_path = Path(source)
            if source_path.is_dir():
                shutil.copytree(source_path, target / source_path.name)
            elif source_path.exists():
                shutil.copy2(source_path, target / source_path.name)
        self._prune()
        return target

    def list_backups(self) -> list[dict[str, Any]]:
        items = []
        for path in sorted(self.backup_dir.iterdir(), reverse=True):
            if path.is_dir():
                files = [
                    file.relative_to(path).as_posix()
                    for file in path.rglob("*")
                    if file.is_file()
                ]
                total_size = sum(
                    (path / file).stat().st_size for file in files
                )
                items.append(
                    {
                        "name": path.name,
                        "path": str(path),
                        "created_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
                        "size": total_size,
                        "files": files,
                    }
                )
        return items

    def resolve_backup(self, name: str) -> Path:
        """解析备份目录并校验，防止路径穿越。"""
        target = (self.backup_dir / name).resolve()
        base = self.backup_dir.resolve()
        if not target.is_dir() or not str(target).startswith(str(base)):
            raise ValueError("invalid backup name")
        return target

    def resolve_file(self, name: str, relative_path: str) -> Path:
        base = self.resolve_backup(name)
        target = (base / relative_path).resolve()
        if not str(target).startswith(str(base)):
            raise ValueError("path escapes backup")
        return target

    def delete_backup(self, name: str) -> bool:
        target = self.resolve_backup(name)
        shutil.rmtree(target)
        return True

    def restore(
        self, name: str, targets: dict[str, str | Path]
    ) -> dict[str, str]:
        """从备份恢复文件到目标路径，返回每个备份文件的处理结果。"""
        source = self.resolve_backup(name)
        results: dict[str, str] = {}
        for backup_file, dest in targets.items():
            src = source / backup_file
            dest_path = Path(dest)
            if not src.exists():
                results[backup_file] = "备份中不存在"
                continue
            staging = dest_path.with_name(dest_path.name + ".restored")
            shutil.copy2(src, staging)
            try:
                os.replace(staging, dest_path)
                results[backup_file] = "已恢复"
            except OSError as exc:
                results[backup_file] = (
                    f"目标文件被占用，已暂存为 {staging.name}"
                    f"（{exc.strerror or exc}）"
                )
        return results

    def compare(self, name_a: str, name_b: str) -> dict[str, Any]:
        """对比两个备份的文件清单与大小差异。"""
        a = self.resolve_backup(name_a)
        b = self.resolve_backup(name_b)
        files_a = {
            file.relative_to(a).as_posix(): file.stat().st_size
            for file in a.rglob("*")
            if file.is_file()
        }
        files_b = {
            file.relative_to(b).as_posix(): file.stat().st_size
            for file in b.rglob("*")
            if file.is_file()
        }
        changed = sorted(
            name
            for name in set(files_a) & set(files_b)
            if files_a[name] != files_b[name]
        )
        return {
            "only_in_a": sorted(set(files_a) - set(files_b)),
            "only_in_b": sorted(set(files_b) - set(files_a)),
            "changed": changed,
            "size_deltas": {
                name: files_b[name] - files_a[name] for name in changed
            },
        }

    def _prune(self) -> None:
        dirs = sorted(
            [path for path in self.backup_dir.iterdir() if path.is_dir()],
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for path in dirs[self.keep :]:
            shutil.rmtree(path)
