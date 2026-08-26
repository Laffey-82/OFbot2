"""data 页面路由。"""

from __future__ import annotations

import time
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    Form,
    Request,
)
from fastapi.responses import (
    HTMLResponse,
    RedirectResponse,
)
from sqlalchemy import func, select

from app.core.config import Settings, save_settings
from app.core.logger import get_logger
from app.core.security import audit_logger
from app.db.base import session_factory
from app.db.models import (
    Record,
    WebAccount,
)
from app.services.records import (
    FieldSchema,
    RecordTypeSchema,
    persist_record_type,
    remove_record_type,
)
from app.web.deps import (
    get_csrf_token,
    get_current_user,
    require_admin,
    require_csrf,
)
from app.web.helpers import flash_redirect

logger = get_logger(__name__)



def build_router(*, app: FastAPI, settings: Settings, templates: Any) -> APIRouter:
    router = APIRouter()
    @router.get("/records", response_class=HTMLResponse)
    async def records_page(
        request: Request,
        user: WebAccount = Depends(get_current_user),
        csrf_token: str = Depends(get_csrf_token),
        page: int = 1,
        status: str = "",
        record_type: str = "",
        order: str = "desc",
    ) -> HTMLResponse:
        schemas = app.state.services.get("schema_registry")
        records = app.state.services.get("records")
        types = schemas.list() if schemas else []
        page_size = 50
        total = 0
        async with session_factory()() as session:
            count_query = select(func.count()).select_from(Record)
            if status:
                count_query = count_query.where(Record.status == status)
            if record_type:
                count_query = count_query.where(
                    Record.record_type == record_type
                )
            total = await session.scalar(count_query) or 0
        total_pages = max(1, (total + page_size - 1) // page_size)
        page = max(1, min(page, total_pages))
        items = (
            await records.list(
                limit=page_size,
                offset=(page - 1) * page_size,
                status=status or None,
                record_type=record_type or None,
                order=order,
            )
            if records
            else []
        )
        state_machine = app.state.services.get("state_machine")
        machine_transitions: dict[str, Any] = {}
        if state_machine is not None and items:
            record_types = {item.record_type for item in items}
            for machine in state_machine.machines.values():
                if machine.name in record_types:
                    machine_transitions[machine.name] = machine
        types_json = [
            {
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
            for schema in types
        ]
        type_field_counts = {
            schema.name: len(schema.fields) for schema in types
        }
        type_field_summaries = {
            schema.name: "、".join(
                f"{field.name}: {field.field_type}" for field in schema.fields
            )
            for schema in types
        }
        return templates.TemplateResponse(
            request,
            "records.html",
            {
                "request": request,
                "user": user,
                "types": types,
                "types_json": types_json,
                "type_field_counts": type_field_counts,
                "type_field_summaries": type_field_summaries,
                "records": items,
                "page": page,
                "total": total,
                "total_pages": total_pages,
                "page_size": page_size,
                "status": status,
                "record_type": record_type,
                "order": order,
                "machine_transitions": machine_transitions,
                "csrf_token": csrf_token,
            },
        )

    @router.post("/records/add")
    async def records_add(
        request: Request,
        user: WebAccount = Depends(require_admin),
        name: str = Form(...),
        fields_json: str = Form(...),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        schemas = app.state.services.get("schema_registry")
        if schemas is None:
            return RedirectResponse("/records?error=1", status_code=303)
        try:
            import json

            fields = json.loads(fields_json)
            schema = RecordTypeSchema(
                name,
                [
                    FieldSchema(
                        f.get("name"),
                        f.get("type", "string"),
                        bool(f.get("required", False)),
                        f.get("default"),
                        f.get("description", ""),
                    )
                    for f in fields
                ],
            )
            schemas.register(schema)
            persist_record_type(settings, schema)
        except Exception:
            return RedirectResponse("/records?error=1", status_code=303)
        return flash_redirect("/records", message=f"记录类型 {name} 已注册")

    @router.post("/records/types/{name}/delete")
    async def records_type_delete(
        name: str,
        request: Request,
        user: WebAccount = Depends(require_admin),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        schemas = app.state.services.get("schema_registry")
        if schemas is None or not schemas.unregister(name):
            return flash_redirect("/records", error="1")
        remove_record_type(settings, name)
        audit_logger.record(
            "records.type_deleted", user.username, target=name, success=True
        )
        return flash_redirect("/records", message=f"记录类型 {name} 已删除")

    @router.post("/records/create")
    async def records_create(
        request: Request,
        user: WebAccount = Depends(require_admin),
        record_type: str = Form(...),
        data_json: str = Form(...),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        service = app.state.services.get("records")
        if service is None:
            return RedirectResponse("/records?error=1", status_code=303)
        try:
            import json

            await service.create(record_type, json.loads(data_json))
        except Exception:
            return RedirectResponse("/records?error=1", status_code=303)
        return flash_redirect("/records", message="记录已创建")

    @router.post("/records/{record_id}/delete")
    async def records_delete(
        record_id: int,
        request: Request,
        user: WebAccount = Depends(require_admin),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        service = app.state.services.get("records")
        if service is None or not await service.delete(record_id):
            return flash_redirect("/records", error="记录不存在")
        return flash_redirect("/records", message="记录已删除")

    @router.post("/records/bulk-delete")
    async def records_bulk_delete(
        request: Request,
        user: WebAccount = Depends(require_admin),
        ids: list[int] = Form(default=[]),
        select_all: str = Form("off"),
        record_type: str = Form(""),
        status: str = Form(""),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        service = app.state.services.get("records")
        if service is None:
            return flash_redirect("/records", error="1")
        deleted = 0
        if select_all == "on":
            items = await service.list(
                record_type=record_type or None,
                limit=10000,
                status=status or None,
            )
            for item in items:
                if await service.delete(item.id):
                    deleted += 1
        else:
            for record_id in ids:
                if await service.delete(record_id):
                    deleted += 1
        return flash_redirect("/records", message=f"已删除 {deleted} 条记录")

    @router.post("/records/bulk-export")
    async def records_bulk_export(
        request: Request,
        user: WebAccount = Depends(require_admin),
        ids: list[int] = Form(default=[]),
        fmt: str = Form("csv"),
        select_all: str = Form("off"),
        record_type: str = Form(""),
        status: str = Form(""),
        csrf: None = Depends(require_csrf),
    ) -> Any:
        export_service = app.state.services.get("export")
        records_service = app.state.services.get("records")
        if export_service is None or records_service is None:
            return flash_redirect("/records", error="1")
        if fmt not in {"csv", "json", "excel", "docx"}:
            return flash_redirect("/records", error="1")
        rows: list[dict[str, Any]] = []
        if select_all == "on":
            items = await records_service.list(
                record_type=record_type or None,
                limit=10000,
                status=status or None,
            )
            for item in items:
                row: dict[str, Any] = {
                    "id": item.id,
                    "status": item.status,
                    "created_at": str(item.created_at),
                }
                row.update(item.data or {})
                rows.append(row)
        else:
            for record_id in ids:
                item = await records_service.get(record_id)
                if item is None:
                    continue
                row = {
                    "id": item.id,
                    "status": item.status,
                    "created_at": str(item.created_at),
                }
                row.update(item.data or {})
                rows.append(row)
        if not rows:
            return flash_redirect("/records", error="1")
        name = f"records_selected_{int(time.time())}"
        try:
            if fmt == "json":
                path = export_service.export_json(rows, name)
            elif fmt == "csv":
                path = export_service.export_csv(rows, name)
            elif fmt == "excel":
                path = export_service.export_excel(rows, name)
            else:
                path = export_service.export_docx(rows, name, title="Records")
        except Exception:
            return flash_redirect("/records", error="1")
        audit_logger.record(
            "records.bulk_exported",
            user.username,
            target=path.name,
            success=True,
            detail={"rows": len(rows)},
        )
        from fastapi.responses import FileResponse

        media = {
            "csv": "text/csv",
            "json": "application/json",
            "excel": (
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
            "docx": (
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
        }[fmt]
        return FileResponse(path, media_type=media)

    @router.post("/records/{record_id}/update")
    async def records_update(
        record_id: int,
        request: Request,
        user: WebAccount = Depends(require_admin),
        data_json: str = Form(...),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        service = app.state.services.get("records")
        if service is None:
            return flash_redirect("/records", error="1")
        try:
            import json

            await service.update(record_id, json.loads(data_json))
        except Exception:
            return flash_redirect("/records", error="1")
        return flash_redirect("/records", message="记录已更新")

    @router.post("/records/{record_id}/transition")
    async def records_transition(
        record_id: int,
        user: WebAccount = Depends(require_admin),
        target: str = Form(...),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        records_service = app.state.services.get("records")
        state_machine = app.state.services.get("state_machine")
        if records_service is None or state_machine is None:
            return flash_redirect("/records", error="1")
        record = await records_service.get(record_id)
        if record is None:
            return flash_redirect("/records", error="1")
        machine = state_machine.machines.get(record.record_type)
        if machine is None:
            return flash_redirect("/records", error="1")
        transition = next(
            (
                item
                for item in machine.transitions
                if item.from_status == (record.status or "")
                and item.to_status == target
            ),
            None,
        )
        if transition is None:
            return flash_redirect("/records", error="1")
        try:
            state_machine.transition(
                machine.name,
                record.status or "",
                target,
                permission=transition.permission or "",
            )
        except ValueError:
            return flash_redirect("/records", error="1")
        previous = record.status
        await records_service.set_status(record_id, target)
        audit_logger.record(
            "record.transitioned",
            user.username,
            target=f"{record.record_type}:{record_id}",
            success=True,
            detail={"from": previous, "to": target},
        )
        return flash_redirect(
            "/records", message=f"记录 #{record_id} 状态已流转至 {target}"
        )

    @router.get("/state-machines", response_class=HTMLResponse)
    async def state_machines_page(
        request: Request,
        user: WebAccount = Depends(get_current_user),
        csrf_token: str = Depends(get_csrf_token),
    ) -> HTMLResponse:
        service = app.state.services.get("state_machine")
        machines: list[dict[str, Any]] = []
        if service:
            for machine in service.machines.values():
                machines.append(
                    {
                        "name": machine.name,
                        "initial": machine.initial,
                        "transitions": [
                            {
                                "from_status": transition.from_status,
                                "to_status": transition.to_status,
                                "permission": transition.permission,
                            }
                            for transition in machine.transitions
                        ],
                    }
                )
        return templates.TemplateResponse(
            request,
            "state_machines.html",
            {
                "request": request,
                "user": user,
                "machines": machines,
                "csrf_token": csrf_token,
            },
        )

    @router.post("/state-machines/add")
    async def state_machines_add(
        request: Request,
        user: WebAccount = Depends(require_admin),
        name: str = Form(...),
        transitions_json: str = Form(...),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        service = app.state.services.get("state_machine")
        if service is None:
            return RedirectResponse("/state-machines?error=1", status_code=303)
        try:
            import json

            from app.services.state_machine import StateMachine, Transition

            machine = StateMachine(name)
            for item in json.loads(transitions_json):
                machine.add(
                    Transition(
                        item.get("from", ""),
                        item.get("to", ""),
                        permission=item.get("permission", ""),
                    )
                )
            service.register(machine)
        except Exception:
            return RedirectResponse("/state-machines?error=1", status_code=303)
        return flash_redirect("/state-machines", message=f"状态机 {name} 已注册")

    @router.post("/state-machines/{name}/delete")
    async def state_machines_delete(
        name: str,
        request: Request,
        user: WebAccount = Depends(require_admin),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        service = app.state.services.get("state_machine")
        if service is None or not service.unregister(name):
            return flash_redirect("/state-machines", error="1")
        return flash_redirect("/state-machines", message=f"状态机 {name} 已删除")

    @router.get("/api-keys", response_class=HTMLResponse)
    async def api_keys_page(
        request: Request,
        user: WebAccount = Depends(get_current_user),
        csrf_token: str = Depends(get_csrf_token),
    ) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "api_keys.html",
            {
                "request": request,
                "user": user,
                "keys": settings.web.api_keys,
                "csrf_token": csrf_token,
            },
        )

    @router.post("/api-keys/add")
    async def api_keys_add(
        request: Request,
        user: WebAccount = Depends(require_admin),
        key: str = Form(...),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        if key and key not in settings.web.api_keys:
            settings.web.api_keys.append(key)
            save_settings(settings)
            audit_logger.record("api_key.added", user.username, target="api_keys", success=True)
        return flash_redirect("/api-keys", message="API Key 已添加")

    @router.post("/api-keys/remove")
    async def api_keys_remove(
        request: Request,
        user: WebAccount = Depends(require_admin),
        key: str = Form(...),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        if key in settings.web.api_keys:
            settings.web.api_keys = [item for item in settings.web.api_keys if item != key]
            save_settings(settings)
            audit_logger.record("api_key.removed", user.username, target="api_keys", success=True)
        return flash_redirect("/api-keys", message="API Key 已删除")


    return router
