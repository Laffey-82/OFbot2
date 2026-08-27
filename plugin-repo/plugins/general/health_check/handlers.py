"""health_check 插件处理器：/health 健康检查。"""

from __future__ import annotations

from app.core.messages import Message, MessageEvent
from app.core.plugin import PluginContext

_ctx: PluginContext | None = None


def setup(ctx: PluginContext) -> None:
    global _ctx
    _ctx = ctx


async def health_command(
    event: MessageEvent, args: Message, command_ctx
) -> None:
    adapters = getattr(_ctx.bot, "status", {})
    await event.reply(f"健康检查通过\n适配器：{adapters}")
