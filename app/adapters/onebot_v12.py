"""OneBot v12 适配器（Lagrange.OneBot / NapCat 兼容）：正向/反向 WS + HTTP。"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx
import websockets
from fastapi import WebSocket

from app.adapters.base import BotClient, ProtocolAdapter, make_http_client
from app.core.bus import get_bus
from app.core.config import ConnectionSettings
from app.core.events import BotDisconnected, NoticeReceived
from app.core.logger import get_logger
from app.core.messages import (
    GroupMessageEvent,
    Message,
    MessageSegment,
    PrivateMessageEvent,
    Sender,
)

logger = get_logger(__name__)


class OneBotV12Adapter(ProtocolAdapter):
    def __init__(
        self, settings: ConnectionSettings, bot_id: str, bot_client: BotClient
    ) -> None:
        self.settings = settings
        self.bot_id = bot_id
        self.bot_client = bot_client
        self.self_id = ""
        self._running = False
        self._reconnects = 0
        self._ws: Any = None
        self._reverse_connections: list[Any] = []
        self._http: httpx.AsyncClient | None = None
        self._mode = settings.mode
        self.reverse_path = settings.path or "/onebot/v12/ws"
        self.http_path = "/onebot/v12/http"

    def _http_client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = make_http_client(15.0)
        return self._http

    def _is_forward(self) -> bool:
        return self._mode in {"forward", "forward_ws"}

    def _is_http(self) -> bool:
        return self._mode == "http"

    async def start(self) -> None:
        if not self._is_forward():
            if self._is_http():
                self.bot_client.status[self.bot_id] = "connected"
                self.bot_client.details[self.bot_id] = {
                    "self_id": self.settings.self_id,
                    "connected_at": time.time(),
                    "mode": "http",
                }
            return
        self._running = True
        while self._running:
            try:
                await self._connect_forward()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("onebot v12 forward connection failed: %s", exc)
                self.bot_client.status[self.bot_id] = "disconnected"
            if self._running:
                await asyncio.sleep(self.settings.reconnect_interval)

    async def test(self) -> tuple[bool, str]:
        if self._is_http():
            url = f"http://{self.settings.host}:{self.settings.port}/api/v1/get_version"
            try:
                async with make_http_client(5) as client:
                    response = await client.post(url, json={})
                    response.raise_for_status()
                    return True, "OneBot v12 HTTP 连接成功"
            except Exception as exc:
                return False, str(exc)
        if not self._is_forward():
            return False, "反向模式不支持主动测试，请检查客户端是否已连接本服务"
        url = f"ws://{self.settings.host}:{self.settings.port}{self.settings.path}"
        headers = {}
        if self.settings.access_token:
            headers["Authorization"] = f"Bearer {self.settings.access_token}"
        try:
            async with websockets.connect(
                url, open_timeout=5, additional_headers=headers
            ):
                return True, "WebSocket 连接成功"
        except Exception as exc:
            return False, str(exc)

    async def stop(self) -> None:
        self._running = False
        self.bot_client.status[self.bot_id] = "disconnected"
        try:
            get_bus().dispatch(
                BotDisconnected(bot_id=self.bot_id, self_id=self.self_id)
            )
        except RuntimeError:
            pass
        if self._ws is not None and self._ws not in self._reverse_connections:
            try:
                await self._ws.close()
            except Exception:
                pass
        if self._http is not None:
            try:
                await self._http.aclose()
            except Exception:
                pass
            self._http = None

    async def _connect_forward(self) -> None:
        url = f"ws://{self.settings.host}:{self.settings.port}{self.settings.path}"
        headers = {}
        if self.settings.access_token:
            headers["Authorization"] = f"Bearer {self.settings.access_token}"
        async with websockets.connect(
            url, additional_headers=headers
        ) as ws:
            self._ws = ws
            self._reconnects += 1
            self.bot_client.status[self.bot_id] = "connected"
            self.bot_client.details[self.bot_id] = {
                "self_id": self.settings.self_id,
                "connected_at": time.time(),
                "reconnects": self._reconnects,
            }
            async for raw in ws:
                await self._handle_raw(raw)

    async def handle_reverse_ws(self, websocket: WebSocket) -> None:
        await websocket.accept()
        if self.settings.access_token:
            token = websocket.headers.get("authorization", "")
            if token != f"Bearer {self.settings.access_token}":
                await websocket.close(code=1008)
                return
        self._ws = websocket
        self._reverse_connections.append(websocket)
        self._reconnects += 1
        self.bot_client.status[self.bot_id] = "connected"
        self.bot_client.details[self.bot_id] = {
            "self_id": self.settings.self_id,
            "connected_at": time.time(),
            "reconnects": self._reconnects,
        }
        try:
            while True:
                raw = await websocket.receive_text()
                await self._handle_raw(raw)
        except Exception:
            pass
        finally:
            self._ws = None
            if websocket in self._reverse_connections:
                self._reverse_connections.remove(websocket)
            self.bot_client.status[self.bot_id] = "disconnected"

    async def handle_http_event(self, data: dict[str, Any]) -> None:
        if self.bot_id in self.bot_client.details:
            self.bot_client.details[self.bot_id]["last_heartbeat"] = time.time()
        await self._handle_payload(data)

    async def _handle_raw(self, raw: str) -> None:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return
        if self.bot_id in self.bot_client.details:
            self.bot_client.details[self.bot_id]["last_heartbeat"] = time.time()
        await self._handle_payload(data)

    async def _handle_payload(self, data: dict[str, Any]) -> None:
        event_type = data.get("type", "")
        if event_type == "message":
            await self._handle_message(data)
        elif event_type == "notice":
            get_bus().dispatch(
                NoticeReceived(
                    bot_id=self.bot_id,
                    self_id=self.self_id,
                    notice_type=data.get("detail_type", ""),
                    user_id=str(data.get("user_id", "")),
                    group_id=str(data.get("group_id", "")),
                    raw_event=data,
                )
            )

    async def _handle_message(self, data: dict[str, Any]) -> None:
        detail_type = data.get("detail_type", "")
        if detail_type not in {"group", "private"}:
            return
        user_id = str(data.get("user_id", ""))
        message = Message.from_segments(
            self._parse_segments(data.get("message", []))
        )
        at_self = any(
            segment.type == "at"
            and str(segment.data.get("user_id", "")) == str(self.self_id)
            for segment in message.segments
        )
        sender = Sender(user_id, str(data.get("user_name") or user_id))

        async def reply(content: str | Message | MessageSegment) -> None:
            if detail_type == "group":
                await self.send_group_message(
                    str(data.get("group_id", "")), content
                )
            else:
                await self.send_private_message(user_id, content)

        if detail_type == "group":
            event = GroupMessageEvent(
                bot_id=self.bot_id,
                self_id=self.self_id,
                raw_event=data,
                message_id=str(data.get("message_id", "")),
                user_id=user_id,
                sender=sender,
                message=message,
                group_id=str(data.get("group_id", "")),
                at_self=at_self,
            )
        else:
            event = PrivateMessageEvent(
                bot_id=self.bot_id,
                self_id=self.self_id,
                raw_event=data,
                message_id=str(data.get("message_id", "")),
                user_id=user_id,
                sender=sender,
                message=message,
                at_self=at_self,
            )
        event.reply = reply
        await self.bot_client.handle_bot_event(event)

    @staticmethod
    def _parse_segments(message: Any) -> list[MessageSegment]:
        segments: list[MessageSegment] = []
        if isinstance(message, str):
            segments.append(MessageSegment("text", {"text": message}))
        elif isinstance(message, list):
            for item in message:
                if not isinstance(item, dict):
                    continue
                item_type = item.get("type", "")
                item_data = item.get("data", {}) or {}
                if item_type == "text":
                    segments.append(
                        MessageSegment("text", {"text": item_data.get("text", "")})
                    )
                elif item_type == "at":
                    segments.append(
                        MessageSegment("at", {"user_id": item_data.get("user_id", "")})
                    )
                elif item_type == "image":
                    segments.append(
                        MessageSegment(
                            "image",
                            {
                                "file": item_data.get("file_id", ""),
                                "url": item_data.get("file", item_data.get("url", "")),
                            },
                        )
                    )
                elif item_type == "reply":
                    segments.append(
                        MessageSegment(
                            "reply", {"message_id": item_data.get("message_id", "")}
                        )
                    )
                else:
                    segments.append(MessageSegment(item_type, item_data))
        return segments or [MessageSegment("text", {"text": ""})]

    @staticmethod
    def _to_v12(message: str | Message | MessageSegment) -> list[dict[str, Any]]:
        if isinstance(message, MessageSegment):
            message = Message.from_segments([message])
        elif isinstance(message, str):
            message = Message.text(message)
        parts: list[dict[str, Any]] = []
        for segment in message.segments:
            if segment.type == "text":
                parts.append(
                    {"type": "text", "data": {"text": segment.data.get("text", "")}}
                )
            elif segment.type == "at":
                parts.append(
                    {"type": "at", "data": {"user_id": segment.data.get("user_id", "")}}
                )
            elif segment.type == "image":
                parts.append(
                    {
                        "type": "image",
                        "data": {"file_id": segment.data.get("file", "")},
                    }
                )
            elif segment.type == "reply":
                parts.append(
                    {
                        "type": "reply",
                        "data": {"message_id": segment.data.get("message_id", "")},
                    }
                )
            else:
                parts.append({"type": segment.type, "data": segment.data})
        return parts

    async def send_group_message(
        self, group_id: str, message: str | Message | MessageSegment
    ) -> bool:
        return await self._send_action(
            "send_message",
            {
                "detail_type": "group",
                "group_id": group_id,
                "message": self._to_v12(message),
            },
        )

    async def send_private_message(
        self, user_id: str, message: str | Message | MessageSegment
    ) -> bool:
        return await self._send_action(
            "send_message",
            {
                "detail_type": "private",
                "user_id": user_id,
                "message": self._to_v12(message),
            },
        )

    async def _send_action(self, action: str, params: dict[str, Any]) -> bool:
        if self._is_http():
            url = (
                f"http://{self.settings.host}:{self.settings.port}"
                f"/api/v1/{action}"
            )
            try:
                response = await self._http_client().post(
                    url,
                    json={"action": action, "params": params},
                )
                response.raise_for_status()
                return True
            except Exception:
                logger.exception("onebot v12 http action failed: %s", action)
                return False
        payload = json.dumps(
            {"action": action, "params": params, "echo": str(time.time())}
        )
        sent = False
        for websocket in list(self._reverse_connections):
            try:
                if hasattr(websocket, "send_text"):
                    await websocket.send_text(payload)
                else:
                    await websocket.send(payload)
                sent = True
            except Exception:
                logger.exception("onebot v12 send action failed: %s", action)
        if self._ws is not None:
            try:
                if hasattr(self._ws, "send_text"):
                    await self._ws.send_text(payload)
                else:
                    await self._ws.send(payload)
                sent = True
            except Exception:
                logger.exception("onebot v12 send action failed: %s", action)
        return sent
