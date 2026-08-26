from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class MessageSegment:
    type: str
    data: dict[str, Any] = field(default_factory=dict)

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
