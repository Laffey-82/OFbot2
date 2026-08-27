from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.db.base import get_engine, init_db, reset_db_engine
from app.services.workflow import WorkflowEngine
from app.services.workflow_templates import (
    BUILTIN_TEMPLATES,
    WorkflowTemplateService,
)


@pytest.mark.asyncio
async def test_workflow_dry_run_valid_and_invalid() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        url = f"sqlite+aiosqlite:///{Path(tmp_dir).as_posix()}/test.db"
        reset_db_engine()
        engine = get_engine(url)
        await init_db(url)
        workflow_engine = WorkflowEngine()

        async def echo(context, **kwargs):
            return kwargs.get("text", "")

        workflow_engine.register_action("echo", echo)
        created = await workflow_engine.create(
            "demo",
            {
                "trigger": {"type": "message"},
                "condition": {"field": "message", "op": "contains", "value": "hi"},
                "steps": [{"action": "echo", "params": {"text": "hi"}}],
            },
        )
        report = await workflow_engine.dry_run(created.id, {"message": "hello hi"})
        assert report["valid"] is True
        assert report["condition_matched"] is True
        assert report["would_run_steps"] == 1

        bad = await workflow_engine.create(
            "bad",
            {
                "trigger": {"type": "schedule"},
                "steps": [{"action": "missing_action", "params": {}}],
            },
        )
        report = await workflow_engine.dry_run(bad.id)
        assert report["valid"] is False
        assert any("missing_action" in error for error in report["errors"])
        assert any("cron" in error for error in report["errors"])

        await engine.dispose()
        reset_db_engine()


@pytest.mark.asyncio
async def test_workflow_step_timing_recorded() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        url = f"sqlite+aiosqlite:///{Path(tmp_dir).as_posix()}/test.db"
        reset_db_engine()
        engine = get_engine(url)
        await init_db(url)
        workflow_engine = WorkflowEngine()

        async def echo(context, **kwargs):
            return "ok"

        workflow_engine.register_action("echo", echo)
        created = await workflow_engine.create(
            "timing", {"steps": [{"action": "echo", "params": {}}]}
        )
        run = await workflow_engine.execute(created.id)
        assert run.status == "succeeded"
        step = run.result["steps"][0]
        assert "elapsed_ms" in step
        assert step["elapsed_ms"] >= 0
        fetched = await workflow_engine.get_run(run.id)
        assert fetched is not None and fetched.status == "succeeded"
        await engine.dispose()
        reset_db_engine()


def test_workflow_templates_builtin() -> None:
    service = WorkflowTemplateService()
    templates = service.list_templates()
    assert len(templates) >= 4
    assert service.get_template("message_reply") is not None
    assert service.get_template("missing") is None


@pytest.mark.asyncio
async def test_workflow_template_import() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        url = f"sqlite+aiosqlite:///{Path(tmp_dir).as_posix()}/test.db"
        reset_db_engine()
        engine = get_engine(url)
        await init_db(url)
        workflow_engine = WorkflowEngine()
        service = WorkflowTemplateService()
        workflow = await service.import_template(
            workflow_engine, "message_reply"
        )
        assert workflow.name.endswith("（导入）")
        assert workflow.definition["trigger"]["type"] == "message"
        await engine.dispose()
        reset_db_engine()


def test_builtin_templates_have_required_fields() -> None:
    for template in BUILTIN_TEMPLATES:
        assert template["id"]
        assert template["name"]
        assert isinstance(template["definition"], dict)
        assert "steps" in template["definition"]
