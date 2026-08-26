from __future__ import annotations

import asyncio

from app.adapters.base import BotClient
from app.adapters.mirai import MiraiAdapter
from app.adapters.onebot_v12 import OneBotV12Adapter
from app.adapters.qq_official import OfficialQQAdapter
from app.adapters.satori import SatoriAdapter
from app.core.config import ConnectionSettings, load_settings
from app.core.scopes import ScopePolicyService
from app.runtime import build_adapters


def _conn(**overrides) -> ConnectionSettings:
    data = {
        "id": "test",
        "protocol": "onebot",
        "version": "v11",
        "mode": "forward_ws",
    }
    data.update(overrides)
    return ConnectionSettings(**data)


def test_onebot_v12_parses_segments() -> None:
    adapter = OneBotV12Adapter(_conn(version="v12"), "t", BotClient())
    message = adapter._parse_segments(
        [
            {"type": "text", "data": {"text": "hi"}},
            {"type": "at", "data": {"user_id": "100"}},
            {"type": "image", "data": {"file_id": "f1"}},
        ]
    )
    assert message[0].type == "text"
    assert message[1].type == "at"
    assert message[2].type == "image"
    out = adapter._to_v12("hello")
    assert out == [{"type": "text", "data": {"text": "hello"}}]


def test_satori_parses_content() -> None:
    adapter = SatoriAdapter(_conn(protocol="satori"), "t", BotClient())
    segments = adapter._parse_content(
        [
            {"type": "text", "data": "你好"},
            {"type": "at", "data": "100"},
            {"type": "image", "data": "https://x/a.png"},
        ]
    )
    assert segments[0].type == "text"
    assert segments[1].type == "at"
    assert segments[2].type == "image"
    out = adapter._to_satori("hi")
    assert out == [{"type": "text", "data": "hi"}]


def test_mirai_parses_chain() -> None:
    adapter = MiraiAdapter(
        _conn(protocol="mirai", api_base="http://127.0.0.1:8080"),
        "t",
        BotClient(),
    )
    segments = adapter._parse_chain(
        [
            {"type": "Plain", "text": "hi"},
            {"type": "At", "target": 100},
            {"type": "Image", "imageId": "i1", "url": "u"},
        ]
    )
    assert segments[0].type == "text"
    assert segments[1].type == "at"
    assert segments[2].type == "image"
    chain = adapter._to_chain("hi")
    assert chain == [{"type": "Plain", "text": "hi"}]


def test_qq_official_strips_at_prefix() -> None:
    OfficialQQAdapter(
        _conn(protocol="qq_official", app_id="1", token="t"),
        "t",
        BotClient(),
    )
    content = "#你好"
    assert content.lstrip("#") == "你好"


def test_build_adapters_all_protocols() -> None:
    settings = load_settings()
    settings.transport.connections = [
        _conn(id="onebot11", protocol="onebot", version="v11", mode="forward_ws"),
        _conn(id="onebot12", protocol="onebot", version="v12", mode="forward_ws"),
        _conn(id="red1", protocol="red", mode="forward_ws", token="secret"),
        _conn(id="satori1", protocol="satori", mode="forward_ws"),
        _conn(id="mirai1", protocol="mirai", mode="http"),
        _conn(id="official1", protocol="qq_official", mode="ws_gateway"),
    ]
    bot_client = BotClient()
    adapters, reverse_routes = build_adapters(settings, bot_client)
    ids = {getattr(item, "bot_id", "") for item in adapters}
    assert ids == {
        "onebot11",
        "onebot12",
        "red1",
        "satori1",
        "mirai1",
        "official1",
    }
    assert reverse_routes == []


def test_build_adapters_reverse_route() -> None:
    settings = load_settings()
    settings.transport.connections = [
        _conn(id="napcat", mode="reverse_ws", path="/onebot/v11/ws")
    ]
    bot_client = BotClient()
    adapters, reverse_routes = build_adapters(settings, bot_client)
    assert adapters == []
    assert reverse_routes == [("/onebot/v11/ws", reverse_routes[0][1])]


def test_bot_client_scope_routing() -> None:
    settings = load_settings()
    policy = ScopePolicyService(settings)
    policy.set_connection("group:200", "target_conn")
    client = BotClient(scope_policy=policy)
    sent: list[str] = []

    class FakeAdapter:
        async def send_group_message(self, group_id: str, message: str) -> bool:
            sent.append("default")
            return True

        async def send_private_message(self, user_id: str, message: str) -> bool:
            return True

    class TargetAdapter:
        async def send_group_message(self, group_id: str, message: str) -> bool:
            sent.append("target")
            return True

        async def send_private_message(self, user_id: str, message: str) -> bool:
            return True

    client.register("default", FakeAdapter())
    client.register("target_conn", TargetAdapter())
    client.set_active("default")
    assert asyncio.run(client.send_group_message("200", "hi")) is True
    assert sent == ["target"]
