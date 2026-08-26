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
    params = getattr(command_ctx, "params", None) or {}
    content = (
        params.get("content")
        if params
        else args.extract_plain_text().strip()
    )
    await event.reply(
        f"{greeting}，pong！参数：{content or '（空）'}"
    )


async def greet_command(
    event: MessageEvent, args: Message, command_ctx
) -> None:
    """子命令示例：/greet hello [target] ｜ /greet world [count]。"""
    subcommand = getattr(command_ctx, "subcommand", "")
    params = getattr(command_ctx, "params", None) or {}
    if subcommand == "hello":
        await event.reply(f"你好，{params.get('target', '世界')}！")
    elif subcommand == "world":
        count = max(1, int(params.get("count", 1) or 1))
        await event.reply("Hello World! " * count)
    else:
        await event.reply("用法：/greet hello|world")


async def on_group_message(event: GroupMessageReceived) -> None:
    if event.message == "template:echo":
        await _ctx.bot.send_group_message(event.group_id, "template echo")


async def daily_task() -> None:
    """由 plugin.json features.tasks 声明，按目标环境功能开关门控执行。"""
    _ctx.logger.info("template daily task triggered")
