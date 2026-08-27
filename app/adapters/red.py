from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx
import websockets

from app.adapters.base import BaseAdapter, BotClient, make_http_client
from app.core.bus import get_bus
from app.core.config import ConnectionSettings, RedSettings
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


class RedAdapter(BaseAdapter):
    def __init__(
        self,
        settings: RedSettings | ConnectionSettings,
        bot_id: str,
        bot_client: BotClient,
    ) -> None:
        super().__init__(settings, bot_client)
        self.settings = settings
        self.bot_id = bot_id
        self.self_id = ""
        self._ws: Any = None
        self._http: httpx.AsyncClient | None = None

    def _http_client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = make_http_client(30.0)
        return self._http

    async def start(self) -> None:
        await self.run_reconnect_loop(self._connect_loop, self.bot_id)

    async def test(self) -> tuple[bool, str]:
        """尝试一次 Red WebSocket 握手，验证连接配置。"""
        url = f"ws://{self.settings.host}:{self.settings.port}/"
        try:
            async with websockets.connect(url, open_timeout=5) as ws:
                await ws.send(
                    json.dumps(
                        {
                            "type": "meta::connect",
                            "payload": {"token": self.settings.token},
                        }
                    )
                )
                data = json.loads(
                    await asyncio.wait_for(ws.recv(), timeout=5)
                )
                if data.get("type") == "meta::connect":
                    version = data.get("payload", {}).get("version", "?")
                    return True, f"连接成功，版本 {version}"
                return False, "握手响应异常"
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
        url = f"ws://{self.settings.host}:{self.settings.port}/"
        async with websockets.connect(url, ping_interval=20) as ws:
            self._ws = ws
            self._reconnects += 1
            await ws.send(
                json.dumps(
                    {
                        "type": "meta::connect",
                        "payload": {"token": self.settings.token},
                    }
                )
            )
            connect_data = json.loads(await ws.recv())
            auth_data = connect_data.get("payload", {}).get("authData", {})
            self.self_id = str(auth_data.get("uin", self.self_id))
            self.bot_client.status[self.bot_id] = "connected"
            self.bot_client.details[self.bot_id] = {
                "self_id": self.self_id,
                "connected_at": time.time(),
                "reconnects": self._reconnects,
                "version": connect_data.get("payload", {}).get("version", ""),
            }
            logger.info(
                "red adapter connected self_id=%s version=%s",
                self.self_id,
                connect_data.get("payload", {}).get("version", ""),
            )
            await self.recv_loop(ws, self._handle_raw, self.bot_id)

    async def _handle_raw(self, raw: str) -> None:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return
        if self.bot_id in self.bot_client.details:
            self.bot_client.details[self.bot_id]["last_heartbeat"] = time.time()
        if data.get("type") == "notice::recv":
            for item in data.get("payload", []):
                self._dispatch_notice(item)
            return
        if data.get("type") != "message::recv":
            return
        for item in data.get("payload", []):
            await self._handle_message(item)

    def _dispatch_notice(self, data: dict[str, Any]) -> None:
        """Red 通知载荷 best-effort 映射；未知载荷不丢弃，落 NoticeReceived。"""
        from app.core.bus import get_bus
        from app.core.events import (
            FileUploaded,
            GroupPoke,
            MessageRecalled,
            NoticeReceived,
        )

        notice_type = str(data.get("noticeType", "") or "")
        user_id = str(data.get("userUin") or data.get("senderUin") or "")
        group_id = str(data.get("peerUin") or data.get("peerUid") or "")
        operator_id = str(data.get("operatorUin") or "")
        target_id = str(data.get("targetUin") or "")
        common = {
            "bot_id": self.bot_id,
            "self_id": self.self_id,
            "notice_type": notice_type,
            "user_id": user_id,
            "group_id": group_id,
            "operator_id": operator_id,
            "target_id": target_id,
            "file_name": str(data.get("fileName", "") or ""),
            "file_size": int(data.get("fileSize", 0) or 0),
            "raw_event": data,
        }
        if "poke" in notice_type.lower():
            get_bus().dispatch(GroupPoke(**common))
        elif "upload" in notice_type.lower():
            get_bus().dispatch(FileUploaded(**common))
        elif "recall" in notice_type.lower():
            get_bus().dispatch(
                MessageRecalled(
                    bot_id=self.bot_id,
                    self_id=self.self_id,
                    message_id=str(data.get("msgId", "")),
                    user_id=user_id,
                    group_id=group_id,
                    operator_id=operator_id,
                    raw_event=data,
                )
            )
        else:
            get_bus().dispatch(NoticeReceived(**common))

    async def _handle_message(self, data: dict[str, Any]) -> None:
        chat_type = int(data.get("chatType", 0))
        if chat_type not in (1, 2):
            return
        sender_uin = str(data.get("senderUin") or data.get("senderUid") or "")
        peer_uin = str(data.get("peerUin") or data.get("peerUid") or "")
        nick = data.get("sendMemberName") or data.get("sendNickName") or sender_uin
        message_id = str(data.get("msgId", ""))
        raw_event = data
        segments = self._parse_segments(data.get("elements", []))
        message = Message.from_segments(segments)

        async def reply(content: str | Message | MessageSegment) -> None:
            if chat_type == 2:
                target = peer_uin
                await self.send_group_message(target, content)
            else:
                target = peer_uin
                await self.send_private_message(target, content)

        if chat_type == 2:
            group_id = peer_uin
            event = GroupMessageEvent(
                bot_id=self.bot_id,
                self_id=self.self_id,
                raw_event=raw_event,
                message_id=message_id,
                user_id=sender_uin,
                sender=Sender(sender_uin, nick),
                message=message,
                group_id=group_id,
                group_name=data.get("peerName"),
            )
        else:
            event = PrivateMessageEvent(
                bot_id=self.bot_id,
                self_id=self.self_id,
                raw_event=raw_event,
                message_id=message_id,
                user_id=peer_uin,
                sender=Sender(sender_uin, nick),
                message=message,
            )
        event.reply = reply
        await self.bot_client.handle_bot_event(event)

    def _parse_segments(self, elements: list[dict[str, Any]]) -> list[MessageSegment]:
        segments: list[MessageSegment] = []
        for element in elements:
            element_type = int(element.get("elementType", 0))
            if element_type == 1:
                text = element.get("textElement", {}).get("content", "")
                if text:
                    segments.append(MessageSegment("text", {"text": text}))
            elif element_type == 2:
                pic = element.get("picElement", {})
                segments.append(
                    MessageSegment(
                        "image",
                        {
                            "file": pic.get("sourcePath", ""),
                            "url": pic.get("sourcePath", ""),
                            "md5": pic.get("md5HexStr", ""),
                        },
                    )
                )
            elif element_type == 3:
                file = element.get("fileElement", {})
                segments.append(
                    MessageSegment(
                        "file",
                        {"file": file.get("filePath", ""), "name": file.get("fileName", "")},
                    )
                )
            elif element_type == 4:
                ptt = element.get("pttElement", {})
                segments.append(
                    MessageSegment(
                        "voice",
                        {"file": ptt.get("filePath", ""), "duration": ptt.get("duration", 0)},
                    )
                )
            elif element_type == 5:
                video = element.get("videoElement", {})
                segments.append(
                    MessageSegment(
                        "video",
                        {"file": video.get("filePath", ""), "name": video.get("fileName", "")},
                    )
                )
            elif element_type == 6:
                face = element.get("faceElement", {})
                segments.append(
                    MessageSegment("face", {"id": face.get("faceIndex", 0)})
                )
            elif element_type == 7:
                reply = element.get("replyElement", {})
                segments.append(
                    MessageSegment(
                        "reply",
                        {
                            "message_id": reply.get("replayMsgId", ""),
                            "user_id": reply.get("senderUin", ""),
                        },
                    )
                )
            else:
                segments.append(MessageSegment("json", {"data": element}))
        return segments or [MessageSegment("text", {"text": ""})]

    async def send_group_message(
        self, group_id: str, message: str | Message | MessageSegment
    ) -> bool:
        return await self._send_message(2, group_id, message)

    async def send_private_message(
        self, user_id: str, message: str | Message | MessageSegment
    ) -> bool:
        return await self._send_message(1, user_id, message)

    async def _send_message(
        self,
        chat_type: int,
        target: str,
        message: str | Message | MessageSegment,
    ) -> bool:
        if isinstance(message, MessageSegment):
            message = Message.from_segments([message])
        elif isinstance(message, str):
            message = Message.text(message)
        elements = self._to_elements(message)
        payload = {
            "peer": {"chatType": chat_type, "peerUin": str(target), "guildId": None},
            "elements": elements,
        }
        try:
            response = await self._http_client().post(
                f"{self.settings.api_base.rstrip('/')}/message/send",
                headers={"Authorization": f"Bearer {self.settings.token}"},
                json=payload,
            )
            if response.status_code != 200:
                logger.warning(
                    "red send_message failed status=%s body=%s",
                    response.status_code,
                    response.text,
                )
                return False
            return True
        except Exception:
            logger.exception("red send_message exception")
            return False

    @staticmethod
    def _to_elements(message: str | Message | MessageSegment) -> list[dict[str, Any]]:
        if isinstance(message, MessageSegment):
            message = Message.from_segments([message])
        elif isinstance(message, str):
            message = Message.text(message)
        elements: list[dict[str, Any]] = []
        for segment in message.segments:
            stype = segment.type
            data = segment.data
            if stype == "text":
                elements.append(
                    {"elementType": 1, "textElement": {"content": data.get("text", "")}}
                )
            elif stype == "at":
                elements.append(
                    {
                        "elementType": 7,
                        "atElement": {
                            "target": int(data.get("user_id", 0) or 0)
                        },
                    }
                )
            elif stype == "image":
                elements.append(
                    {
                        "elementType": 2,
                        "picElement": {
                            "sourcePath": data.get("file") or data.get("url", ""),
                            "md5HexStr": data.get("md5", ""),
                        },
                    }
                )
            elif stype in {"voice", "record"}:
                elements.append(
                    {
                        "elementType": 4,
                        "pttElement": {
                            "filePath": data.get("file") or data.get("url", "")
                        },
                    }
                )
            elif stype == "video":
                elements.append(
                    {
                        "elementType": 5,
                        "videoElement": {
                            "filePath": data.get("file") or data.get("url", ""),
                            "fileName": data.get("name", ""),
                        },
                    }
                )
            elif stype == "file":
                elements.append(
                    {
                        "elementType": 3,
                        "fileElement": {
                            "filePath": data.get("file", ""),
                            "fileName": data.get("name", ""),
                        },
                    }
                )
            elif stype == "face":
                elements.append(
                    {
                        "elementType": 6,
                        "faceElement": {"faceIndex": int(data.get("id", 0) or 0)},
                    }
                )
            elif stype == "reply":
                elements.append(
                    {
                        "elementType": 7,
                        "replyElement": {
                            "replayMsgId": data.get("message_id", ""),
                            "senderUin": data.get("user_id", ""),
                        },
                    }
                )
            else:
                elements.append(
                    {"elementType": 1, "textElement": {"content": str(segment)}}
                )
        return elements or [{"elementType": 1, "textElement": {"content": ""}}]
