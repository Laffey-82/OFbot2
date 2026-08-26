from __future__ import annotations

import tempfile
from pathlib import Path

import httpx
import pytest

from app.core.bus import get_bus, reset_bus
from app.core.capabilities import Capability, CapabilityRegistry
from app.db.base import get_engine, init_db, reset_db_engine, session_factory
from app.services.aggregation import AggregationService
from app.services.ai import AIService, MockAIProvider, OpenAIChatProvider
from app.services.alerts import AlertService
from app.services.records import (
    FieldSchema,
    RecordService,
    RecordTypeSchema,
    SchemaRegistry,
)
from app.services.state_machine import StateMachine, StateMachineService, Transition
from app.services.webhook import WebhookService
from app.services.workflow import WorkflowEngine


def test_capability_registry() -> None:
    registry = CapabilityRegistry()
    registry.register(Capability(name="records", methods=["create"]))
    assert registry.has("records")
    assert registry.require(["records", "missing"]) == ["missing"]


def test_aggregation_service() -> None:
    service = AggregationService()
    rows = [{"type": "a", "amount": 1}, {"type": "a", "amount": 2}, {"type": "b", "amount": 3}]
    grouped = service.group_by(rows, "type")
    assert len(grouped["a"]) == 2
    assert service.sum(rows, "amount") == 6
    assert service.count(rows) == 3
    assert service.avg(rows, "amount") == 2


def test_state_machine_transition() -> None:
    machine = StateMachine("order", initial="pending")
    machine.add(Transition("pending", "done"))
    service = StateMachineService()
    service.register(machine)
    assert service.transition("order", "pending", "done") == "done"
    with pytest.raises(ValueError):
        service.transition("order", "done", "pending")


@pytest.mark.asyncio
async def test_alert_service() -> None:
    service = AlertService()
    service.add_rule("adapter-down", event="adapter_disconnected")
    notified: list[str] = []

    async def notifier(rule, detail: str) -> None:
        notified.append(rule.name)

    service.set_notifier(notifier)
    triggered = await service.check("adapter_disconnected", "onebot")
    assert triggered[0].name == "adapter-down"
    assert notified == ["adapter-down"]
    assert service.remove_rule("adapter-down") is True


def test_webhook_service_remove() -> None:
    service = WebhookService()
    service.register("default")
    assert service.remove("default") is True
    assert service.remove("missing") is False


@pytest.mark.asyncio
async def test_ai_service_mock() -> None:
    service = AIService()
    service.register(MockAIProvider())
    result = await service.chat([{"role": "user", "content": "hello"}])
    assert "hello" in result


@pytest.mark.asyncio
async def test_openai_provider_chat() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}}]},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAIChatProvider(
        base_url="https://example.com/v1",
        api_key="test",
        model="gpt",
        client=client,
    )
    result = await provider.chat([{"role": "user", "content": "hi"}])
    assert result == "ok"
    await client.aclose()


@pytest.mark.asyncio
async def test_record_service_with_schema() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        url = f"sqlite+aiosqlite:///{Path(tmp_dir).as_posix()}/test.db"
        reset_db_engine()
        engine = get_engine(url)
        await init_db(url)
        schemas = SchemaRegistry()
        schemas.register(
            RecordTypeSchema(
                "note",
                [FieldSchema("title", required=True), FieldSchema("content", default="")],
            )
        )
        service = RecordService(schemas)
        record = await service.create("note", {"title": "hello"})
        assert record.data["title"] == "hello"
        records = await service.list("note")
        assert len(records) == 1
        await engine.dispose()
        reset_db_engine()
        try:
            await get_bus().stop(clear=True)
        except Exception:
            pass
        reset_bus()


@pytest.mark.asyncio
async def test_workflow_engine_executes_actions() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        url = f"sqlite+aiosqlite:///{Path(tmp_dir).as_posix()}/test.db"
        reset_db_engine()
        engine = get_engine(url)
        await init_db(url)
        workflow = WorkflowEngine()
        calls: list[str] = []

        async def action(context, **kwargs):
            calls.append(kwargs.get("text", ""))
            return "ok"

        workflow.register_action("echo", action)
        created = await workflow.create(
            "demo", {"steps": [{"action": "echo", "params": {"text": "hi"}}]}
        )
        run = await workflow.execute(created.id)
        assert run.status == "succeeded"
        assert calls == ["hi"]
        await engine.dispose()
        reset_db_engine()


