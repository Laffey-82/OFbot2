from __future__ import annotations

import re
import tempfile
from pathlib import Path

import pytest

from app.core.config import load_settings
from app.db.base import get_engine, init_db, reset_db_engine
from app.services.workflow import WorkflowEngine
from app.web.app import create_app, ensure_default_admin


@pytest.mark.asyncio
async def test_workflow_execute_skips_when_disabled() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        url = f"sqlite+aiosqlite:///{(Path(tmp_dir) / 'wf.db').as_posix()}"
        await reset_db_engine()
        engine = get_engine(url)
        await init_db(url)
        workflow_engine = WorkflowEngine()

        async def act(context, **kwargs):
            return "ran"

        workflow_engine.register_action("echo", act)
        created = await workflow_engine.create(
            "disabled",
            {
                "trigger": {"type": "schedule", "cron": "0 9 * * *"},
                "steps": [{"action": "echo", "params": {}}],
            },
        )
        from app.db.base import session_factory
        from app.db.models import Workflow

        async with session_factory()() as session:
            workflow = await session.get(Workflow, created.id)
            workflow.enabled = False
            await session.commit()

        run = await workflow_engine.execute(created.id)
        assert run.status == "skipped"
        assert run.result.get("reason") == "workflow disabled"
        await engine.dispose()
        await reset_db_engine()


async def _login_and_get_csrf(client, base_url: str) -> str:
    response = await client.post(
        "/login",
        data={"username": "admin", "password": "admin"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    page = await client.get("/workflows")
    assert page.status_code == 200
    match = re.search(
        r'name="csrf_token" value="([^"]+)"', page.text
    )
    assert match
    return match.group(1)


@pytest.mark.asyncio
async def test_web_workflow_create_schedule_registers_cron() -> None:
    from httpx import ASGITransport, AsyncClient

    from app.core.scheduler import SchedulerService

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        settings = load_settings()
        settings.config_path = str(Path(tmp_dir) / "config.yaml")
        settings.database.url = (
            f"sqlite+aiosqlite:///{(Path(tmp_dir) / 'w.db').as_posix()}"
        )
        await reset_db_engine()
        engine = get_engine(settings.database.url)
        await init_db(settings.database.url)
        await ensure_default_admin(settings)

        workflow_engine = WorkflowEngine()
        scheduler = SchedulerService()
        app = create_app(settings, plugin_manager=None)
        app.state.services["workflow"] = workflow_engine
        app.state.scheduler = scheduler

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t"
        ) as client:
            csrf = await _login_and_get_csrf(client, "http://t")
            response = await client.post(
                "/workflows/create",
                data={
                    "csrf_token": csrf,
                    "name": "定时播报",
                    "steps_json": '[{"action": "echo", "params": {}}]',
                    "trigger_json": '{"type": "schedule", "cron": "0 9 * * *"}',
                    "condition_json": "",
                },
                follow_redirects=False,
            )
            assert response.status_code == 303
        workflows = await workflow_engine.list()
        assert len(workflows) == 1
        assert scheduler.scheduler.get_job(f"workflow-{workflows[0].id}") is not None
        scheduler.shutdown(wait=False)
        await engine.dispose()
        await reset_db_engine()


@pytest.mark.asyncio
async def test_web_workflow_enable_registers_cron() -> None:
    from httpx import ASGITransport, AsyncClient

    from app.core.scheduler import SchedulerService

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        settings = load_settings()
        settings.config_path = str(Path(tmp_dir) / "config.yaml")
        settings.database.url = (
            f"sqlite+aiosqlite:///{(Path(tmp_dir) / 'w.db').as_posix()}"
        )
        await reset_db_engine()
        engine = get_engine(settings.database.url)
        await init_db(settings.database.url)
        await ensure_default_admin(settings)

        workflow_engine = WorkflowEngine()
        created = await workflow_engine.create(
            "offline",
            {
                "trigger": {"type": "schedule", "cron": "0 8 * * *"},
                "steps": [],
            },
        )
        from app.db.base import session_factory
        from app.db.models import Workflow

        async with session_factory()() as session:
            workflow = await session.get(Workflow, created.id)
            workflow.enabled = False
            await session.commit()

        scheduler = SchedulerService()
        app = create_app(settings, plugin_manager=None)
        app.state.services["workflow"] = workflow_engine
        app.state.scheduler = scheduler

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t"
        ) as client:
            csrf = await _login_and_get_csrf(client, "http://t")
            response = await client.post(
                f"/workflows/{created.id}/enable",
                data={"csrf_token": csrf},
                follow_redirects=False,
            )
            assert response.status_code == 303
        assert scheduler.scheduler.get_job(f"workflow-{created.id}") is not None
        scheduler.shutdown(wait=False)
        await engine.dispose()
        await reset_db_engine()


def test_apply_security_settings_rebuilds_policy() -> None:
    from app.core.commands import command_registry
    from app.core.config import Settings
    from app.web.helpers import apply_security_settings

    settings = Settings()
    settings.security.sensitive_words = ["违禁词"]
    settings.security.max_message_length = 123
    apply_security_settings(settings)
    assert command_registry.security is not None
    assert command_registry.security.validate_text("含违禁词") is not None
    assert command_registry.security.validate_text("普通文本") is None
    assert command_registry.security.max_message_length == 123
