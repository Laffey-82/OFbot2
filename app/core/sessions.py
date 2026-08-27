"""轻量多轮会话上下文：pending / confirm / clear，TTL 过期。

以 bot_id + 群/私聊 + 用户 为键，用于「删除确认」「AI 多轮追问」等交互。
进程内实现并设容量上限，避免内存无限增长。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from app.core.logger import get_logger

logger = get_logger(__name__)


def session_key(bot_id: str, group_id: str, user_id: str) -> str:
    return f"{bot_id or ''}:{group_id or 'private'}:{user_id or ''}"


@dataclass
class ChatSession:
    """单个会话上下文。"""

    key: str
    bot_id: str = ""
    group_id: str = ""
    user_id: str = ""
    pending: str | None = None
    state: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def touch(self) -> None:
        self.updated_at = time.time()

    async def ask(self, question: str) -> str:
        """设置待确认状态并返回引导文案。"""
        self.pending = question
        self.touch()
        return f"{question}（发送「确认」继续，或发送「取消」放弃）"

    async def confirm(self) -> bool:
        """确认当前待确认操作并清除。"""
        if not self.pending:
            return False
        self.pending = None
        self.touch()
        return True

    async def cancel(self) -> bool:
        if not self.pending:
            return False
        self.pending = None
        self.touch()
        return True

    async def clear(self) -> None:
        self.pending = None
        self.state.clear()
        self.touch()


class SessionManager:
    """会话管理器：按需创建、TTL 清理、容量上限。"""

    def __init__(
        self, *, ttl_seconds: float = 600.0, max_sessions: int = 1000
    ) -> None:
        self.ttl_seconds = max(30.0, float(ttl_seconds))
        self.max_sessions = max(2, int(max_sessions))
        self._sessions: dict[str, ChatSession] = {}

    def get(
        self,
        bot_id: str = "",
        group_id: str = "",
        user_id: str = "",
        *,
        create: bool = True,
    ) -> ChatSession | None:
        key = session_key(bot_id, group_id, user_id)
        session = self._sessions.get(key)
        if session is None and create:
            self.prune()
            if len(self._sessions) >= self.max_sessions:
                # 容量满时淘汰最久未更新的会话
                oldest = min(
                    self._sessions.values(),
                    key=lambda item: item.updated_at,
                    default=None,
                )
                if oldest is not None:
                    self._sessions.pop(oldest.key, None)
            session = ChatSession(
                key=key,
                bot_id=bot_id,
                group_id=group_id,
                user_id=user_id,
            )
            self._sessions[key] = session
        if session is not None:
            session.touch()
        return session

    def prune(self, now: float | None = None) -> int:
        now = time.time() if now is None else now
        expired = [
            key
            for key, session in self._sessions.items()
            if now - session.updated_at > self.ttl_seconds
        ]
        for key in expired:
            self._sessions.pop(key, None)
        return len(expired)

    def remove(self, key: str) -> bool:
        return self._sessions.pop(key, None) is not None

    def active_count(self) -> int:
        self.prune()
        return len(self._sessions)


session_manager = SessionManager()
