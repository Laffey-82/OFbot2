"""Satori 协议适配器（Chronocat 新版 / Lagrange.Satori）：正向 WS + HTTP API。"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx
import websockets

from app.adapters.base import BotClient, ProtocolAdapter, make_http_client
from app.core.bus import get_bus
from app.core.config import ConnectionSettings
from app.core.events import BotDisconnected
from app.core.logger import get_logger
from app.core.messages import (
    GroupMessageEvent,
    Message,
    MessageSegment,
    PrivateMessageEvent,
    Sender,
)

logger = get_logger(__name__)


class SatoriAdapter(ProtocolAdapter):
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
        self._http: httpx.AsyncClient | None = None
        self.api_base = (
            settings.api_base
            or f"http://{settings.host}:{settings.port}"
        )

    def _http_client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = make_http_client(15.0)
        return self._http

    def _headers(self) -> dict[str, str]:
        headers = {}
        if self.settings.token:
            headers["Authorization"] = f"Bearer {self.settings.token}"
        return headers

    async def start(self) -> None:
        self._running = True
        while self._running:
            try:
                await self._connect_loop()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("satori connection failed: %s", exc)
                self.bot_client.status[self.bot_id] = "disconnected"
            if self._running:
                await asyncio.sleep(self.settings.reconnect_interval)

    async def test(self) -> tuple[bool, str]:
        url = f"ws://{self.settings.host}:{self.settings.port}{self.settings.path or '/'}"
        try:
            async with websockets.connect(
                url, open_timeout=5, additional_headers=self._headers()
            ):
                return True, "Satori 网关连接成功"
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
        if self._ws is not None:
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

    async def _connect_loop(self) -> None:
        url = f"ws://{self.settings.host}:{self.settings.port}{self.settings.path or '/'}"
        async with websockets.connect(
            url, additional_headers=self._headers(), ping_interval=20
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

    async def _handle_raw(self, raw: str) -> None:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return
        if self.bot_id in self.bot_client.details:
            self.bot_client.details[self.bot_id]["last_heartbeat"] = time.time()
        event_type = data.get("type", "")
        body = data.get("body", {}) or {}
        if event_type == "login-added" and body:
            login = body if isinstance(body, dict) else {}
            self.self_id = str(
                login.get("self_id")
                or login.get("user", {}).get("id", "")
                or self.self_id
            )
            self.bot_client.details[self.bot_id]["self_id"] = self.self_id
        elif event_type == "message.created":
            await self._handle_message(body)

    async def _handle_message(self, body: dict[str, Any]) -> None:
        channel = body.get("channel", {}) or {}
        guild = body.get("guild", {}) or {}
        user = body.get("user", {}) or {}
        member = body.get("member", {}) or {}
        message = body.get("message", {}) or {}
        user_id = str(user.get("id", ""))
        segments = self._parse_content(body.get("content", []))
        at_self = any(
            segment.type == "at"
            and str(segment.data.get("user_id", "")) == str(self.self_id)
            for segment in segments
        )
        nickname = (
            member.get("nick")
            or member.get("name")
            or user.get("name")
            or user_id
        )

        async def reply(content: str | Message | MessageSegment) -> None:
            if guild:
                await self.send_group_message(str(channel.get("id", "")), content)
            else:
                await self.send_private_message(user_id, content)

        if guild:
            event = GroupMessageEvent(
                bot_id=self.bot_id,
                self_id=self.self_id,
                raw_event=body,
                message_id=str(message.get("id", "")),
                user_id=user_id,
                sender=Sender(user_id, str(nickname)),
                message=Message.from_segments(segments),
                group_id=str(channel.get("id", "")),
                at_self=at_self,
            )
        else:
            event = PrivateMessageEvent(
                bot_id=self.bot_id,
                self_id=self.self_id,
                raw_event=body,
                message_id=str(message.get("id", "")),
                user_id=user_id,
                sender=Sender(user_id, str(nickname)),
                message=Message.from_segments(segments),
                at_self=at_self,
            )
        event.reply = reply
        await self.bot_client.handle_bot_event(event)

    @staticmethod
    def _parse_content(content: Any) -> list[MessageSegment]:
        segments: list[MessageSegment] = []
        if isinstance(content, str):
            segments.append(MessageSegment("text", {"text": content}))
        elif isinstance(content, list):
            for item in content:
                if not isinstance(item, dict):
                    continue
                item_type = item.get("type", "")
                item_data = item.get("data", "")
                if item_type == "text":
                    segments.append(MessageSegment("text", {"text": str(item_data)}))
                elif item_type == "at":
                    segments.append(MessageSegment("at", {"user_id": str(item_data)}))
                elif item_type == "image":
                    segments.append(
                        MessageSegment("image", {"url": str(item_data)})
                    )
                elif item_type == "quote":
                    segments.append(
                        MessageSegment(
                            "reply", {"message_id": str(item_data)}
                        )
                    )
                else:
                    segments.append(
                        MessageSegment(item_type, {"data": item_data})
                    )
        return segments or [MessageSegment("text", {"text": ""})]

    @staticmethod
    def _to_satori(message: str | Message | MessageSegment) -> list[dict[str, Any]]:
        if isinstance(message, MessageSegment):
            message = Message.from_segments([message])
        elif isinstance(message, str):
            message = Message.text(message)
        parts: list[dict[str, Any]] = []
        for segment in message.segments:
            if segment.type == "text":
                parts.append(
                    {"type": "text", "data": segment.data.get("text", "")}
                )
            elif segment.type == "at":
                parts.append(
                    {"type": "at", "data": str(segment.data.get("user_id", ""))}
                )
            elif segment.type == "image":
                parts.append(
                    {
                        "type": "image",
                        "data": segment.data.get("url")
                        or segment.data.get("file", ""),
                    }
                )
            elif segment.type == "reply":
                parts.append(
                    {
                        "type": "quote",
                        "data": str(segment.data.get("message_id", "")),
                    }
                )
            else:
                parts.append({"type": segment.type, "data": segment.data})
        return parts

    async def send_group_message(
        self, group_id: str, message: str | Message | MessageSegment
    ) -> bool:
        return await self._api(
            "message.create",
            {"channel_id": str(group_id), "content": self._to_satori(message)},
        )

    async def send_private_message(
        self, user_id: str, message: str | Message | MessageSegment
    ) -> bool:
        return await self._api(
            "message.create",
            {
                "channel_id": f"private:{user_id}",
                "content": self._to_satori(message),
            },
        )

    async def _api(self, action: str, params: dict[str, Any]) -> bool:
        try:
            response = await self._http_client().post(
                f"{self.api_base}/v1/{action}",
                json=params,
                headers=self._headers(),
            )
            response.raise_for_status()
            return True
        except Exception:
            logger.exception("satori api failed: %s", action)
            return False
