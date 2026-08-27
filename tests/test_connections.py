from __future__ import annotations

import asyncio

import pytest

from app.adapters.base import BotClient
from app.adapters.mirai import MiraiAdapter
from app.adapters.onebot import OneBotAdapter
from app.adapters.onebot_v12 import OneBotV12Adapter
from app.adapters.qq_official import OfficialQQAdapter
from app.adapters.satori import SatoriAdapter
from app.core.config import ConnectionSettings, load_settings
from app.core.messages import Message, MessageSegment
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


@pytest.mark.asyncio
async def test_onebot_v11_notice_dispatch() -> None:
    """OneBot v11 notice 按类型分发：戳一戳 / 群文件上传 / 撤回。"""
    from app.core.bus import get_bus, reset_bus
    from app.core.events import FileUploaded, GroupPoke, MessageRecalled

    client = BotClient()
    adapter = OneBotAdapter(_conn(), "test", client)
    captured: list = []
    bus = get_bus()
    bus.on(GroupPoke, lambda event: captured.append(event))
    bus.on(FileUploaded, lambda event: captured.append(event))
    bus.on(MessageRecalled, lambda event: captured.append(event))

    await adapter._handle_notice_or_request(
        {
            "post_type": "notice",
            "notice_type": "poke",
            "group_id": 200,
            "user_id": 100,
            "operator_id": 1,
            "target_id": 100,
        }
    )
    await adapter._handle_notice_or_request(
        {
            "post_type": "notice",
            "notice_type": "group_upload",
            "group_id": 200,
            "user_id": 100,
            "file": {"name": "a.txt", "size": 3},
        }
    )
    await adapter._handle_notice_or_request(
        {
            "post_type": "notice",
            "notice_type": "group_recall",
            "group_id": 200,
            "user_id": 100,
            "message_id": "m1",
            "operator_id": 1,
        }
    )
    await bus.wait_until_idle()
    assert any(
        isinstance(event, GroupPoke)
        and event.group_id == "200"
        and event.target_id == "100"
        for event in captured
    )
    assert any(
        isinstance(event, FileUploaded)
        and event.file_name == "a.txt"
        and event.file_size == 3
        for event in captured
    )
    assert any(
        isinstance(event, MessageRecalled) and event.message_id == "m1"
        for event in captured
    )
    await get_bus().stop(clear=True)
    reset_bus()


def test_segment_factories_and_message_concat() -> None:
    assert MessageSegment.text("hi").data == {"text": "hi"}
    assert MessageSegment.at(100).data == {"user_id": "100"}
    assert MessageSegment.image(file="f", url="u").data == {
        "file": "f",
        "url": "u",
    }
    assert MessageSegment.voice(file="v").type == "voice"
    assert MessageSegment.video(file="v").type == "video"
    assert MessageSegment.record(url="r").data == {"url": "r"}
    assert MessageSegment.file(file="f", name="n").data == {
        "file": "f",
        "name": "n",
    }
    assert MessageSegment.face(1).data == {"id": "1"}
    assert MessageSegment.reply(message_id="m", user_id="u").data == {
        "message_id": "m",
        "user_id": "u",
    }
    assert MessageSegment.forward("f").data == {"id": "f"}
    assert MessageSegment.markdown("# hi").data == {"content": "# hi"}
    assert MessageSegment.json({"a": 1}).data == {"data": {"a": 1}}

    message = Message.text("a").add_segment(MessageSegment.at(1)) + MessageSegment.text("b")
    assert [segment.type for segment in message.segments] == [
        "text",
        "at",
        "text",
    ]


def test_onebot_v11_to_array_full_segments() -> None:
    adapter = OneBotAdapter(_conn(), "t", BotClient())
    message = (
        Message.text("hi")
        + MessageSegment.at(100)
        + MessageSegment.image(file="a.png")
        + MessageSegment.voice(file="v.amr")
        + MessageSegment.video(file="vid.mp4")
        + MessageSegment.face(1)
        + MessageSegment.json({"k": "v"})
        + MessageSegment.reply(message_id="m")
    )
    array = adapter._to_array(message)
    types = [item["type"] for item in array]
    assert types == [
        "text",
        "at",
        "image",
        "record",
        "video",
        "face",
        "json",
        "reply",
    ]
    assert array[1]["data"]["qq"] == "100"
    assert array[3]["type"] == "record"


def test_red_elements_and_other_mappings() -> None:
    from app.adapters.mirai import MiraiAdapter
    from app.adapters.red import RedAdapter
    from app.adapters.satori import SatoriAdapter

    red = RedAdapter(
        _conn(protocol="red", api_base="http://127.0.0.1:8080"), "t", BotClient()
    )
    elements = red._to_elements(
        Message.text("hi")
        + MessageSegment.at(100)
        + MessageSegment.image(file="a.png")
        + MessageSegment.voice(file="v.amr")
        + MessageSegment.file(file="f", name="n")
    )
    kinds = [item["elementType"] for item in elements]
    assert kinds == [1, 7, 2, 4, 3]

    satori = SatoriAdapter(_conn(protocol="satori"), "t", BotClient())
    content = satori._to_satori(
        Message.text("hi")
        + MessageSegment.voice(file="v")
        + MessageSegment.video(file="vid")
        + MessageSegment.file(file="f")
    )
    assert [item["type"] for item in content] == ["text", "audio", "video", "file"]

    mirai = MiraiAdapter(
        _conn(protocol="mirai", api_base="http://127.0.0.1:8080"), "t", BotClient()
    )
    chain = mirai._to_chain(
        Message.text("hi") + MessageSegment.voice(file="v") + MessageSegment.file(file="f")
    )
    assert [item["type"] for item in chain] == ["Plain", "Voice", "File"]
