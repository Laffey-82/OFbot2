from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

import pytest

from app.web.helpers import safe_zip_arcname


def test_cq_unescape_entities() -> None:
    from app.adapters.onebot import OneBotAdapter

    message = OneBotAdapter._parse_cq(
        None, "[CQ:face,id=100&#44;1]文本&#93;结束"
    )
    segments = message.segments
    assert segments[0].type == "face"
    assert segments[0].data.get("id") == "100,1"
    assert segments[1].type == "text"
    assert segments[1].data.get("text") == "文本]结束"


def test_mirai_at_target_non_numeric_fallback() -> None:
    from app.adapters.mirai import MiraiAdapter
    from app.core.messages import Message, MessageSegment

    message = Message.from_segments([MessageSegment.at("abc")])
    chain = MiraiAdapter._to_chain(message)
    assert chain[0]["type"] == "At"
    assert chain[0]["target"] == 0


def test_safe_zip_arcname() -> None:
    assert safe_zip_arcname("a/b.txt") == "a/b.txt"
    assert safe_zip_arcname("..\\..\\evil.txt") == "evil.txt"
    assert safe_zip_arcname("/etc/passwd") == "etc/passwd"
    assert safe_zip_arcname("..") == "file"


def test_reverse_routes_refreshed_on_reconfigure() -> None:
    from app.adapters.base import BotClient
    from app.adapters.manager import ConnectionManager

    class Stub:
        def __init__(self, path: str) -> None:
            self.bot_id = f"adapter-{path}"
            self.reverse_path = path

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        async def handle_reverse_ws(self, websocket) -> None:
            pass

    manager = ConnectionManager()
    manager.attach(BotClient())
    manager.adopt([Stub("/onebot/v11/ws")])
    manager.collect_reverse_routes()
    assert manager.reverse_routes[0][0] == "/onebot/v11/ws"

    asyncio.run(manager.reconfigure([Stub("/onebot/v12/ws")]))
    assert manager.reverse_routes[0][0] == "/onebot/v12/ws"


@pytest.mark.asyncio
async def test_qq_official_heartbeat_single_task() -> None:
    from app.adapters.base import BotClient
    from app.adapters.qq_official import OfficialQQAdapter
    from app.core.bus import get_bus, reset_bus
    from app.core.config import ConnectionSettings

    adapter = OfficialQQAdapter(
        ConnectionSettings(
            id="qq",
            protocol="qq_official",
            app_id="1",
            token="t",
        ),
        "qq",
        BotClient(),
    )
    adapter._running = True
    await adapter._handle_raw_frame(
        json.dumps({"op": 10, "d": {"heartbeat_interval": 30000}})
    )
    first = adapter._heartbeat_task
    assert first is not None
    await adapter._handle_raw_frame(
        json.dumps({"op": 10, "d": {"heartbeat_interval": 30000}})
    )
    assert adapter._heartbeat_task is not first
    await asyncio.sleep(0.05)
    assert first.done()
    await adapter.stop()
    try:
        await get_bus().stop(clear=True)
    except Exception:
        pass
    reset_bus()


def test_file_service_resolve_rejects_traversal() -> None:
    from app.services.files import FileService

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        service = FileService(Path(tmp_dir))
        with pytest.raises(ValueError):
            service.resolve("../etc/passwd")


@pytest.mark.asyncio
async def test_scopes_add_validation() -> None:
    import re

    from httpx import ASGITransport, AsyncClient

    from app.core.config import load_settings
    from app.db.base import get_engine, init_db, reset_db_engine
    from app.web.app import create_app, ensure_default_admin

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        settings = load_settings()
        settings.config_path = str(Path(tmp_dir) / "config.yaml")
        settings.database.url = (
            f"sqlite+aiosqlite:///{(Path(tmp_dir) / 'w.db').as_posix()}"
        )
        reset_db_engine()
        engine = get_engine(settings.database.url)
        await init_db(settings.database.url)
        await ensure_default_admin(settings)
        app = create_app(settings, plugin_manager=None)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t"
        ) as client:
            await client.post(
                "/login",
                data={"username": "admin", "password": "admin"},
            )
            page = await client.get("/scopes")
            match = re.search(
                r'name="csrf_token" value="([^"]+)"', page.text
            )
            assert match
            csrf = match.group(1)
            bad = await client.post(
                "/scopes/add",
                data={"csrf_token": csrf, "group_id": "abc"},
                follow_redirects=False,
            )
            assert bad.status_code == 303
            assert "group:abc" not in settings.runtime.scopes
            good = await client.post(
                "/scopes/add",
                data={"csrf_token": csrf, "group_id": "200"},
                follow_redirects=False,
            )
            assert good.status_code == 303
            assert "group:200" in settings.runtime.scopes
        await engine.dispose()
        reset_db_engine()
