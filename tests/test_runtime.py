from __future__ import annotations

from typing import Any

import pytest

from app.adapters.base import BotClient
from app.core.config import ConnectionSettings, load_settings
from app.runtime import (
    auto_reenable_disabled,
    build_adapters,
    build_ai_service,
    infer_field_type,
    prune_audit_logs,
)


def test_infer_field_type() -> None:
    assert infer_field_type(True) == "boolean"
    assert infer_field_type(3) == "integer"
    assert infer_field_type(1.5) == "number"
    assert infer_field_type("x") == "string"
    assert infer_field_type(None) == "string"


@pytest.mark.asyncio
async def test_prune_audit_logs() -> None:
    """超过保留期的审计日志被清理，未超期保留；retention_days<=0 不清理。"""
    import tempfile
    from datetime import UTC, datetime, timedelta
    from pathlib import Path

    from sqlalchemy import select

    from app.db.base import get_engine, init_db, reset_db_engine, session_factory
    from app.db.models import AuditLog

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        url = f"sqlite+aiosqlite:///{Path(tmp_dir).as_posix()}/test.db"
        await reset_db_engine()
        engine = get_engine(url)
        await init_db(url)
        async with session_factory()() as session:
            session.add(
                AuditLog(
                    action="old",
                    actor="a",
                    timestamp=datetime.now(UTC) - timedelta(days=40),
                )
            )
            session.add(
                AuditLog(
                    action="new",
                    actor="a",
                    timestamp=datetime.now(UTC),
                )
            )
            await session.commit()

        deleted = await prune_audit_logs(retention_days=30)
        assert deleted == 1
        async with session_factory()() as session:
            remaining = (await session.scalars(select(AuditLog))).all()
            assert [item.action for item in remaining] == ["new"]

        assert await prune_audit_logs(retention_days=0) == 0

        await engine.dispose()
        await reset_db_engine()


@pytest.mark.asyncio
async def test_auto_reenable_disabled_with_cooldown() -> None:
    """超过冷却期的自动停用任务/流程被重新启用，未到期的保留停用。"""
    import tempfile
    from datetime import UTC, datetime, timedelta
    from pathlib import Path

    from sqlalchemy import select

    from app.core.bus import get_bus, reset_bus
    from app.core.events import TaskAutoReenabled, WorkflowAutoReenabled
    from app.core.subscriptions import EventSubscriptionRegistry
    from app.db.base import get_engine, init_db, reset_db_engine, session_factory
    from app.db.models import Task, Workflow

    try:
        await get_bus().stop(clear=True)
    except Exception:
        pass
    await reset_bus()
    received: list[Any] = []
    registry = EventSubscriptionRegistry()
    registry.subscribe(
        TaskAutoReenabled,
        lambda event: received.append(event),
        plugin_name="test",
    )
    registry.subscribe(
        WorkflowAutoReenabled,
        lambda event: received.append(event),
        plugin_name="test",
    )

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        url = f"sqlite+aiosqlite:///{Path(tmp_dir).as_posix()}/test.db"
        await reset_db_engine()
        engine = get_engine(url)
        await init_db(url)
        old = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        recent = datetime.now(UTC).isoformat()
        async with session_factory()() as session:
            session.add(
                Task(
                    task_id="old_task",
                    name="old",
                    type="interval",
                    interval_seconds=60,
                    params={
                        "auto_disabled": old,
                        "self_heal_cycles": [
                            {"disabled": old, "reenabled": None}
                        ],
                    },
                    enabled=False,
                )
            )
            session.add(
                Task(
                    task_id="recent_task",
                    name="recent",
                    type="interval",
                    interval_seconds=60,
                    params={"auto_disabled": recent},
                    enabled=False,
                )
            )
            session.add(
                Workflow(
                    name="old_flow",
                    definition={
                        "auto_disabled": {
                            "reason": "x",
                            "at": old,
                        },
                        "self_heal_cycles": [
                            {"disabled": old, "reenabled": None}
                        ],
                    },
                    enabled=False,
                )
            )
            await session.commit()

        result = await auto_reenable_disabled(threshold_seconds=3600)
        assert result == {"tasks": 1, "workflows": 1}
        async with session_factory()() as session:
            old_task = await session.scalar(
                select(Task).where(Task.task_id == "old_task")
            )
            recent_task = await session.scalar(
                select(Task).where(Task.task_id == "recent_task")
            )
            old_flow = await session.scalar(
                select(Workflow).where(Workflow.name == "old_flow")
            )
            assert old_task is not None and old_task.enabled is True
            assert "auto_disabled" not in old_task.params
            assert (
                old_task.params.get("self_heal_cycles", [{}])[-1][
                    "reenabled"
                ]
                is not None
            )
            assert recent_task is not None and recent_task.enabled is False
        assert old_flow is not None and old_flow.enabled is True
        assert "auto_disabled" not in old_flow.definition
        assert (
            old_flow.definition.get("self_heal_cycles", [{}])[-1][
                "reenabled"
            ]
            is not None
        )
        assert any(isinstance(item, TaskAutoReenabled) for item in received)
        assert any(
            isinstance(item, WorkflowAutoReenabled) for item in received
        )

        await engine.dispose()
        await reset_db_engine()
        await get_bus().stop(clear=True)
        await reset_bus()


def test_build_ai_service_defaults_to_mock() -> None:
    settings = load_settings()
    settings.plugin_configs["ai"] = {}
    service = build_ai_service(settings)
    assert set(service.providers) == {"mock"}
    assert service.active_provider == "mock"


def test_build_ai_service_registers_openai() -> None:
    settings = load_settings()
    settings.plugin_configs["ai"] = {"openai": {"api_key": "sk-test"}}
    service = build_ai_service(settings)
    assert "openai" in service.providers
    assert service.active_provider == "openai"


def test_build_adapters_skips_red_without_token() -> None:
    settings = load_settings()
    settings.transport.connections = [
        ConnectionSettings(
            id="red",
            protocol="red",
            mode="forward_ws",
            token="",
        )
    ]
    bot_client = BotClient()
    adapters, reverse_routes = build_adapters(settings, bot_client)
    assert adapters == []
    assert reverse_routes == []
    assert "red" not in bot_client.adapters


def test_build_adapters_registers_red_and_onebot() -> None:
    settings = load_settings()
    settings.transport.connections = [
        ConnectionSettings(
            id="red",
            protocol="red",
            mode="forward_ws",
            token="secret",
        ),
        ConnectionSettings(
            id="onebot",
            protocol="onebot",
            version="v11",
            mode="forward_ws",
        ),
    ]
    bot_client = BotClient()
    adapters, _ = build_adapters(settings, bot_client)
    assert len(adapters) == 2
    assert "red" in bot_client.adapters
    assert "onebot" in bot_client.adapters
