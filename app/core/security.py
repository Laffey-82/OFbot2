from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

from app.core.logger import get_logger

logger = get_logger(__name__)

_audit_persist_tasks: set[asyncio.Task[None]] = set()


class SlidingWindowRateLimiter:
    def __init__(self, max_windows: int = 10_000) -> None:
        self._windows: dict[str, deque[float]] = defaultdict(deque)
        self.max_windows = max_windows

    def allow(self, key: str, limit: int, window_seconds: float) -> bool:
        now = time.monotonic()
        window = self._windows[key]
        while window and window[0] <= now - window_seconds:
            window.popleft()
        if len(window) >= limit:
            return False
        window.append(now)
        self._trim()
        return True

    def _trim(self) -> None:
        if len(self._windows) <= self.max_windows:
            return
        now = time.monotonic()
        expired = [
            k for k, w in self._windows.items()
            if not w or w[-1] <= now - 3600
        ]
        for k in expired:
            self._windows.pop(k, None)
        if len(self._windows) > self.max_windows:
            excess = len(self._windows) - self.max_windows
            oldest = sorted(
                self._windows,
                key=lambda k: self._windows[k][0] if self._windows[k] else 0.0,
            )[:excess]
            for k in oldest:
                self._windows.pop(k, None)


@dataclass
class RateLimitSpec:
    limit: int
    window_seconds: float


def parse_rate_limit(value: str) -> RateLimitSpec:
    try:
        count, unit = value.strip().split("/", 1)
        count = int(count)
        multiplier = {
            "s": 1,
            "sec": 1,
            "second": 1,
            "m": 60,
            "min": 60,
            "minute": 60,
            "h": 3600,
            "hour": 3600,
        }[unit.lower()]
        return RateLimitSpec(count, float(multiplier))
    except Exception:
        return RateLimitSpec(20, 60)


class SecurityPolicy:
    def __init__(
        self,
        *,
        max_message_length: int = 2000,
        max_arg_length: int = 500,
        default_cooldown_seconds: float = 1.0,
        rate_limit_default: str = "20/minute",
        sensitive_words: list[str] | None = None,
        blocked_users: list[str] | None = None,
    ) -> None:
        self.max_message_length = max_message_length
        self.max_arg_length = max_arg_length
        self.default_cooldown_seconds = default_cooldown_seconds
        self.rate_limit_default = parse_rate_limit(rate_limit_default)
        self.sensitive_words = [word.lower() for word in (sensitive_words or [])]
        self.blocked_users = set(blocked_users or [])
        self.limiter = SlidingWindowRateLimiter()
        self._last_command: dict[str, float] = {}

    def validate_text(self, text: str) -> str | None:
        if len(text) > self.max_message_length:
            return "消息过长"
        if len(text) > self.max_arg_length:
            return "参数过长"
        lowered = text.lower()
        for word in self.sensitive_words:
            if word and word in lowered:
                return "消息包含敏感内容"
        return None

    def check_blocked(self, user_id: str) -> bool:
        return str(user_id) in self.blocked_users

    def check_rate(self, key: str, spec: RateLimitSpec | None = None) -> bool:
        spec = spec or self.rate_limit_default
        return self.limiter.allow(key, spec.limit, spec.window_seconds)

    def check_cooldown(self, key: str, cooldown: float) -> bool:
        now = time.monotonic()
        if now - self._last_command.get(key, 0.0) < cooldown:
            return False
        self._last_command[key] = now
        if len(self._last_command) > 10_000:
            self._evict_cooldown(now, cooldown)
        return True

    def _evict_cooldown(self, now: float, cooldown: float) -> None:
        expired = [k for k, t in self._last_command.items() if now - t >= cooldown]
        for k in expired:
            self._last_command.pop(k, None)
        if len(self._last_command) > 10_000:
            oldest_keys = sorted(
                self._last_command, key=lambda k: self._last_command[k]
            )[: len(self._last_command) - 10_000]
            for k in oldest_keys:
                self._last_command.pop(k, None)


def _on_audit_task_done(task: asyncio.Task[None]) -> None:
    _audit_persist_tasks.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.warning("audit persist task failed: %s", exc)


class AuditLogger:
    def __init__(self) -> None:
        self._events: deque[dict[str, Any]] = deque(maxlen=1000)
        self._persist_callback = None

    def set_persist_callback(self, callback: Any) -> None:
        self._persist_callback = callback

    def record(
        self,
        action: str,
        actor: str = "",
        *,
        target: str = "",
        success: bool = True,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self._events.appendleft(
            {
                "timestamp": time.time(),
                "action": action,
                "actor": actor,
                "target": target,
                "success": success,
                "detail": detail or {},
            }
        )
        logger.info(
            "audit action=%s actor=%s target=%s success=%s detail=%s",
            action,
            actor,
            target,
            success,
            detail or {},
        )
        if self._persist_callback is not None:
            try:
                task = asyncio.create_task(
                    self._persist_callback(
                        action=action,
                        actor=actor,
                        target=target,
                        success=success,
                        detail=detail or {},
                    )
                )
                _audit_persist_tasks.add(task)
                task.add_done_callback(_on_audit_task_done)
            except RuntimeError:
                pass

    def recent(self, limit: int = 100) -> list[dict[str, Any]]:
        return list(self._events)[:limit]


audit_logger = AuditLogger()
