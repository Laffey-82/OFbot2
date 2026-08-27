from __future__ import annotations

import sys
import importlib.util
from pathlib import Path

_handlers_path = Path(__file__).resolve().parents[1] / "handlers.py"
_spec = importlib.util.spec_from_file_location("calc_handlers_test", _handlers_path)
handlers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(handlers)

from app.core.messages import Message, MessageEvent  # noqa: E402
_eval = handlers._eval
calc_command = handlers.calc_command


def test_eval_whitelist() -> None:
    assert _eval(__import__("ast").parse("1+2*3", mode="eval")) == 7
    assert _eval(__import__("ast").parse("2**10", mode="eval")) == 1024
    assert _eval(__import__("ast").parse("-5", mode="eval")) == -5


class FakeEvent:
    def __init__(self) -> None:
        self.replies: list[str] = []

    async def reply(self, content: str) -> None:
        self.replies.append(content)


async def test_calc_command_replies_result() -> None:
    event = FakeEvent()
    await calc_command(event, Message("1+2*3"), None)
    assert event.replies and "1+2*3 = 7" in event.replies[0]


async def test_calc_command_invalid_expression() -> None:
    event = FakeEvent()
    await calc_command(event, Message("__import__('os')"), None)
    assert event.replies and "表达式无效" in event.replies[0]
