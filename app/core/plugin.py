from __future__ import annotations

import functools
import importlib
import importlib.util
import inspect
import json
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field, ValidationError, field_validator

from app.core.bus import get_bus
from app.core.cache import TTLCache
from app.core.commands import CommandRegistry
from app.core.events import PluginFailed, PluginLoaded, PluginUnloaded
from app.core.logger import get_logger
from app.core.parsing import ParamSpec, SubcommandSpec
from app.core.permissions import PermissionManager
from app.core.plugin_tasks import PluginTaskEntry, PluginTaskRegistry
from app.core.rules import RuleRegistry, RuleSpec
from app.core.scopes import ScopePolicyService, feature_key, resolve_scope
from app.core.sessions import SessionManager
from app.core.subscriptions import EventSubscriptionRegistry
from app.services.preset_utils import now, paginate, render_card

logger = get_logger(__name__)

PLUGIN_API_VERSION = 1


def _call_with_ctx(func: Callable, *args: Any, ctx: Any = None, **kwargs: Any) -> Any:
    """handler 若声明 ctx 参数则注入 PluginContext；否则保持原签名调用。"""
    if "ctx" in inspect.signature(func).parameters:
        kwargs["ctx"] = ctx
    return func(*args, **kwargs)


class DeclaredCommand(BaseModel):
    name: str
    aliases: list[str] = Field(default_factory=list)
    handler: str
    rules: list[RuleSpec] = Field(default_factory=list)
    session: bool = False
    permission: str = "bot.command"
    description: str = ""
    usage: str = ""
    examples: list[str] = Field(default_factory=list)
    cooldown: float = 0.0
    rate_limit: str | None = None
    priority: int = 10
    block: bool = True
    params: list[ParamSpec] = Field(default_factory=list)
    subcommands: list[SubcommandSpec] = Field(default_factory=list)
    max_arg_length: int | None = None


class DeclaredTask(BaseModel):
    id: str
    kind: str = "interval"  # interval | cron | date
    params: dict[str, Any] = Field(default_factory=dict)
    handler: str
    target: str | list[str] = "all"  # all | group:<id> | private:* | 上述的列表
    description: str = ""

    @field_validator("target")
    @classmethod
    def _validate_target(cls, value: Any) -> Any:
        entries = value if isinstance(value, list) else [value]
        for entry in entries:
            if not isinstance(entry, str):
                raise TypeError(f"task target 必须为字符串或字符串列表：{entry!r}")
            if entry != "all" and not (
                entry.startswith("group:") or entry == "private:*"
            ):
                raise ValueError(f"task target 取值非法：{entry}")
        return value


class DeclaredListener(BaseModel):
    event: str
    handler: str
    rules: list[RuleSpec] = Field(default_factory=list)
    description: str = ""


class FeatureSpec(BaseModel):
    id: str
    label: str = ""
    description: str = ""
    enable_on_default: bool = True
    manage_permission: str = ""
    commands: list[DeclaredCommand] = Field(default_factory=list)
    tasks: list[DeclaredTask] = Field(default_factory=list)
    listeners: list[DeclaredListener] = Field(default_factory=list)


class PluginManifest(BaseModel):
    name: str
    api_version: int = PLUGIN_API_VERSION
    version: str = "0.1.0"
    description: str = ""
    author: str = ""
    sandbox: str = "inline"  # inline | process（子进程隔离 + 能力白名单）
    sandbox_policy: dict[str, Any] = Field(default_factory=dict)
    dependencies: dict[str, str] = Field(default_factory=dict)
    permissions: list[str] = Field(default_factory=list)
    permission_roles: dict[str, list[str]] = Field(default_factory=dict)
    conflicts: dict[str, str] = Field(default_factory=dict)
    config_schema: dict[str, Any] = Field(default_factory=dict)
    web: bool = False
    models: list[str] = Field(default_factory=list)
    migrations: list[str] = Field(default_factory=list)
    entry: str = "create_plugin"
    features: list[FeatureSpec] = Field(default_factory=list)
    commands: list[DeclaredCommand] = Field(default_factory=list)
    tasks: list[DeclaredTask] = Field(default_factory=list)
    listeners: list[DeclaredListener] = Field(default_factory=list)

    @field_validator("sandbox")
    @classmethod
    def _validate_sandbox(cls, value: Any) -> str:
        value = str(value or "inline").strip()
        if value not in {"inline", "process"}:
            raise ValueError("sandbox 仅支持 inline 或 process")
        return value

    @field_validator("conflicts")
    @classmethod
    def _validate_conflicts(cls, value: dict[str, str]) -> dict[str, str]:
        for command, action in value.items():
            if action not in {"rename", "skip"}:
                raise ValueError(
                    f"conflicts[{command}] 仅支持 rename 或 skip，收到：{action}"
                )
        return value

    def effective_features(self) -> list[FeatureSpec]:
        """无 features 时，顶层声明回落 <plugin>.default。"""
        if self.features:
            return self.features
        if self.commands or self.tasks or self.listeners:
            return [
                FeatureSpec(
                    id="default",
                    label="默认功能",
                    commands=self.commands,
                    tasks=self.tasks,
                    listeners=self.listeners,
                )
            ]
        return []


