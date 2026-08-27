"""points 插件：基于通用记录（records）的积分查询与发放。"""

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
            "points",
            [
                FieldSchema("user_id", "string", required=True),
                FieldSchema("points", "integer", required=True),
            ],
            description="积分记录",
        )
    )


async def points_command(
    event: MessageEvent, args: Message, command_ctx
) -> None:
    user_id = str(getattr(event, "user_id", "") or "")
    if not user_id:
        await event.reply("无法识别用户")
        return
    sub = getattr(command_ctx, "subcommand", "")
    params = getattr(command_ctx, "params", None) or {}
    records = await _ctx.records.list(record_type="points", limit=1000)

    if sub == "add":
        target = str(params.get("user_id", "")).strip()
        amount = int(params.get("amount", 0))
        mine = [
            item for item in records if item.data.get("user_id") == target
        ]
        if mine:
            current = int(mine[-1].data.get("points", 0))
            await _ctx.records.update(
                mine[-1].id, {"points": current + amount}
            )
        else:
            await _ctx.records.create(
                "points", {"user_id": target, "points": amount}
            )
        await event.reply(f"已为 {target} 发放 {amount} 积分")
        return

    total = sum(
        int(item.data.get("points", 0))
        for item in records
        if item.data.get("user_id") == user_id
    )
    await event.reply(f"你的积分：{total}")
