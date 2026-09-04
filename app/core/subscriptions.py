from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.core.bus import get_bus
from app.core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class SubscriptionEntry:
    plugin_name: str
    handler: Callable
    active: bool = True


class EventSubscriptionRegistry:
    def __init__(self) -> None:
        self.bus = get_bus()
        self._entries: dict[Any, list[SubscriptionEntry]] = {}
        self._forwarders: dict[Any, Callable] = {}

    def subscribe(
        self,
        event_type: Any,
        handler: Callable,
        plugin_name: str,
    ) -> SubscriptionEntry:
        entry = SubscriptionEntry(plugin_name, handler)
        self._entries.setdefault(event_type, []).append(entry)
        self._ensure_forwarder(event_type)
        return entry

    def unsubscribe_plugin(self, plugin_name: str) -> int:
        removed = 0
        for event_type in list(self._entries):
            original = self._entries[event_type]
            filtered = [
                entry for entry in original
                if entry.plugin_name != plugin_name
            ]
            removed += len(original) - len(filtered)
            if filtered:
                self._entries[event_type] = filtered
            else:
                del self._entries[event_type]
        return removed

    def _ensure_forwarder(self, event_type: Any) -> None:
        if event_type in self._forwarders:
            return

        async def forward(event: Any) -> None:
            for entry in list(self._entries.get(event_type, [])):
                if not entry.active:
                    continue
                try:
                    result = entry.handler(event)
                    if hasattr(result, "__await__"):
                        await result
                except Exception:
                    logger.exception(
                        "event handler failed plugin=%s event=%s",
                        entry.plugin_name,
                        event_type,
                    )

        self._forwarders[event_type] = forward
        self.bus.on(event_type, forward)
