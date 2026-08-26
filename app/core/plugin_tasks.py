"""插件任务登记表：manifest 声明的定时任务，网页只读展示 + 启停。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class PluginTaskEntry:
    plugin: str
    task_id: str
    feature_id: str = ""
    kind: str = "interval"  # interval | cron | date
    params: dict[str, Any] = field(default_factory=dict)
    handler: Any = None
    target: str = "all"  # all | group:<id> | private:*
    description: str = ""
    enabled: bool = True
    job_id: str = ""

    @property
    def full_id(self) -> str:
        return f"{self.plugin}.{self.task_id}"


class PluginTaskRegistry:
    """内存登记表；启停通过调度器 pause/resume 即时生效，并持久化到 runtime.plugin_tasks。"""

    def __init__(self, scheduler: Any = None) -> None:
        self.scheduler = scheduler
        self._entries: dict[str, PluginTaskEntry] = {}

    def register(self, entry: PluginTaskEntry) -> None:
        self._entries[entry.full_id] = entry

    def get(self, plugin: str, task_id: str) -> PluginTaskEntry | None:
        return self._entries.get(f"{plugin}.{task_id}")

    def get_by_full_id(self, full_id: str) -> PluginTaskEntry | None:
        return self._entries.get(full_id)

    def list(self) -> list[PluginTaskEntry]:
        return sorted(
            self._entries.values(), key=lambda item: (item.plugin, item.task_id)
        )

    def list_for_plugin(self, plugin: str) -> list[PluginTaskEntry]:
        return [
            entry for entry in self.list() if entry.plugin == plugin
        ]

    def unregister_plugin(self, plugin: str) -> int:
        removed = [
            full_id
            for full_id, entry in self._entries.items()
            if entry.plugin == plugin
        ]
        for full_id in removed:
            self._entries.pop(full_id, None)
        return len(removed)

    def set_enabled(self, plugin: str, task_id: str, enabled: bool) -> bool:
        entry = self.get(plugin, task_id)
        if entry is None:
            return False
        entry.enabled = bool(enabled)
        if self.scheduler is not None and entry.job_id:
            job = self.scheduler.scheduler.get_job(entry.job_id)
            if job is not None:
                if enabled:
                    job.resume()
                else:
                    job.pause()
        return True
