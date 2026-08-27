from __future__ import annotations

from app.core.plugin import Plugin, PluginContext

from . import handlers


class AuditViewerPlugin(Plugin):
    name = "audit_viewer"
    version = "1.0.0"

    def setup(self, ctx: PluginContext) -> None:
        handlers.setup(ctx)


def create_plugin() -> Plugin:
    return AuditViewerPlugin()
