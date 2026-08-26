from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from app.adapters.base import BotClient
from app.core.cache import TTLCache
from app.core.commands import CommandRegistry
from app.core.permissions import PermissionManager
from app.core.plugin import PluginManager, PluginManifest
from app.core.subscriptions import EventSubscriptionRegistry


def _manifest(name: str = "demo") -> dict:
    return {
        "name": name,
        "api_version": 1,
        "version": "0.1.0",
        "description": "test",
        "author": "me",
        "dependencies": {},
        "features": [
            {
                "id": "main",
                "label": "主要",
                "enable_on_default": True,
                "commands": [
                    {
                        "name": "demo",
                        "handler": "handlers.demo_command",
                        "permission": f"{name}.demo",
                        "usage": "/demo [内容]",
                        "examples": ["/demo 你好"],
                    }
                ],
                "tasks": [
                    {
                        "id": "tick",
                        "kind": "interval",
                        "params": {"seconds": 3600},
                        "handler": "handlers.tick",
                        "target": "all",
                    }
                ],
                "listeners": [
                    {
                        "event": "GroupMessageReceived",
                        "handler": "handlers.on_message",
                    }
                ],
            }
        ],
    }


def test_manifest_features_parse_and_fallback() -> None:
    manifest = PluginManifest.model_validate(_manifest())
    assert manifest.features[0].commands[0].usage == "/demo [内容]"
    assert manifest.features[0].tasks[0].target == "all"

    fallback = PluginManifest.model_validate(
        {
            "name": "x",
            "api_version": 1,
            "commands": [
                {
                    "name": "old",
                    "handler": "handlers.old_command",
                }
            ],
        }
    )
    features = fallback.effective_features()
    assert len(features) == 1
    assert features[0].id == "default"
    assert features[0].commands[0].name == "old"


def test_handler_symbol_missing_raises() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        plugin_dir = Path(tmp) / "demo"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.json").write_text(
            json.dumps(_manifest()), encoding="utf-8"
        )
        (plugin_dir / "__init__.py").write_text(
            "from app.core.plugin import Plugin, PluginContext\n"
            "class DemoPlugin(Plugin):\n"
            "    def setup(self, ctx):\n"
            "        pass\n"
            "def create_plugin():\n"
            "    return DemoPlugin()\n",
            encoding="utf-8",
        )
        (plugin_dir / "handlers.py").write_text(
            "async def demo_command(event, args, command_ctx): pass\n",
            encoding="utf-8",
        )
        manager = PluginManager(
            Path(tmp),
            commands=CommandRegistry(),
            db=None,
            scheduler=None,
            cache=TTLCache(),
            bot=BotClient(),
            permissions=PermissionManager(),
            services={},
            subscriptions=EventSubscriptionRegistry(),
        )
        with pytest.raises(ValueError):
            manager.load_plugin("demo", plugin_dir, config={})
