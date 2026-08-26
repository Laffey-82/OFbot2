from __future__ import annotations

from app.core.events import NoticeReceived
from app.core.plugin import Plugin, PluginContext


class WelcomePlugin(Plugin):
    def setup(self, ctx: PluginContext) -> None:
        text = ctx.config.get("text", "欢迎新成员！输入 /help 查看指令")

        async def on_notice(event: NoticeReceived) -> None:
            if event.notice_type in {"group_increase", "group_admin_set"}:
                await ctx.send_group(event.group_id, text)

        ctx.subscribe(NoticeReceived, on_notice)


def create_plugin() -> Plugin:
    return WelcomePlugin()
