"""signin 插件：基于通用记录（records）的每日签到。"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from app.core.messages import Message, MessageEvent
from app.core.plugin import PluginContext
from app.services.records import FieldSchema, RecordTypeSchema

_ctx: PluginContext | None = None


def setup(ctx: PluginContext) -> None:
    global _ctx
    _ctx = ctx
    ctx.records.schemas.register(
        RecordTypeSchema(
            "signin",
            [
                FieldSchema("user_id", "string", required=True),
                FieldSchema("date", "string", required=True),
                FieldSchema("nickname", "string", required=False),
            ],
            description="每日签到记录",
        )
    )


async def signin_command(
    event: MessageEvent, args: Message, command_ctx
) -> None:
    user_id = str(getattr(event, "user_id", "") or "")
    if not user_id:
        await event.reply("无法识别用户")
        return
    today = datetime.now(UTC).date().isoformat()
    records = await _ctx.records.list(record_type="signin", limit=1000)
    mine = [
        item
        for item in records
        if item.data.get("user_id") == user_id
    ]
    if any(item.data.get("date") == today for item in mine):
        await event.reply(f"今天已经签到过啦（累计 {len(mine)} 天）")
        return
    await _ctx.records.create(
        "signin",
        {
            "user_id": user_id,
            "date": today,
            "nickname": str(getattr(event, "user_id", "")),
        },
    )
    streak = _consecutive_days(mine, datetime.now(UTC).date())
    await event.reply(
        f"签到成功！连续签到 {streak} 天，累计 {len(mine) + 1} 天"
    )


def _consecutive_days(records: list, today: date) -> int:
    dates = {
        date.fromisoformat(item.data["date"])
        for item in records
        if isinstance(item.data.get("date"), str)
    }
    streak = 0
    cursor = today
    while cursor in dates:
        streak += 1
        cursor -= timedelta(days=1)
    return streak
