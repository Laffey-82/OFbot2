"""example_ai 插件处理器：/ask 调用统一 AI 能力。"""

from __future__ import annotations

from app.core.messages import Message, MessageEvent
from app.core.plugin import PluginContext

_ctx: PluginContext | None = None


def setup(ctx: PluginContext) -> None:
    global _ctx
    _ctx = ctx


async def ask_command(
    event: MessageEvent, args: Message, command_ctx
) -> None:
    prompt = args.extract_plain_text().strip()
    if not prompt:
        await event.reply("用法：/ask <问题>")
        return
    try:
        answer = await _ctx.ai.chat(
            [
                {
                    "role": "system",
                    "content": _ctx.config.get(
                        "system_prompt", "你是一个友好的机器人助手。"
                    ),
                },
                {"role": "user", "content": prompt},
            ]
        )
        await event.reply(answer)
    except Exception:
        await event.reply("AI 服务暂不可用，请先配置 Provider 或稍后再试。")
