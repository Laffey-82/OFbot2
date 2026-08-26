"""配置与设置向导路由。"""

from __future__ import annotations

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
    JSONResponse,
    RedirectResponse,
)

from app.core.commands import command_registry
from app.core.config import Settings, save_settings
from app.core.logger import get_logger, set_log_level
from app.core.permissions import permission_manager
from app.core.security import audit_logger
from app.db.base import session_factory
from app.db.models import WebAccount
from app.web.deps import (
    get_csrf_token,
    get_current_user,
    require_admin,
    require_csrf,
)
from app.web.helpers import flash_redirect
from app.web.security import password_hasher

logger = get_logger(__name__)


def _validate_rate_limit(value: str) -> bool:
    """严格校验限流格式，如 20/minute、10/h。"""
    try:
        count, unit = value.strip().split("/", 1)
        count = int(count)
        return count > 0 and unit.lower() in {
            "s",
            "sec",
            "second",
            "m",
            "min",
            "minute",
            "h",
            "hour",
        }
    except (ValueError, TypeError):
        return False


def build_router(*, app: FastAPI, settings: Settings, templates: Any) -> APIRouter:
    router = APIRouter()

    @router.get("/config", response_class=HTMLResponse)
    async def config_page(
        request: Request,
        user: WebAccount = Depends(get_current_user),
        csrf_token: str = Depends(get_csrf_token),
    ) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "config.html",
            {
                "request": request,
                "user": user,
                "config": settings.model_dump(mode="json"),
                "csrf_token": csrf_token,
            },
        )

    @router.post("/config")
    async def config_update(
        request: Request,
        user: WebAccount = Depends(require_admin),
        command_start: str = Form(""),
        command_sep: str = Form(""),
        log_level: str = Form("INFO"),
        nickname: str = Form(""),
        superusers: str = Form(""),
        plugin_repo_url: str = Form(""),
        plugin_repo_token: str = Form(""),
        webhook_history_retention: int = Form(-1),
        webhook_history_page_size: int = Form(-1),
        export_job_retention: int = Form(-1),
        export_job_retention_days: int = Form(-1),
        export_retries: int = Form(-1),
        auto_disable_workflows_after_failures: int = Form(-1),
        auto_disable_after_failures: int = Form(-1),
        log_retention_days: int = Form(-1),
        log_max_files: int = Form(-1),
        session_ttl_seconds: int = Form(-1),
        scheduler_timezone: str = Form(""),
        scheduler_max_instances: int = Form(-1),
        scheduler_coalesce: str = Form(""),
        max_message_length: int = Form(-1),
        max_arg_length: int = Form(-1),
        default_cooldown_seconds: float = Form(-1),
        rate_limit_default: str = Form(""),
        sensitive_words: str = Form(""),
        audit_retention_days: int = Form(-1),
        login_failure_delay_seconds: float = Form(-1),
        max_login_attempts: int = Form(-1),
        login_lock_seconds: int = Form(-1),
        heartbeat_stale_seconds: int = Form(-1),
        alert_history_retention_days: int = Form(-1),
        alert_min_interval_seconds: int = Form(-1),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            return RedirectResponse("/config?error=1", status_code=303)
        if command_start:
            settings.basic.command_start = [
                item.strip() for item in command_start.split(",") if item.strip()
            ]
        if command_sep:
            settings.basic.command_sep = [
                item.strip() for item in command_sep.split(",") if item.strip()
            ]
        settings.web.plugin_repo_url = plugin_repo_url.strip()
        settings.web.plugin_repo_token = plugin_repo_token.strip()
        settings.basic.log_level = log_level
        if nickname:
            settings.basic.nickname = [
                item.strip() for item in nickname.split(",") if item.strip()
            ]
        if superusers:
            settings.basic.superusers = [
                item.strip() for item in superusers.split(",") if item.strip()
            ]
        if webhook_history_retention >= 0:
            settings.web.webhook_history_retention = webhook_history_retention
        if webhook_history_page_size >= 0:
            settings.web.webhook_history_page_size = webhook_history_page_size
        if export_job_retention >= 0:
            settings.web.export_job_retention = export_job_retention
        if export_job_retention_days >= 0:
            settings.web.export_job_retention_days = export_job_retention_days
        if export_retries >= 0:
            settings.web.export_retries = export_retries
        if auto_disable_workflows_after_failures >= 0:
            settings.web.auto_disable_workflows_after_failures = (
                auto_disable_workflows_after_failures
            )
        if auto_disable_after_failures >= 0:
            settings.scheduler.auto_disable_after_failures = (
                auto_disable_after_failures
            )
        if log_retention_days >= 1:
            settings.basic.log_retention_days = log_retention_days
        if log_max_files >= 1:
            settings.basic.log_max_files = log_max_files
        if session_ttl_seconds >= 300:
            settings.web.session_ttl_seconds = session_ttl_seconds
        if scheduler_timezone.strip():
            settings.scheduler.timezone = scheduler_timezone.strip()
        if scheduler_max_instances >= 1:
            settings.scheduler.max_instances = scheduler_max_instances
        if scheduler_coalesce in {"on", "off"}:
            settings.scheduler.coalesce = scheduler_coalesce == "on"
        if max_message_length >= 1:
            settings.security.max_message_length = max_message_length
        if max_arg_length >= 1:
            settings.security.max_arg_length = max_arg_length
        if default_cooldown_seconds >= 0:
            settings.security.default_cooldown_seconds = (
                default_cooldown_seconds
            )
        if rate_limit_default.strip():
            if not _validate_rate_limit(rate_limit_default):
                return RedirectResponse("/config?error=1", status_code=303)
            settings.security.rate_limit_default = (
                rate_limit_default.strip()
            )
        if sensitive_words:
            settings.security.sensitive_words = [
                item.strip()
                for item in sensitive_words.split(",")
                if item.strip()
            ]
        if audit_retention_days >= 1:
            settings.security.audit_retention_days = audit_retention_days
        if login_failure_delay_seconds >= 0:
            settings.security.login_failure_delay_seconds = (
                login_failure_delay_seconds
            )
        if max_login_attempts >= 0:
            settings.security.max_login_attempts = max_login_attempts
        if login_lock_seconds >= 0:
            settings.security.login_lock_seconds = login_lock_seconds
        if heartbeat_stale_seconds >= 1:
            settings.security.heartbeat_stale_seconds = heartbeat_stale_seconds
        if alert_history_retention_days >= 1:
            settings.web.alert_history_retention_days = (
                alert_history_retention_days
            )
        if alert_min_interval_seconds >= 0:
            settings.web.alert_min_interval_seconds = (
                alert_min_interval_seconds
            )
        save_settings(settings)
        permission_manager.apply_superusers(settings.basic.superusers)
        command_registry.set_command_start(settings.basic.command_start)
        command_registry.set_command_sep(settings.basic.command_sep)
        set_log_level(log_level)
        audit_logger.record(
            "config.updated",
            user.username,
            target="config.yaml",
            success=True,
        )
        return flash_redirect("/config", message="配置已保存")

    @router.get("/setup", response_class=HTMLResponse)
    async def setup_page(
        request: Request,
        user: WebAccount = Depends(get_current_user),
        csrf_token: str = Depends(get_csrf_token),
    ) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "setup.html",
            {
                "request": request,
                "user": user,
                "config": settings.model_dump(mode="json"),
                "csrf_token": csrf_token,
            },
        )

    @router.get("/setup/check")
    async def setup_check(
        request: Request,
        user: WebAccount = Depends(require_admin),
    ) -> JSONResponse:
        from app.services.doctor import run_environment_checks

        checks = await run_environment_checks(
            settings, app_state=app.state
        )
        return JSONResponse({"checks": checks})

    @router.post("/setup")
    async def setup_save(
        request: Request,
        user: WebAccount = Depends(require_admin),
        current_password: str = Form(""),
        new_password: str = Form(""),
        protocol: str = Form("red"),
        red_host: str = Form("127.0.0.1"),
        red_port: int = Form(16530),
        red_token: str = Form(""),
        red_api_base: str = Form(""),
        onebot_enabled: str = Form("off"),
        onebot_mode: str = Form("forward"),
        onebot_host: str = Form("127.0.0.1"),
        onebot_port: int = Form(9090),
        onebot_path: str = Form("/onebot/v11/ws"),
        onebot_access_token: str = Form(""),
        csrf: None = Depends(require_csrf),
    ) -> RedirectResponse:
        if protocol not in {"red", "onebot"}:
            return flash_redirect("/setup", error="1")
        if not (1 <= red_port <= 65535) or not (1 <= onebot_port <= 65535):
            return flash_redirect("/setup", error="1")
        if protocol == "red" and not red_token.strip():
            return flash_redirect("/setup", error="1")
        if protocol == "red" and not red_host.strip():
            return flash_redirect("/setup", error="1")
        if protocol == "onebot" and not onebot_host.strip():
            return flash_redirect("/setup", error="1")
        if new_password:
            if len(new_password) < 6:
                return flash_redirect("/setup", error="1")
            async with session_factory()() as session:
                account = await session.get(WebAccount, user.id)
                if account is None or not password_hasher.verify_password(
                    current_password, account.password_hash
                ):
                    return flash_redirect("/setup", error="1")
                account.password_hash = password_hasher.hash_password(new_password)
                await session.commit()
            audit_logger.record(
                "web.password_changed", user.username, target=str(user.id), success=True
            )
        settings.transport.protocol = protocol
        settings.transport.red.host = red_host
        settings.transport.red.port = red_port
        settings.transport.red.token = red_token
        if red_api_base:
            settings.transport.red.api_base = red_api_base
        settings.transport.onebot.enabled = onebot_enabled == "on"
        settings.transport.onebot.mode = (
            onebot_mode if onebot_mode in {"forward", "reverse"} else "forward"
        )
        settings.transport.onebot.host = onebot_host
        settings.transport.onebot.port = onebot_port
        settings.transport.onebot.path = onebot_path
        settings.transport.onebot.access_token = onebot_access_token
        save_settings(settings)
        audit_logger.record(
            "setup.completed", user.username, target="transport", success=True
        )
        message = "设置已保存"
        reconfigure = getattr(app.state, "reconfigure_adapters", None)
        if reconfigure is not None:
            try:
                await reconfigure()
                message += "，协议连接已热重载"
            except Exception:
                logger.exception("adapter reconfigure failed")
                message += "；协议连接重载失败，请重启服务"
        else:
            message += "；协议配置将在重启后生效"
        return flash_redirect("/", message=message)

    return router
