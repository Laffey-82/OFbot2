"""Mirai HTTP 适配器（mirai-api-http v2）：verify/session + fetchMessage 轮询。"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from app.adapters.base import BaseAdapter, BotClient, make_http_client
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

MIRAI_REAUTH_MAX_FAILURES = 3


class MiraiAdapter(BaseAdapter):
    def __init__(
        self, settings: ConnectionSettings, bot_id: str, bot_client: BotClient
    ) -> None:
        super().__init__(settings, bot_client)
        self.settings = settings
        self.bot_id = bot_id
        self.self_id = settings.self_id
        self._session_key = ""
        self._reauth_failures = 0
        self._http: httpx.AsyncClient | None = None
        self.api_base = settings.api_base or f"http://{settings.host}:{settings.port}"
        self.verify_key = settings.token or settings.access_token

    def _http_client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = make_http_client(15.0)
        return self._http

    async def start(self) -> None:
        await self.run_reconnect_loop(self._connect_loop, self.bot_id)

    async def _connect_loop(self) -> None:
        await self._ensure_session()
        self._mark_connected()
        self.bot_client.status[self.bot_id] = "connected"
        self.bot_client.details[self.bot_id] = {
            "self_id": self.self_id,
            "connected_at": time.time(),
        }
        while self._running:
            await self._poll_once()
            await asyncio.sleep(0.5)

    async def test(self) -> tuple[bool, str]:
        try:
            await self._ensure_session()
            return True, "Mirai HTTP 连接成功"
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
        if self._http is not None:
            try:
                await self._http.aclose()
            except Exception:
                pass
            self._http = None

    async def _ensure_session(self, force: bool = False) -> None:
        if self._session_key and not force:
            return
        if force:
            self._session_key = ""
        response = await self._http_client().post(
            f"{self.api_base}/verify",
            json={"verifyKey": self.verify_key},
        )
        response.raise_for_status()
        data = response.json()
        if data.get("code") != 0:
            raise RuntimeError(f"mirai verify failed: {data}")
        self._session_key = str(data.get("session", ""))
        bind = await self._http_client().post(
            f"{self.api_base}/bind",
            json={"sessionKey": self._session_key, "qq": int(self.self_id or 0)},
        )
        bind.raise_for_status()

    async def _poll_once(self) -> None:
        try:
            response = await self._http_client().get(
                f"{self.api_base}/fetchMessage",
                params={"sessionKey": self._session_key},
            )
            response.raise_for_status()
        except Exception as exc:
            logger.warning("mirai fetchMessage failed bot=%s: %s", self.bot_id, exc)
            return
        data = response.json()
        code = data.get("code")
        if code not in (0, None):
            logger.warning(
                "mirai poll code=%s bot=%s, session 失效，强制重新认证",
                code,
                self.bot_id,
            )
            self._session_key = ""
            try:
                await self._ensure_session(force=True)
            except Exception as exc:
                self._reauth_failures += 1
                if self._reauth_failures >= MIRAI_REAUTH_MAX_FAILURES:
                    self._reauth_failures = 0
                    raise RuntimeError(
                        f"mirai 重新认证连续 {MIRAI_REAUTH_MAX_FAILURES} 次失败: {exc}"
                    ) from exc
                logger.warning(
                    "mirai re-auth failed %s/%s bot=%s: %s",
                    self._reauth_failures,
                    MIRAI_REAUTH_MAX_FAILURES,
                    self.bot_id,
                    exc,
                )
                return
            self._reauth_failures = 0
            return
        for item in data.get("data") or []:
            await self._handle_event(item)

    async def _handle_event(self, item: dict[str, Any]) -> None:
        event_type = item.get("type", "")
        if event_type == "GroupMessage":
            sender = item.get("sender", {}) or {}
            user_id = str(sender.get("id", ""))
            nickname = str(sender.get("memberName") or sender.get("nickname") or user_id)
            message = Message.from_segments(
                self._parse_chain(item.get("messageChain", []))
            )

            async def reply(content: str | Message | MessageSegment) -> None:
                await self.send_group_message(
                    str(item.get("sender", {}).get("group", {}).get("id", "")),
                    content,
                )

            event = GroupMessageEvent(
                bot_id=self.bot_id,
                self_id=self.self_id,
                raw_event=item,
                message_id=str(item.get("id", "")),
                user_id=user_id,
                sender=Sender(user_id, nickname),
                message=message,
                group_id=str(item.get("sender", {}).get("group", {}).get("id", "")),
            )
            event.reply = reply
            await self.bot_client.handle_bot_event(event)
        elif event_type == "FriendMessage":
            sender = item.get("sender", {}) or {}
            user_id = str(sender.get("id", ""))
            nickname = str(sender.get("nickname") or user_id)
            message = Message.from_segments(
                self._parse_chain(item.get("messageChain", []))
            )

            async def reply_private(
                content: str | Message | MessageSegment,
            ) -> None:
                await self.send_private_message(user_id, content)

            event = PrivateMessageEvent(
                bot_id=self.bot_id,
                self_id=self.self_id,
                raw_event=item,
                message_id=str(item.get("id", "")),
                user_id=user_id,
                sender=Sender(user_id, nickname),
                message=message,
            )
            event.reply = reply_private
            await self.bot_client.handle_bot_event(event)

    @staticmethod
    def _parse_chain(chain: list[dict[str, Any]]) -> list[MessageSegment]:
        segments: list[MessageSegment] = []
        for item in chain or []:
            item_type = item.get("type", "")
            if item_type == "Plain":
                text = item.get("text", "")
                if text:
                    segments.append(MessageSegment("text", {"text": text}))
            elif item_type == "At":
                segments.append(
                    MessageSegment("at", {"user_id": str(item.get("target", ""))})
                )
            elif item_type == "Image":
                segments.append(
                    MessageSegment(
                        "image",
                        {
                            "file": item.get("imageId", ""),
                            "url": item.get("url", ""),
                        },
                    )
                )
            elif item_type == "Quote":
                segments.append(
                    MessageSegment(
                        "reply",
                        {"message_id": str(item.get("id", ""))},
                    )
                )
            elif item_type == "Face":
                segments.append(
                    MessageSegment("face", {"id": item.get("faceId", 0)})
                )
        return segments or [MessageSegment("text", {"text": ""})]

    @staticmethod
    def _to_chain(message: str | Message | MessageSegment) -> list[dict[str, Any]]:
        if isinstance(message, MessageSegment):
            message = Message.from_segments([message])
        elif isinstance(message, str):
            message = Message.text(message)
        chain: list[dict[str, Any]] = []
        for segment in message.segments:
            if segment.type == "text":
                chain.append(
                    {"type": "Plain", "text": segment.data.get("text", "")}
                )
            elif segment.type == "at":
                try:
                    target = int(segment.data.get("user_id", 0) or 0)
                except (TypeError, ValueError):
                    target = 0
                chain.append({"type": "At", "target": target})
            elif segment.type == "image":
                chain.append(
                    {
                        "type": "Image",
                        "path": segment.data.get("file", ""),
                    }
                )
            elif segment.type in {"voice", "record"}:
                chain.append(
                    {
                        "type": "Voice",
                        "path": segment.data.get("file", "")
                        or segment.data.get("url", ""),
                    }
                )
            elif segment.type == "file":
                chain.append(
                    {
                        "type": "File",
                        "path": segment.data.get("file", ""),
                        "name": segment.data.get("name", ""),
                    }
                )
            elif segment.type == "reply":
                chain.append(
                    {"type": "Quote", "id": int(segment.data.get("message_id", 0) or 0)}
                )
            else:
                chain.append({"type": segment.type, **segment.data})
        return chain

    async def send_group_message(
        self, group_id: str, message: str | Message | MessageSegment
    ) -> bool:
        return await self._send(
            "sendGroupMessage",
            {"target": int(group_id), "messageChain": self._to_chain(message)},
        )

    async def send_private_message(
        self, user_id: str, message: str | Message | MessageSegment
    ) -> bool:
        return await self._send(
            "sendFriendMessage",
            {"target": int(user_id), "messageChain": self._to_chain(message)},
        )

    async def _send(self, action: str, params: dict[str, Any]) -> bool:
        try:
            await self._ensure_session()
            response = await self._http_client().post(
                f"{self.api_base}/{action}",
                json={"sessionKey": self._session_key, **params},
            )
            response.raise_for_status()
            return response.json().get("code") in (0, None)
        except Exception:
            logger.exception("mirai send failed: %s", action)
            return False
