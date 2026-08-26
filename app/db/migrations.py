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

    async def run(self, migration_paths: list[str]) -> None:
        for path in migration_paths:
            if path in self._applied:
                continue
            module = load_migration_module(path)
            upgrade: Callable | None = getattr(module, "upgrade", None)
            if upgrade is None:
                raise ValueError(f"migration {path} has no upgrade function")
            result = upgrade()
            if hasattr(result, "__await__"):
                await result
            self._applied.add(path)
            logger.info("migration applied: %s", path)

