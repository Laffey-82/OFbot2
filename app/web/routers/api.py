"""REST API 路由（/api/v1/*）。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import JSONResponse, Response
from sqlalchemy import func, select

from app.core.capabilities import capability_registry
from app.core.config import save_settings
from app.core.observability import get_system_metrics, metrics
from app.db.base import session_factory
from app.db.models import Record, Task, WebAccount
from app.services.alerts import persist_alert_rules
from app.services.records import (
    FieldSchema,
    RecordTypeSchema,
    persist_record_type,
    remove_record_type,
)
from app.web.deps import require_admin, require_api_key
from app.web.helpers import (
    MAX_UPLOAD_BYTES,
    PROJECT_ROOT,
    _task_executor,
)

router = APIRouter()


@router.get("/api/v1/status", dependencies=[Depends(require_api_key)])
async def api_status(request: Request, ) -> dict[str, Any]:
    bot_client = getattr(request.app.state, "bot_client", None)
    adapters = getattr(bot_client, "status", {})
    details = getattr(bot_client, "details", {})
    counters = getattr(bot_client, "counters", {})
    merged_details: dict[str, Any] = {}
    for name in set(details) | set(counters):
        merged_details[name] = {
            **details.get(name, {}),
            **counters.get(name, {}),
        }
    base_metrics = get_system_metrics()
    counters_metrics = {
        "commands_total": metrics.counters.get("commands_total", 0),
        "commands_failed_total": metrics.counters.get("commands_failed_total", 0),
        "tasks_completed_total": metrics.counters.get("tasks_completed_total", 0),
        "tasks_failed_total": metrics.counters.get("tasks_failed_total", 0),
    }
    return {
        "status": "ok",
        "metrics": {**base_metrics, **counters_metrics},
        "adapters": adapters,
        "adapter_details": merged_details,
    }

@router.get("/api/v1/metrics/history", dependencies=[Depends(require_api_key)])
async def api_metrics_history(
    request: Request,
    hours: int = 6,
) -> JSONResponse:
    from datetime import timedelta

    from app.db.models import MetricsSample

    hours = max(1, min(24 * 7, hours))
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    async with session_factory()() as session:
        rows = (
            await session.scalars(
                select(MetricsSample)
                .where(MetricsSample.created_at >= cutoff)
                .order_by(MetricsSample.created_at.asc())
            )
        ).all()
    points: list[dict[str, Any]] = []
    for row in rows:
        points.append(
            {
                "ts": row.created_at.isoformat() if row.created_at else "",
                "cpu": row.cpu_percent,
                "memory": row.memory_percent,
                "tasks": row.active_tasks,
                "threads": row.threads,
                "processes": row.processes,
            }
        )
    return JSONResponse({"points": points, "hours": hours})

@router.get("/monitor/history/export")
async def monitor_history_export(
    request: Request,
    user: WebAccount = Depends(require_admin),
    hours: int = 24,
) -> Response:
    import csv
    import io
    from datetime import timedelta

    from app.db.models import MetricsSample

    hours = max(1, min(24 * 7, hours))
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    async with session_factory()() as session:
        rows = (
            await session.scalars(
                select(MetricsSample)
                .where(MetricsSample.created_at >= cutoff)
                .order_by(MetricsSample.created_at.asc())
            )
        ).all()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "timestamp",
            "cpu_percent",
            "memory_percent",
            "active_tasks",
            "threads",
            "processes",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row.created_at.isoformat() if row.created_at else "",
                row.cpu_percent,
                row.memory_percent,
                row.active_tasks,
                row.threads,
                row.processes,
            ]
        )
    filename = (
        f"metrics_{hours}h_"
        f"{datetime.now(UTC).strftime('%Y%m%d_%H%M')}.csv"
    )
    return Response(
        buffer.getvalue().encode("utf-8-sig"),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        },
    )

@router.get("/api/v1/capabilities", dependencies=[Depends(require_api_key)])
async def api_capabilities(request: Request, ) -> dict[str, Any]:
    return {
        "capabilities": [
            {
                "name": capability.name,
                "version": capability.version,
                "description": capability.description,
                "methods": capability.methods,
            }
            for capability in capability_registry.list()
        ]
    }

@router.get("/api/v1/workflows", dependencies=[Depends(require_api_key)])
async def api_workflows(request: Request, ) -> dict[str, Any]:
    engine = request.app.state.services.get("workflow")
    workflows = await engine.list() if engine else []
    return {
        "workflows": [
            {"id": workflow.id, "name": workflow.name, "enabled": workflow.enabled}
            for workflow in workflows
        ]
    }

@router.post("/api/v1/workflows", dependencies=[Depends(require_api_key)])
async def api_workflows_create(request: Request) -> dict[str, Any]:
    engine = request.app.state.services.get("workflow")
    if engine is None:
        raise HTTPException(status_code=404, detail="workflow unavailable")
    body = await request.json()
    definition: dict[str, Any] = {"steps": body.get("steps", [])}
    if body.get("trigger"):
        definition["trigger"] = body["trigger"]
    if body.get("condition"):
        definition["condition"] = body["condition"]
    workflow = await engine.create(body["name"], definition)
    return {"id": workflow.id, "name": workflow.name}

@router.post(
    "/api/v1/workflows/{workflow_id}/run", dependencies=[Depends(require_api_key)]
)
async def api_workflow_run(request: Request, workflow_id: int) -> dict[str, Any]:
    engine = request.app.state.services.get("workflow")
    if engine is None:
        raise HTTPException(status_code=404, detail="workflow unavailable")
    run = await engine.execute(workflow_id)
    return {"run_id": run.id, "status": run.status}

@router.get("/api/v1/records", dependencies=[Depends(require_api_key)])
async def api_records(
    request: Request,
    record_type: str = Query(""),
    status: str = Query(""),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    service = request.app.state.services.get("records")
    records = (
        await service.list(
            record_type=record_type or None,
            status=status or None,
            limit=limit,
            offset=offset,
        )
        if service
        else []
    )
    async with session_factory()() as session:
        count_query = select(func.count()).select_from(Record)
        if record_type:
            count_query = count_query.where(
                Record.record_type == record_type
            )
        if status:
            count_query = count_query.where(Record.status == status)
        total = (await session.scalar(count_query)) or 0
    return {
        "records": [
            {
                "id": record.id,
                "record_type": record.record_type,
                "status": record.status,
                "data": record.data,
            }
            for record in records
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }

@router.post("/api/v1/records", dependencies=[Depends(require_api_key)])
async def api_records_create(request: Request) -> dict[str, Any]:
    service = request.app.state.services.get("records")
    if service is None:
        raise HTTPException(status_code=404, detail="records unavailable")
    body = await request.json()
    record = await service.create(body["record_type"], body.get("data", {}))
    return {"id": record.id, "status": record.status}

@router.delete(
    "/api/v1/records/{record_id}", dependencies=[Depends(require_api_key)]
)
async def api_records_delete(request: Request, record_id: int) -> dict[str, Any]:
    service = request.app.state.services.get("records")
    if service is None or not await service.delete(record_id):
        raise HTTPException(status_code=404, detail="record not found")
    return {"success": True}

@router.get("/api/v1/record-types", dependencies=[Depends(require_api_key)])
async def api_record_types(request: Request, ) -> dict[str, Any]:
    schemas = request.app.state.services.get("schema_registry")
    types = schemas.list() if schemas else []
    return {
        "record_types": [
            {
                "name": schema.name,
                "description": schema.description,
                "fields": [
                    {
                        "name": field.name,
                        "type": field.field_type,
                        "required": field.required,
                        "default": field.default,
                    }
                    for field in schema.fields
                ],
            }
            for schema in types
        ]
    }

@router.post("/api/v1/record-types", dependencies=[Depends(require_api_key)])
async def api_record_types_create(request: Request) -> dict[str, Any]:
    schemas = request.app.state.services.get("schema_registry")
    if schemas is None:
        raise HTTPException(status_code=404, detail="records unavailable")
    body = await request.json()
    name = str(body["name"])
    schema = RecordTypeSchema(
        name,
        [
            FieldSchema(
                field.get("name"),
                field.get("type", "string"),
                bool(field.get("required", False)),
                field.get("default"),
                field.get("description", ""),
            )
            for field in body.get("fields", [])
        ],
        description=str(body.get("description", "")),
    )
    schemas.register(schema)
    persist_record_type(request.app.state.settings, schema)
    return {"name": name}

@router.delete(
    "/api/v1/record-types/{name}", dependencies=[Depends(require_api_key)]
)
async def api_record_types_delete(request: Request, name: str) -> dict[str, Any]:
    schemas = request.app.state.services.get("schema_registry")
    if schemas is None or not schemas.unregister(name):
        raise HTTPException(status_code=404, detail="record type not found")
    remove_record_type(request.app.state.settings, name)
    return {"success": True}

@router.get("/api/v1/webhooks", dependencies=[Depends(require_api_key)])
async def api_webhooks(request: Request, ) -> dict[str, Any]:
    service = request.app.state.services.get("webhook")
    names = sorted(service.webhooks) if service else []
    from app.db.models import WebhookEvent

    history: dict[str, list[dict[str, Any]]] = {}
    try:
        async with session_factory()() as session:
            events = (
                await session.scalars(
                    select(WebhookEvent)
                    .order_by(WebhookEvent.created_at.desc())
                    .limit(200)
                )
            ).all()
    except Exception:
        events = []
    for event in events:
        history.setdefault(event.webhook_name, []).append(
            {
                "time": (
                    event.created_at.isoformat() if event.created_at else ""
                ),
                "payload": event.payload,
            }
        )
    history = {name: entries[:10] for name, entries in history.items()}
    return {
        "webhooks": names,
        "filters": service.filters if service else {},
        "last_triggered": service.last_triggered if service else {},
        "history": history,
    }

@router.delete(
    "/api/v1/webhooks/{name}", dependencies=[Depends(require_api_key)]
)
async def api_webhooks_delete(request: Request, name: str) -> dict[str, Any]:
    service = request.app.state.services.get("webhook")
    if service is None or not service.remove(name):
        raise HTTPException(status_code=404, detail="webhook not found")
    request.app.state.settings.plugin_configs.setdefault("webhooks", {}).pop(name, None)
    save_settings(request.app.state.settings)
    return {"success": True}

@router.get("/api/v1/alerts", dependencies=[Depends(require_api_key)])
async def api_alerts(request: Request, ) -> dict[str, Any]:
    service = request.app.state.services.get("alerts")
    rules = service.rules if service else []
    return {
        "rules": [
            {
                "name": rule.name,
                "event": rule.event,
                "target_group": rule.target_group,
                "target_private": getattr(rule, "target_private", ""),
                "enabled": rule.enabled,
                "keyword": rule.keyword,
            }
            for rule in rules
        ]
    }

@router.get("/api/v1/state-machines", dependencies=[Depends(require_api_key)])
async def api_state_machines(request: Request, ) -> dict[str, Any]:
    service = request.app.state.services.get("state_machine")
    machines = list(service.machines) if service else []
    return {"state_machines": machines}

@router.post("/api/v1/state-machines", dependencies=[Depends(require_api_key)])
async def api_state_machines_create(request: Request) -> dict[str, Any]:
    service = request.app.state.services.get("state_machine")
    if service is None:
        raise HTTPException(status_code=404, detail="state machine unavailable")
    body = await request.json()
    from app.services.state_machine import StateMachine, Transition

    machine = StateMachine(body["name"])
    for item in body.get("transitions", []):
        machine.add(
            Transition(
                item.get("from", ""),
                item.get("to", ""),
                permission=item.get("permission", ""),
            )
        )
    service.register(machine)
    return {"name": body["name"]}

@router.post(
    "/api/v1/state-machines/{name}/transition",
    dependencies=[Depends(require_api_key)],
)
async def api_state_machine_transition(name: str, request: Request) -> dict[str, Any]:
    service = request.app.state.services.get("state_machine")
    if service is None:
        raise HTTPException(status_code=404, detail="state machine unavailable")
    body = await request.json()
    target = service.transition(
        name,
        body["from"],
        body["to"],
        permission=body.get("permission", ""),
    )
    return {"to": target}

@router.delete(
    "/api/v1/alerts/{name}", dependencies=[Depends(require_api_key)]
)
async def api_alerts_delete(request: Request, name: str) -> dict[str, Any]:
    service = request.app.state.services.get("alerts")
    if service is None or not service.remove_rule(name):
        raise HTTPException(status_code=404, detail="alert rule not found")
    persist_alert_rules(request.app.state.settings, service)
    return {"success": True}

@router.post("/api/v1/webhooks", dependencies=[Depends(require_api_key)])
async def api_webhooks_create(request: Request) -> dict[str, Any]:
    service = request.app.state.services.get("webhook")
    if service is None:
        raise HTTPException(status_code=404, detail="webhook unavailable")
    body = await request.json()
    name = str(body["name"])
    payload_filter = body.get("filter")
    if payload_filter is not None and not isinstance(payload_filter, dict):
        raise HTTPException(status_code=400, detail="filter must be an object")
    service.register(name, payload_filter)
    request.app.state.settings.plugin_configs.setdefault("webhooks", {})[name] = (
        payload_filter or {}
    )
    save_settings(request.app.state.settings)
    return {"name": name}

@router.post("/api/v1/alerts", dependencies=[Depends(require_api_key)])
async def api_alerts_create(request: Request) -> dict[str, Any]:
    service = request.app.state.services.get("alerts")
    if service is None:
        raise HTTPException(status_code=404, detail="alerts unavailable")
    body = await request.json()
    name = str(body["name"])
    service.add_rule(
        name,
        str(body.get("event", "*")),
        str(body.get("target_group", "")),
        str(body.get("target_private", "")),
        str(body.get("keyword", "")),
        int(body.get("min_interval_seconds", 0) or 0),
    )
    persist_alert_rules(request.app.state.settings, service)
    return {"name": name}

@router.post(
    "/api/v1/alerts/{name}/toggle", dependencies=[Depends(require_api_key)]
)
async def api_alerts_toggle(request: Request, name: str) -> dict[str, Any]:
    service = request.app.state.services.get("alerts")
    if service is None:
        raise HTTPException(status_code=404, detail="alerts unavailable")
    enabled = service.toggle_rule(name)
    if not service.rules or not any(r.name == name for r in service.rules):
        raise HTTPException(status_code=404, detail="alert rule not found")
    persist_alert_rules(request.app.state.settings, service)
    return {"name": name, "enabled": enabled}

@router.delete(
    "/api/v1/state-machines/{name}", dependencies=[Depends(require_api_key)]
)
async def api_state_machines_delete(request: Request, name: str) -> dict[str, Any]:
    service = request.app.state.services.get("state_machine")
    if service is None or not service.unregister(name):
        raise HTTPException(status_code=404, detail="state machine not found")
    return {"success": True}

@router.get("/api/v1/tasks", dependencies=[Depends(require_api_key)])
async def api_tasks(
    request: Request,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    async with session_factory()() as session:
        total = (
            await session.scalar(select(func.count()).select_from(Task))
        ) or 0
        tasks = (
            await session.scalars(
                select(Task)
                .order_by(Task.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
        ).all()
    return {
        "tasks": [
            {
                "task_id": task.task_id,
                "name": task.name,
                "type": task.type,
                "status": task.status,
                "enabled": task.enabled,
                "last_run_time": (
                    task.last_run_time.isoformat() if task.last_run_time else None
                ),
            }
            for task in tasks
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }

@router.post("/api/v1/tasks", dependencies=[Depends(require_api_key)])
async def api_tasks_create(request: Request) -> dict[str, Any]:
    body = await request.json()
    task_type = str(body.get("task_type", "interval"))
    if task_type not in {"interval", "cron"}:
        raise HTTPException(status_code=400, detail="task_type must be interval or cron")
    task_id = uuid4().hex
    interval_seconds = body.get("interval_seconds")
    cron_expression = str(body.get("cron_expression", ""))
    async with session_factory()() as session:
        session.add(
            Task(
                task_id=task_id,
                name=str(body["name"]),
                type=task_type,
                cron_expression=cron_expression or None,
                interval_seconds=int(interval_seconds) if interval_seconds else None,
                params={
                    "group_id": str(body.get("group_id", "")),
                    "message": str(body.get("message", "")),
                },
                enabled=bool(body.get("enabled", True)),
            )
        )
        await session.commit()
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler:
        func = _task_executor(task_id, request.app)
        try:
            if task_type == "cron" and cron_expression:
                scheduler.add_cron_job(
                    func, job_id=task_id, cron_expression=cron_expression
                )
            elif task_type == "interval" and interval_seconds:
                scheduler.add_interval_job(
                    func, job_id=task_id, seconds=int(interval_seconds)
                )
        except Exception:
            async with session_factory()() as session:
                task = await session.scalar(
                    select(Task).where(Task.task_id == task_id)
                )
                if task:
                    await session.delete(task)
                    await session.commit()
            raise HTTPException(
                status_code=400, detail="invalid task schedule configuration"
            )
    return {"task_id": task_id}

@router.post(
    "/api/v1/tasks/{task_id}/toggle", dependencies=[Depends(require_api_key)]
)
async def api_tasks_toggle(request: Request, task_id: str) -> dict[str, Any]:
    async with session_factory()() as session:
        task = await session.scalar(select(Task).where(Task.task_id == task_id))
        if task is None:
            raise HTTPException(status_code=404, detail="task not found")
        task.enabled = not task.enabled
        await session.commit()
    return {"task_id": task_id, "enabled": task.enabled}

@router.post(
    "/api/v1/tasks/{task_id}/run", dependencies=[Depends(require_api_key)]
)
async def api_tasks_run(request: Request, task_id: str) -> dict[str, Any]:
    await _task_executor(task_id, request.app)()
    return {"task_id": task_id, "status": "executed"}

@router.delete(
    "/api/v1/tasks/{task_id}", dependencies=[Depends(require_api_key)]
)
async def api_tasks_delete(request: Request, task_id: str) -> dict[str, Any]:
    async with session_factory()() as session:
        task = await session.scalar(select(Task).where(Task.task_id == task_id))
        if task is None:
            raise HTTPException(status_code=404, detail="task not found")
        await session.delete(task)
        await session.commit()
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler:
        try:
            scheduler.remove_job(task_id)
        except Exception:
            pass
    return {"success": True}

@router.post(
    "/api/v1/plugins/{name}/reload", dependencies=[Depends(require_api_key)]
)
async def api_plugin_reload(request: Request, name: str) -> dict[str, Any]:
    if request.app.state.plugin_manager is None:
        raise HTTPException(status_code=404, detail="plugin manager unavailable")
    success = await request.app.state.plugin_manager.reload_plugin(name)
    if not success:
        raise HTTPException(status_code=400, detail=f"plugin not loaded: {name}")
    return {"success": True, "name": name}

@router.post(
    "/api/v1/plugins/{name}/unload", dependencies=[Depends(require_api_key)]
)
async def api_plugin_unload(request: Request, name: str) -> dict[str, Any]:
    if request.app.state.plugin_manager is None:
        raise HTTPException(status_code=404, detail="plugin manager unavailable")
    success = await request.app.state.plugin_manager.unload_plugin(name)
    if not success:
        raise HTTPException(status_code=400, detail=f"plugin not loaded: {name}")
    return {"success": True, "name": name}

@router.get(
    "/api/v1/plugins/conflicts", dependencies=[Depends(require_api_key)]
)
async def api_plugin_conflicts(request: Request) -> dict[str, Any]:
    manager = getattr(request.app.state, "plugin_manager", None)
    if manager is None:
        raise HTTPException(status_code=404, detail="plugin manager unavailable")
    return {
        "conflicts": [
            {"plugin": item["name"], "conflicts": item.get("conflicts", [])}
            for item in manager.get_loaded_plugins()
            if item.get("conflicts")
        ]
    }

@router.get("/api/v1/backups", dependencies=[Depends(require_api_key)])
async def api_backups(request: Request, ) -> dict[str, Any]:
    service = request.app.state.services.get("backup")
    if service is None:
        raise HTTPException(status_code=404, detail="backup service unavailable")
    return {"backups": service.list_backups()}

@router.post("/api/v1/backups", dependencies=[Depends(require_api_key)])
async def api_create_backup(request: Request, ) -> dict[str, Any]:
    service = request.app.state.services.get("backup")
    if service is None:
        raise HTTPException(status_code=404, detail="backup service unavailable")
    root = PROJECT_ROOT
    target = await asyncio.to_thread(
        service.create_backup,
        root / "config.yaml",
        root / "data" / "ofbot2.db",
        root / "plugins",
    )
    return {"path": str(target)}

@router.post("/api/v1/plugins/install", dependencies=[Depends(require_api_key)])
async def api_install_plugin(request: Request, file: UploadFile = File(...)) -> dict[str, Any]:
    installer = request.app.state.services.get("installer")
    if installer is None:
        raise HTTPException(status_code=404, detail="installer unavailable")
    import tempfile
    from pathlib import Path

    suffix = Path(file.filename or "plugin.zip").suffix or ".zip"
    if file.size is not None and file.size > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413, detail="upload too large (max 100MB)"
        )
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413, detail="upload too large (max 100MB)"
        )
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir) / f"plugin{suffix}"
        tmp_path.write_bytes(data)
        try:
            target = await asyncio.to_thread(installer.install_zip, tmp_path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"installed": target.name, "path": str(target)}

