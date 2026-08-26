from __future__ import annotations

from bubus import EventBus

_bus = EventBus(name="OFbot2", max_history_size=500)


def get_bus() -> EventBus:
    return _bus


def reset_bus() -> EventBus:
    global _bus
    _bus = EventBus(name="OFbot2", max_history_size=500)
    return _bus