class PluginContext:
    def __init__(
        self,
        *,
        name: str,
        config: dict[str, Any],
        bus: Any,
        commands: CommandRegistry,
        db: Any,
        scheduler: Any,
        cache: TTLCache,
        bot: Any,
        permissions: PermissionManager,
        services: dict[str, Any],
        subscriptions: EventSubscriptionRegistry,
        capabilities: Any = None,
        records: Any = None,
        state_machine: Any = None,
        aggregation: Any = None,
        audit: Any = None,
        ai: Any = None,
        workflow: Any = None,
        scope_policy: ScopePolicyService | None = None,
        task_registry: PluginTaskRegistry | None = None,
        rules: RuleRegistry | None = None,
        session: SessionManager | None = None,
    ) -> None:
        self.name = name
        self.config = config
        self.bus = bus
        self.commands = commands
        self.db = db
        self.scheduler = scheduler
        self.cache = cache
        self.bot = bot
        self.permissions = permissions
        self.services = services
        self.subscriptions = subscriptions
        self.capabilities = capabilities
        self.records = records
        self.state_machine = state_machine
        self.aggregation = aggregation
        self.audit = audit
        self.ai = ai
        self.workflow = workflow
        self.scope_policy = scope_policy
        self.task_registry = task_registry
        self.rules = rules or RuleRegistry()
        self.session = session or SessionManager()
        self.features: dict[str, FeatureSpec] = {}
        self.storage = cache
        self.logger = get_logger(f"plugin.{name}")
        self._models: list[type[Any]] = []
        self._migrations: list[str] = []
        self._routers: list[APIRouter] = []
        self._subscriptions: list[tuple[Any, Any]] = []
        self._background_tasks: list[Any] = []

    def subscribe(self, event_type: Any, handler: Callable) -> Any:
        entry = self.subscriptions.subscribe(event_type, handler, self.name)
        self._subscriptions.append((event_type, entry))
        return entry

    def register_models(self, *models: type[Any]) -> None:
        self._models.extend(models)

    def register_migrations(self, *paths: str) -> None:
        self._migrations.extend(paths)

    def register_router(self, router: APIRouter) -> None:
        if not isinstance(router, APIRouter):
            raise TypeError("router must be an APIRouter")
        self._routers.append(router)

    def register_task(self, coroutine_factory: Callable[[], Any]) -> Any:
        self._background_tasks.append(coroutine_factory)
        return coroutine_factory

    def register_managed_task(
        self,
        task_id: str,
        kind: str,
        params: dict[str, Any],
        handler: Callable,
        *,
        target: str | list[str] = "all",
        description: str = "",
    ) -> PluginTaskEntry:
        """注册运行时定时任务：进入 PluginTaskRegistry（Web 定时任务页可见、可启停）。"""
        if kind not in {"interval", "cron", "date"}:
            raise ValueError(f"task kind 仅支持 interval/cron/date，收到：{kind}")
        entry = PluginTaskEntry(
            plugin=self.name,
            task_id=task_id,
            feature_id="",
            kind=kind,
            params=dict(params),
            handler=handler,
            target=target,
            description=description,
        )
        job_id = f"plugin.{self.name}.{task_id}"
        entry.job_id = job_id

        async def run() -> None:
            return await _call_with_ctx(handler, ctx=self)

        try:
            if kind == "cron":
                self.scheduler.add_cron_job(
                    run,
                    job_id=job_id,
                    cron_expression=str(params.get("cron", "")),
                    plugin_name=self.name,
                )
            elif kind == "date":
                from datetime import UTC, datetime

                run_date = params.get("run_date")
                parsed = (
                    datetime.fromisoformat(str(run_date))
                    if isinstance(run_date, str)
                    else run_date
                )
                if parsed is not None and parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=UTC)
                self.scheduler.add_date_job(
                    run,
                    job_id=job_id,
                    run_date=parsed,
                    plugin_name=self.name,
                )
            else:
                self.scheduler.add_interval_job(
                    run,
                    job_id=job_id,
                    seconds=int(params.get("seconds", 3600)),
                    plugin_name=self.name,
                )
        except Exception as exc:
            self.logger.warning("managed task %s registration failed: %s", task_id, exc)
            entry.enabled = False
        if self.task_registry is not None:
            self.task_registry.register(entry)
        return entry

    def require_permission(self, permission: str) -> Callable:
        def decorator(func: Callable) -> Callable:
            func.__required_permission__ = permission
            return func

        return decorator

    def paginate(self, items: list[Any], page: int = 1, page_size: int = 10) -> tuple[list[Any], int, int]:
        return paginate(items, page, page_size)

    def render_card(self, title: str, lines: Iterable[str]) -> str:
        return render_card(title, lines)

    def now(self):
        return now()

    def dispatch(self, event: Any) -> Any:
        """派发事件到事件总线（插件内便捷入口）。"""
        return self.bus.dispatch(event)

    def schedule_once(
        self, delay_seconds: float, coroutine_factory: Callable[[], Any]
    ) -> str:
        """注册一次性延迟任务，delay 秒后执行（返回 job_id）。"""
        import time
        from datetime import UTC, datetime, timedelta

        job_id = f"{self.name}.once.{int(time.time() * 1000)}"
        run_date = datetime.now(UTC) + timedelta(
            seconds=max(0.1, float(delay_seconds))
        )
        self.scheduler.add_date_job(
            coroutine_factory,
            job_id=job_id,
            run_date=run_date,
            plugin_name=self.name,
        )
        return job_id

    def register_webhook(
        self,
        name: str,
        payload_filter: dict[str, Any] | None = None,
    ) -> None:
        """注册插件 Webhook（复用 WebhookService，运行时生效）。"""
        service = self.services.get("webhook")
        if service is None:
            raise RuntimeError("webhook service unavailable")
        service.register(name, payload_filter)

    async def send_group(self, group_id: str, message: Any) -> bool:
        return await self.bot.send_group_message(str(group_id), message)

    async def send_private(self, user_id: str, message: Any) -> bool:
        return await self.bot.send_private_message(str(user_id), message)

    def text_image(self, text: str, **kwargs: Any) -> Path:
        """把文本渲染为 PNG 图片（依赖 textimg 服务，Pillow 可选）。"""
        service = self.services.get("textimg")
        if service is None:
            raise RuntimeError("textimg service unavailable")
        return service.render(text, **kwargs)


