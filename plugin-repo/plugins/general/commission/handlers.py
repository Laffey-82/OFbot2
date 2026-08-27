"""commission 插件处理器：/commission 分账计算。"""

from __future__ import annotations

from app.core.messages import Message, MessageEvent
from app.core.plugin import PluginContext
from app.services.preset_utils import format_money

_ctx: PluginContext | None = None


def setup(ctx: PluginContext) -> None:
    global _ctx
    _ctx = ctx


async def commission_command(
    event: MessageEvent, args: Message, command_ctx
) -> None:
    text = args.extract_plain_text().strip()
    try:
        price = float(text)
    except ValueError:
        await event.reply("用法：/commission <金额>")
        return
    config = _ctx.config or {}
    parts = [
        ("打手", float(config.get("打手", 0.68))),
        ("接单人", float(config.get("接单人", 0.18))),
        ("OF", float(config.get("OF", 0.09))),
        ("应急公款", float(config.get("应急公款", 0.05))),
    ]
    await event.reply(
        "\n".join(f"{name}：{format_money(price * ratio)}" for name, ratio in parts)
    )
