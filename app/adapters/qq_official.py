"""QQ 官方机器人适配器（官方 API v2）：WS Gateway 收消息 + REST 发送。

限制：群聊仅接收 @ 机器人消息（GROUP_AT_MESSAGE_CREATE），存在官方频控。
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx
import websockets

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

GROUP_AT_MESSAGE_CREATE = "GROUP_AT_MESSAGE_CREATE"
C2C_MESSAGE_CREATE = "C2C_MESSAGE_CREATE"
GROUP_AND_C2C_EVENT = "GROUP_AND_C2C_EVENT"


class OfficialQQAdapter(BaseAdapter):
    def __init__(
        self, settings: ConnectionSettings, bot_id: str, bot_client: BotClient
    ) -> None:
        super().__init__(settings, bot_client)
        self.settings = settings
        self.bot_id = bot_id
        self.self_id = settings.self_id
        self._ws: Any = None
        self._http: httpx.AsyncClient | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self.api_base = (
            settings.api_base or "https://api.sgroup.qq.com"
        ).rstrip("/")

    def _http_client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = make_http_client(15.0)
        return self._http

    def _auth_header(self) -> str:
        return f"QQBot {self.settings.app_id}.{self.settings.token}"

    async def start(self) -> None:
        await self.run_reconnect_loop(self._connect_loop, self.bot_id)

    async def test(self) -> tuple[bool, str]:
        try:
            response = await self._http_client().get(
                f"{self.api_base}/gateway",
                headers={"Authorization": self._auth_header()},
            )
            response.raise_for_status()
            return True, "官方机器人网关鉴权成功"
        except Exception as exc:
            return False, str(exc)

    async def stop(self) -> None:
        self._running = False
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
            self._heartbeat_task = None
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
        response = await self._http_client().get(
            f"{self.api_base}/gateway",
            headers={"Authorization": self._auth_header()},
        )
        response.raise_for_status()
        gateway_url = (response.json().get("url") or "").strip()
        if not gateway_url:
            raise RuntimeError("gateway url 为空")
        async with websockets.connect(
            gateway_url, ping_interval=20
        ) as ws:
            self._ws = ws
            self._reconnects += 1
            self.bot_client.status[self.bot_id] = "connected"
            self._mark_connected()
            self.bot_client.details[self.bot_id] = {
                "self_id": self.self_id,
                "connected_at": time.time(),
                "reconnects": self._reconnects,
            }
            await ws.send(
                json.dumps(
                    {
                        "op": 2,
                        "d": {
                            "token": f"{self.settings.app_id}.{self.settings.token}",
                            "intents": 1 << 25,
                            "shard": [0, 1],
                        },
                    }
                )
            )
            try:
                await self.recv_loop(ws, self._handle_raw_frame, self.bot_id)
            finally:
                if self._heartbeat_task is not None:
                    self._heartbeat_task.cancel()
                    try:
                        await self._heartbeat_task
                    except asyncio.CancelledError:
                        pass
                    except Exception:
                        pass
                    self._heartbeat_task = None

    async def _handle_raw_frame(self, raw: str) -> None:
        try:
            data = json.loads(raw)
        except (TypeError, ValueError) as exc:
            logger.warning(
                "qq official 收到无法解析的帧，已跳过: %.120s (%s)", raw, exc
            )
            return
        op = data.get("op")
        if op == 10:
            interval = (
                data.get("d", {}).get("heartbeat_interval", 30000)
                or 30000
            )
            if self._heartbeat_task is not None:
                self._heartbeat_task.cancel()
            self._heartbeat_task = asyncio.create_task(
                self._heartbeat_loop(
                    self._ws, max(1, int(interval) / 1000)
                )
            )
        elif op == 0:
            await self._handle_event(data.get("d", {}))

    async def _heartbeat_loop(self, ws: Any, interval: float) -> None:
        while self._running:
            await asyncio.sleep(interval)
            try:
                await ws.send(json.dumps({"op": 1, "d": None}))
            except Exception:
                return

    async def _handle_event(self, payload: dict[str, Any]) -> None:
        if self.bot_id in self.bot_client.details:
            self.bot_client.details[self.bot_id]["last_heartbeat"] = time.time()
        event_type = payload.get("t", "")
        if event_type not in {GROUP_AT_MESSAGE_CREATE, C2C_MESSAGE_CREATE}:
            return
        data = payload.get("d", {}) or {}
        content = str(data.get("content", "") or "")
        content = content.removeprefix("#")
        message = Message.text(content)
        user = data.get("author", {}) or {}
        user_id = str(
            user.get("member_openid")
            or user.get("user_openid")
            or user.get("id", "")
        )

        if event_type == GROUP_AT_MESSAGE_CREATE:
            group_openid = str(data.get("group_openid", ""))

            async def reply(content: str | Message | MessageSegment) -> None:
                await self.send_group_message(group_openid, content)

            event = GroupMessageEvent(
                bot_id=self.bot_id,
                self_id=self.self_id,
                raw_event=data,
                message_id=str(data.get("id", "")),
                user_id=user_id,
                sender=Sender(user_id, str(user.get("username") or user_id)),
                message=message,
                group_id=group_openid,
                at_self=True,
            )
            event.reply = reply
            await self.bot_client.handle_bot_event(event)
        elif event_type == C2C_MESSAGE_CREATE:
            openid = user_id

            async def reply_private(
                content: str | Message | MessageSegment,
            ) -> None:
                await self.send_private_message(openid, content)

            event = PrivateMessageEvent(
                bot_id=self.bot_id,
                self_id=self.self_id,
                raw_event=data,
                message_id=str(data.get("id", "")),
                user_id=openid,
                sender=Sender(openid, str(user.get("username") or openid)),
                message=message,
            )
            event.reply = reply_private
            await self.bot_client.handle_bot_event(event)

    async def send_group_message(
        self, group_id: str, message: str | Message | MessageSegment
    ) -> bool:
        text = message.extract_plain_text() if isinstance(message, Message) else str(message)
        if isinstance(message, MessageSegment):
            text = message.data.get("text", "") or str(message)
        try:
            response = await self._http_client().post(
                f"{self.api_base}/v2/groups/{group_id}/messages",
                headers={"Authorization": self._auth_header()},
                json={"msg_type": 0, "content": text},
            )
            response.raise_for_status()
            return True
        except Exception:
            logger.exception("qq official group send failed")
            return False

    async def send_private_message(
        self, user_id: str, message: str | Message | MessageSegment
    ) -> bool:
        text = message.extract_plain_text() if isinstance(message, Message) else str(message)
        if isinstance(message, MessageSegment):
            text = message.data.get("text", "") or str(message)
        try:
            response = await self._http_client().post(
                f"{self.api_base}/v2/users/{user_id}/messages",
                headers={"Authorization": self._auth_header()},
                json={"msg_type": 0, "content": text},
            )
            response.raise_for_status()
            return True
        except Exception:
            logger.exception("qq official private send failed")
            return False
