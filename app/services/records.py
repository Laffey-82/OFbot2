from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.core.bus import get_bus
from app.core.capabilities import Capability
from app.core.config import Settings, save_settings
from app.core.events import RecordChanged
from app.core.logger import get_logger
from app.db.base import session_factory
from app.db.models import Record

logger = get_logger(__name__)


def schema_to_dict(schema: RecordTypeSchema) -> dict[str, Any]:
    return {
        "name": schema.name,
        "description": schema.description,
        "fields": [
            {
                "name": field.name,
                "type": field.field_type,
                "required": field.required,
                "default": field.default,
                "description": field.description,
            }
            for field in schema.fields
        ],
    }


def schema_from_dict(data: dict[str, Any]) -> RecordTypeSchema:
    return RecordTypeSchema(
        str(data["name"]),
        [
            FieldSchema(
                str(field.get("name", "")),
                str(field.get("type", "string")),
                bool(field.get("required", False)),
                field.get("default"),
                str(field.get("description", "")),
            )
            for field in data.get("fields", [])
        ],
        description=str(data.get("description", "")),
    )


def persist_record_type(settings: Settings, schema: RecordTypeSchema) -> None:
    """将记录类型持久化到 settings.plugin_configs（供 Web / REST 使用）。"""
    saved = settings.plugin_configs.setdefault("records", {}).setdefault(
        "types", []
    )
    saved = [t for t in saved if t.get("name") != schema.name]
    saved.append(schema_to_dict(schema))
    settings.plugin_configs["records"]["types"] = saved
    save_settings(settings)


def remove_record_type(settings: Settings, name: str) -> None:
    saved = settings.plugin_configs.get("records", {}).get("types", [])
    settings.plugin_configs["records"]["types"] = [
        t for t in saved if t.get("name") != name
    ]
    save_settings(settings)


class FieldSchema:
    def __init__(
        self,
        name: str,
        field_type: str = "string",
        required: bool = False,
        default: Any = None,
        description: str = "",
    ) -> None:
        self.name = name
        self.field_type = field_type
        self.required = required
        self.default = default
        self.description = description


class RecordTypeSchema:
    def __init__(
        self,
        name: str,
        fields: list[FieldSchema] | None = None,
        description: str = "",
    ) -> None:
        self.name = name
        self.fields = fields or []
        self.description = description

    def validate(self, data: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        field_map = {field.name: field for field in self.fields}
        for name, field in field_map.items():
            if name in data:
                result[name] = data[name]
            elif field.default is not None:
                result[name] = field.default
            elif field.required:
                raise ValueError(f"field {name} is required")
        return result


class SchemaRegistry:
    def __init__(self) -> None:
        self._schemas: dict[str, RecordTypeSchema] = {}

    def register(self, schema: RecordTypeSchema) -> RecordTypeSchema:
        self._schemas[schema.name] = schema
        return schema

    def get(self, name: str) -> RecordTypeSchema:
        schema = self._schemas.get(name)
        if schema is None:
            raise KeyError(f"record type not registered: {name}")
        return schema

    def list(self) -> list[RecordTypeSchema]:
        return list(self._schemas.values())

    def unregister(self, name: str) -> bool:
        return self._schemas.pop(name, None) is not None


class RecordService:
    def __init__(self, schemas: SchemaRegistry) -> None:
        self.schemas = schemas

    async def create(self, record_type: str, data: dict[str, Any]) -> Record:
        schema = self.schemas.get(record_type)
        validated = schema.validate(data)
        async with session_factory()() as session:
            record = Record(record_type=record_type, data=validated)
            session.add(record)
            await session.commit()
            await session.refresh(record)
        try:
            get_bus().dispatch(RecordChanged(action="created", record_type=record_type, record_id=record.id))
        except RuntimeError:
            pass
        return record

    async def get(self, record_id: int) -> Record | None:
        async with session_factory()() as session:
            return await session.get(Record, record_id)

    async def list(
        self,
        record_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
        status: str | None = None,
        order: str = "desc",
    ) -> list[Record]:
        async with session_factory()() as session:
            query = select(Record)
            if record_type:
                query = query.where(Record.record_type == record_type)
            if status:
                query = query.where(Record.status == status)
            if order == "asc":
                query = query.order_by(Record.created_at.asc())
            else:
                query = query.order_by(Record.created_at.desc())
            query = query.offset(offset).limit(limit)
            return list((await session.scalars(query)).all())

    async def update(self, record_id: int, data: dict[str, Any]) -> Record | None:
        async with session_factory()() as session:
            record = await session.get(Record, record_id)
            if record is None:
                return None
            schema = self.schemas.get(record.record_type)
            merged = {**record.data, **data}
            record.data = schema.validate(merged)
            await session.commit()
            await session.refresh(record)
        try:
            get_bus().dispatch(RecordChanged(action="updated", record_type=record.record_type, record_id=record.id))
        except RuntimeError:
            pass
        return record

    async def set_status(self, record_id: int, status: str) -> Record | None:
        """仅更新记录状态（不派发事件；事件由状态机服务在校验通过时派发）。"""
        async with session_factory()() as session:
            record = await session.get(Record, record_id)
            if record is None:
                return None
            record.status = status
            await session.commit()
            await session.refresh(record)
            return record

    async def delete(self, record_id: int) -> bool:
        async with session_factory()() as session:
            record = await session.get(Record, record_id)
            if record is None:
                return False
            record_type = record.record_type
            await session.delete(record)
            await session.commit()
        try:
            get_bus().dispatch(RecordChanged(action="deleted", record_type=record_type, record_id=record_id))
        except RuntimeError:
            pass
        return True


def register_record_capability() -> Capability:
    return Capability(
        name="records",
        description="通用记录 CRUD 与字段校验",
        methods=["create", "get", "list", "update", "delete"],
    )