@pytest.mark.asyncio
async def test_workflow_engine_condition() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        url = f"sqlite+aiosqlite:///{Path(tmp_dir).as_posix()}/test.db"
        reset_db_engine()
        engine = get_engine(url)
        await init_db(url)
        workflow = WorkflowEngine()
        calls: list[str] = []

        async def action(context, **kwargs):
            calls.append(kwargs.get("text", ""))
            return "ok"

        workflow.register_action("echo", action)
        matched = await workflow.create(
            "matched",
            {
                "condition": [
                    {"field": "message", "op": "contains", "value": "签到"}
                ],
                "steps": [{"action": "echo", "params": {"text": "hi"}}],
            },
        )
        run = await workflow.execute(matched.id, {"message": "我要签到"})
        assert run.status == "succeeded"
        assert calls == ["hi"]

        skipped = await workflow.create(
            "skipped",
            {
                "condition": [
                    {"field": "message", "op": "contains", "value": "签到"}
                ],
                "steps": [{"action": "echo", "params": {"text": "hi"}}],
            },
        )
        run = await workflow.execute(skipped.id, {"message": "普通消息"})
        assert run.status == "skipped"
        assert calls == ["hi"]
        assert run.result.get("reason") == "condition not matched"

        any_mode = await workflow.create(
            "any-mode",
            {
                "condition": {
                    "match": "any",
                    "conditions": [
                        {"field": "message", "op": "contains", "value": "签到"},
                        {"field": "message", "op": "contains", "value": "打卡"},
                    ],
                },
                "steps": [{"action": "echo", "params": {"text": "hi"}}],
            },
        )
        run = await workflow.execute(any_mode.id, {"message": "今天打卡"})
        assert run.status == "succeeded"
        assert calls == ["hi", "hi"]

        await engine.dispose()
        reset_db_engine()


@pytest.mark.asyncio
async def test_workflow_engine_trigger() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        url = f"sqlite+aiosqlite:///{Path(tmp_dir).as_posix()}/test.db"
        reset_db_engine()
        engine = get_engine(url)
        await init_db(url)
        workflow = WorkflowEngine()

        async def action(context, **kwargs):
            return "ok"

        workflow.register_action("echo", action)
        await workflow.create(
            "webhook-flow",
            {
                "trigger": {"type": "webhook"},
                "steps": [{"action": "echo", "params": {"text": "hi"}}],
            },
        )
        runs = await workflow.trigger("webhook", {"payload": {}})
        assert len(runs) == 1
        assert runs[0].status == "succeeded"
        await engine.dispose()
        reset_db_engine()


@pytest.mark.asyncio
async def test_workflow_failure_dispatches_event() -> None:
    """流程运行失败应派发 WorkflowRunFailed 事件（告警互联基础）。"""
    from app.core.bus import get_bus, reset_bus
    from app.core.events import WorkflowRunFailed
    from app.core.subscriptions import EventSubscriptionRegistry

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        url = f"sqlite+aiosqlite:///{Path(tmp_dir).as_posix()}/test.db"
        reset_db_engine()
        engine = get_engine(url)
        await init_db(url)
        workflow = WorkflowEngine()
        wf = await workflow.create(
            "bad-flow",
            {"steps": [{"action": "missing_action"}]},
        )
        received: list[WorkflowRunFailed] = []
        registry = EventSubscriptionRegistry()
        registry.subscribe(
            WorkflowRunFailed,
            lambda event: received.append(event),
            plugin_name="test",
        )
        run = await workflow.execute(wf.id)
        assert run.status == "failed"
        assert received and received[0].workflow_name == "bad-flow"
        assert received[0].run_id == run.id
        await engine.dispose()
        reset_db_engine()
        await get_bus().stop(clear=True)
        reset_bus()


@pytest.mark.asyncio
async def test_workflow_auto_disabled_after_consecutive_failures() -> None:
    """流程连续失败达到阈值自动停用，且触发器跳过停用流程。"""
    from app.core.bus import get_bus, reset_bus
    from app.core.events import WorkflowAutoDisabled
    from app.core.subscriptions import EventSubscriptionRegistry

    try:
        await get_bus().stop(clear=True)
    except Exception:
        pass
    reset_bus()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        url = f"sqlite+aiosqlite:///{Path(tmp_dir).as_posix()}/test.db"
        reset_db_engine()
        engine = get_engine(url)
        await init_db(url)
        workflow = WorkflowEngine(auto_disable_after_failures=2)

        async def bad_action(context, **kwargs):
            raise ValueError("boom")

        workflow.register_action("bad", bad_action)
        received: list[WorkflowAutoDisabled] = []
        registry = EventSubscriptionRegistry()
        registry.subscribe(
            WorkflowAutoDisabled,
            lambda event: received.append(event),
            plugin_name="test",
        )
        wf = await workflow.create(
            "flaky-flow",
            {
                "trigger": {"type": "webhook"},
                "steps": [{"action": "bad"}],
            },
        )
        run1 = await workflow.execute(wf.id)
        run2 = await workflow.execute(wf.id)
        assert run1.status == "failed"
        assert run2.status == "failed"

        from app.db.models import Workflow

        async with session_factory()() as session:
            stored = await session.get(Workflow, wf.id)
            assert stored is not None
            assert stored.enabled is False
            assert stored.definition.get("auto_disabled") is not None
            cycles = stored.definition.get("self_heal_cycles") or []
            assert len(cycles) == 1
            assert cycles[0]["disabled"] is not None
            assert cycles[0]["reenabled"] is None
        assert received and received[0].workflow_name == "flaky-flow"

        # 触发器应跳过已停用流程
        runs = await workflow.trigger("webhook", {})
        assert runs == []

        await engine.dispose()
        reset_db_engine()
        await get_bus().stop(clear=True)
        reset_bus()
