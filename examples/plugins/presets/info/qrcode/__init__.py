from __future__ import annotations

from app.core.messages import Message, MessageEvent
from app.core.plugin import Plugin, PluginContext


class QrCodePlugin(Plugin):
    def setup(self, ctx: PluginContext) -> None:
        @ctx.commands.command("qrcode", aliases={"二维码"}, permission="qrcode.use", plugin_name=ctx.name)
        async def qrcode(event: MessageEvent, args: Message, command_ctx) -> None:
            text = args.extract_plain_text().strip()
            if not text:
                await event.reply("用法：/qrcode <内容>")
                return
            try:
                import qrcode
            except ImportError:
                await event.reply("缺少依赖：请执行 pip install qrcode")
                return
            img = qrcode.make(text)
            path = ctx.services["files"].base_dir / "qrcode.png"
            img.save(path)
            await event.reply(str(path))


def create_plugin() -> Plugin:
    return QrCodePlugin()
