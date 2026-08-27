from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class MessageSegment:
    type: str
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def text(cls, text: str) -> MessageSegment:
        return cls("text", {"text": text})

    @classmethod
    def at(cls, user_id: str | int) -> MessageSegment:
        return cls("at", {"user_id": str(user_id)})

    @classmethod
    def image(cls, file: str = "", url: str = "") -> MessageSegment:
        data: dict[str, Any] = {}
        if file:
            data["file"] = str(file)
        if url:
            data["url"] = str(url)
        return cls("image", data)

    @classmethod
    def voice(cls, file: str = "", url: str = "") -> MessageSegment:
        data: dict[str, Any] = {}
        if file:
            data["file"] = str(file)
        if url:
            data["url"] = str(url)
        return cls("voice", data)

    @classmethod
    def video(cls, file: str = "", url: str = "") -> MessageSegment:
        data: dict[str, Any] = {}
        if file:
            data["file"] = str(file)
        if url:
            data["url"] = str(url)
        return cls("video", data)

    @classmethod
    def record(cls, file: str = "", url: str = "") -> MessageSegment:
        data: dict[str, Any] = {}
        if file:
            data["file"] = str(file)
        if url:
            data["url"] = str(url)
        return cls("record", data)

    @classmethod
    def file(cls, file: str = "", name: str = "") -> MessageSegment:
        data: dict[str, Any] = {}
        if file:
            data["file"] = str(file)
        if name:
            data["name"] = str(name)
        return cls("file", data)

    @classmethod
    def face(cls, face_id: int | str = 0) -> MessageSegment:
        return cls("face", {"id": str(face_id)})

    @classmethod
    def reply(
        cls, message_id: str | int = "", user_id: str | int = ""
    ) -> MessageSegment:
        data: dict[str, Any] = {}
        if message_id:
            data["message_id"] = str(message_id)
        if user_id:
            data["user_id"] = str(user_id)
        return cls("reply", data)

    @classmethod
    def forward(cls, forward_id: str | int = "") -> MessageSegment:
        return cls("forward", {"id": str(forward_id)})

    @classmethod
    def markdown(cls, content: str = "") -> MessageSegment:
        return cls("markdown", {"content": content})

    @classmethod
    def json(cls, data: dict[str, Any] | str) -> MessageSegment:
        return cls("json", {"data": data})

    def __str__(self) -> str:
        if self.type == "text":
            return str(self.data.get("text", ""))
        if self.type == "at":
            return f"[@{self.data.get('user_id', '')}]"
        return f"[{self.type}]"


class Message:
    def __init__(self, content: str | Iterable[MessageSegment] | None = None):
        if content is None:
            self.segments: list[MessageSegment] = []
        elif isinstance(content, str):
            self.segments = [MessageSegment("text", {"text": content})]
        else:
            self.segments = list(content)

    @classmethod
    def text(cls, content: str) -> Message:
        return cls(content)

    @classmethod
    def from_segments(cls, segments: Iterable[MessageSegment]) -> Message:
        return cls(segments)

    def add_segment(self, segment: MessageSegment | str) -> Message:
        if isinstance(segment, str):
            segment = MessageSegment.text(segment)
        self.segments.append(segment)
        return self

    def __add__(self, other: str | MessageSegment | Message) -> Message:
        result = Message(list(self.segments))
        if isinstance(other, Message):
            result.segments.extend(other.segments)
        else:
            result.add_segment(other)
        return result

    def extract_plain_text(self) -> str:
        return "".join(segment.data.get("text", "") for segment in self.segments if segment.type == "text")

    def __str__(self) -> str:
        return "".join(str(segment) for segment in self.segments)

    def __len__(self) -> int:
        return len(self.extract_plain_text())


@dataclass(slots=True)
class Sender:
    user_id: str
    nickname: str | None = None
    card: str | None = None


@dataclass
class BotEvent:
    bot_id: str
    self_id: str
    raw_event: dict[str, Any]


@dataclass
class MessageEvent(BotEvent):
    message_id: str = ""
    user_id: str = ""
    sender: Sender | None = None
    message: Message = field(default_factory=Message)
    at_self: bool = False

    async def reply(self, message: str | Message | MessageSegment) -> None:
        raise NotImplementedError


@dataclass
class GroupMessageEvent(MessageEvent):
    group_id: str = ""
    group_name: str | None = None


@dataclass
class PrivateMessageEvent(MessageEvent):
    pass


@dataclass
class NoticeEvent(BotEvent):
    notice_type: str = ""
    user_id: str = ""
    group_id: str = ""


@dataclass
class RequestEvent(BotEvent):
    request_type: str = ""
    user_id: str = ""
    group_id: str = ""
    flag: str = ""
