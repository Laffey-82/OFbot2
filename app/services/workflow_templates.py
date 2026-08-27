"""流程模板库：内置模板 + 本地模板目录，供 Web 一键导入。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.logger import get_logger

logger = get_logger(__name__)

BUILTIN_TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "message_reply",
        "name": "群消息自动回复",
        "category": "消息",
        "description": "收到群消息后回复固定文案",
        "definition": {
            "trigger": {"type": "message"},
            "condition": {"field": "message", "op": "contains", "value": "hello"},
            "steps": [
                {
                    "action": "send_group",
                    "params": {
                        "group_id": "{{group_id}}",
                        "message": "你好，我是 OFbot 2 🤖",
                    },
                }
            ],
        },
    },
    {
        "id": "ai_chat_reply",
        "name": "AI 对话回复",
        "category": "AI",
        "description": "群内消息交给 AI 生成回复（需配置 AI Provider）",
        "definition": {
            "trigger": {"type": "message"},
            "condition": {"field": "message", "op": "contains", "value": "AI"},
            "steps": [
                {
                    "action": "ai_chat",
                    "params": {"prompt": "{{message}}"},
                },
                {
                    "action": "send_group",
                    "params": {
                        "group_id": "{{group_id}}",
                        "message": "{{ai_chat.output}}",
                    },
                },
            ],
        },
    },
    {
        "id": "daily_summary_record",
        "name": "定时写入记录",
        "category": "数据",
        "description": "每日 9 点自动创建一条记录",
        "definition": {
            "trigger": {"type": "schedule", "cron": "0 9 * * *"},
            "steps": [
                {
                    "action": "create_record",
                    "params": {
                        "record_type": "daily",
                        "data": '{"note": "每日汇总"}',
                    },
                }
            ],
        },
    },
    {
        "id": "webhook_forward",
        "name": "Webhook 转发到群",
        "category": "自动化",
        "description": "收到 Webhook 后把载荷转发到指定群",
        "definition": {
            "trigger": {"type": "webhook"},
            "steps": [
                {
                    "action": "send_group",
                    "params": {
                        "group_id": "",
                        "message": "Webhook 收到：{{payload}}",
                    },
                }
            ],
        },
    },
]


class WorkflowTemplateService:
    """模板来源：内置模板优先，其次扫描本地 templates 目录的 JSON 文件。"""

    def __init__(self, templates_dir: str | Path | None = None) -> None:
        self.templates_dir = Path(templates_dir) if templates_dir else None

    def list_templates(self) -> list[dict[str, Any]]:
        templates = [dict(item) for item in BUILTIN_TEMPLATES]
        if self.templates_dir is not None and self.templates_dir.exists():
            for path in sorted(self.templates_dir.glob("*.json")):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(data, dict) and data.get("id") and data.get("definition"):
                        templates.append(data)
                except (ValueError, json.JSONDecodeError) as exc:
                    logger.warning("跳过无效流程模板 %s：%s", path.name, exc)
        return templates

    def get_template(self, template_id: str) -> dict[str, Any] | None:
        for template in self.list_templates():
            if template.get("id") == template_id:
                return template
        return None

    async def import_template(
        self, engine: Any, template_id: str, name: str | None = None
    ) -> Any:
        """导入模板为流程并返回创建的 Workflow。"""
        template = self.get_template(template_id)
        if template is None:
            raise KeyError(f"流程模板不存在：{template_id}")
        definition = json.loads(
            json.dumps(template["definition"])
        )
        return await engine.create(
            name or f"{template['name']}（导入）",
            definition,
        )
