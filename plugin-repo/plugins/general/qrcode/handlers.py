"""qrcode 插件处理器：/qrcode 生成二维码。"""

from __future__ import annotations

from app.core.messages import Message, MessageEvent
from app.core.plugin import PluginContext

_ctx: PluginContext | None = None


def setup(ctx: PluginContext) -> None:
    global _ctx
    _ctx = ctx


async def qrcode_command(
    event: MessageEvent, args: Message, command_ctx
) -> None:
    text = args.extract_plain_text().strip()
    if not text:
        await event.reply("用法：/qrcode <内容>")
        return
    try:
        import qrcode
    except ImportError:
        await event.reply("缺少依赖：请执行 pip install qrcode")
        return
    files = _ctx.services.get("files")
    if files is None:
        await event.reply("文件服务不可用")
        return
    img = qrcode.make(text)
    path = files.base_dir / "qrcode.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    await event.reply(str(path))
