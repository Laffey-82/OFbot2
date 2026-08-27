"""random_choice 插件：/choose 随机选择。"""

from __future__ import annotations

import random

from app.core.messages import Message, MessageEvent
from app.core.plugin import PluginContext

_ctx: PluginContext | None = None


def setup(ctx: PluginContext) -> None:
    global _ctx
    _ctx = ctx


async def choose_command(
    event: MessageEvent, args: Message, command_ctx
) -> None:
    params = getattr(command_ctx, "params", None) or {}
    items = [
        item.strip()
        for item in str(params.get("items", "")).replace("，", ",").replace(" ", ",").split(",")
        if item.strip()
    ]
    if len(items) < 2:
        await event.reply("至少提供两个选项，用空格或逗号分隔，如：/choose 火锅 烧烤")
        return
    await event.reply(f"我选：{random.choice(items)} 🎲")
