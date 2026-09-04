from __future__ import annotations

import importlib.util
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

from app.core.logger import get_logger

logger = get_logger(__name__)


def load_migration_module(path: str | Path) -> ModuleType:
    path = Path(path)
    spec = importlib.util.spec_from_file_location(f"migration_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load migration: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MigrationRunner:
    def __init__(self) -> None:
        self._applied: set[str] = set()

    async def _load_applied(self) -> set[str]:
        """从持久化表读取已应用迁移；数据库不可用时退化为内存模式。"""
        applied = set(self._applied)
        try:
            from sqlalchemy import select

            from app.db.base import session_factory
            from app.db.models import MigrationRecord

            async with session_factory()() as session:
                rows = (
                    await session.scalars(select(MigrationRecord.name))
                ).all()
            applied.update(rows)
        except RuntimeError:
            # 引擎未初始化（如独立脚本/测试），仅内存去重
            pass
        except Exception as exc:
            logger.warning(
                "无法读取迁移记录表，按内存模式运行：%s", exc
            )
        return applied

    async def _record(self, name: str) -> None:
        try:
            from datetime import UTC, datetime

            from app.db.base import session_factory
            from app.db.models import MigrationRecord

            async with session_factory()() as session:
                session.add(
                    MigrationRecord(
                        name=name,
                        applied_at=datetime.now(UTC),
                    )
                )
                await session.commit()
        except RuntimeError:
            pass
        except Exception as exc:
            logger.warning("迁移记录写入失败：%s", exc)

    async def run(self, migration_paths: list[str]) -> None:
        persisted = await self._load_applied()
        for path in migration_paths:
            path_obj = Path(path)
            record_name = f"{path_obj.parent.name}/{path_obj.name}"
            if (
                path in self._applied
                or path in persisted
                or record_name in persisted
            ):
                self._applied.add(path)
                continue
            module = load_migration_module(path)
            upgrade: Callable | None = getattr(module, "upgrade", None)
            if upgrade is None:
                raise ValueError(f"migration {path} has no upgrade function")
            result = upgrade()
            if hasattr(result, "__await__"):
                await result
            self._applied.add(path)
            persisted.add(path)
            await self._record(record_name)
            logger.info("migration applied: %s", path)
