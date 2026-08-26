"""template 插件声明式命令 / 任务 / 监听处理器。"""

from __future__ import annotations

from app.core.events import GroupMessageReceived
from app.core.messages import Message, MessageEvent
from app.core.plugin import PluginContext

_ctx: PluginContext | None = None


def setup(ctx: PluginContext) -> None:
    global _ctx
    _ctx = ctx


async def ping_command(
    event: MessageEvent, args: Message, command_ctx
) -> None:
    greeting = _ctx.config.get("greeting", "你好")
    await event.reply(
        f"{greeting}，pong！参数：{args.extract_plain_text() or '（空）'}"
    )


async def on_group_message(event: GroupMessageReceived) -> None:
    if event.message == "template:echo":
        await _ctx.bot.send_group_message(event.group_id, "template echo")


async def daily_task() -> None:
    """由 plugin.json features.tasks 声明，按目标环境功能开关门控执行。"""
    _ctx.logger.info("template daily task triggered")
