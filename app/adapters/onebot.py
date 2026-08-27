from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

import httpx
import websockets
from fastapi import WebSocket

from app.adapters.base import BaseAdapter, BotClient, make_http_client
from app.core.bus import get_bus
from app.core.config import ConnectionSettings, OneBotSettings
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


class OneBotAdapter(BaseAdapter):
    def __init__(
        self,
        settings: OneBotSettings | ConnectionSettings,
        bot_id: str,
        bot_client: BotClient,
    ) -> None:
        super().__init__(settings, bot_client)
        self.settings = settings
        self.bot_id = bot_id
        self.self_id = ""
        self._ws: Any = None
        self._reverse_connections: list[Any] = []
        self._http: httpx.AsyncClient | None = None
        self._mode = getattr(settings, "mode", "forward")
        self.reverse_path = getattr(settings, "path", "/onebot/v11/ws")
        self.http_path = "/onebot/v11/http"

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
                    "self_id": getattr(self.settings, "self_id", ""),
                    "connected_at": time.time(),
                    "mode": "http",
                }
            return
        await self.run_reconnect_loop(self._connect_forward, self.bot_id)

    async def test(self) -> tuple[bool, str]:
        """尝试连接验证配置：正向 WS 握手 / HTTP 调 get_login_info。"""
        if self._is_http():
            url = f"http://{self.settings.host}:{self.settings.port}/get_login_info"
            try:
                async with make_http_client(5) as client:
                    response = await client.post(url, json={})
                    response.raise_for_status()
                    return True, "HTTP API 连接成功"
            except Exception as exc:
                return False, str(exc)
        if not self._is_forward():
            return False, "反向模式不支持主动测试，请检查 NapCat 是否已连接本服务"
        url = f"ws://{self.settings.host}:{self.settings.port}{self.settings.path}"
        headers = {}
        if self.settings.access_token:
            headers["Authorization"] = f"Bearer {self.settings.access_token}"
        connect_kwargs: dict[str, Any] = {}
        if headers:
            connect_kwargs["additional_headers"] = headers
        try:
            async with websockets.connect(url, open_timeout=5, **connect_kwargs):
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
        connect_kwargs: dict[str, Any] = {}
        if headers:
            connect_kwargs["additional_headers"] = headers
        async with websockets.connect(url, **connect_kwargs) as ws:
            self._ws = ws
            self._reconnects += 1
            self.bot_client.status[self.bot_id] = "connected"
            self.bot_client.details[self.bot_id] = {
                "self_id": "",
                "connected_at": time.time(),
                "reconnects": self._reconnects,
            }
            await self.recv_loop(ws, self._handle_raw, self.bot_id)

    async def handle_reverse_ws(self, websocket: WebSocket) -> None:
        await websocket.accept()
        if self.settings.access_token:
            token = websocket.headers.get("authorization", "")
            expected = f"Bearer {self.settings.access_token}"
            if token != expected:
                await websocket.close(code=1008)
                return
        self._ws = websocket
        self._reverse_connections.append(websocket)
        self._reconnects += 1
        self.bot_client.status[self.bot_id] = "connected"
        self.bot_client.details[self.bot_id] = {
            "self_id": "",
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
        """OneBot v11 反向 HTTP 事件入口（NapCat 将事件 POST 到本服务）。"""
        if self.bot_id in self.bot_client.details:
            self.bot_client.details[self.bot_id]["last_heartbeat"] = time.time()
        post_type = data.get("post_type")
        if post_type == "message":
            await self._handle_message(data)
        elif post_type in {"notice", "request"}:
            await self._handle_notice_or_request(data)

    async def _handle_raw(self, raw: str) -> None:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return
        if self.bot_id in self.bot_client.details:
            self.bot_client.details[self.bot_id]["last_heartbeat"] = time.time()
        post_type = data.get("post_type")
        if post_type == "message":
            await self._handle_message(data)
        elif post_type in {"notice", "request"}:
            await self._handle_notice_or_request(data)

    async def _handle_notice_or_request(self, data: dict[str, Any]) -> None:
        from app.core.bus import get_bus
        from app.core.events import RequestReceived

        post_type = data.get("post_type")
        if post_type == "notice":
            self._dispatch_notice(data)
        elif post_type == "request":
            get_bus().dispatch(
                RequestReceived(
                    bot_id=self.bot_id,
                    self_id=self.self_id,
                    request_type=data.get("request_type", ""),
                    user_id=str(data.get("user_id", "")),
                    group_id=str(data.get("group_id", "")),
                    flag=data.get("flag", ""),
                    raw_event=data,
                )
            )

    def _dispatch_notice(self, data: dict[str, Any]) -> None:
        """按 notice_type 分发细分事件：戳一戳 / 群文件上传 / 撤回。"""
        from app.core.bus import get_bus
        from app.core.events import (
            FileUploaded,
            GroupPoke,
            MessageRecalled,
            NoticeReceived,
        )

        notice_type = data.get("notice_type", "")
        common = {
            "bot_id": self.bot_id,
            "self_id": self.self_id,
            "notice_type": notice_type,
            "user_id": str(data.get("user_id", "")),
            "group_id": str(data.get("group_id", "")),
            "operator_id": str(data.get("operator_id", "")),
            "target_id": str(data.get("target_id", "")),
            "file_name": "",
            "file_size": 0,
            "raw_event": data,
        }
        if notice_type == "poke":
            get_bus().dispatch(GroupPoke(**common))
        elif notice_type == "group_upload":
            file_info = data.get("file", {}) or {}
            common["file_name"] = str(file_info.get("name", ""))
            try:
                common["file_size"] = int(file_info.get("size", 0) or 0)
            except (TypeError, ValueError):
                common["file_size"] = 0
            get_bus().dispatch(FileUploaded(**common))
        elif notice_type in {"group_recall", "friend_recall"}:
            get_bus().dispatch(
                MessageRecalled(
                    bot_id=self.bot_id,
                    self_id=self.self_id,
                    message_id=str(data.get("message_id", "")),
                    user_id=str(data.get("user_id", "")),
                    group_id=str(data.get("group_id", "")),
                    operator_id=str(data.get("operator_id", "")),
                    raw_event=data,
                )
            )
        else:
            get_bus().dispatch(NoticeReceived(**common))

    async def _handle_message(self, data: dict[str, Any]) -> None:
        message_type = data.get("message_type")
        if message_type not in {"group", "private"}:
            return
        user_id = str(data.get("user_id", ""))
        sender_data = data.get("sender", {})
        nickname = sender_data.get("nickname") or sender_data.get("card") or user_id
        card = sender_data.get("card")
        message = self._parse_message(data.get("message", ""), data.get("raw_message", ""))
        at_self = any(
            segment.type == "at"
            and str(segment.data.get("user_id", "")) == str(self.self_id)
            for segment in message.segments
        )

        async def reply(content: str | Message | MessageSegment) -> None:
            if message_type == "group":
                await self.send_group_message(str(data.get("group_id", "")), content)
            else:
                await self.send_private_message(user_id, content)

        if message_type == "group":
            event = GroupMessageEvent(
                bot_id=self.bot_id,
                self_id=self.self_id,
                raw_event=data,
                message_id=str(data.get("message_id", "")),
                user_id=user_id,
                sender=Sender(user_id, nickname, card),
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
                sender=Sender(user_id, nickname, card),
                message=message,
                at_self=at_self,
            )
        event.reply = reply
        await self.bot_client.handle_bot_event(event)

    def _parse_message(self, message_data: Any, raw_message: str = "") -> Message:
        if isinstance(message_data, str):
            return self._parse_cq(message_data)
        if isinstance(message_data, list):
            segments: list[MessageSegment] = []
            for item in message_data:
                if not isinstance(item, dict):
                    continue
                item_type = item.get("type", "")
                item_data = item.get("data", {})
                segments.append(MessageSegment(item_type, item_data))
            return Message.from_segments(segments)
        return Message(raw_message)

    def _parse_cq(self, text: str) -> Message:
        segments: list[MessageSegment] = []
        pattern = re.compile(r"\[CQ:([a-zA-Z0-9_-]+),([^\]]+)\]")
        pos = 0
        for match in pattern.finditer(text):
            if match.start() > pos:
                segments.append(MessageSegment("text", {"text": text[pos : match.start()]}))
            cq_type = match.group(1)
            data = {}
            for part in match.group(2).split(","):
                if "=" in part:
                    key, value = part.split("=", 1)
                    data[key.strip()] = value.strip()
            segments.append(MessageSegment(cq_type, data))
            pos = match.end()
        if pos < len(text):
            segments.append(MessageSegment("text", {"text": text[pos:]}))
        return Message.from_segments(segments)

    async def send_group_message(
        self, group_id: str, message: str | Message | MessageSegment
    ) -> bool:
        return await self._send_action(
            "send_group_msg",
            {"group_id": int(group_id), "message": self._to_array(message)},
        )

    async def send_private_message(
        self, user_id: str, message: str | Message | MessageSegment
    ) -> bool:
        return await self._send_action(
            "send_private_msg",
            {"user_id": int(user_id), "message": self._to_array(message)},
        )

    def _to_array(self, message: str | Message | MessageSegment) -> list[dict[str, Any]]:
        """统一消息段 → OneBot v11 消息数组（规避 CQ 码转义问题）。"""
        if isinstance(message, MessageSegment):
            message = Message.from_segments([message])
        elif isinstance(message, str):
            message = Message.text(message)
        parts: list[dict[str, Any]] = []
        for segment in message.segments:
            item = self._segment_to_onebot(segment)
            if item is not None:
                parts.append(item)
        if not parts:
            parts.append({"type": "text", "data": {"text": ""}})
        return parts

    @staticmethod
    def _segment_to_onebot(segment: MessageSegment) -> dict[str, Any] | None:
        stype = segment.type
        data = segment.data
        if stype == "text":
            return {"type": "text", "data": {"text": data.get("text", "")}}
        if stype == "at":
            return {"type": "at", "data": {"qq": str(data.get("user_id", ""))}}
        if stype == "image":
            return {
                "type": "image",
                "data": {"file": data.get("file") or data.get("url", "")},
            }
        if stype in {"voice", "record"}:
            return {
                "type": "record",
                "data": {"file": data.get("file") or data.get("url", "")},
            }
        if stype == "video":
            return {
                "type": "video",
                "data": {"file": data.get("file") or data.get("url", "")},
            }
        if stype == "file":
            return {"type": "file", "data": {"file": data.get("file", "")}}
        if stype == "face":
            return {"type": "face", "data": {"id": data.get("id", 0)}}
        if stype == "reply":
            return {
                "type": "reply",
                "data": {"id": data.get("message_id", "")},
            }
        if stype == "forward":
            return {"type": "forward", "data": {"id": data.get("id", "")}}
        if stype == "markdown":
            return {
                "type": "markdown",
                "data": {"content": data.get("content", "")},
            }
        if stype == "json":
            return {"type": "json", "data": {"data": data.get("data", {})}}
        logger.warning("onebot v11 未知消息段类型：%s", stype)
        return {"type": stype, "data": dict(data)}

    async def _send_action(self, action: str, params: dict[str, Any]) -> bool:
        if self._is_http():
            url = f"http://{self.settings.host}:{self.settings.port}/{action}"
            headers = {}
            token = getattr(self.settings, "access_token", "")
            if token:
                headers["Authorization"] = f"Bearer {token}"
            try:
                response = await self._http_client().post(
                    url, json=params, headers=headers
                )
                response.raise_for_status()
                return True
            except Exception:
                logger.exception("onebot http action failed: %s", action)
                return False
        payload = json.dumps(
            {
                "action": action,
                "params": params,
                "echo": str(asyncio.get_running_loop().time()),
            }
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
                logger.exception("onebot send action failed: %s", action)
        if self._ws is not None:
            try:
                if hasattr(self._ws, "send_text"):
                    await self._ws.send_text(payload)
                else:
                    await self._ws.send(payload)
                sent = True
            except Exception:
                logger.exception("onebot send action failed: %s", action)
        return sent
