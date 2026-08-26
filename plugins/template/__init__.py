from __future__ import annotations

from fastapi import APIRouter

from app.core.plugin import Plugin, PluginContext

from . import handlers


class TemplatePlugin(Plugin):
    name = "template"
    version = "1.0.0"

    def setup(self, ctx: PluginContext) -> None:
        handlers.setup(ctx)
        # 可选：注册 Web 路由（配合 plugin.json 的 web: true）
        router = APIRouter(prefix="/template", tags=["template"])

        @router.get("/status")
        async def status() -> dict[str, str]:
            return {"plugin": ctx.name, "version": self.version}

        ctx.register_router(router)


def create_plugin() -> Plugin:
    return TemplatePlugin()
