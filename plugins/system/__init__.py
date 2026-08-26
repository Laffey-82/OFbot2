from __future__ import annotations

from app.core.plugin import Plugin, PluginContext

from . import handlers


class SystemPlugin(Plugin):
    name = "system"
    version = "1.0.0"

    def setup(self, ctx: PluginContext) -> None:
        handlers.setup(ctx)


def create_plugin() -> Plugin:
    return SystemPlugin()
