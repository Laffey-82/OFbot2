from __future__ import annotations

from collections.abc import Callable

from app.core.logger import get_logger

logger = get_logger(__name__)


class GroupWhitelistService:
    def __init__(
        self,
        groups: list[str] | None = None,
        on_change: Callable[[list[str]], None] | None = None,
    ) -> None:
        self._groups = {str(group) for group in (groups or [])}
        self._on_change = on_change

    def contains(self, group_id: str) -> bool:
        if not self._groups:
            return True
        return str(group_id) in self._groups

    def add(self, group_id: str) -> bool:
        group_id = str(group_id)
        if group_id in self._groups:
            return False
        self._groups.add(group_id)
        self._notify()
        return True

    def remove(self, group_id: str) -> bool:
        group_id = str(group_id)
        if group_id not in self._groups:
            return False
        self._groups.remove(group_id)
        self._notify()
        return True

    def list(self) -> list[str]:
        return sorted(self._groups)

    def _notify(self) -> None:
        if self._on_change is not None:
            self._on_change(self.list())
