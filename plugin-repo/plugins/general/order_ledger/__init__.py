"""order_ledger 插件：代打单管理（订单/分账/统计/导出/排行/账目/定时任务，OFbot 重写）。"""

from __future__ import annotations

from app.core.plugin import Plugin, PluginContext

from . import handlers, models, services, tasks  # noqa: F401


class OfbotPlugin(Plugin):
    def setup(self, ctx: PluginContext) -> None:
        services.init(ctx)
        handlers.init(ctx)
        tasks.init(ctx)
        ctx.logger.info(
            "order_ledger plugin ready: models=%s tasks=%s",
            "order_ledger_orders, order_ledger_commission_history",
            "no_take_remind / daily_commission / weekly_commission / monthly_archive",
        )


def create_plugin() -> Plugin:
    return OfbotPlugin()
