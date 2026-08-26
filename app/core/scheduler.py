from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.logger import get_logger

logger = get_logger(__name__)


class SchedulerService:
    def __init__(
        self,
        *,
        timezone: str = "Asia/Shanghai",
        max_instances: int = 1,
        coalesce: bool = True,
    ) -> None:
        self.scheduler = AsyncIOScheduler(
            timezone=timezone,
            job_defaults={
                "coalesce": coalesce,
                "max_instances": max_instances,
                "misfire_grace_time": 30,
            },
        )
        self._plugin_jobs: dict[str, set[str]] = {}

    def start(self) -> None:
        if not self.scheduler.running:
            self.scheduler.start()

    def shutdown(self, wait: bool = False) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=wait)

    def add_interval_job(
        self,
        func: Callable[..., Any],
        *,
        job_id: str,
        seconds: int,
        plugin_name: str = "",
        **kwargs: Any,
    ) -> str:
        self._remove_if_exists(job_id)
        self.scheduler.add_job(
            func,
            trigger=IntervalTrigger(seconds=seconds),
            id=job_id,
            replace_existing=True,
            **kwargs,
        )
        self._track_plugin(plugin_name, job_id)
        return job_id

    def add_cron_job(
        self,
        func: Callable[..., Any],
        *,
        job_id: str,
        cron_expression: str,
        plugin_name: str = "",
        **kwargs: Any,
    ) -> str:
        CronTrigger.from_crontab(cron_expression)
        self._remove_if_exists(job_id)
        self.scheduler.add_job(
            func,
            trigger=CronTrigger.from_crontab(cron_expression),
            id=job_id,
            replace_existing=True,
            **kwargs,
        )
        self._track_plugin(plugin_name, job_id)
        return job_id

    def add_date_job(
        self,
        func: Callable[..., Any],
        *,
        job_id: str,
        run_date: datetime,
        plugin_name: str = "",
        **kwargs: Any,
    ) -> str:
        self._remove_if_exists(job_id)
        self.scheduler.add_job(
            func,
            trigger=DateTrigger(run_date=run_date),
            id=job_id,
            replace_existing=True,
            **kwargs,
        )
        self._track_plugin(plugin_name, job_id)
        return job_id

    def remove_job(self, job_id: str) -> bool:
        self._remove_if_exists(job_id)
        for jobs in self._plugin_jobs.values():
            jobs.discard(job_id)
        return True

    def remove_plugin_jobs(self, plugin_name: str) -> None:
        if not plugin_name:
            return
        for job_id in list(self._plugin_jobs.get(plugin_name, set())):
            self._remove_if_exists(job_id)
        self._plugin_jobs.pop(plugin_name, None)

    def _remove_if_exists(self, job_id: str) -> None:
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)

    def _track_plugin(self, plugin_name: str, job_id: str) -> None:
        if plugin_name:
            self._plugin_jobs.setdefault(plugin_name, set()).add(job_id)

