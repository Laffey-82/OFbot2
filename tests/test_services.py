from __future__ import annotations

import json
import tempfile
from datetime import date
from pathlib import Path

import pytest

from app.core.config import load_settings
from app.db.base import get_engine, init_db, reset_db_engine, session_factory
from app.services.aggregation import AggregationService
from app.services.alerts import AlertService
from app.services.audit_service import AuditService
from app.services.backup import BackupService
from app.services.export import ExportService
from app.services.files import FileService
from app.services.state_machine import (
    StateMachine,
    StateMachineService,
    Transition,
)
from app.services.webhook import WebhookService


def test_export_services() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        exporter = ExportService(Path(tmp_dir) / "exports")
        rows = [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]

        csv_path = exporter.export_csv(rows, "data")
        assert csv_path.exists()
        json_path = exporter.export_json(rows, "data")
        assert json.loads(json_path.read_text(encoding="utf-8")) == rows
        xlsx_path = exporter.export_excel(rows, "data")
        assert xlsx_path.exists()
        docx_path = exporter.export_docx(rows, "data", title="Test")
        assert docx_path.exists()


def test_backup_and_file_services() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        root = Path(tmp_dir)
        source_dir = root / "source"
        source_dir.mkdir()
        (source_dir / "a.txt").write_text("hello", encoding="utf-8")
        backup = BackupService(root / "backups", keep=2)
        target = backup.create_backup(source_dir)
        assert (target / "source" / "a.txt").exists()
        assert backup.list_backups()

        files = FileService(root / "files")
        saved = files.save_bytes(b"x" * 10, suffix=".bin")
        assert saved.exists()
        assert saved.read_bytes() == b"x" * 10
        try:
            files.resolve("../escape.txt")
        except ValueError:
            pass
        else:
            raise AssertionError("path escape should be rejected")


def test_aggregation_filter_by_date() -> None:
    service = AggregationService()
    rows = [
        {"ts": "2026-08-01T10:00:00"},
        {"ts": "2026-08-15T10:00:00"},
        {"ts": "2026-09-01T10:00:00"},
    ]
    result = service.filter_by_date(
        rows, "ts", date(2026, 8, 1), date(2026, 8, 31)
    )
    assert len(result) == 2


def test_state_machine_permission_gating() -> None:
    machine = StateMachine("order", initial="pending")
    machine.add(Transition("pending", "paid", permission="order.pay"))
    service = StateMachineService()
    service.register(machine)
    with pytest.raises(ValueError):
        service.transition("order", "pending", "paid")
    assert (
        service.transition(
            "order", "pending", "paid", permission="order.pay"
        )
        == "paid"
    )


def test_webhook_nested_filter() -> None:
    service = WebhookService()
    service.register("nested", {"data.event": "finished", "data.user.id": 7})
    assert service.matches(
        "nested", {"data": {"event": "finished", "user": {"id": 7}}}
    )
    assert not service.matches("nested", {"data": {"event": "other"}})
    assert service.matches("no_filter", {"anything": 1})


@pytest.mark.asyncio
async def test_audit_service_persists_record() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = Path(tmp_dir) / "test.db"
        settings = load_settings()
        settings.database.url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
        await reset_db_engine()
        engine = get_engine(settings.database.url)
        await init_db(settings.database.url)

        from sqlalchemy import func, select

        from app.db.models import AuditLog

        service = AuditService()
        await service.record(
            "test.action",
            "admin",
            target="x",
            success=True,
            detail={"k": "v"},
        )
        async with session_factory()() as session:
            count = await session.scalar(
                select(func.count()).select_from(AuditLog)
            )
            assert count == 1
            row = await session.scalar(
                select(AuditLog).where(AuditLog.action == "test.action")
            )
            assert row is not None and row.actor == "admin"

        await engine.dispose()
        await reset_db_engine()


@pytest.mark.asyncio
async def test_alert_service_debounce() -> None:
    """告警通知去抖：间隔内重复触发只通知一次。"""
    service = AlertService(min_interval_seconds=3600)
    service.add_rule("debounce", event="workflow.failed")
    notified: list[str] = []

    async def notifier(rule, detail: str) -> None:
        notified.append(rule.name)

    service.set_notifier(notifier)
    await service.check("workflow.failed", "a（#1）：x")
    await service.check("workflow.failed", "a（#1）：x")
    assert len(notified) == 1

    no_debounce = AlertService(min_interval_seconds=0)
    no_debounce.add_rule("always", event="*")
    always: list[str] = []

    async def notifier2(rule, detail: str) -> None:
        always.append(rule.name)

    no_debounce.set_notifier(notifier2)
    await no_debounce.check("task.failed", "x")
    await no_debounce.check("task.failed", "x")
    assert len(always) == 2


@pytest.mark.asyncio
async def test_alert_rule_specific_debounce() -> None:
    """规则级去抖覆盖全局：仅配置间隔的规则受去抖约束。"""
    service = AlertService()
    service.add_rule("custom", event="*", min_interval_seconds=3600)
    service.add_rule("default", event="*")
    notified: list[str] = []

    async def notifier(rule, detail: str) -> None:
        notified.append(rule.name)

    service.set_notifier(notifier)
    await service.check("x", "1")
    await service.check("x", "1")
    assert notified.count("custom") == 1
    assert notified.count("default") == 2
