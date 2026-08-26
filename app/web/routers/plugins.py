"""插件、命令速查与能力中心路由。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    File,
    Form,
    Request,
    UploadFile,
)
from fastapi.responses import (
    HTMLResponse,
    RedirectResponse,
    Response,
)

from app.core.capabilities import capability_registry
from app.core.commands import command_registry
from app.core.config import Settings, save_settings
from app.core.logger import get_logger
from app.core.security import audit_logger
from app.db.models import WebAccount
from app.services.plugin_state import get_plugin_states, save_plugin_state
from app.web.deps import (
    get_csrf_token,
    get_current_user,
    require_admin,
    require_csrf,
)
from app.web.helpers import flash_redirect

logger = get_logger(__name__)

ROOT = Path(__file__).resolve().parents[3]


def _version_greater(candidate: str, base: str) -> bool:
    """简单语义化版本比较（X.Y.Z）。"""

    def parts(value: str) -> tuple:
        return tuple(
            int(part) for part in value.split(".")[:3] if part.isdigit()
        ) or (0,)

    return parts(candidate) > parts(base)


def _repo_service(app: FastAPI, settings: Settings):
    """获取插件仓库服务；每次读取最新 repo_url/token（配置页修改即时生效）。"""
    service = getattr(app.state, "plugin_repo_service", None)
    if service is None:
        from app.services.plugin_repo import PluginRepoService

        service = PluginRepoService(
            ROOT / "plugins",
            ROOT / "plugin-repo",
            repo_url=settings.web.plugin_repo_url,
            token=settings.web.plugin_repo_token,
        )
        app.state.plugin_repo_service = service
    service.repo_url = (settings.web.plugin_repo_url or "").strip()
    service.token = (settings.web.plugin_repo_token or "").strip()
    service._cache = None
    return service


def build_router(*, app: FastAPI, settings: Settings, templates: Any) -> APIRouter:
    router = APIRouter()

    @router.get("/plugins", response_class=HTMLResponse)
    async def plugins_page(
        request: Request,
        user: WebAccount = Depends(get_current_user),
        csrf_token: str = Depends(get_csrf_token),
    ) -> HTMLResponse:
        plugins = (
            app.state.plugin_manager.get_loaded_plugins()
            if app.state.plugin_manager
            else []
        )
        manager = app.state.plugin_manager
        if manager:
            loaded_names = {plugin["name"] for plugin in plugins}
            for name in sorted(manager.discover()):
                if name in loaded_names:
                    continue
                manifest = manager.read_manifest(manager.discover()[name])
                plugins.append(
                    {
                        "name": name,
                        "version": manifest.version,
                        "description": manifest.description,
                        "state": "unloaded",
                        "config_schema": manifest.config_schema,
                        "config": settings.plugin_configs.get(name, {}),
                    }
                )
        scaffold = app.state.services.get("scaffold")
        scaffold_templates = scaffold.list_templates() if scaffold else []
        states = await get_plugin_states()
        for plugin in plugins:
            persisted = states.get(plugin.get("name", ""), {})
            if persisted.get("state") == "error":
                plugin["state"] = "error"
            plugin["error"] = persisted.get("error", "") or plugin.get(
                "error", ""
            )
            if manager is not None:
                loaded = manager.loaded.get(plugin.get("name", ""))
                if loaded is not None:
                    plugin["features"] = [
                        {
                            "key": key,
                            "label": spec.label or spec.id,
                            "description": spec.description,
                            "enable_on_default": spec.enable_on_default,
                            "commands": len(spec.commands),
                            "tasks": len(spec.tasks),
                            "listeners": len(spec.listeners),
                        }
                        for key, spec in loaded.features.items()
                    ]
                else:
                    plugin["features"] = []
        command_counts: dict[str, int] = {}
        for command in command_registry.get_commands():
            plugin_name = command.plugin_name or "未归属"
            command_counts[plugin_name] = command_counts.get(plugin_name, 0) + 1
        return templates.TemplateResponse(
            request,
            "plugins.html",
            {
                "request": request,
                "user": user,
                "plugins": plugins,
                "templates": scaffold_templates,
                "command_counts": command_counts,
                "csrf_token": csrf_token,
            },
        )

    @router.get("/commands", response_class=HTMLResponse)
    async def commands_page(
        request: Request,
        user: WebAccount = Depends(get_current_user),
        q: str = "",
        plugin: str = "",
    ) -> HTMLResponse:
        from app.core.permissions import permission_manager

        rows: list[dict] = []
        for command in command_registry.get_commands():
            perm = permission_manager.get_permission(command.permission)
            rows.append(
                {
                    "name": command.name,
                    "aliases": sorted(command.aliases - {command.name}),
                    "description": command.description,
                    "permission": command.permission,
                    "permission_desc": perm.description if perm else "",
                    "cooldown": command.cooldown,
                    "rate_limit": command.rate_limit or "",
                    "usage": command.usage,
                    "examples": command.examples,
                    "params": [
                        param.model_dump() for param in command.params
                    ],
                    "subcommands": [
                        sub.model_dump() for sub in command.subcommands
                    ],
                    "plugin": command.plugin_name or "未归属",
                }
            )
        plugin_names = sorted({row["plugin"] for row in rows})
        if plugin:
            rows = [row for row in rows if row["plugin"] == plugin]
        query = q.strip().lower()
        if query:
            rows = [
                row
                for row in rows
                if query in row["name"].lower()
                or query in row["description"].lower()
                or query in row["permission"].lower()
                or query in row["plugin"].lower()
                or any(query in alias.lower() for alias in row["aliases"])
            ]
        return templates.TemplateResponse(
            request,
            "commands.html",
            {
                "request": request,
                "user": user,
                "rows": rows,
                "plugin_names": plugin_names,
                "q": q,
                "plugin": plugin,
                "command_prefix": (command_registry.command_start or ["/"])[0],
            },
        )

    @router.get("/commands/export")
    async def commands_export(
        request: Request,
        user: WebAccount = Depends(get_current_user),
        q: str = "",
        plugin: str = "",
    ) -> Response:
        import csv
        import io

        from app.core.permissions import permission_manager

        rows: list[dict] = []
        for command in command_registry.get_commands():
            perm = permission_manager.get_permission(command.permission)
            rows.append(
                {
                    "name": command.name,
                    "aliases": " ".join(
                        sorted(command.aliases - {command.name})
                    ),
                    "description": command.description,
                    "permission": command.permission,
                    "permission_desc": perm.description if perm else "",
                    "cooldown": command.cooldown,
                    "rate_limit": command.rate_limit or "",
                    "usage": command.usage,
                    "examples": " ｜ ".join(command.examples),
                    "params": " ".join(
                        f"{param.name}:{param.type}" for param in command.params
                    ),
                    "subcommands": " ".join(
                        sub.name for sub in command.subcommands
                    ),
                    "plugin": command.plugin_name or "未归属",
                }
            )
        if plugin:
            rows = [row for row in rows if row["plugin"] == plugin]
        query = q.strip().lower()
        if query:
            rows = [
                row
                for row in rows
                if query in row["name"].lower()
                or query in row["description"].lower()
                or query in row["permission"].lower()
                or query in row["plugin"].lower()
            ]
        buffer = io.StringIO()
        fieldnames = [
            "name",
            "aliases",
            "description",
            "permission",
            "permission_desc",
            "cooldown",
            "rate_limit",
            "usage",
            "examples",
            "params",
            "subcommands",
            "plugin",
        ]
        writer = csv.DictWriter(buffer, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        filename = f"commands_{datetime.now(UTC).strftime('%Y%m%d_%H%M')}.csv"
        return Response(
            buffer.getvalue().encode("utf-8-sig"),
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            },
        )

    @router.get("/plugins/repo", response_class=HTMLResponse)
    async def plugin_repo_page(
        request: Request,
        user: WebAccount = Depends(get_current_user),
        csrf_token: str = Depends(get_csrf_token),
        q: str = "",
        category: str = "",
    ) -> HTMLResponse:
        service = _repo_service(app, settings)
        plugins: list[dict] = []
        error = ""
        try:
            for meta in await service.list_plugins():
                data = meta.model_dump()
                installed_version = service.installed_version(data["name"])
                data["installed_version"] = installed_version or ""
                data["can_update"] = bool(
                    installed_version
                    and _version_greater(data.get("version", ""), installed_version)
                )
                plugins.append(data)
        except Exception as exc:
            error = str(exc)
        installed = {
            path.name
            for path in service.plugins_dir.iterdir()
            if (path / "plugin.json").exists()
        }
        categories = sorted(
            {str(item["category"]) for item in plugins if item.get("category")}
        )
        query = q.strip().lower()
        if query:
            plugins = [
                item
                for item in plugins
                if query in item["name"].lower()
                or query in item.get("description", "").lower()
                or query in item.get("author", "").lower()
            ]
        if category:
            plugins = [
                item for item in plugins if item.get("category") == category
            ]
        return templates.TemplateResponse(
            request,
            "plugin_repo.html",
            {
                "request": request,
                "user": user,
                "plugins": plugins,
                "error": error,
                "installed": installed,
                "categories": categories,
                "q": q,
                "category": category,
                "mode": "URL" if settings.web.plugin_repo_url else "本地目录",
                "repo_url": settings.web.plugin_repo_url,
                "has_token": bool(settings.web.plugin_repo_token),
                "csrf_token": csrf_token,
            },
        )

    @router.post("/plugins/repo/install")
    async def plugin_repo_install(
        request: Request,
        user: WebAccount = Depends(require_admin),
        plugin_id: str = Form(...),
        target_name: str = Form(""),
        replace: str = Form(""),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        service = _repo_service(app, settings)
        try:
            installed = await service.install(
                plugin_id,
                target_name.strip() or None,
                replace=replace == "1",
            )
        except Exception as exc:
            audit_logger.record(
                "plugin_repo.install_failed",
                user.username,
                target=plugin_id,
                success=False,
                detail={"error": str(exc)},
            )
            return flash_redirect(
                "/plugins/repo", error=f"安装失败：{exc}"
            )
        audit_logger.record(
            "plugin_repo.installed",
            user.username,
            target=plugin_id,
            success=True,
        )
        return flash_redirect(
            "/plugins/repo",
            message=f"已安装 {installed.name}（默认未启用，可在「插件」页启用）",
        )

    @router.post("/plugins/{name}/reload")
    async def reload_plugin(
        name: str,
        request: Request,
        user: WebAccount = Depends(require_admin),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        manager = app.state.plugin_manager
        if manager is None or not await manager.reload_plugin(name):
            return flash_redirect("/plugins", error=f"插件 {name} 未加载或不存在")
        audit_logger.record(
            "plugin.reloaded", user.username, target=name, success=True
        )
        return flash_redirect("/plugins", message=f"插件 {name} 已重载")

    @router.post("/plugins/{name}/unload")
    async def unload_plugin(
        name: str,
        request: Request,
        user: WebAccount = Depends(require_admin),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        manager = app.state.plugin_manager
        if manager is None or not await manager.unload_plugin(name):
            return flash_redirect("/plugins", error=f"插件 {name} 未加载或不存在")
        if manager:
            audit_logger.record(
                "plugin.unloaded", user.username, target=name, success=True
            )
        await save_plugin_state(name, "unloaded")
        settings.plugins[name] = False
        save_settings(settings)
        return flash_redirect("/plugins", message=f"插件 {name} 已卸载")

    @router.post("/plugins/{name}/load")
    async def load_plugin_route(
        name: str,
        request: Request,
        user: WebAccount = Depends(require_admin),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        manager = app.state.plugin_manager
        if manager is None or name not in manager.discover():
            return flash_redirect("/plugins", error="1")
        try:
            manager.load_plugin(
                name,
                manager.plugins_dir / name,
                config=settings.plugin_configs.get(name, {}),
            )
            await manager.start_plugin(name)
        except Exception as exc:
            logger.exception("failed to load plugin %s", name)
            await save_plugin_state(name, "error", error=str(exc))
            return flash_redirect("/plugins", error=f"加载失败：{exc}")
        await save_plugin_state(name, "loaded", version=(
            manager.read_manifest(manager.plugins_dir / name).version
        ))
        settings.plugins[name] = True
        save_settings(settings)
        audit_logger.record(
            "plugin.loaded", user.username, target=name, success=True
        )
        return flash_redirect("/plugins", message=f"插件 {name} 已启用")

    @router.post("/plugins/{name}/config")
    async def plugin_config_save(
        name: str,
        request: Request,
        user: WebAccount = Depends(require_admin),
        config_json: str = Form(...),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        import json

        try:
            config = json.loads(config_json)
            if not isinstance(config, dict):
                raise TypeError("config must be an object")
        except Exception:
            return flash_redirect("/plugins", error="1")
        settings.plugin_configs[name] = config
        save_settings(settings)
        if app.state.plugin_manager:
            await app.state.plugin_manager.reload_plugin(name, config=config)
        audit_logger.record(
            "plugin.config_updated", user.username, target=name, success=True
        )
        return flash_redirect("/plugins", message=f"插件 {name} 配置已保存并重载")

    @router.post("/plugins/new")
    async def plugin_scaffold_create(
        request: Request,
        user: WebAccount = Depends(require_admin),
        name: str = Form(...),
        template: str = Form(""),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        import re

        name = name.strip()
        if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
            return flash_redirect("/plugins", error="1")
        scaffold = app.state.services.get("scaffold")
        if scaffold is None:
            return flash_redirect("/plugins", error="1")
        try:
            scaffold.create_from_template(template or "dice", name)
        except Exception:
            return flash_redirect("/plugins", error="1")
        settings.plugins[name] = True
        settings.plugin_configs.setdefault(name, {})
        save_settings(settings)
        if app.state.plugin_manager:
            try:
                app.state.plugin_manager.load_plugin(
                    name,
                    app.state.plugin_manager.plugins_dir / name,
                    config=settings.plugin_configs.get(name, {}),
                )
                await app.state.plugin_manager.start_plugin(name)
            except Exception as exc:
                logger.exception("failed to load scaffolded plugin %s", name)
                await save_plugin_state(
                    name, "error", error=str(exc), version="0.1.0"
                )
                return flash_redirect(
                    "/plugins",
                    error=f"插件已创建但加载失败：{type(exc).__name__}: {exc}",
                )
            await save_plugin_state(name, "loaded", version="0.1.0")
        audit_logger.record(
            "plugin.scaffolded", user.username, target=name, success=True
        )
        return flash_redirect("/plugins", message=f"插件 {name} 已创建并启用")

    @router.post("/plugins/install")
    async def plugin_install_upload(
        request: Request,
        user: WebAccount = Depends(require_admin),
        file: UploadFile = File(...),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        installer = app.state.services.get("installer")
        if installer is None:
            return flash_redirect("/plugins", error="1")
        import tempfile
        from pathlib import Path

        suffix = Path(file.filename or "plugin.zip").suffix or ".zip"
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir) / f"plugin{suffix}"
            tmp_path.write_bytes(await file.read())
            try:
                target = installer.install_zip(tmp_path)
            except ValueError as exc:
                audit_logger.record(
                    "plugin.install_failed",
                    user.username,
                    target=str(file.filename or ""),
                    success=False,
                    detail={"error": str(exc)},
                )
                return flash_redirect("/plugins", error="2")
        audit_logger.record(
            "plugin.installed",
            user.username,
            target=target.name,
            success=True,
        )
        return flash_redirect(
            "/plugins",
            message=f"插件 {target.name} 已安装，可前往插件列表启用",
        )

    @router.get("/capabilities", response_class=HTMLResponse)
    async def capabilities_page(
        request: Request,
        user: WebAccount = Depends(get_current_user),
    ) -> HTMLResponse:
        capabilities = capability_registry.list()
        return templates.TemplateResponse(
            request,
            "capabilities.html",
            {"request": request, "user": user, "capabilities": capabilities},
        )

    return router