class Plugin:
    name = ""
    version = "0.1.0"

    def setup(self, ctx: PluginContext) -> None:
        pass

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass


@dataclass
class LoadedPlugin:
    name: str
    path: Path
    manifest: PluginManifest
    module: ModuleType
    instance: Plugin
    context: PluginContext
    state: str = "loaded"
    error: str = ""
    features: dict[str, FeatureSpec] = field(default_factory=dict)
    conflicts: list[dict[str, Any]] = field(default_factory=list)


class PluginManager:
    def __init__(
        self,
        plugins_dir: str | Path,
        *,
        commands: CommandRegistry,
        db: Any,
        scheduler: Any,
        cache: TTLCache,
        bot: Any,
        permissions: PermissionManager,
        services: dict[str, Any],
        subscriptions: EventSubscriptionRegistry,
        capabilities: Any = None,
        records: Any = None,
        state_machine: Any = None,
        aggregation: Any = None,
        audit: Any = None,
        ai: Any = None,
        workflow: Any = None,
        scope_policy: ScopePolicyService | None = None,
        task_registry: PluginTaskRegistry | None = None,
        rules: RuleRegistry | None = None,
        session: SessionManager | None = None,
    ) -> None:
        self.plugins_dir = Path(plugins_dir)
        self.commands = commands
        self.db = db
        self.scheduler = scheduler
        self.cache = cache
        self.bot = bot
        self.permissions = permissions
        self.services = services
        self.subscriptions = subscriptions
        self.capabilities = capabilities
        self.records = records
        self.state_machine = state_machine
        self.aggregation = aggregation
        self.audit = audit
        self.ai = ai
        self.workflow = workflow
        self.scope_policy = scope_policy or ScopePolicyService()
        self.task_registry = task_registry or PluginTaskRegistry()
        self.rules = rules or RuleRegistry()
        self.session = session or SessionManager()
        self._runtime_task_states: dict[str, dict[str, bool]] | None = None
        self._resolution: dict[str, dict[str, str]] | None = None
        self.loaded: dict[str, LoadedPlugin] = {}

    @staticmethod
    def resolve_dotted(module: ModuleType, dotted: str) -> Callable:
        obj: Any = module
        for part in dotted.split("."):
            if not hasattr(obj, part):
                raise ValueError(f"handler 符号 {dotted} 不存在于插件包中")
            obj = getattr(obj, part)
        if not callable(obj):
            raise TypeError(f"handler 符号 {dotted} 不是可调用对象")
        return obj

    def discover(self) -> dict[str, Path]:
        if not self.plugins_dir.exists():
            return {}
        return {
            child.name: child
            for child in self.plugins_dir.iterdir()
            if child.is_dir() and (child / "plugin.json").exists()
        }

    def read_manifest(self, path: Path) -> PluginManifest:
        manifest_path = path / "plugin.json"
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            return PluginManifest.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise ValueError(f"plugin manifest invalid: {manifest_path}") from exc

    def validate_rules(self, manifest: PluginManifest) -> None:
        """校验 manifest 中声明的规则均已在规则注册表注册。"""
        unknown: list[str] = []
        for feature in manifest.effective_features():
            for command in feature.commands:
                unknown.extend(self.rules.validate(command.rules))
            for listener in feature.listeners:
                unknown.extend(self.rules.validate(listener.rules))
        if unknown:
            names = "、".join(sorted(set(unknown)))
            raise ValueError(f"插件声明了未注册的规则：{names}")

    def dependency_order(
        self, manifests: dict[str, PluginManifest], enabled: set[str]
    ) -> list[str]:
        graph: dict[str, set[str]] = {}
        for name, manifest in manifests.items():
            graph[name] = set(manifest.dependencies) & enabled

        visiting: set[str] = set()
        visited: list[str] = []

        def visit(name: str) -> None:
            if name in visiting:
                raise ValueError(f"plugin dependency cycle detected at {name}")
            if name in visited:
                return
            visiting.add(name)
            for dependency in sorted(graph[name]):
                if dependency not in manifests:
                    raise ValueError(f"plugin {name} depends on missing plugin {dependency}")
                visit(dependency)
            visiting.remove(name)
            visited.append(name)

        for name in sorted(enabled):
            visit(name)
        return visited

    @staticmethod
    def compute_resolution(
        ordered_plugins: list[str], manifests: dict[str, PluginManifest]
    ) -> dict[str, dict[str, str]]:
        """按加载顺序 + system 保留规则，为每个插件的每条命令计算 keep/rename/skip。"""
        claims: dict[str, str] = {}
        for plugin in ordered_plugins:
            manifest = manifests[plugin]
            for feature in manifest.effective_features():
                for command in feature.commands:
                    for name in [command.name, *command.aliases]:
                        if name not in claims or plugin == "system" and claims[name] != "system":
                            claims[name] = plugin

        actions: dict[str, dict[str, str]] = {}
        for plugin in ordered_plugins:
            manifest = manifests[plugin]
            plugin_actions: dict[str, str] = {}
            for feature in manifest.effective_features():
                for command in feature.commands:
                    override = manifest.conflicts.get(command.name)
                    if override == "skip":
                        plugin_actions[command.name] = "skip"
                    elif claims.get(command.name) != plugin:
                        plugin_actions[command.name] = "rename"
                    else:
                        plugin_actions[command.name] = "keep"
            actions[plugin] = plugin_actions
        return actions

    def _current_claims(self) -> dict[str, str]:
        """从命令注册表收集 名称/别名 → 归属插件。"""
        claims: dict[str, str] = {}
        for command in self.commands.get_commands():
            claims[command.name] = command.plugin_name
            for alias in command.aliases:
                claims[alias] = command.plugin_name
        return claims

    def _resolution_for(self, name: str, manifest: PluginManifest) -> dict[str, str]:
        """返回插件的命令解决动作；批量加载用预计算表，单独加载按当前注册表推断。"""
        if self._resolution is not None and name in self._resolution:
            return self._resolution[name]
        claims = self._current_claims()
        actions: dict[str, str] = {}
        for feature in manifest.effective_features():
            for command in feature.commands:
                override = manifest.conflicts.get(command.name)
                if override == "skip":
                    actions[command.name] = "skip"
                    continue
                owner = claims.get(command.name)
                if owner is None or owner == name:
                    actions[command.name] = "keep"
                elif owner == "system" or name == "system":
                    # 单独加载时保持注册表一致性：无论哪方是 system，当前插件都让位
                    actions[command.name] = "rename"
                else:
                    actions[command.name] = "rename"
        return actions

    def get_context(self, plugin_name: str) -> PluginContext | None:
        """按插件名获取 PluginContext（供命令 handler ctx 注入等使用）。"""
        loaded = self.loaded.get(plugin_name)
        return loaded.context if loaded is not None else None

    def load_enabled(
        self, enabled: dict[str, bool], plugin_configs: dict[str, dict[str, Any]]
    ) -> list[LoadedPlugin]:
        discovered = self.discover()
        manifests: dict[str, PluginManifest] = {}
        for name, path in discovered.items():
            manifest = self.read_manifest(path)
            if manifest.api_version != PLUGIN_API_VERSION:
                logger.warning(
                    "skip plugin %s due to incompatible api version %s",
                    name,
                    manifest.api_version,
                )
                continue
            manifests[name] = manifest

        enabled_names = {name for name, value in enabled.items() if value}
        enabled_names = enabled_names & set(manifests)
        for name in sorted(enabled_names):
            if name not in manifests:
                logger.warning("enabled plugin %s not found", name)

        order = self.dependency_order(manifests, enabled_names)
        self._resolution = self.compute_resolution(order, manifests)
        result: list[LoadedPlugin] = []
        for name in order:
            try:
                result.append(
                    self.load_plugin(
                        name,
                        discovered[name],
                        config=plugin_configs.get(name, {}),
                    )
                )
            except Exception as exc:
                logger.exception("failed to load plugin %s", name)
                self.bus().dispatch(
                    PluginFailed(plugin_name=name, version="", error=str(exc))
                )
        self._resolution = None
        return result

    def bus(self) -> Any:
        return get_bus()

    def load_plugin(
        self,
        name: str,
        path: Path | None = None,
        *,
        config: dict[str, Any] | None = None,
    ) -> LoadedPlugin:
        path = path or self.plugins_dir / name
        manifest = self.read_manifest(path)
        if manifest.name != name:
            raise ValueError(
                f"plugin directory {name} does not match manifest name {manifest.name}"
            )
        if manifest.api_version != PLUGIN_API_VERSION:
            raise ValueError("incompatible plugin api version")
        self.validate_rules(manifest)
        for permission in manifest.permissions:
            self.permissions.register_permission(permission)
            roles = manifest.permission_roles.get(permission)
            if roles:
                for role in roles:
                    self.permissions.grant_role_permission(role, permission)
            else:
                # 默认行为保持不变：未指定角色映射的权限授予 user
                self.permissions.grant_role_permission("user", permission)

        if manifest.sandbox == "process":
            return self._load_plugin_process(name, path, manifest, config)

        module_name = f"plugins.{name}"
        spec = importlib.util.spec_from_file_location(module_name, path / "__init__.py")
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load plugin module: {name}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        for model_module in manifest.models:
            importlib.import_module(f"{module_name}.{model_module}")
        factory = getattr(module, manifest.entry, None)
        if factory is None:
            raise ValueError(f"plugin entry {manifest.entry} not found")
        instance = factory()
        if not isinstance(instance, Plugin):
            raise TypeError("plugin entry must return a Plugin instance")
        instance.name = name
        instance.version = manifest.version

        ctx = self._build_context(name, config or {})
        for migration in manifest.migrations:
            ctx.register_migrations(str(path / migration))
        instance.setup(ctx)
        loaded = LoadedPlugin(
            name=name,
            path=path,
            manifest=manifest,
            module=module,
            instance=instance,
            context=ctx,
        )
        self.loaded[name] = loaded
        loaded.features = self._register_declarative(loaded)
        self.bus().dispatch(
            PluginLoaded(plugin_name=name, version=manifest.version)
        )
        logger.info("plugin loaded: %s %s", name, manifest.version)
        return loaded

    def _build_context(self, name: str, config: dict[str, Any]) -> PluginContext:
        """构建父进程侧 PluginContext（inline 与 process 模式共用）。"""
        return PluginContext(
            name=name,
            config=config,
            bus=get_bus(),
            commands=self.commands,
            db=self.db,
            scheduler=self.scheduler,
            cache=self.cache,
            bot=self.bot,
            permissions=self.permissions,
            services=self.services,
            subscriptions=self.subscriptions,
            capabilities=self.capabilities,
            records=self.records,
            state_machine=self.state_machine,
            aggregation=self.aggregation,
            audit=self.audit,
            ai=self.ai,
            workflow=self.workflow,
            scope_policy=self.scope_policy,
            task_registry=self.task_registry,
            rules=self.rules,
            session=self.session,
        )

    def _load_plugin_process(
        self,
        name: str,
        path: Path,
        manifest: PluginManifest,
        config: dict[str, Any] | None,
    ) -> LoadedPlugin:
        """process 模式：父进程只持有模块代理与 IPC 桥，插件在子进程运行。"""
        from app.core.plugin_ipc import (
            PluginProcessBridge,
            RemotePluginInstance,
            RemotePluginModule,
        )

        if manifest.models:
            raise ValueError(
                "process 沙箱插件不支持注册 SQLAlchemy 模型（models 字段）"
            )
        ctx = self._build_context(name, config or {})
        bridge = PluginProcessBridge(
            name=name,
            plugin_dir=path,
            manifest=manifest,
            config=config or {},
            context=ctx,
        )
        module: Any = RemotePluginModule(bridge)
        module_name = f"plugins.{name}"
        sys.modules[module_name] = module
        instance = RemotePluginInstance(bridge)
        loaded = LoadedPlugin(
            name=name,
            path=path,
            manifest=manifest,
            module=module,  # type: ignore[arg-type]
            instance=instance,
            context=ctx,
        )
        self.loaded[name] = loaded
        loaded.features = self._register_declarative(loaded)
        self.bus().dispatch(
            PluginLoaded(plugin_name=name, version=manifest.version)
        )
        logger.info("plugin loaded (sandbox=process): %s %s", name, manifest.version)
        return loaded

    def _register_declarative(self, loaded: LoadedPlugin) -> dict[str, FeatureSpec]:
        """按 manifest features 自动注册命令、定时任务与监听器（handler 为包内点分符号）。"""
        name = loaded.name
        features: dict[str, FeatureSpec] = {}
        actions = self._resolution_for(name, loaded.manifest)
        registered_names: set[str] = set()
        conflict_log: list[dict[str, Any]] = []
        for feature in loaded.manifest.effective_features():
            key = feature_key(name, feature.id)
            features[key] = feature
            for declared in feature.commands:
                action = actions.get(declared.name, "keep")
                if action == "skip":
                    conflict_log.append(
                        {"command": declared.name, "action": "skip", "effective": ""}
                    )
                    logger.warning(
                        "plugin %s 命令 /%s 按 conflicts 声明跳过注册", name, declared.name
                    )
                    continue
                handler = self.resolve_dotted(loaded.module, declared.handler)
                effective = (
                    f"{name}.{declared.name}" if action == "rename" else declared.name
                )
                if effective in registered_names:
                    raise ValueError(
                        f"插件 {name} 内部命令名重复：/{effective}"
                    )
                claims = self._current_claims()
                kept_aliases: set[str] = set()
                for alias in set(declared.aliases):
                    if alias in registered_names:
                        raise ValueError(f"插件 {name} 内部别名重复：/{alias}")
                    owner = claims.get(alias)
                    if owner is None or owner == name:
                        kept_aliases.add(alias)
                    else:
                        conflict_log.append(
                            {
                                "command": declared.name,
                                "alias": alias,
                                "action": "dropped",
                                "effective": effective,
                                "other": owner,
                            }
                        )
                        logger.warning(
                            "plugin %s 别名 /%s 与插件 %s 冲突，已丢弃",
                            name,
                            alias,
                            owner,
                        )
                if action == "rename":
                    conflict_log.append(
                        {
                            "command": declared.name,
                            "action": "rename",
                            "effective": effective,
                            "other": claims.get(declared.name, ""),
                        }
                    )
                    logger.warning(
                        "plugin %s 命令 /%s 与插件 %s 冲突，注册为 /%s",
                        name,
                        declared.name,
                        claims.get(declared.name, "?"),
                        effective,
                    )
                self.commands.register(
                    effective,
                    handler,
                    aliases=kept_aliases,
                    rules=list(declared.rules),
                    session=declared.session,
                    permission=declared.permission,
                    cooldown=declared.cooldown,
                    rate_limit=declared.rate_limit,
                    priority=declared.priority,
                    block=declared.block,
                    plugin_name=name,
                    description=declared.description,
                    feature_id=key,
                    usage=declared.usage,
                    examples=list(declared.examples),
                    params=list(declared.params),
                    subcommands=list(declared.subcommands),
                    max_arg_length=declared.max_arg_length,
                )
                registered_names.add(effective)
                registered_names.update(kept_aliases)
            for declared in feature.tasks:
                self._register_manifest_task(loaded, feature, declared, key)
            for declared in feature.listeners:
                self._register_manifest_listener(loaded, feature, declared, key)
        loaded.context.features = features
        loaded.conflicts = conflict_log
        return features

    def _register_manifest_task(
        self,
        loaded: LoadedPlugin,
        feature: FeatureSpec,
        declared: DeclaredTask,
        feature_key_id: str,
    ) -> None:
        handler = self.resolve_dotted(loaded.module, declared.handler)
        params = self._resolve_task_params(
            dict(declared.params), loaded.context.config
        )
        entry = PluginTaskEntry(
            plugin=loaded.name,
            task_id=declared.id,
            feature_id=feature_key_id,
            kind=declared.kind,
            params=params,
            handler=handler,
            target=declared.target,
            description=declared.description,
        )
        enabled = True
        stored = self.runtime_task_states.get(loaded.name, {}).get(declared.id)
        if isinstance(stored, bool):
            enabled = stored
        entry.enabled = enabled
        job_id = f"plugin.{loaded.name}.{declared.id}"
        entry.job_id = job_id
        try:
            if declared.kind == "cron":
                self.scheduler.add_cron_job(
                    functools.partial(self._run_manifest_task, entry),
                    job_id=job_id,
                    cron_expression=str(params.get("cron", "")),
                    plugin_name=loaded.name,
                )
            elif declared.kind == "date":
                from datetime import UTC, datetime

                run_date = params.get("run_date")
                parsed = (
                    datetime.fromisoformat(str(run_date))
                    if isinstance(run_date, str)
                    else run_date
                )
                if parsed is not None and parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=UTC)
                self.scheduler.add_date_job(
                    functools.partial(self._run_manifest_task, entry),
                    job_id=job_id,
                    run_date=parsed,
                    plugin_name=loaded.name,
                )
            else:
                self.scheduler.add_interval_job(
                    functools.partial(self._run_manifest_task, entry),
                    job_id=job_id,
                    seconds=int(params.get("seconds", 3600)),
                    plugin_name=loaded.name,
                )
            if not enabled:
                self.task_registry.set_enabled(
                    loaded.name, declared.id, False
                )
        except Exception as exc:
            logger.warning(
                "plugin %s task %s registration failed: %s",
                loaded.name,
                declared.id,
                exc,
            )
            entry.enabled = False
        self.task_registry.register(entry)

    @staticmethod
    def _resolve_task_params(
        params: dict[str, Any], config: dict[str, Any]
    ) -> dict[str, Any]:
        """解析任务参数模板（${a.b.c} 指向插件配置点分路径），缺失回退静态值。"""
        resolved: dict[str, Any] = {}
        for key, value in params.items():
            if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
                path = value[2:-1].strip().split(".")
                current: Any = config
                try:
                    for part in path:
                        current = current[part]
                except (KeyError, TypeError, IndexError):
                    logger.warning(
                        "task 参数模板 %s 无法从插件配置解析，使用静态值", value
                    )
                    resolved[key] = value
                else:
                    resolved[key] = current
            else:
                resolved[key] = value
        return resolved

    async def _run_manifest_task(self, entry: PluginTaskEntry) -> None:
        """按任务 target 与功能开关门控执行。"""
        if not entry.enabled:
            return
        targets = (
            list(entry.target)
            if isinstance(entry.target, list)
            else [entry.target]
        )
        loaded = self.loaded.get(entry.plugin)
        for target in targets:
            if target == "private:*":
                if not self._feature_enabled(
                    entry.plugin, entry.feature_id, "private:*"
                ):
                    continue
            elif target.startswith("group:"):
                if not self._feature_enabled(
                    entry.plugin, entry.feature_id, target
                ):
                    continue
            elif not self._feature_enabled(
                entry.plugin, entry.feature_id, "group:*"
            ):
                continue
            try:
                await _call_with_ctx(
                    entry.handler,
                    ctx=loaded.context if loaded is not None else None,
                )
            except Exception:
                logger.exception(
                    "plugin task failed: %s.%s", entry.plugin, entry.task_id
                )

    def _register_manifest_listener(
        self,
        loaded: LoadedPlugin,
        feature: FeatureSpec,
        declared: DeclaredListener,
        feature_key_id: str,
    ) -> None:
        import app.core.events as events_module

        event_cls = getattr(events_module, declared.event, None)
        if event_cls is None:
            raise ValueError(
                f"listener 事件 {declared.event} 不存在于 app.core.events"
            )
        handler = self.resolve_dotted(loaded.module, declared.handler)

        async def wrapped(event: Any) -> None:
            group_id = getattr(event, "group_id", "") or ""
            scope = resolve_scope(group_id)
            if not self._feature_enabled(
                loaded.name, feature_key_id, scope
            ):
                return
            if declared.rules:
                passed, _ = await self.rules.check(declared.rules, event)
                if not passed:
                    return
            await _call_with_ctx(
                handler, event, ctx=loaded.context
            )

        loaded.context.subscribe(event_cls, wrapped)

    def _feature_enabled(
        self, plugin: str, feature_key_id: str, scope: str
    ) -> bool:
        if self.scope_policy is None:
            return True
        default = True
        loaded = self.loaded.get(plugin)
        if loaded and feature_key_id in loaded.features:
            default = loaded.features[feature_key_id].enable_on_default
        return self.scope_policy.feature_enabled(
            plugin, feature_key_id.split(".", 1)[-1], scope, default=default
        )

    @property
    def runtime_task_states(self) -> dict[str, dict[str, bool]]:
        """插件任务启停状态（来自 settings.runtime.plugin_tasks，由调用方写入）。"""
        if self._runtime_task_states is None:
            self._runtime_task_states = {}
        return self._runtime_task_states

    def set_runtime_task_states(self, states: dict[str, dict[str, bool]]) -> None:
        self._runtime_task_states = states

    async def start_plugin(self, name: str) -> None:
        loaded = self.loaded[name]
        await loaded.instance.start()

    async def start_all(self) -> None:
        for name in list(self.loaded):
            try:
                await self.start_plugin(name)
            except Exception as exc:
                loaded = self.loaded[name]
                loaded.state = "error"
                loaded.error = str(exc)
                logger.exception("plugin start failed: %s", name)
                self.bus().dispatch(
                    PluginFailed(plugin_name=name, version=loaded.manifest.version, error=str(exc))
                )

    async def unload_plugin(self, name: str) -> bool:
        loaded = self.loaded.pop(name, None)
        if loaded is None:
            return False
        try:
            await loaded.instance.stop()
        except Exception as exc:
            logger.warning("plugin stop failed: %s: %s", name, exc)
        for event_type, entry in loaded.context._subscriptions:
            entry.active = False
        self.subscriptions.unsubscribe_plugin(name)
        self.commands.unregister_plugin(name)
        if self.scheduler is not None:
            self.scheduler.remove_plugin_jobs(name)
        if self.task_registry is not None:
            self.task_registry.unregister_plugin(name)
        module_name = f"plugins.{name}"
        sys.modules.pop(module_name, None)
        for module_key in list(sys.modules):
            if module_key == module_name or module_key.startswith(f"{module_name}."):
                sys.modules.pop(module_key, None)
        self.bus().dispatch(
            PluginUnloaded(
                plugin_name=name, version=loaded.manifest.version
            )
        )
        logger.info("plugin unloaded: %s", name)
        return True

    async def reload_plugin(
        self, name: str, config: dict[str, Any] | None = None
    ) -> bool:
        if name not in self.loaded:
            return False
        loaded = self.loaded[name]
        if config is None:
            config = loaded.context.config
        old_manifest = loaded.manifest
        await self.unload_plugin(name)
        self.load_plugin(name, loaded.path, config=config)
        await self.start_plugin(name)
        new_manifest = self.loaded[name].manifest
        if old_manifest.models != new_manifest.models:
            logger.warning(
                "插件 %s 模型声明发生变化，表结构不支持热更新，请重启服务后生效",
                name,
            )
        old_tasks = {
            (feature.id, task.id): dict(task.params)
            for feature in old_manifest.effective_features()
            for task in feature.tasks
        }
        new_tasks = {
            (feature.id, task.id): dict(task.params)
            for feature in new_manifest.effective_features()
            for task in feature.tasks
        }
        if old_tasks != new_tasks:
            logger.warning(
                "插件 %s 定时任务声明/参数变化，已按新声明重新注册",
                name,
            )
        return True

    def get_loaded_plugins(self) -> list[dict[str, Any]]:
        return [
            {
                "name": item.name,
                "version": item.manifest.version,
                "description": item.manifest.description,
                "state": item.state,
                "error": item.error,
                "config_schema": item.manifest.config_schema,
                "config": item.context.config,
                "conflicts": list(item.conflicts),
            }
            for item in self.loaded.values()
        ]

    def collect_routers(self) -> list[APIRouter]:
        routers: list[APIRouter] = []
        for loaded in self.loaded.values():
            routers.extend(loaded.context._routers)
        return routers
