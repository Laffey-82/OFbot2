"""system_status 插件处理器：/system 系统状态。"""

from __future__ import annotations

from app.core.messages import Message, MessageEvent
from app.core.plugin import PluginContext

_ctx: PluginContext | None = None


def setup(ctx: PluginContext) -> None:
    global _ctx
    _ctx = ctx


async def system_command(
    event: MessageEvent, args: Message, command_ctx
) -> None:
    manager = _ctx.services.get("plugin_manager")
    count = len(manager.get_loaded_plugins()) if manager else 0
    await event.reply(f"OFbot 2 运行正常\n已加载插件：{count}")
