from __future__ import annotations

import json
from typing import Any

from app.adapters.base import BotClient
from app.adapters.onebot import OneBotAdapter
from app.adapters.onebot_v12 import OneBotV12Adapter
from app.core.config import ConnectionSettings, OneBotSettings
from app.core.messages import MessageEvent


class FakeWebSocket:
    """记录 send 调用次数的假 WebSocket（模拟反向 WS 连接）。"""

    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_text(self, payload: str) -> None:
        self.sent.append(payload)

    async def send(self, payload: str) -> None:
        self.sent.append(payload)


class RecordingClient(BotClient):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[MessageEvent] = []

    async def handle_bot_event(self, event: MessageEvent) -> bool:
        self.events.append(event)
        return True


def _v12_conn(**overrides: Any) -> ConnectionSettings:
    data: dict[str, Any] = {
        "id": "t12",
        "protocol": "onebot",
        "version": "v12",
        "mode": "reverse_ws",
    }
    data.update(overrides)
    return ConnectionSettings(**data)


async def test_v11_reverse_ws_send_action_sends_once() -> None:
    adapter = OneBotAdapter(
        OneBotSettings(mode="reverse_ws"), "bot11", RecordingClient()
    )
    ws = FakeWebSocket()
    adapter._ws = ws
    adapter._reverse_connections.append(ws)

    assert await adapter.send_group_message("200", "hi") is True
    assert len(ws.sent) == 1
    assert json.loads(ws.sent[0])["action"] == "send_group_msg"


async def test_v12_reverse_ws_send_action_sends_once() -> None:
    adapter = OneBotV12Adapter(_v12_conn(), "bot12", RecordingClient())
    ws = FakeWebSocket()
    adapter._ws = ws
    adapter._reverse_connections.append(ws)

    assert await adapter.send_group_message("200", "hi") is True
    assert len(ws.sent) == 1
    assert json.loads(ws.sent[0])["action"] == "send_message"


async def test_v11_forward_ws_send_action_single_socket() -> None:
    adapter = OneBotAdapter(
        OneBotSettings(mode="forward"), "bot11", RecordingClient()
    )
    ws = FakeWebSocket()
    adapter._ws = ws

    assert await adapter.send_private_message("100", "hi") is True
    assert len(ws.sent) == 1


async def test_v11_self_id_backfilled_from_event() -> None:
    client = RecordingClient()
    adapter = OneBotAdapter(
        OneBotSettings(mode="reverse_ws"), "bot11", client
    )
    client.details["bot11"] = {"self_id": "", "connected_at": 0.0}
    payload = json.dumps(
        {
            "post_type": "message",
            "message_type": "group",
            "group_id": 200,
            "user_id": 100,
            "message_id": 1,
            "self_id": 10001,
            "raw_message": "hello",
            "message": "hello",
            "sender": {"nickname": "tester"},
        }
    )

    await adapter._handle_raw(payload)

    assert adapter.self_id == "10001"
    assert client.details["bot11"]["self_id"] == "10001"


async def test_v11_self_id_backfill_via_http_event() -> None:
    adapter = OneBotAdapter(
        OneBotSettings(mode="http"), "bot11", RecordingClient()
    )

    await adapter.handle_http_event(
        {"post_type": "notice", "notice_type": "poke", "self_id": 10001}
    )

    assert adapter.self_id == "10001"


async def test_v11_self_id_backfill_idempotent_and_stable() -> None:
    adapter = OneBotAdapter(
        OneBotSettings(mode="reverse_ws"), "bot11", RecordingClient()
    )
    base = {
        "post_type": "message",
        "message_type": "private",
        "user_id": 100,
        "message_id": 1,
        "self_id": 10001,
        "raw_message": "hi",
        "message": "hi",
        "sender": {"nickname": "tester"},
    }

    await adapter._handle_raw(json.dumps(base))
    assert adapter.self_id == "10001"

    await adapter._handle_raw(json.dumps(base))
    assert adapter.self_id == "10001"

    without_self_id = dict(base)
    without_self_id.pop("self_id")
    await adapter._handle_raw(json.dumps(without_self_id))
    assert adapter.self_id == "10001"


async def test_v12_self_id_backfilled_from_event_and_at_self() -> None:
    client = RecordingClient()
    adapter = OneBotV12Adapter(_v12_conn(), "bot12", client)
    client.details["bot12"] = {"self_id": "", "connected_at": 0.0}
    payload = json.dumps(
        {
            "type": "message",
            "detail_type": "group",
            "message_id": "m1",
            "user_id": "100",
            "group_id": "200",
            "self_id": 10086,
            "message": [
                {"type": "at", "data": {"user_id": "10086"}},
                {"type": "text", "data": {"text": "hi"}},
            ],
        }
    )

    await adapter._handle_raw(payload)

    assert adapter.self_id == "10086"
    assert client.details["bot12"]["self_id"] == "10086"
    assert client.events
    assert client.events[0].at_self is True


async def test_v12_self_id_backfill_idempotent() -> None:
    adapter = OneBotV12Adapter(_v12_conn(), "bot12", RecordingClient())
    base = {
        "type": "notice",
        "detail_type": "group_poke",
        "self_id": 10086,
        "user_id": "100",
        "group_id": "200",
    }

    await adapter._handle_raw(json.dumps(base))
    assert adapter.self_id == "10086"

    await adapter._handle_raw(json.dumps(base))
    assert adapter.self_id == "10086"


def test_v12_self_id_initialized_from_settings() -> None:
    adapter = OneBotV12Adapter(
        _v12_conn(self_id="10000"), "bot12", RecordingClient()
    )
    assert adapter.self_id == "10000"


def test_v12_self_id_defaults_empty() -> None:
    adapter = OneBotV12Adapter(_v12_conn(), "bot12", RecordingClient())
    assert adapter.self_id == ""
