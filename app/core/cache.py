from __future__ import annotations

import time
from collections import OrderedDict
from threading import RLock
from typing import Generic, TypeVar

T = TypeVar("T")


class TTLCache(Generic[T]):
    def __init__(self, max_size: int = 1024, default_ttl: float = 300.0) -> None:
        self.max_size = max_size
        self.default_ttl = default_ttl
        self._data: OrderedDict[str, tuple[float, T]] = OrderedDict()
        self._lock = RLock()

    def get(self, key: str) -> T | None:
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            expires_at, value = item
            if expires_at <= time.monotonic():
                self._data.pop(key, None)
                return None
            self._data.move_to_end(key)
            return value

    def set(self, key: str, value: T, ttl: float | None = None) -> None:
        ttl = self.default_ttl if ttl is None else ttl
        with self._lock:
            self._data[key] = (time.monotonic() + ttl, value)
            self._data.move_to_end(key)
            self._trim()

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def _trim(self) -> None:
        now = time.monotonic()
        while len(self._data) > self.max_size:
            self._data.popitem(last=False)
        expired = [key for key, (expires_at, _) in self._data.items() if expires_at <= now]
        for key in expired:
            self._data.pop(key, None)

    def __len__(self) -> int:
        return len(self._data)

