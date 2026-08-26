from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from typing import Any

from app.core.logger import get_logger

logger = get_logger(__name__)


class MetricsRegistry:
    def __init__(self, history_size: int = 1000) -> None:
        self.counters: dict[str, float] = defaultdict(float)
        self.gauges: dict[str, float] = defaultdict(float)
        self.history: dict[str, deque[tuple[float, float]]] = defaultdict(
            lambda: deque(maxlen=history_size)
        )

    def inc(self, name: str, value: float = 1.0, labels: dict[str, str] | None = None) -> None:
        key = self._key(name, labels)
        self.counters[key] += value

    def set_gauge(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        key = self._key(name, labels)
        self.gauges[key] = value
        self.history[key].append((time.time(), value))

    def snapshot(self) -> dict[str, Any]:
        return {
            "counters": dict(self.counters),
            "gauges": dict(self.gauges),
        }

    def prometheus_text(self) -> str:
        lines: list[str] = []
        for key, value in self.counters.items():
            lines.append(f"{key} {value}")
        for key, value in self.gauges.items():
            lines.append(f"{key} {value}")
        return "\n".join(lines) + "\n"

    @staticmethod
    def _key(name: str, labels: dict[str, str] | None) -> str:
        if not labels:
            return name
        suffix = ",".join(f'{key}="{value}"' for key, value in sorted(labels.items()))
        return f"{name}{{{suffix}}}"


metrics = MetricsRegistry()


def get_system_metrics() -> dict[str, float]:
    try:
        active_tasks = len(asyncio.all_tasks())
    except RuntimeError:
        active_tasks = 0.0
    cpu_percent = 0.0
    memory_percent = 0.0
    thread_count = 0
    process_count = 0
    try:
        import psutil

        cpu_percent = psutil.cpu_percent(interval=None)
        memory_percent = psutil.virtual_memory().percent
        thread_count = psutil.Process().num_threads()
        process_count = len(psutil.process_iter())
    except Exception:
        pass
    return {
        "cpu_percent": cpu_percent,
        "memory_percent": memory_percent,
        "thread_count": thread_count,
        "process_count": process_count,
        "active_tasks": active_tasks,
        "uptime_seconds": time.monotonic(),
    }
