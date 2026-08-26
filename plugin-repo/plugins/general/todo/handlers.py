"""todo 插件：基于通用记录（records）的个人待办，演示子命令 + 参数。"""

from __future__ import annotations

from app.core.messages import Message, MessageEvent
from app.core.plugin import PluginContext
from app.services.records import FieldSchema, RecordTypeSchema

_ctx: PluginContext | None = None


def setup(ctx: PluginContext) -> None:
    global _ctx
    _ctx = ctx
    ctx.records.schemas.register(
        RecordTypeSchema(
            "todo",
            [
                FieldSchema("user_id", "string", required=True),
                FieldSchema("text", "string", required=True),
                FieldSchema("done", "boolean", required=False),
            ],
            description="个人待办",
        )
    )


async def todo_command(
    event: MessageEvent, args: Message, command_ctx
) -> None:
    user_id = str(getattr(event, "user_id", "") or "")
    if not user_id:
        await event.reply("无法识别用户")
        return
    sub = getattr(command_ctx, "subcommand", "")
    params = getattr(command_ctx, "params", None) or {}
    mine = [
        item
        for item in await _ctx.records.list(record_type="todo", limit=1000)
        if item.data.get("user_id") == user_id
    ]
    if sub == "add":
        await _ctx.records.create(
            "todo",
            {"user_id": user_id, "text": params["content"], "done": False},
        )
        await event.reply("已添加待办")
        return
    if sub == "list":
        if not mine:
            await event.reply("暂无待办，/todo add <内容> 添加")
            return
        lines = ["你的待办："]
        for index, item in enumerate(mine, start=1):
            mark = "✅" if item.data.get("done") else "⬜"
            lines.append(f"{index}. {mark} {item.data.get('text', '')}")
        await event.reply("\n".join(lines[:20]))
        return
    if sub in {"done", "del"}:
        index = int(params.get("id", 0))
        if index < 1 or index > len(mine):
            await event.reply(f"序号无效，当前共 {len(mine)} 条")
            return
        target = mine[index - 1]
        if sub == "done":
            await _ctx.records.update(target.id, {"done": True})
            await event.reply("已标记完成 ✅")
        else:
            await _ctx.records.delete(target.id)
            await event.reply("已删除")
        return
    await event.reply("用法：/todo add|list|done|del")
