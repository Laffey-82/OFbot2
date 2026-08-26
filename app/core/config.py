from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator


class BasicSettings(BaseModel):
    command_start: list[str] = Field(default_factory=lambda: ["/", "!"])
    command_sep: list[str] = Field(default_factory=lambda: ["."])
    nickname: list[str] = Field(default_factory=lambda: ["OFbot_2"])
    superusers: list[str] = Field(default_factory=list)
    language: str = "zh-CN"
    log_level: str = "INFO"
    log_retention_days: int = 14
    log_max_files: int = 60


class RedSettings(BaseModel):
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 16530
    token: str = ""
    api_base: str = "http://127.0.0.1:16530"
    reconnect_interval: float = 3.0


class OneBotSettings(BaseModel):
    enabled: bool = False
    mode: str = "forward"
    host: str = "127.0.0.1"
    port: int = 9090
    path: str = "/onebot/v11/ws"
    access_token: str = ""


class ConnectionSettings(BaseModel):
    """统一连接配置（多协议多账号并存）。"""

    id: str = "napcat_main"
    protocol: str = "onebot"  # onebot | red | satori | mirai | qq_official
    version: str = "v11"  # onebot: v11 | v12
    mode: str = "reverse_ws"  # forward_ws | reverse_ws | http | ws_gateway | http_polling
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 8080
    path: str = "/onebot/v11/ws"
    access_token: str = ""
    token: str = ""
    api_base: str = ""
    app_id: str = ""
    secret: str = ""
    self_id: str = ""
    reconnect_interval: float = 3.0
    extra: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: Any) -> str:
        value = str(value or "").strip()
        if not value or not value.replace("_", "").replace("-", "").isalnum():
            raise ValueError("connection id 只能包含字母、数字、下划线与连字符")
        return value


class TransportSettings(BaseModel):
    protocol: str = "red"
    red: RedSettings = Field(default_factory=RedSettings)
    onebot: OneBotSettings = Field(default_factory=OneBotSettings)
    connections: list[ConnectionSettings] = Field(default_factory=list)

    def ensure_connections(self) -> None:
        """从旧 transport.red/onebot 播种连接配置；为空时写入推荐默认值。"""
        if self.connections:
            return
        seeded = False
        if self.red.enabled and self.red.token:
            self.connections.append(
                ConnectionSettings(
                    id="red",
                    protocol="red",
                    mode="forward_ws",
                    host=self.red.host,
                    port=self.red.port,
                    token=self.red.token,
                    api_base=self.red.api_base,
                    reconnect_interval=self.red.reconnect_interval,
                    path="/",
                )
            )
            seeded = True
        if self.onebot.enabled:
            self.connections.append(
                ConnectionSettings(
                    id="onebot",
                    protocol="onebot",
                    version="v11",
                    mode=(
                        "reverse_ws"
                        if self.onebot.mode == "reverse"
                        else "forward_ws"
                    ),
                    host=self.onebot.host,
                    port=self.onebot.port,
                    path=self.onebot.path,
                    access_token=self.onebot.access_token,
                )
            )
            seeded = True
        if not seeded:
            # 推荐默认：NapCat OneBot v11 反向 WebSocket
            self.connections.append(
                ConnectionSettings(
                    id="napcat_main",
                    protocol="onebot",
                    version="v11",
                    mode="reverse_ws",
                    host="127.0.0.1",
                    port=8080,
                    path="/onebot/v11/ws",
                )
            )


class ScopeEntry(BaseModel):
    """单个监听环境的策略配置。"""

    connection: str = ""
    features: dict[str, bool] = Field(default_factory=dict)
    permissions: dict[str, bool] = Field(default_factory=dict)
    blocked_users: list[str] = Field(default_factory=list)
    silent_deny: bool = False


class RuntimeSettings(BaseModel):
    """运行时策略：监听环境作用域与插件任务启停（config.yaml 存储，即时生效）。"""

    scopes: dict[str, ScopeEntry] = Field(default_factory=dict)
    plugin_tasks: dict[str, dict[str, bool]] = Field(default_factory=dict)


class DatabaseSettings(BaseModel):
    url: str = "sqlite+aiosqlite:///data/ofbot2.db"


