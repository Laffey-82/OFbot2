"""事件总线封装：bubus EventBus 单例。"""

from __future__ import annotations

import os
import threading

from bubus import EventBus

_bus = EventBus(name="OFbot2", max_history_size=500)


def get_bus() -> EventBus:
    return _bus


def reset_bus() -> EventBus:
    global _bus
    _bus = EventBus(name="OFbot2", max_history_size=500)
    return _bus


def arm_hard_exit(timeout: float = 6.0) -> threading.Timer:
    """在独立线程中安排「超时强制退出」兜底。

    bubus 的 stop() 在高 pending 事件时可能同步阻塞事件循环，
    asyncio 超时无法救援；此定时器保证进程必然退出。
    """
    timer = threading.Timer(
        max(1.0, float(timeout)), lambda: os._exit(0)
    )
    timer.daemon = True
    timer.start()
    return timer
