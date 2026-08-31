from __future__ import annotations

import logging

import pytest

from app.adapters.base import BotClient
from app.core.bus import get_bus, reset_bus
from app.core.commands import CommandRegistry, command_registry
from app.core.logger import (
    TraceIdFilter,
    get_logger,
    set_trace_id,
    trace_id_var,
)
from app.core.messages import (
    GroupMessageEvent,
    Message,
    MessageSegment,
    Sender,
)
from app.core.security import SecurityPolicy


class CaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def test_trace_id_contextvar() -> None:
    assert trace_id_var.get() == ""
    value = set_trace_id()
    assert len(value) == 12
    assert trace_id_var.get() == value
    set_trace_id("abc")
    assert trace_id_var.get() == "abc"
    set_trace_id("")
    assert trace_id_var.get() == ""


def test_trace_id_injected_into_log_records() -> None:
    logger = get_logger("test-trace")
    logger.setLevel(logging.DEBUG)
    handler = CaptureHandler()
    handler.addFilter(TraceIdFilter())
    handler.setFormatter(logging.Formatter("%(trace_id)s"))
    logger.addHandler(handler)
    try:
        set_trace_id("t12345678901")
        logger.info("hello")
        set_trace_id("")
        assert handler.records
        assert handler.records[-1].trace_id == "t12345678901"
    finally:
        logger.removeHandler(handler)
        set_trace_id("")


def make_event() -> GroupMessageEvent:
    replies: list[str] = []
    event = GroupMessageEvent(
        bot_id="test",
        self_id="10",
        raw_event={},
        message_id="1",
        user_id="1",
        sender=Sender("1", "tester"),
        message=Message("/trace"),
        group_id="2",
    )

    async def reply(message: str | Message | MessageSegment) -> None:
        replies.append(str(message))

    event.reply = reply
    return event


@pytest.mark.asyncio
async def test_handle_bot_event_sets_trace_and_command_context() -> None:
    registry = CommandRegistry()
    registry.set_command_start(["/"])
    registry.set_security(SecurityPolicy())
    seen: dict[str, str] = {}

    async def handler(event, args, command_ctx) -> None:
        seen["trace"] = command_ctx.trace_id
        await event.reply("ok")

    registry.register("trace", handler, permission="bot.command")
    original = command_registry.handle_message
    command_registry.handle_message = registry.handle_message
    try:
        client = BotClient()
        event = make_event()
        await client.handle_bot_event(event)
        assert seen["trace"]
        assert getattr(event, "trace_id", "") == seen["trace"]
        assert trace_id_var.get() == ""  # 处理完恢复
    finally:
        command_registry.handle_message = original
        await get_bus().stop(clear=True)
        await reset_bus()