class WebSettings(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8000
    secret: str = ""
    session_ttl_seconds: int = 60 * 60 * 8
    api_keys: list[str] = Field(default_factory=list)
    plugin_repo_url: str = ""
    plugin_repo_token: str = ""
    export_job_retention: int = 50
    export_retries: int = 0
    export_job_retention_days: int = 0
    webhook_history_retention: int = 200
    webhook_history_page_size: int = 20
    cpu_threshold: int = 80
    memory_threshold: int = 85
    alert_history_retention_days: int = 30
    alert_min_interval_seconds: int = 0
    auto_disable_workflows_after_failures: int = 0


class SchedulerSettings(BaseModel):
    timezone: str = "Asia/Shanghai"
    max_instances: int = 1
    coalesce: bool = True
    auto_backup_enabled: bool = False
    backup_interval_hours: int = 24
    auto_disable_after_failures: int = 0
    auto_reenable_after_seconds: int = 0
    auto_reenable_interval_seconds: int = 60


class SecuritySettings(BaseModel):
    max_message_length: int = 2000
    max_arg_length: int = 500
    default_cooldown_seconds: float = 1.0
    rate_limit_default: str = "20/minute"
    sensitive_words: list[str] = Field(default_factory=list)
    blocked_users: list[str] = Field(default_factory=list)
    unknown_command_hint: bool = True
    audit_retention_days: int = 90
    login_failure_delay_seconds: float = 0.5
    max_login_attempts: int = 5
    login_lock_seconds: int = 300
    heartbeat_stale_seconds: int = 300


class Settings(BaseModel):
    config_path: str = ""
    basic: BasicSettings = Field(default_factory=BasicSettings)
    transport: TransportSettings = Field(default_factory=TransportSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    web: WebSettings = Field(default_factory=WebSettings)
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    runtime: RuntimeSettings = Field(default_factory=RuntimeSettings)
    plugins: dict[str, bool] = Field(default_factory=dict)
    plugin_configs: dict[str, dict[str, Any]] = Field(default_factory=dict)

    @field_validator("basic", mode="before")
    @classmethod
    def _normalize_command_start(cls, v: Any) -> Any:
        if isinstance(v, dict) and isinstance(v.get("command_start"), str):
            v = dict(v)
            v["command_start"] = [v["command_start"]]
        return v


DEFAULT_CONFIG = {
    "basic": {
        "command_start": ["/", "!"],
        "command_sep": ["."],
        "nickname": ["OFbot_2"],
        "superusers": [],
        "language": "zh-CN",
        "log_level": "INFO",
        "log_retention_days": 14,
        "log_max_files": 60,
    },
    "transport": {
        "protocol": "red",
        "red": {
            "enabled": True,
            "host": "127.0.0.1",
            "port": 16530,
            "token": "",
            "api_base": "http://127.0.0.1:16530",
            "reconnect_interval": 3.0,
        },
        "onebot": {
            "enabled": False,
            "mode": "forward",
            "host": "127.0.0.1",
            "port": 9090,
            "path": "/onebot/v11/ws",
            "access_token": "",
        },
    },
    "database": {"url": "sqlite+aiosqlite:///data/ofbot2.db"},
    "web": {
        "host": "127.0.0.1",
        "port": 8000,
        "secret": "",
        "session_ttl_seconds": 28800,
        "api_keys": [],
        "plugin_repo_url": "",
        "plugin_repo_token": "",
        "cpu_threshold": 80,
        "memory_threshold": 85,
        "alert_history_retention_days": 30,
        "alert_min_interval_seconds": 0,
        "auto_disable_workflows_after_failures": 0,
    },
    "scheduler": {
        "timezone": "Asia/Shanghai",
        "max_instances": 1,
        "coalesce": True,
        "auto_backup_enabled": False,
        "backup_interval_hours": 24,
        "auto_disable_after_failures": 0,
        "auto_reenable_after_seconds": 0,
        "auto_reenable_interval_seconds": 60,
    },
    "security": {
        "max_message_length": 2000,
        "max_arg_length": 500,
        "default_cooldown_seconds": 1.0,
        "rate_limit_default": "20/minute",
        "sensitive_words": [],
        "blocked_users": [],
        "unknown_command_hint": True,
        "audit_retention_days": 90,
        "login_failure_delay_seconds": 0.5,
        "max_login_attempts": 5,
        "login_lock_seconds": 300,
        "heartbeat_stale_seconds": 300,
    },
    "runtime": {
        "scopes": {
            "group:*": {
                "connection": "",
                "features": {},
                "permissions": {},
                "blocked_users": [],
                "silent_deny": False,
            },
            "private:*": {
                "connection": "",
                "features": {},
                "permissions": {},
                "blocked_users": [],
                "silent_deny": False,
            },
        },
        "plugin_tasks": {},
    },
    "plugins": {"template": True, "system": True},
    "plugin_configs": {
        "template": {"greeting": "你好"},
        "system": {"groups": []},
    },
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_settings(path: str | Path | None = None) -> Settings:
    if path is None:
        path = Path(__file__).resolve().parents[2] / "config.yaml"
    path = Path(path)
    data = _deep_merge(DEFAULT_CONFIG, {})
    if path.exists():
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        data = _deep_merge(data, loaded)
    settings = Settings.model_validate(data)
    settings.config_path = str(path)
    settings.transport.ensure_connections()
    _seed_legacy_blocked(settings)
    return settings


def _seed_legacy_blocked(settings: Settings) -> None:
    """旧 security.blocked_users 播种进 group:* 作用域（仅在作用域为空时）。"""
    if not settings.security.blocked_users:
        return
    if settings.runtime.scopes.get("group:*", ScopeEntry()).blocked_users:
        return
    entry = settings.runtime.scopes.setdefault("group:*", ScopeEntry())
    entry.blocked_users = list(settings.security.blocked_users)


def save_settings(settings: Settings, path: str | Path | None = None) -> None:
    if path is None:
        path = Path(settings.config_path or Path(__file__).resolve().parents[2] / "config.yaml")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    data = settings.model_dump(mode="json")
    data.pop("config_path", None)
    tmp.write_text(
        yaml.safe_dump(data, allow_unicode=True, indent=4),
        encoding="utf-8",
    )
    os.replace(tmp, path)
