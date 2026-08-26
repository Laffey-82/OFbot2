from __future__ import annotations

from app.core.messages import Message, MessageEvent
from app.core.plugin import Plugin, PluginContext


class ExampleAIPlugin(Plugin):
    def setup(self, ctx: PluginContext) -> None:
        @ctx.commands.command(
            "ask",
            aliases={"问问"},
            permission="example_ai.ask",
            plugin_name=ctx.name,
            description="调用已配置的 AI Provider 回答问题（示例插件）",
        )
        async def ask(event: MessageEvent, args: Message, command_ctx) -> None:
            prompt = args.extract_plain_text().strip()
            if not prompt:
                await event.reply("用法：/ask <问题>")
                return
            try:
                answer = await ctx.ai.chat(
                    [
                        {"role": "system", "content": "你是一个友好的机器人助手。"},
                        {"role": "user", "content": prompt},
                    ]
                )
                await event.reply(answer)
            except Exception:
                await event.reply("AI 服务暂不可用，请先配置 Provider 或稍后再试。")


def create_plugin() -> Plugin:
    return ExampleAIPlugin()
