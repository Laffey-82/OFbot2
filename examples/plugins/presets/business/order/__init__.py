from __future__ import annotations

from uuid import uuid4

from app.core.messages import Message, MessageEvent
from app.core.plugin import Plugin, PluginContext
from app.services.preset_utils import JsonStore, preset_data_path


class OrderPlugin(Plugin):
    def setup(self, ctx: PluginContext) -> None:
        store = JsonStore(preset_data_path("order"))

        @ctx.commands.command("order", permission="order.use", plugin_name=ctx.name)
        async def order(event: MessageEvent, args: Message, command_ctx) -> None:
            parts = args.extract_plain_text().strip().split(maxsplit=1)
            action = parts[0].lower() if parts else "list"
            data = await store.load()
            orders = data.setdefault("orders", [])
            if action == "add" and len(parts) == 2:
                info, price_text = parts[1].rsplit(maxsplit=1)
                try:
                    price = float(price_text)
                except ValueError:
                    await event.reply("价格无效")
                    return
                orders.append(
                    {
                        "id": uuid4().hex[:8],
                        "info": info,
                        "price": price,
                        "status": "pending",
                    }
                )
                await store.save()
                await event.reply(f"订单已创建：{orders[-1]['id']}")
                return
            if action == "list":
                if not orders:
                    await event.reply("暂无订单")
                    return
                await event.reply(
                    "\n".join(f"{o['id']} {o['info']} ¥{o['price']:.2f} {o['status']}" for o in orders)
                )
                return
            if action == "done" and len(parts) == 2:
                for o in orders:
                    if o["id"] == parts[1]:
                        o["status"] = "done"
                        await store.save()
                        await event.reply("订单已完成")
                        return
                await event.reply("订单不存在")
                return
            if action == "delete" and len(parts) == 2:
                data["orders"] = [o for o in orders if o["id"] != parts[1]]
                await store.save()
                await event.reply("订单已删除")
                return
            await event.reply("用法：/order add <信息> <价格> | list | done <id> | delete <id>")


def create_plugin() -> Plugin:
    return OrderPlugin()
