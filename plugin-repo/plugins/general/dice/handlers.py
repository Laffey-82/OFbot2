"""dice 插件处理器：/roll [面数]。"""

from __future__ import annotations

import random

from app.core.messages import Message, MessageEvent
from app.core.plugin import PluginContext

_ctx: PluginContext | None = None


def setup(ctx: PluginContext) -> None:
    global _ctx
    _ctx = ctx


async def roll_command(
    event: MessageEvent, args: Message, command_ctx
) -> None:
    params = getattr(command_ctx, "params", None) or {}
    faces = int(params.get("faces") or 100)
    faces = max(2, min(faces, 100000))
    result = random.randint(1, faces)
    await event.reply(f"🎲 掷出了 {result}（1-{faces}）")
