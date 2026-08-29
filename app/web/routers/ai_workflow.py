"""ai_workflow 页面路由。"""

from __future__ import annotations

import hmac
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    Form,
    HTTPException,
    Request,
)
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
)

from app.core.config import Settings, save_settings
from app.core.logger import get_logger
from app.core.security import audit_logger
from app.db.base import session_factory
from app.db.models import (
    WebAccount,
    Workflow,
    WorkflowRun,
)
from app.services.ai import (
    AnthropicProvider,
    GeminiProvider,
    OllamaProvider,
    OpenAIChatProvider,
)
from app.web.deps import (
    get_csrf_token,
    get_current_user,
    require_admin,
    require_csrf,
)
from app.web.helpers import (
    flash_redirect,
)

logger = get_logger(__name__)


def _record_schema_options(
    app: Any,
) -> tuple[list[str], dict[str, list[dict[str, str]]]]:
    """返回记录类型名列表与字段定义（供 create_record 模板生成）。"""
    schemas = app.state.services.get("schema_registry")
    types = schemas.list() if schemas else []
    names = [schema.name for schema in types]
    fields = {
        schema.name: [
            {"name": field.name, "type": field.field_type}
            for field in schema.fields
        ]
        for schema in types
    }
    return names, fields

def build_router(*, app: FastAPI, settings: Settings, templates: Any) -> APIRouter:
    router = APIRouter()
    @router.get("/ai", response_class=HTMLResponse)
    async def ai_page(
        request: Request,
        user: WebAccount = Depends(get_current_user),
        csrf_token: str = Depends(get_csrf_token),
    ) -> HTMLResponse:
        ai = app.state.services.get("ai")
        providers = list(ai.providers) if ai else []
        matrix = ai.matrix() if ai else {}
        active = ai.active_provider if ai else "mock"
        saved = settings.plugin_configs.get("ai", {})
        defaults = {
            "openai": {
                "api_key": "",
                "base_url": "https://api.openai.com/v1",
                "model": "gpt-4o-mini",
            },
            "anthropic": {
                "api_key": "",
                "base_url": "https://api.anthropic.com",
                "model": "claude-3-5-sonnet-latest",
            },
            "gemini": {
                "api_key": "",
                "base_url": "https://generativelanguage.googleapis.com",
                "model": "gemini-1.5-flash",
            },
            "ollama": {
                "api_key": "",
                "base_url": "http://127.0.0.1:11434",
                "model": "qwen2.5:7b",
            },
        }
        for name, base in defaults.items():
            merged = dict(base)
            merged.update(saved.get(name, {}))
            defaults[name] = merged
        return templates.TemplateResponse(
            request,
            "ai.html",
            {
                "request": request,
                "user": user,
                "providers": providers,
                "matrix": matrix,
                "active": active,
                "configs": defaults,
                "csrf_token": csrf_token,
            },
        )

    @router.post("/ai/config")
    async def ai_config(
        request: Request,
        user: WebAccount = Depends(require_admin),
        provider: str = Form("openai"),
        api_key: str = Form(""),
        base_url: str = Form(""),
        model: str = Form(""),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        if provider not in {"openai", "anthropic", "gemini", "ollama"}:
            return flash_redirect("/ai", error="1")
        cfg: dict[str, str] = {"api_key": api_key, "base_url": base_url, "model": model}
        settings.plugin_configs.setdefault("ai", {})[provider] = cfg
        save_settings(settings)
        ai = app.state.services.get("ai")
        if ai:
            if provider == "openai" and api_key:
                ai.register(
                    OpenAIChatProvider(
                        base_url=base_url or "https://api.openai.com/v1",
                        api_key=api_key,
                        model=model or "gpt-4o-mini",
                    )
                )
            elif provider == "anthropic" and api_key:
                ai.register(
                    AnthropicProvider(
                        base_url=base_url or "https://api.anthropic.com",
                        api_key=api_key,
                        model=model or "claude-3-5-sonnet-latest",
                    )
                )
            elif provider == "gemini" and api_key:
                ai.register(
                    GeminiProvider(
                        base_url=base_url or "https://generativelanguage.googleapis.com",
                        api_key=api_key,
                        model=model or "gemini-1.5-flash",
                    )
                )
            elif provider == "ollama":
                ai.register(
                    OllamaProvider(
                        base_url=base_url or "http://127.0.0.1:11434",
                        model=model or "qwen2.5:7b",
                    )
                )
            if provider in ai.providers:
                ai.set_active(provider)
        audit_logger.record(
            "ai.config_updated", user.username, target=provider, success=True
        )
        return flash_redirect("/ai", message="AI 配置已保存")

    @router.post("/ai/activate")
    async def ai_activate(
        request: Request,
        user: WebAccount = Depends(require_admin),
        provider: str = Form("mock"),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        ai = app.state.services.get("ai")
        if ai is None or provider not in ai.providers:
            return flash_redirect("/ai", error="1")
        ai.set_active(provider)
        audit_logger.record(
            "ai.activated", user.username, target=provider, success=True
        )
        return flash_redirect("/ai", message=f"已切换到 {provider} Provider")

    @router.post("/ai/test")
    async def ai_test(
        request: Request,
        user: WebAccount = Depends(require_admin),
        provider: str = Form("mock"),
        csrf: None = Depends(require_csrf),
    ) -> JSONResponse:
        ai = app.state.services.get("ai")
        if ai is None or provider not in ai.providers:
            return JSONResponse(
                {"ok": False, "detail": "provider 未注册，请先保存配置"}
            )
        try:
            reply = await ai.chat(
                [{"role": "user", "content": "请回复 OK"}],
                provider=provider,
            )
            return JSONResponse({"ok": True, "reply": reply})
        except Exception as exc:
            return JSONResponse({"ok": False, "detail": str(exc)})

    @router.get("/ai/agent")
    async def ai_agent_status(
        request: Request,
        user: WebAccount = Depends(get_current_user),
    ) -> JSONResponse:
        runner = app.state.services.get("agent")
        if runner is None:
            return JSONResponse({"tools": [], "logs": []})
        return JSONResponse(
            {
                "tools": runner.list_tools(),
                "logs": runner.get_logs(limit=20),
            }
        )

    @router.post("/ai/agent/run")
    async def ai_agent_run(
        request: Request,
        user: WebAccount = Depends(require_admin),
        prompt: str = Form(...),
        session_id: str = Form("web"),
        max_rounds: int = Form(5),
        csrf: None = Depends(require_csrf),
    ) -> JSONResponse:
        runner = app.state.services.get("agent")
        if runner is None:
            return JSONResponse({"ok": False, "detail": "Agent 未初始化"})
        permission_check = app.state.services.get("agent_permission")
        try:
            final = await runner.run(
                prompt,
                session_id=session_id or "web",
                max_rounds=max_rounds,
                permission_check=permission_check,
            )
        except Exception as exc:
            audit_logger.record(
                "agent.run_failed",
                user.username,
                target=session_id or "web",
                success=False,
                detail={"error": str(exc)},
            )
            return JSONResponse({"ok": False, "detail": str(exc)})
        audit_logger.record(
            "agent.run",
            user.username,
            target=session_id or "web",
            success=True,
            detail={"prompt": prompt[:200]},
        )
        return JSONResponse(
            {
                "ok": True,
                "final": final,
                "logs": runner.get_logs(
                    session_id=session_id or "web", limit=5
                ),
            }
        )

    @router.get("/workflows", response_class=HTMLResponse)
    async def workflows_page(
        request: Request,
        user: WebAccount = Depends(get_current_user),
        csrf_token: str = Depends(get_csrf_token),
    ) -> HTMLResponse:
        engine = app.state.services.get("workflow")
        workflows = await engine.list() if engine else []
        runs = await engine.list_runs() if engine else []
        actions = sorted(engine.actions) if engine else []
        record_types, record_schemas = _record_schema_options(app)
        template_service = app.state.services.get("workflow_templates")
        template_list = (
            template_service.list_templates()
            if template_service is not None
            else []
        )
        return templates.TemplateResponse(
            request,
            "workflows.html",
            {
                "request": request,
                "user": user,
                "workflows": workflows,
                "runs": runs,
                "actions": actions,
                "record_types": record_types,
                "record_schemas": record_schemas,
                "templates": template_list,
                "csrf_token": csrf_token,
            },
        )

    @router.post("/workflows/{workflow_id}/dry-run")
    async def workflows_dry_run(
        workflow_id: int,
        request: Request,
        user: WebAccount = Depends(require_admin),
        csrf: None = Depends(require_csrf),
    ) -> JSONResponse:
        engine = app.state.services.get("workflow")
        if engine is None:
            return JSONResponse(
                {"ok": False, "detail": "流程引擎未初始化"}
            )
        try:
            report = await engine.dry_run(workflow_id, {})
        except Exception as exc:
            return JSONResponse({"ok": False, "detail": str(exc)})
        audit_logger.record(
            "workflow.dry_run",
            user.username,
            target=str(workflow_id),
            success=bool(report["valid"]),
        )
        return JSONResponse({"ok": True, "report": report})

    @router.post("/workflows/import-template")
    async def workflows_import_template(
        request: Request,
        user: WebAccount = Depends(require_admin),
        template_id: str = Form(...),
        name: str = Form(""),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        engine = app.state.services.get("workflow")
        templates = app.state.services.get("workflow_templates")
        if engine is None or templates is None:
            return flash_redirect("/workflows", error="模板服务未初始化")
        try:
            workflow = await templates.import_template(
                engine, template_id, name or None
            )
        except Exception as exc:
            return flash_redirect("/workflows", error=f"导入失败：{exc}")
        audit_logger.record(
            "workflow.template_imported",
            user.username,
            target=template_id,
            success=True,
        )
        return flash_redirect(
            "/workflows", message=f"已从模板导入流程 {workflow.name}"
        )

    @router.post("/workflows/dry-run-definition")
    async def workflows_dry_run_definition(
        request: Request,
        user: WebAccount = Depends(require_admin),
        steps_json: str = Form(...),
        trigger_json: str = Form(""),
        condition_json: str = Form(""),
        csrf: None = Depends(require_csrf),
    ) -> JSONResponse:
        engine = app.state.services.get("workflow")
        if engine is None:
            return JSONResponse(
                {"ok": False, "detail": "流程引擎未初始化"}
            )
        try:
            import json

            steps = json.loads(steps_json)
            definition: dict[str, Any] = {"steps": steps}
            if trigger_json:
                trigger = json.loads(trigger_json)
                if isinstance(trigger, dict) and trigger.get("type"):
                    definition["trigger"] = trigger
            if condition_json:
                condition = json.loads(condition_json)
                if isinstance(condition, (dict, list)):
                    definition["condition"] = condition
        except Exception as exc:
            return JSONResponse({"ok": False, "detail": f"JSON 无效：{exc}"})

        errors: list[str] = []
        warnings: list[str] = []
        steps = definition.get("steps", [])
        if not steps:
            warnings.append("流程没有动作步骤")
        for index, step in enumerate(steps, start=1):
            action_name = step.get("action") if isinstance(step, dict) else None
            if not action_name:
                errors.append(f"第 {index} 步缺少 action")
            elif action_name not in engine.actions:
                errors.append(f"第 {index} 步动作 {action_name} 未注册")
            elif not isinstance(step.get("params"), dict):
                errors.append(f"第 {index} 步参数必须是对象")
        audit_logger.record(
            "workflow.dry_run_definition",
            user.username,
            target="definition",
            success=not errors,
        )
        return JSONResponse(
            {
                "ok": True,
                "report": {
                    "valid": not errors,
                    "errors": errors,
                    "warnings": warnings,
                    "would_run_steps": len(steps) if not errors else 0,
                },
            }
        )

    @router.post("/workflows/create")
    async def workflows_create(
        request: Request,
        user: WebAccount = Depends(require_admin),
        name: str = Form(...),
        steps_json: str = Form(...),
        trigger_json: str = Form(""),
        condition_json: str = Form(""),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        engine = app.state.services.get("workflow")
        if engine is None:
            return RedirectResponse("/workflows?error=1", status_code=303)
        try:
            import json

            steps = json.loads(steps_json)
            definition: dict[str, Any] = {"steps": steps}
            if trigger_json:
                trigger = json.loads(trigger_json)
                if isinstance(trigger, dict) and trigger.get("type"):
                    definition["trigger"] = trigger
            if condition_json:
                condition = json.loads(condition_json)
                if isinstance(condition, (dict, list)):
                    definition["condition"] = condition
            workflow = await engine.create(name, definition)
        except Exception:
            return RedirectResponse("/workflows?error=1", status_code=303)
        scheduler = getattr(app.state, "scheduler", None)
        if scheduler:
            trigger = definition.get("trigger", {})
            if trigger.get("type") == "schedule" and trigger.get("cron"):
                try:
                    import functools

                    scheduler.add_cron_job(
                        functools.partial(engine.execute, workflow.id),
                        job_id=f"workflow-{workflow.id}",
                        cron_expression=trigger["cron"],
                    )
                except Exception:
                    pass
        return flash_redirect("/workflows", message=f"流程 {name} 已创建")

    @router.post("/workflows/{workflow_id}/run")
    async def workflows_run(
        workflow_id: int,
        request: Request,
        user: WebAccount = Depends(require_admin),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        engine = app.state.services.get("workflow")
        if engine is None:
            return RedirectResponse("/workflows?error=1", status_code=303)
        try:
            await engine.execute(workflow_id)
        except Exception:
            return RedirectResponse("/workflows?error=1", status_code=303)
        return flash_redirect("/workflows", message="流程已运行")

    @router.post("/workflows/{workflow_id}/enable")
    async def workflows_enable(
        workflow_id: int,
        request: Request,
        user: WebAccount = Depends(require_admin),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        from app.db.base import session_factory
        from app.db.models import Workflow

        engine = app.state.services.get("workflow")
        async with session_factory()() as session:
            workflow = await session.get(Workflow, workflow_id)
            if workflow is None:
                return flash_redirect("/workflows", error="1")
            workflow.enabled = True
            definition = dict(workflow.definition)
            definition.pop("auto_disabled", None)
            workflow.definition = definition
            await session.commit()
        scheduler = getattr(app.state, "scheduler", None)
        if scheduler:
            trigger = workflow.definition.get("trigger", {})
            if trigger.get("type") == "schedule" and trigger.get("cron"):
                try:
                    import functools

                    if engine is not None:
                        scheduler.add_cron_job(
                            functools.partial(engine.execute, workflow_id),
                            job_id=f"workflow-{workflow_id}",
                            cron_expression=trigger["cron"],
                        )
                except Exception:
                    pass
        audit_logger.record(
            "workflow.enabled",
            user.username,
            target=str(workflow_id),
            success=True,
        )
        return flash_redirect("/workflows", message="流程已重新启用")

    @router.post("/workflows/{workflow_id}/delete")
    async def workflows_delete(
        workflow_id: int,
        request: Request,
        user: WebAccount = Depends(require_admin),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        engine = app.state.services.get("workflow")
        if engine is None:
            return flash_redirect("/workflows", error="1")
        try:
            removed = await engine.delete(workflow_id)
            if not removed:
                return flash_redirect("/workflows", error="1")
        except Exception:
            return flash_redirect("/workflows", error="1")
        scheduler = getattr(app.state, "scheduler", None)
        if scheduler:
            try:
                scheduler.remove_job(f"workflow-{workflow_id}")
            except Exception:
                pass
        return flash_redirect("/workflows", message="流程已删除")

    @router.get("/workflows/{workflow_id}/edit", response_class=HTMLResponse)
    async def workflow_edit_page(
        workflow_id: int,
        request: Request,
        user: WebAccount = Depends(get_current_user),
        csrf_token: str = Depends(get_csrf_token),
    ) -> HTMLResponse:
        engine = app.state.services.get("workflow")
        workflow = await engine.get(workflow_id) if engine else None
        if workflow is None:
            raise HTTPException(status_code=404, detail="workflow not found")
        actions = sorted(engine.actions) if engine else []
        record_types, record_schemas = _record_schema_options(app)
        return templates.TemplateResponse(
            request,
            "workflow_edit.html",
            {
                "request": request,
                "user": user,
                "workflow": workflow,
                "actions": actions,
                "record_types": record_types,
                "record_schemas": record_schemas,
                "csrf_token": csrf_token,
            },
        )

    @router.post("/workflows/{workflow_id}/edit")
    async def workflow_edit_save(
        workflow_id: int,
        request: Request,
        user: WebAccount = Depends(require_admin),
        name: str = Form(...),
        steps_json: str = Form(...),
        trigger_json: str = Form(""),
        condition_json: str = Form(""),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        import json

        engine = app.state.services.get("workflow")
        if engine is None:
            return flash_redirect("/workflows", error="1")
        try:
            steps = json.loads(steps_json)
            definition: dict[str, Any] = {"steps": steps}
            if trigger_json:
                trigger = json.loads(trigger_json)
                if isinstance(trigger, dict) and trigger.get("type"):
                    definition["trigger"] = trigger
            if condition_json:
                condition = json.loads(condition_json)
                if isinstance(condition, (dict, list)):
                    definition["condition"] = condition
            workflow = await engine.update(workflow_id, name=name, definition=definition)
            if workflow is None:
                return flash_redirect("/workflows", error="1")
        except Exception:
            return flash_redirect("/workflows", error="1")
        scheduler = getattr(app.state, "scheduler", None)
        if scheduler:
            try:
                scheduler.remove_job(f"workflow-{workflow_id}")
            except Exception:
                pass
            trigger = definition.get("trigger", {})
            if trigger.get("type") == "schedule" and trigger.get("cron"):
                try:
                    import functools

                    scheduler.add_cron_job(
                        functools.partial(engine.execute, workflow_id),
                        job_id=f"workflow-{workflow_id}",
                        cron_expression=trigger["cron"],
                    )
                except Exception:
                    pass
        audit_logger.record(
            "workflow.updated", user.username, target=str(workflow_id), success=True
        )
        return flash_redirect("/workflows", message=f"流程 {name} 已更新")

    @router.get("/workflows/runs/{run_id}", response_class=HTMLResponse)
    async def workflow_run_detail(
        run_id: int,
        request: Request,
        user: WebAccount = Depends(get_current_user),
        csrf_token: str = Depends(get_csrf_token),
    ) -> HTMLResponse:

        async with session_factory()() as session:
            run = await session.get(WorkflowRun, run_id)
            workflow = (
                await session.get(Workflow, run.workflow_id) if run else None
            )
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        return templates.TemplateResponse(
            request,
            "workflow_run.html",
            {
                "request": request,
                "user": user,
                "run": run,
                "workflow": workflow,
                "csrf_token": csrf_token,
            },
        )

    @router.post("/webhook/{name}")
    async def webhook_receive(name: str, request: Request) -> dict[str, Any]:
        secret = getattr(settings.web, "webhook_secret", "") or ""
        if secret:
            supplied = request.headers.get("x-webhook-secret", "")
            if not supplied or not hmac.compare_digest(supplied, secret):
                return JSONResponse(
                    status_code=403, content={"detail": "invalid webhook secret"}
                )
        service = app.state.services.get("webhook")
        if service is None or not await service.handle(name, await request.json()):
            raise HTTPException(status_code=404, detail="webhook not found")
        return {"success": True}


    return router
