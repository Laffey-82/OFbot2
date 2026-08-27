from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any


def preset_data_path(name: str) -> Path:
    root = Path(__file__).resolve().parents[2]
    path = root / "data" / "presets" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def now() -> datetime:
    return datetime.now()


def paginate(items: list[Any], page: int = 1, page_size: int = 10) -> tuple[list[Any], int, int]:
    total = len(items)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))
    start = (page - 1) * page_size
    return items[start : start + page_size], total_pages, total


def render_card(title: str, lines: Iterable[str]) -> str:
    body = "\n".join(lines)
    return f"{title}\n{'-' * 18}\n{body}"


def split_message(text: str, limit: int = 1800) -> list[str]:
    """长消息按 1800 字符阈值分片，优先在换行处切分，避免截断。"""
    text = str(text or "")
    limit = max(200, int(limit))
    if len(text) <= limit:
        return [text] if text else []
    chunks: list[str] = []
    remainder = text
    while len(remainder) > limit:
        head = remainder[:limit]
        cut = head.rfind("\n")
        if cut <= limit // 2:
            cut = head.rfind(" ")
        if cut <= limit // 2:
            cut = limit
        else:
            cut += 1
        chunks.append(remainder[:cut].rstrip())
        remainder = remainder[cut:].lstrip()
    if remainder:
        chunks.append(remainder)
    return chunks


def format_money(value: float) -> str:
    return f"¥{value:.2f}"


class JsonStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = asyncio.Lock()
        self._data: dict[str, Any] = {}

    async def load(self) -> dict[str, Any]:
        async with self._lock:
            if not self.path.exists():
                self._data = {}
                return self._data
            self._data = await asyncio.to_thread(
                json.loads, self.path.read_text(encoding="utf-8")
            )
            return self._data

    async def save(self) -> None:
        async with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(
                self.path.write_text,
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    async def get(self, key: str, default: Any = None) -> Any:
        data = await self.load()
        return data.get(key, default)

    async def set(self, key: str, value: Any) -> None:
        data = await self.load()
        data[key] = value
        await self.save()

    async def append(self, key: str, value: Any) -> None:
        data = await self.load()
        data.setdefault(key, []).append(value)
        await self.save()
