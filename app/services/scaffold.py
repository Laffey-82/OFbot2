from __future__ import annotations

import json
import shutil
from pathlib import Path

from app.core.logger import get_logger
from app.services.plugin_installer import validate_plugin_name

logger = get_logger(__name__)


class ScaffoldService:
    def __init__(self, examples_dir: str | Path, plugins_dir: str | Path) -> None:
        self.examples_dir = Path(examples_dir)
        self.plugins_dir = Path(plugins_dir)
        self.plugins_dir.mkdir(parents=True, exist_ok=True)

    def list_templates(self) -> list[dict[str, str]]:
        presets_dir = self.examples_dir / "presets"
        if not presets_dir.exists():
            return []
        templates: list[dict[str, str]] = []
        for category in sorted(presets_dir.iterdir()):
            if not category.is_dir():
                continue
            for template_dir in sorted(category.iterdir()):
                manifest_path = template_dir / "plugin.json"
                if not manifest_path.exists():
                    continue
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                templates.append(
                    {
                        "category": category.name,
                        "name": manifest.get("name", template_dir.name),
                        "description": manifest.get("description", ""),
                        "version": manifest.get("version", ""),
                    }
                )
        return templates

    def create_from_template(self, template_name: str, target_name: str) -> Path:
        target_name = validate_plugin_name(target_name)
        source = self._find_template(template_name)
        target = self.plugins_dir / target_name
        if target.exists():
            raise ValueError(f"plugin already exists: {target_name}")
        shutil.copytree(
            source,
            target,
            ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"),
        )
        for file_path in target.rglob("*.py"):
            content = file_path.read_text(encoding="utf-8")
            content = content.replace(template_name, target_name)
            content = content.replace("{plugin_name}", target_name)
            file_path.write_text(content, encoding="utf-8")
        manifest_path = target / "plugin.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["name"] = target_name
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        logger.info("scaffold %s created as %s", template_name, target_name)
        return target

    def create_featured(
        self,
        target_name: str,
        *,
        with_task: bool = False,
        with_listener: bool = False,
        with_web: bool = False,
        with_model: bool = False,
    ) -> Path:
        """生成声明式 features 插件（命令 + 可选任务/监听/Web/模型）。"""
        target_name = validate_plugin_name(target_name)
        target = self.plugins_dir / target_name
        if target.exists():
            raise ValueError(f"plugin already exists: {target_name}")
        target.mkdir(parents=True)
        commands = [
            {
                "name": "demo",
                "aliases": ["示例"],
                "handler": "handlers.demo_command",
                "permission": f"{target_name}.demo",
                "description": "示例命令：原样回复内容",
                "usage": "/demo [内容]",
                "examples": ["/demo 你好"],
                "cooldown": 2,
            }
        ]
        tasks = []
        listeners = []
        if with_task:
            tasks.append(
                {
                    "id": "sample_task",
                    "kind": "interval",
                    "params": {"seconds": 3600},
                    "handler": "handlers.sample_task",
                    "target": "all",
                    "description": "每小时触发的示例任务（按所在群功能开关门控）",
                }
            )
        if with_listener:
            listeners.append(
                {
                    "event": "GroupMessageReceived",
                    "handler": "handlers.on_group_message",
                    "description": "监听群消息，命中关键字时回复",
                }
            )
        manifest = {
            "name": target_name,
            "api_version": 1,
            "version": "0.1.0",
            "description": f"{target_name}：由 ofbot2 plugin new 生成的声明式插件",
            "author": "OFbot 2",
            "dependencies": {},
            "permissions": [f"{target_name}.demo"],
            "config_schema": {
                "type": "object",
                "properties": {
                    "greeting": {
                        "type": "string",
                        "default": "你好",
                        "description": "demo 命令回复前缀",
                    }
                },
            },
            "web": with_web,
            "models": ["models"] if with_model else [],
            "migrations": [],
            "entry": "create_plugin",
            "features": [
                {
                    "id": "main",
                    "label": "主要功能",
                    "description": "演示命令与能力组合",
                    "enable_on_default": True,
                    "manage_permission": f"{target_name}.admin",
                    "commands": commands,
                    "tasks": tasks,
                    "listeners": listeners,
                }
            ],
        }
        (target / "plugin.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        handler_parts = [
            '"""' + target_name + ' 插件处理器（由 plugin.json features 声明引用）。"""',
            "",
            "from __future__ import annotations",
            "",
            "from app.core.messages import Message, MessageEvent",
            "from app.core.plugin import PluginContext",
            "",
            "_ctx: PluginContext | None = None",
            "",
            "",
            "def setup(ctx: PluginContext) -> None:",
            "    global _ctx",
            "    _ctx = ctx",
            "",
            "",
            "async def demo_command(event: MessageEvent, args: Message, command_ctx) -> None:",
            '    greeting = _ctx.config.get("greeting", "你好")',
            '    await event.reply(f"{greeting}，收到：{args.extract_plain_text() or \'（空）\'}")',
        ]
        if with_listener:
            handler_parts += [
                "",
                "",
                "async def on_group_message(event) -> None:",
                "    from app.core.events import GroupMessageReceived",
                "",
                "    if event.message == 'sample:hello':",
                "        await _ctx.bot.send_group_message(event.group_id, '你好，我是 " + target_name + "！')",
            ]
        if with_task:
            handler_parts += [
                "",
                "",
                "async def sample_task() -> None:",
                "    _ctx.logger.info('" + target_name + " sample_task triggered')",
            ]
        (target / "handlers.py").write_text(
            "\n".join(handler_parts) + "\n",
            encoding="utf-8",
        )
        init_lines = [
            "from __future__ import annotations",
            "",
            "from app.core.plugin import Plugin, PluginContext",
            "",
            "from . import handlers",
            "",
            "",
            "class " + target_name.title().replace("_", "") + "Plugin(Plugin):",
            f'    name = "{target_name}"',
            '    version = "0.1.0"',
            "",
            "    def setup(self, ctx: PluginContext) -> None:",
            "        handlers.setup(ctx)",
        ]
        if with_web:
            init_lines += [
                "        from fastapi import APIRouter",
                "",
                "        router = APIRouter(prefix='/" + target_name + "', tags=['" + target_name + "'])",
                "",
                "        @router.get('/status')",
                "        async def status() -> dict:",
                "            return {'plugin': ctx.name}",
                "",
                "        ctx.register_router(router)",
            ]
        if with_model:
            init_lines += [
                "        from . import models",
                "",
                "        ctx.register_models(models.SampleRecord)",
            ]
        init_lines += [
            "",
            "",
            "def create_plugin() -> Plugin:",
            "    return " + target_name.title().replace("_", "") + "Plugin()",
            "",
        ]
        (target / "__init__.py").write_text(
            "\n".join(init_lines), encoding="utf-8"
        )
        if with_model:
            (target / "models.py").write_text(
                "\n".join(
                    [
                        "from __future__ import annotations",
                        "",
                        "from datetime import datetime",
                        "",
                        "from sqlalchemy import DateTime, Integer, String, func",
                        "from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column",
                        "",
                        "",
                        "class Base(DeclarativeBase):",
                        "    pass",
                        "",
                        "",
                        "class SampleRecord(Base):",
                        f'    __tablename__ = "{target_name}_sample_records"',
                        "    id: Mapped[int] = mapped_column(Integer, primary_key=True)",
                        "    content: Mapped[str] = mapped_column(String(500), default='')",
                        "    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
        logger.info("featured scaffold %s created", target_name)
        return target

    def _find_template(self, template_name: str) -> Path:
        presets_dir = self.examples_dir / "presets"
        if not presets_dir.exists():
            raise ValueError(f"template not found: {template_name}")
        for category in presets_dir.iterdir():
            candidate = category / template_name
            if (candidate / "plugin.json").exists():
                return candidate
        raise ValueError(f"template not found: {template_name}")
