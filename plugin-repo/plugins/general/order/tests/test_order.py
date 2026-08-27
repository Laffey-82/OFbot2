from __future__ import annotations

import sys
import importlib.util
from pathlib import Path

_handlers_path = Path(__file__).resolve().parents[1] / "handlers.py"
_spec = importlib.util.spec_from_file_location("order_handlers_test", _handlers_path)
handlers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(handlers)

from app.core.messages import Message  # noqa: E402
from app.services.preset_utils import JsonStore  # noqa: E402
order_command = handlers.order_command
setup = handlers.setup


class FakeEvent:
    def __init__(self) -> None:
        self.replies: list[str] = []

    async def reply(self, content: str) -> None:
        self.replies.append(content)


async def test_order_crud(tmp_path) -> None:
    setup(object())
    _store = handlers._store

    _store._data = {}
    _store.path = tmp_path / "order.json"

    event = FakeEvent()
    await order_command(event, Message("add 代打 50"), None)
    assert event.replies and "订单已创建" in event.replies[0]

    event2 = FakeEvent()
    await order_command(event2, Message("list"), None)
    assert event2.replies and "代打" in event2.replies[0]
    order_id = event.replies[0].split("：")[-1].strip()

    event3 = FakeEvent()
    await order_command(event3, Message(f"done {order_id}"), None)
    assert event3.replies and "订单已完成" in event3.replies[0]

    event4 = FakeEvent()
    await order_command(event4, Message(f"delete {order_id}"), None)
    assert event4.replies and "订单已删除" in event4.replies[0]
