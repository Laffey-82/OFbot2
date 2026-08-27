"""协议契约矩阵：OneBot v11/v12、Red、Satori、Mirai、官方机器人。

每个协议用假服务端验证：握手 → 群消息归一化 → 出站发送载荷；另覆盖
鉴权失败（test() 返回 False）、notice 分发（GroupPoke）与媒体段归一化。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest
import websockets

from app.adapters.base import BotClient
from app.adapters.mirai import MiraiAdapter
from app.adapters.onebot import OneBotAdapter
from app.adapters.onebot_v12 import OneBotV12Adapter
from app.adapters.qq_official import OfficialQQAdapter
from app.adapters.red import RedAdapter
from app.adapters.satori import SatoriAdapter
from app.core.bus import get_bus, reset_bus
from app.core.config import ConnectionSettings


def make_connection(**kwargs: Any) -> ConnectionSettings:
    return ConnectionSettings(**{key: value for key, value in kwargs.items()})


class RecordingClient(BotClient):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[Any] = []

    async def handle_bot_event(self, event):
        self.events.append(event)
        return True


async def wait_for(predicate, timeout: float = 5.0) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.05)
    return False


def http_factory(handler):
    def factory(timeout: float = 15.0):
        return httpx.AsyncClient(
            transport=httpx.MockTransport(handler), timeout=timeout
        )

    return factory


@pytest.mark.asyncio
async def test_matrix_onebot_v11_forward() -> None:
    received_actions: list[dict] = []

    async def ws_handler(websocket) -> None:
        await websocket.send(
            json.dumps(
                {
                    "post_type": "message",
                    "message_type": "group",
                    "group_id": 200,
                    "user_id": 100,
                    "message_id": 1,
                    "raw_message": "/ping",
                    "message": "/ping",
                    "sender": {"nickname": "tester", "card": None},
                }
            )
        )
        first = json.loads(await websocket.recv())
        received_actions.append(first)

    async with websockets.serve(ws_handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        client = RecordingClient()
        adapter = OneBotAdapter(
            make_connection(host="127.0.0.1", port=port, mode="forward"),
            "t1",
            client,
        )
        task = asyncio.create_task(adapter.start())
        try:
            assert await wait_for(lambda: bool(client.events))
            event = client.events[0]
            assert (event.group_id, event.user_id) == ("200", "100")
            assert event.message.extract_plain_text() == "/ping"
            assert await adapter.send_group_message("200", "hi") is True
            assert await wait_for(lambda: bool(received_actions))
            assert received_actions[0]["action"] == "send_group_msg"
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await adapter.stop()
            await _cleanup_bus()


@pytest.mark.asyncio
async def test_matrix_onebot_v12_forward_and_media() -> None:
    received_actions: list[dict] = []

    async def ws_handler(websocket) -> None:
        await websocket.send(
            json.dumps(
                {
                    "type": "message",
                    "detail_type": "group",
                    "message_id": "m1",
                    "user_id": "100",
                    "group_id": "200",
                    "message": [
                        {"type": "text", "data": {"text": "看这张图"}},
                        {"type": "image", "data": {"file": "a.png", "url": "https://x/a.png"}},
                        {"type": "at", "data": {"user_id": "10"}},
                        {"type": "voice", "data": {"file": "v.silk"}},
                    ],
                }
            )
        )
        received_actions.append(json.loads(await websocket.recv()))

    async with websockets.serve(ws_handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        client = RecordingClient()
        adapter = OneBotV12Adapter(
            make_connection(
                id="t2",
                protocol="onebot",
                version="v12",
                host="127.0.0.1",
                port=port,
                mode="forward_ws",
            ),
            "t2",
            client,
        )
        task = asyncio.create_task(adapter.start())
        try:
            assert await wait_for(lambda: bool(client.events))
            event = client.events[0]
            assert (event.group_id, event.user_id) == ("200", "100")
            types = [segment.type for segment in event.message.segments]
            assert types == ["text", "image", "at", "voice"]
            assert await adapter.send_group_message("200", "hi") is True
            assert await wait_for(lambda: bool(received_actions))
            action = received_actions[0]
            assert action["action"] == "send_message"
            assert action["params"]["detail_type"] == "group"
            assert action["params"]["message"][0]["type"] == "text"
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await adapter.stop()
            await _cleanup_bus()


@pytest.mark.asyncio
async def test_matrix_red_handshake_and_http_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[httpx.Request] = []

    def http_handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={"ok": True})

    async def ws_handler(websocket) -> None:
        connect = json.loads(await websocket.recv())
        assert connect["type"] == "meta::connect"
        await websocket.send(json.dumps({"type": "meta::connect", "payload": {}}))
        await websocket.send(
            json.dumps(
                {
                    "type": "message::recv",
                    "payload": [
                        {
                            "msgId": "m1",
                            "chatType": 2,
                            "senderUid": "u100",
                            "senderUin": "100",
                            "peerUin": "200",
                            "elements": [
                                {
                                    "elementType": 1,
                                    "textElement": {"content": "/ping"},
                                }
                            ],
                        }
                    ],
                }
            )
        )
        await asyncio.sleep(1)

    monkeypatch.setattr(
        "app.adapters.red.make_http_client", http_factory(http_handler)
    )
    async with websockets.serve(ws_handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        client = RecordingClient()
        adapter = RedAdapter(
            make_connection(
                id="red",
                protocol="red",
                token="tk",
                host="127.0.0.1",
                port=port,
                api_base=f"http://127.0.0.1:{port}",
            ),
            "red",
            client,
        )
        task = asyncio.create_task(adapter.start())
        try:
            assert await wait_for(lambda: bool(client.events))
            event = client.events[0]
            assert (event.group_id, event.user_id) == ("200", "100")
            assert await adapter.send_group_message("200", "hi") is True
            assert sent and "/message/send" in sent[-1].url.path
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await adapter.stop()
            await _cleanup_bus()


@pytest.mark.asyncio
async def test_matrix_satori_forward(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[httpx.Request] = []

    def http_handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={"ok": True})

    async def ws_handler(websocket) -> None:
        await websocket.send(
            json.dumps(
                {
                    "type": "message.created",
                    "body": {
                        "guild": {"id": "g1"},
                        "channel": {"id": "200"},
                        "user": {"id": "100"},
                        "member": {"name": "tester"},
                        "message": {"id": "m1"},
                        "content": [{"type": "text", "data": "/ping"}],
                    },
                }
            )
        )
        await asyncio.sleep(1)

    monkeypatch.setattr(
        "app.adapters.satori.make_http_client", http_factory(http_handler)
    )
    async with websockets.serve(ws_handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        client = RecordingClient()
        adapter = SatoriAdapter(
            make_connection(
                id="satori",
                protocol="satori",
                host="127.0.0.1",
                port=port,
                api_base=f"http://127.0.0.1:{port}",
            ),
            "satori",
            client,
        )
        task = asyncio.create_task(adapter.start())
        try:
            assert await wait_for(lambda: bool(client.events))
            event = client.events[0]
            assert (event.group_id, event.user_id) == ("200", "100")
            assert event.message.extract_plain_text() == "/ping"
            assert await adapter.send_group_message("200", "hi") is True
            assert sent and sent[-1].url.path == "/v1/message.create"
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await adapter.stop()
            await _cleanup_bus()


@pytest.mark.asyncio
async def test_matrix_mirai_http_polling(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[httpx.Request] = []
    fetched = 0

    def http_handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/verify":
            return httpx.Response(200, json={"code": 0, "session": "S"})
        if path == "/bind":
            return httpx.Response(200, json={"code": 0})
        if path == "/fetchMessage":
            nonlocal fetched
            fetched += 1
            if fetched == 1:
                return httpx.Response(
                    200,
                    json={
                        "code": 0,
                        "data": [
                            {
                                "type": "GroupMessage",
                                "id": "m1",
                                "sender": {
                                    "id": 100,
                                    "memberName": "tester",
                                    "group": {"id": 200},
                                },
                                "messageChain": [
                                    {"type": "Plain", "text": "/ping"},
                                    {"type": "Image", "url": "https://x/a.png"},
                                ],
                            }
                        ],
                    },
                )
            return httpx.Response(200, json={"code": 0, "data": []})
        if path == "/sendGroupMessage":
            sent.append(request)
            return httpx.Response(200, json={"code": 0})
        return httpx.Response(404)

    monkeypatch.setattr(
        "app.adapters.mirai.make_http_client", http_factory(http_handler)
    )
    client = RecordingClient()
    adapter = MiraiAdapter(
        make_connection(
            id="mirai",
            protocol="mirai",
            token="verify",
            self_id="1",
            host="127.0.0.1",
            port=1,
            api_base="http://fake",
        ),
        "mirai",
        client,
    )
    task = asyncio.create_task(adapter.start())
    try:
        assert await wait_for(lambda: bool(client.events))
        event = client.events[0]
        assert (event.group_id, event.user_id) == ("200", "100")
        types = [segment.type for segment in event.message.segments]
        assert types == ["text", "image"]
        assert await adapter.send_group_message("200", "hi") is True
        assert sent and sent[-1].url.path == "/sendGroupMessage"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await adapter.stop()
        await _cleanup_bus()


@pytest.mark.asyncio
async def test_matrix_qq_official_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[httpx.Request] = []
    gateway_url: dict[str, str] = {}

    def http_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/gateway":
            return httpx.Response(
                200, json={"url": gateway_url.get("url", ""), "token": ""}
            )
        if "/v2/groups/" in request.url.path:
            sent.append(request)
            return httpx.Response(200, json={"id": "msg-1"})
        return httpx.Response(404)

    async def ws_handler(websocket) -> None:
        identify = json.loads(await websocket.recv())
        assert identify["op"] == 2
        await websocket.send(
            json.dumps({"op": 10, "d": {"heartbeat_interval": 30000}})
        )
        await websocket.send(
            json.dumps(
                {
                    "op": 0,
                    "d": {
                        "t": "GROUP_AT_MESSAGE_CREATE",
                        "d": {
                            "id": "m1",
                            "content": "#/ping",
                            "group_openid": "g_200",
                            "author": {"member_openid": "u100"},
                        },
                    },
                }
            )
        )
        await asyncio.sleep(1)

    async with websockets.serve(ws_handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        gateway_url["url"] = f"ws://127.0.0.1:{port}"
        monkeypatch.setattr(
            "app.adapters.qq_official.make_http_client",
            http_factory(http_handler),
        )
        client = RecordingClient()
        adapter = OfficialQQAdapter(
            make_connection(
                id="qq",
                protocol="qq_official",
                app_id="1",
                token="tk",
                host="127.0.0.1",
                port=port,
                api_base="http://fake",
            ),
            "qq",
            client,
        )
        task = asyncio.create_task(adapter.start())
        try:
            assert await wait_for(lambda: bool(client.events))
            event = client.events[0]
            assert (event.group_id, event.user_id) == ("g_200", "u100")
            assert event.message.extract_plain_text() == "/ping"
            assert await adapter.send_group_message("g_200", "hi") is True
            assert sent and "/v2/groups/" in sent[-1].url.path
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await adapter.stop()
            await _cleanup_bus()


@pytest.mark.asyncio
async def test_matrix_onebot_v11_notice_dispatch() -> None:
    from app.core.events import GroupPoke

    async def ws_handler(websocket) -> None:
        await websocket.send(
            json.dumps(
                {
                    "post_type": "notice",
                    "notice_type": "poke",
                    "user_id": 100,
                    "group_id": 200,
                    "target_id": 100,
                }
            )
        )
        await asyncio.sleep(1)

    dispatched: list[Any] = []

    async def on_poke(event: GroupPoke) -> None:
        dispatched.append(event)

    from app.core.subscriptions import EventSubscriptionRegistry

    registry = EventSubscriptionRegistry()
    registry.subscribe(GroupPoke, on_poke, plugin_name="test")
    async with websockets.serve(ws_handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        client = RecordingClient()
        adapter = OneBotAdapter(
            make_connection(host="127.0.0.1", port=port, mode="forward"),
            "t3",
            client,
        )
        task = asyncio.create_task(adapter.start())
        try:
            assert await wait_for(lambda: bool(dispatched))
            assert dispatched[0].group_id == "200"
            assert dispatched[0].target_id == "100"
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await adapter.stop()
            await _cleanup_bus()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("protocol", "settings_kwargs"),
    [
        ("onebot", {"access_token": "wrong"}),
        ("red", {"token": "wrong"}),
        ("satori", {"token": "wrong"}),
        ("mirai", {"token": "wrong"}),
        ("qq_official", {"app_id": "1", "token": "wrong"}),
    ],
)
async def test_matrix_auth_failure_rejected(
    monkeypatch: pytest.MonkeyPatch,
    protocol: str,
    settings_kwargs: dict[str, Any],
) -> None:
    def deny(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"})

    module_map = {
        "red": "app.adapters.red",
        "satori": "app.adapters.satori",
        "mirai": "app.adapters.mirai",
        "qq_official": "app.adapters.qq_official",
    }
    if protocol in module_map:
        monkeypatch.setattr(
            f"{module_map[protocol]}.make_http_client",
            http_factory(deny),
        )
    client = RecordingClient()
    connection = make_connection(
        id="auth", protocol=protocol, host="127.0.0.1", port=1, **settings_kwargs
    )
    if protocol == "onebot":
        adapter: Any = OneBotAdapter(connection, "auth", client)
    elif protocol == "red":
        adapter = RedAdapter(connection, "auth", client)
    elif protocol == "satori":
        adapter = SatoriAdapter(connection, "auth", client)
    elif protocol == "mirai":
        adapter = MiraiAdapter(connection, "auth", client)
    else:
        adapter = OfficialQQAdapter(connection, "auth", client)
    ok, _ = await adapter.test()
    assert ok is False
    await _cleanup_bus()


async def _cleanup_bus() -> None:
    try:
        await get_bus().stop(clear=True)
    except Exception:
        pass
    reset_bus()
