from __future__ import annotations

import pytest

from app.core.scheduler import SchedulerService


def test_invalid_cron_is_rejected() -> None:
    scheduler = SchedulerService()
    with pytest.raises(ValueError):
        scheduler.add_cron_job(lambda: None, job_id="bad", cron_expression="not a cron")


def test_interval_job_is_added() -> None:
    scheduler = SchedulerService()
    scheduler.add_interval_job(lambda: None, job_id="interval", seconds=60)
    assert scheduler.scheduler.get_job("interval") is not None
    scheduler.shutdown(wait=False)

