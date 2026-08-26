from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import load_settings
from app.db.base import get_engine, init_db, reset_db_engine
from app.web.app import create_app


@pytest.mark.asyncio
async def test_api_records_and_tasks_pagination() -> None:
    """REST 列表接口支持 limit/offset 分页并返回 total。"""
    from app.core.bus import get_bus, reset_bus

    try:
        await get_bus().stop(clear=True)
    except Exception:
        pass
    reset_bus()
    from app.db.base import session_factory
    from app.db.models import Task
    from app.services.records import (
        FieldSchema,
        RecordService,
        RecordTypeSchema,
        SchemaRegistry,
    )

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = Path(tmp_dir) / "api.db"
        settings = load_settings()
        settings.config_path = str(Path(tmp_dir) / "config.yaml")
        settings.database.url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
        settings.web.api_keys = ["test-key"]
        reset_db_engine()
        engine = get_engine(settings.database.url)
        await init_db(settings.database.url)

        schemas = SchemaRegistry()
        schemas.register(
            RecordTypeSchema(
                "order", [FieldSchema("title", "string", True)]
            )
        )
        records = RecordService(schemas)
        async with session_factory()() as session:
            for i in range(3):
                session.add(
                    Task(
                        task_id=f"t{i}",
                        name=f"task-{i}",
                        type="interval",
                        interval_seconds=60,
                        params={},
                        enabled=True,
                    )
                )
            await session.commit()
        for i in range(3):
            await records.create("order", {"title": f"rec-{i}"})

        app = create_app(settings, plugin_manager=None)
        app.state.services["records"] = records
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            headers = {"x-api-key": "test-key"}
            response = await client.get(
                "/api/v1/records?limit=1&offset=1",
                headers=headers,
            )
            assert response.status_code == 200
            body = response.json()
            assert body["total"] == 3
            assert body["limit"] == 1
            assert body["offset"] == 1
            assert len(body["records"]) == 1
            assert body["records"][0]["data"]["title"] == "rec-1"

            response = await client.get(
                "/api/v1/tasks?limit=2&offset=1",
                headers=headers,
            )
            assert response.status_code == 200
            body = response.json()
            assert body["total"] == 3
            assert len(body["tasks"]) == 2
            assert body["tasks"][0]["task_id"] == "t1"

        await engine.dispose()
        reset_db_engine()
        try:
            await get_bus().stop(clear=True)
        except Exception:
            pass
        reset_bus()


@pytest.mark.asyncio
async def test_backup_api_with_service() -> None:
    app = create_app(load_settings())

    class FakeBackup:
        def list_backups(self) -> list[dict[str, str]]:
            return [{"name": "backup-1", "path": "/tmp/backup-1"}]

    app.state.services = {"backup": FakeBackup()}
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/backups")
        assert response.status_code == 200
        assert response.json()["backups"][0]["name"] == "backup-1"

        response = await client.get("/api/v1/status")
        assert response.status_code == 200
        assert "adapters" in response.json()


@pytest.mark.asyncio
async def test_plugin_install_api() -> None:
    app = create_app(load_settings())

    class FakeInstaller:
        def install_zip(self, path: Path) -> Path:
            assert path.exists()
            return path.parent / "installed"

    app.state.services = {"installer": FakeInstaller()}
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/plugins/install",
            files={"file": ("plugin.zip", b"zip-bytes", "application/zip")},
        )
        assert response.status_code == 200
        assert response.json()["installed"] == "installed"


@pytest.mark.asyncio
async def test_read_only_api_endpoints() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        url = f"sqlite+aiosqlite:///{Path(tmp_dir).as_posix()}/test.db"
        reset_db_engine()
        engine = get_engine(url)
        await init_db(url)
        app = create_app(load_settings())
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            for path in [
                "/api/v1/capabilities",
                "/api/v1/workflows",
                "/api/v1/records",
                "/api/v1/webhooks",
                "/api/v1/alerts",
                "/api/v1/state-machines",
            ]:
                response = await client.get(path)
                assert response.status_code == 200
        await engine.dispose()
        reset_db_engine()
