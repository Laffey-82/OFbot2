from __future__ import annotations

import argparse
import asyncio
import importlib.util
import logging
import sys
import time

import httpx

from app.core.paths import runtime_root

ROOT = runtime_root()
logger = logging.getLogger("app.cli")


def _settings():
    from app.core.config import load_settings

    return load_settings(ROOT / "config.yaml")


def _run(args: argparse.Namespace) -> None:
    from main import main as bot_main

    asyncio.run(bot_main(args.config))


def _doctor(args: argparse.Namespace) -> None:
    from app.services.doctor import run_environment_checks

    settings = _settings()
    checks = asyncio.run(run_environment_checks(settings, root=ROOT))
    labels = {
        "pass": "[PASS]",
        "fail": "[FAIL]",
        "warn": "[WARN]",
        "info": "[INFO]",
    }
    failed = 0
    for check in checks:
        print(f"{labels.get(check['status'], '[INFO]')} {check['name']}: {check['detail']}")
        if check["status"] == "fail":
            failed += 1
    if failed:
        print(f"\n发现 {failed} 项失败，请按提示处理（Web 后台「设置向导 → 环境自检」可一键跳转修复）。")
    else:
        print("\n未发现失败项。")


def _status(args: argparse.Namespace) -> None:
    settings = _settings()
    url = f"http://{settings.web.host}:{settings.web.port}/api/v1/status"
    try:
        response = httpx.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        print(f"状态: {data.get('status')}")
        print(f"适配器: {data.get('adapters')}")
    except Exception:
        print("状态: 未运行")


def _logs(args: argparse.Namespace) -> None:
    log_dir = ROOT / "logs"
    candidates = sorted(
        log_dir.glob("ofbot2-*.log"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    log_file = candidates[0] if candidates else log_dir / "ofbot2.log"
    if not log_file.exists():
        print("暂无日志")
        return
    lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in lines[-args.tail :]:
        print(line)


def _backup(args: argparse.Namespace) -> None:
    from app.db.base import resolve_sqlite_path
    from app.services.backup import BackupService

    settings = _settings()
    db_path = resolve_sqlite_path(settings.database.url)
    target = BackupService(ROOT / "data" / "backups").create_backup(
        ROOT / "config.yaml",
        db_path,
        ROOT / "plugins",
    )
    print(f"备份完成: {target}")


def _version(args: argparse.Namespace) -> None:
    from app import __version__

    print(f"OFbot 2 v{__version__}")


def _capabilities(args: argparse.Namespace) -> None:
    from app.core.capabilities import capability_registry
    from app.services.capability_setup import register_builtin_capabilities

    register_builtin_capabilities()

    for capability in capability_registry.list():
        print(f"{capability.name} ({capability.version}) - {capability.description}")


def _plugin_new(args: argparse.Namespace) -> None:
    from app.services.scaffold import ScaffoldService

    service = ScaffoldService(ROOT / "examples" / "plugins", ROOT / "plugins")
    if (
        args.with_task
        or args.with_listener
        or args.with_web
        or args.with_model
    ):
        target = service.create_featured(
            args.name,
            with_task=args.with_task,
            with_listener=args.with_listener,
            with_web=args.with_web,
            with_model=args.with_model,
        )
    else:
        target = service.create_from_template(args.preset, args.name)
    print(f"插件已生成: {target}")
    print("下一步：填写 handlers.py → ofbot2 plugin check <name> → 启动验证。")
    print("提示：默认未启用，请在 config.yaml 的 plugins 中添加并设为 true。")


def _plugin_features(args: argparse.Namespace) -> None:
    from app.core.plugin import PluginManifest

    manifest_path = ROOT / "plugins" / args.name / "plugin.json"
    if not manifest_path.exists():
        print(f"插件不存在: {args.name}")
        return
    manifest = PluginManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    for feature in manifest.effective_features():
        print(
            f"功能 {feature.id}（{feature.label or '未命名'}）"
            f" 默认={'开' if feature.enable_on_default else '关'}"
        )
        if feature.description:
            print(f"  说明：{feature.description}")
        for command in feature.commands:
            print(
                f"  命令 /{command.name} → {command.handler}"
                f"（权限 {command.permission}）"
            )
        for task in feature.tasks:
            print(
                f"  任务 {task.id}（{task.kind}，target={task.target}）"
                f" → {task.handler}"
            )
        for listener in feature.listeners:
            print(f"  监听 {listener.event} → {listener.handler}")


def _plugin_check(args: argparse.Namespace) -> int:
    from app.core.plugin import PLUGIN_API_VERSION, PluginManifest
    from app.core.rules import RuleRegistry

    plugin_dir = ROOT / "plugins" / args.name
    manifest_path = plugin_dir / "plugin.json"
    errors: list[str] = []
    if not manifest_path.exists():
        print(f"[FAIL] 插件不存在: {args.name}")
        return 1
    try:
        manifest = PluginManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
    except Exception as exc:
        print(f"[FAIL] plugin.json 无效: {exc}")
        return 1
    if manifest.name != args.name:
        errors.append(f"目录名 {args.name} 与清单 name {manifest.name} 不一致")
    if manifest.api_version != PLUGIN_API_VERSION:
        errors.append(f"api_version {manifest.api_version} 不受支持")
    if manifest.config_schema:
        try:
            import jsonschema

            jsonschema.Draft7Validator.check_schema(manifest.config_schema)
        except ImportError:
            pass
        except Exception as exc:
            errors.append(f"config_schema 无效：{exc}")
    # 跨插件命令冲突预览：加载期会按「先加载保留 + system 保留 + 后加载命名空间化」解决
    from app.core.config import load_settings
    from app.core.plugin import PluginManager

    manifests: dict[str, PluginManifest] = {}
    plugins_dir = ROOT / "plugins"
    if plugins_dir.exists():
        for path in sorted(plugins_dir.glob("*/plugin.json")):
            try:
                manifests[path.parent.name] = PluginManifest.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
            except Exception as exc:
                logger.warning("跳过无法解析的插件清单 %s：%s", path, exc)
    config_path = ROOT / "config.yaml"
    if config_path.exists():
        try:
            settings = load_settings(config_path)
            enabled = {name for name, flag in settings.plugins.items() if flag}
            manifests = {
                name: manifest
                for name, manifest in manifests.items()
                if name in enabled
            }
        except Exception:
            pass
    if manifests:
        order = [name for name in sorted(manifests) if name in manifests]
        resolution = PluginManager.compute_resolution(order, manifests)
        planned = resolution.get(args.name, {})
        for feature in manifest.effective_features():
            for command in feature.commands:
                action = planned.get(command.name, "keep")
                if action == "rename":
                    print(
                        f"[INFO] 命令 /{command.name} 将注册为 /{args.name}.{command.name}"
                        "（与其他插件冲突，自动命名空间化）"
                    )
                elif action == "skip":
                    print(
                        f"[INFO] 命令 /{command.name} 按 conflicts 声明跳过注册"
                    )
    # 权限角色映射校验
    for permission, roles in manifest.permission_roles.items():
        if permission not in manifest.permissions:
            errors.append(
                f"permission_roles 中的权限点 {permission} 未在 permissions 中声明"
            )
        for role in roles:
            if not str(role).strip():
                errors.append(f"permission_roles[{permission}] 存在空角色名")
    # rest 参数校验：唯一且位于末尾
    for feature in manifest.effective_features():
        for command in feature.commands:
            rest_params = [
                p for p in command.params if p.type.lower() in {"rest", "greedy_string"}
            ]
            if len(rest_params) > 1:
                errors.append(
                    f"命令 /{command.name} 最多只能声明一个 rest 参数"
                )
            if rest_params and command.params[-1] is not rest_params[0]:
                errors.append(
                    f"命令 /{command.name} 的 rest 参数 {rest_params[0].name} 必须位于末尾"
                )
            if command.max_arg_length is not None and command.max_arg_length < 1:
                errors.append(
                    f"命令 /{command.name} 的 max_arg_length 必须为正整数"
                )
    rule_registry = RuleRegistry()
    unknown_rules = []
    for feature in manifest.effective_features():
        for command in feature.commands:
            unknown_rules.extend(rule_registry.validate(command.rules))
        for listener in feature.listeners:
            unknown_rules.extend(rule_registry.validate(listener.rules))
    for rule in sorted(set(unknown_rules)):
        errors.append(f"规则未注册：{rule}（可用：{' / '.join(rule_registry.names())}）")
    module_name = f"plugins.{args.name}"
    module = None
    try:
        spec = importlib.util.spec_from_file_location(
            module_name, plugin_dir / "__init__.py"
        )
        if spec is None or spec.loader is None:
            errors.append("无法加载 __init__.py")
        else:
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
    except Exception as exc:
        errors.append(f"插件模块导入失败: {exc}")
        sys.modules.pop(module_name, None)
    if module is not None:
        for feature in manifest.effective_features():
            for command in feature.commands:
                try:
                    PluginManager.resolve_dotted(module, command.handler)
                except Exception as exc:
                    errors.append(f"命令 /{command.name}：{exc}")
            for task in feature.tasks:
                try:
                    PluginManager.resolve_dotted(module, task.handler)
                except Exception as exc:
                    errors.append(f"任务 {task.id}：{exc}")
            for listener in feature.listeners:
                try:
                    PluginManager.resolve_dotted(module, listener.handler)
                except Exception as exc:
                    errors.append(f"监听 {listener.event}：{exc}")
                import app.core.events as events_module

                if not hasattr(events_module, listener.event):
                    errors.append(
                        f"监听事件 {listener.event} 不存在于 app.core.events"
                    )
    if errors:
        for error in errors:
            print(f"[FAIL] {error}")
        return 1
    from app.services.plugin_installer import audit_plugin_dir

    findings = audit_plugin_dir(plugin_dir)
    if findings:
        print("安全审计：")
        for item in findings:
            print(f"  [{item['level']}] {item['check']}: {item['detail']}")
    print(f"[PASS] 插件 {args.name} 清单与处理器符号校验通过")
    return 0


def _plugin_conflicts(args: argparse.Namespace) -> int:
    """扫描 plugins/ 下全部插件的命令冲突与加载期解决策略。"""
    from app.core.config import load_settings
    from app.core.plugin import PluginManager, PluginManifest

    plugins_dir = ROOT / "plugins"
    manifests: dict[str, PluginManifest] = {}
    if plugins_dir.exists():
        for path in sorted(plugins_dir.glob("*/plugin.json")):
            try:
                manifests[path.parent.name] = PluginManifest.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
            except Exception as exc:
                print(f"[SKIP] {path.parent.name}：清单解析失败 {exc}")
    config_path = ROOT / "config.yaml"
    if config_path.exists():
        try:
            settings = load_settings(config_path)
            enabled = {name for name, flag in settings.plugins.items() if flag}
            manifests = {
                name: manifest
                for name, manifest in manifests.items()
                if name in enabled
            }
        except Exception:
            pass
    if not manifests:
        print("plugins/ 下没有可解析的插件")
        return 1
    order = sorted(manifests)
    resolution = PluginManager.compute_resolution(order, manifests)
    conflicts: list[tuple[str, str, str]] = []
    for plugin in order:
        manifest = manifests[plugin]
        for feature in manifest.effective_features():
            for command in feature.commands:
                action = resolution[plugin].get(command.name, "keep")
                if action != "keep":
                    conflicts.append((plugin, command.name, action))
    if not conflicts:
        print("未发现命令冲突")
        return 0
    print(f"发现 {len(conflicts)} 处命令冲突，加载期解决策略如下：")
    for plugin, name, action in conflicts:
        if action == "rename":
            print(f"  /{name}（{plugin}）→ /{plugin}.{name}（命名空间化）")
        else:
            print(f"  /{name}（{plugin}）→ 跳过注册")
    return 0


def _plugin_e2e(args: argparse.Namespace) -> int:
    """运行插件 e2e/ 目录下的端到端脚本（每个脚本独立进程执行）。"""
    import subprocess

    plugin_dir = ROOT / "plugins" / args.name
    e2e_dir = plugin_dir / "e2e"
    if not e2e_dir.exists():
        print(f"插件 {args.name} 没有 e2e/ 目录，跳过")
        return 0
    scripts = sorted(e2e_dir.glob("*.py"))
    if not scripts:
        print(f"插件 {args.name} 的 e2e/ 目录下没有脚本")
        return 0
    failed: list[str] = []
    for script in scripts:
        print(f"运行 {script.name} …")
        result = subprocess.run(
            [sys.executable, str(script)], cwd=ROOT, check=False
        )
        if result.returncode != 0:
            failed.append(script.name)
    if failed:
        print(f"[FAIL] e2e 脚本失败：{'、'.join(failed)}")
        return 1
    print(f"[PASS] 插件 {args.name} 全部 e2e 脚本通过")
    return 0


def _plugin_dev(args: argparse.Namespace) -> None:
    """开发模式：监视插件目录文件变更，自动调用 Web 热重载。"""
    from app.core.config import load_settings

    plugin_dir = ROOT / "plugins" / args.name
    if not plugin_dir.exists():
        print(f"插件不存在: {args.name}")
        return
    settings = load_settings(ROOT / "config.yaml")
    base_url = f"http://{settings.web.host}:{settings.web.port}"
    key = settings.web.api_keys[0] if settings.web.api_keys else ""
    headers = {"X-API-Key": key} if key else {}
    import httpx

    mtimes: dict[str, float] = {}
    for path in plugin_dir.rglob("*"):
        if path.is_file() and not path.name.endswith((".pyc", ".tmp")):
            mtimes[str(path)] = path.stat().st_mtime
    print(f"监视 {plugin_dir}，修改文件后自动重载插件（Ctrl+C 退出）")
    try:
        while True:
            time.sleep(2)
            changed = []
            for path in plugin_dir.rglob("*"):
                if not path.is_file() or path.name.endswith((".pyc", ".tmp")):
                    continue
                stamp = path.stat().st_mtime
                if mtimes.get(str(path), 0) != stamp:
                    changed.append(path.name)
                    mtimes[str(path)] = stamp
            if not changed:
                continue
            print(f"检测到变更：{', '.join(changed)}，正在重载…")
            try:
                response = httpx.post(
                    f"{base_url}/api/v1/plugins/{args.name}/reload",
                    headers=headers,
                    timeout=10,
                )
                response.raise_for_status()
                print("重载成功")
            except Exception as exc:
                print(f"重载失败: {exc}（请确认机器人已启动并启用 API Key）")
    except KeyboardInterrupt:
        print("\n已退出开发模式")


def _plugin_test(args: argparse.Namespace) -> int:
    import subprocess

    plugin_dir = ROOT / "plugins" / args.name
    test_dir = plugin_dir / "tests"
    if not test_dir.exists():
        print(f"插件 {args.name} 没有 tests/ 目录，跳过")
        return 0
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(test_dir), "-q"],
        cwd=ROOT,
        check=False,
    )
    return result.returncode


def _plugin_repo_list(args: argparse.Namespace) -> int:
    import asyncio

    from app.services.plugin_repo import PluginRepoService

    settings = _settings()
    service = PluginRepoService(
        ROOT / "plugins",
        ROOT / "plugin-repo",
        repo_url=settings.web.plugin_repo_url,
        token=settings.web.plugin_repo_token,
    )
    try:
        plugins = asyncio.run(service.list_plugins())
    except Exception as exc:
        print(f"获取插件仓库失败：{exc}")
        return 1
    if not plugins:
        print("插件仓库为空")
        return 0
    for plugin in plugins:
        print(
            f"{plugin.id} v{plugin.version} [{plugin.category or '—'}] "
            f"{plugin.description}（{plugin.author or '未知作者'}）"
        )
    return 0


def _plugin_repo_install(args: argparse.Namespace) -> int:
    import asyncio

    from app.services.plugin_repo import PluginRepoService

    settings = _settings()
    service = PluginRepoService(
        ROOT / "plugins",
        ROOT / "plugin-repo",
        repo_url=settings.web.plugin_repo_url,
        token=settings.web.plugin_repo_token,
    )
    print("提示：安装插件即执行其代码，请确认来源可信。")
    try:
        installed = asyncio.run(
            service.install(args.id, args.name, replace=args.force)
        )
    except Exception as exc:
        print(f"安装失败：{exc}")
        return 1
    print(
        f"已安装插件：{installed.name}（默认未启用，"
        "可在 Web 插件页或 config.yaml 的 plugins 中启用）"
    )
    return 0


def _plugin_install(args: argparse.Namespace) -> None:
    from app.services.plugin_installer import PluginInstaller

    installer = PluginInstaller(ROOT / "plugins")
    report = installer.audit_zip(args.zip)
    print(
        f"安全审计：{report['file_count']} 个文件，"
        f"警告 {report['warnings']} 项，提示 {report['infos']} 项"
    )
    for item in report["checks"]:
        print(f"  [{item['level'].upper()}] {item['check']}: {item['detail']}")
    if report["warnings"] and not getattr(args, "yes", False):
        answer = input("存在警告项，确认来源可信后继续安装？[y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("已取消安装")
            return
    target = installer.install_zip(args.zip, audit=True)
    print(f"插件已安装: {target}")


def _plugin_audit(args: argparse.Namespace) -> int:
    from app.services.plugin_installer import PluginInstaller

    installer = PluginInstaller(ROOT / "plugins")
    if args.zip:
        report = installer.audit_zip(args.zip)
        print(
            f"安全审计：{report['file_count']} 个文件，"
            f"警告 {report['warnings']} 项，提示 {report['infos']} 项"
        )
        for item in report["checks"]:
            print(f"  [{item['level'].upper()}] {item['check']}: {item['detail']}")
        return 0
    reports = installer.read_audits(args.name)
    if not reports:
        print(f"未找到插件 {args.name} 的审计记录（安装时自动生成）")
        return 1
    for report in reports[-3:]:
        print(
            f"{report.get('plugin')} 安装于 {report.get('installed_at', '')}: "
            f"警告 {report.get('warnings', 0)}，提示 {report.get('infos', 0)}"
        )
    return 0


def _plugin_list(args: argparse.Namespace) -> None:
    plugins_dir = ROOT / "plugins"
    if not plugins_dir.exists():
        print("暂无插件")
        return
    for path in sorted(plugins_dir.iterdir()):
        if (path / "plugin.json").exists():
            print(path.name)


def _connections_list(args: argparse.Namespace) -> None:
    settings = _settings()
    if not settings.transport.connections:
        print("暂无连接配置")
        return
    for conn in settings.transport.connections:
        state = "启用" if conn.enabled else "停用"
        print(
            f"{conn.id} [{conn.protocol}"
            + (f" {conn.version}" if conn.protocol == "onebot" else "")
            + f"] {conn.mode} {conn.host}:{conn.port} {state}"
        )


def _connections_add(args: argparse.Namespace) -> None:
    from app.core.config import ConnectionSettings, save_settings

    settings = _settings()
    if any(item.id == args.conn_id for item in settings.transport.connections):
        print(f"连接 ID 已存在: {args.conn_id}")
        return
    connection = ConnectionSettings(
        id=args.conn_id,
        protocol=args.protocol,
        version=args.version,
        mode=args.mode,
        host=args.host,
        port=args.port,
        path=args.path,
        access_token=args.access_token,
        token=args.token,
        api_base=args.api_base,
    )
    settings.transport.connections.append(connection)
    save_settings(settings)
    print(f"已新增连接 {args.conn_id}（修改即时生效，重启后保持）")


def _connections_test(args: argparse.Namespace) -> None:
    import asyncio

    from app.adapters.base import BotClient
    from app.runtime import build_adapters

    settings = _settings()
    bot_client = BotClient()
    adapters, _ = build_adapters(settings, bot_client)
    target = next(
        (item for item in adapters if getattr(item, "bot_id", "") == args.name),
        None,
    )
    if target is None:
        print(f"连接 {args.name} 未启用或不存在")
        return
    ok, detail = asyncio.run(target.test())
    print(f"{args.name} 测试{'成功' if ok else '失败'}：{detail}")


def _scopes_list(args: argparse.Namespace) -> None:
    settings = _settings()
    scopes = settings.runtime.scopes or {}
    if not scopes:
        print("暂无监听环境配置")
        return
    for key, entry in sorted(scopes.items()):
        features = "，".join(
            f"{name}={ '开' if value else '关' }"
            for name, value in entry.features.items()
        )
        blocked = "，".join(entry.blocked_users)
        print(
            f"{key}"
            + (f" 连接={entry.connection}" if entry.connection else "")
            + (f" 功能[{features}]" if features else "")
            + (f" 黑名单[{blocked}]" if blocked else "")
        )


def _scopes_set(args: argparse.Namespace) -> None:
    from app.core.config import save_settings
    from app.core.scopes import ScopePolicyService

    settings = _settings()
    policy = ScopePolicyService(settings)
    if args.value == "on":
        policy.set_feature(args.scope, args.key, True)
    elif args.value == "off":
        policy.set_feature(args.scope, args.key, False)
    else:
        policy.set_feature(args.scope, args.key, None)
    save_settings(settings)
    print(f"{args.scope} → {args.key} = {args.value}")


def _plugin_reload(args: argparse.Namespace) -> None:
    _plugin_http("reload", args.name)


def _plugin_unload(args: argparse.Namespace) -> None:
    _plugin_http("unload", args.name)


def _plugin_http(action: str, name: str) -> None:
    settings = _settings()
    key = settings.web.api_keys[0] if settings.web.api_keys else ""
    headers = {"X-API-Key": key} if key else {}
    url = f"http://{settings.web.host}:{settings.web.port}/api/v1/plugins/{name}/{action}"
    try:
        response = httpx.post(url, headers=headers, timeout=5)
        response.raise_for_status()
        print(f"插件 {name} {action} 成功")
    except Exception as exc:
        print(f"操作失败: {exc}")
        print("请确认机器人正在运行，或改用 Web 后台操作。")


async def _workflow_list_async() -> None:
    from app.db.base import get_engine, init_db
    from app.services.workflow import WorkflowEngine

    settings = _settings()
    get_engine(settings.database.url)
    await init_db(settings.database.url)
    workflows = await WorkflowEngine().list()
    for workflow in workflows:
        print(f"{workflow.id} {workflow.name} enabled={workflow.enabled}")


async def _workflow_run_async(workflow_id: int) -> None:
    from app.db.base import get_engine, init_db
    from app.services.workflow import WorkflowEngine

    settings = _settings()
    get_engine(settings.database.url)
    await init_db(settings.database.url)
    run = await WorkflowEngine().execute(workflow_id)
    print(f"run {run.id} status={run.status}")


def _workflow_list(args: argparse.Namespace) -> None:
    asyncio.run(_workflow_list_async())


def _workflow_run(args: argparse.Namespace) -> None:
    asyncio.run(_workflow_run_async(args.id))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ofbot2")
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="启动机器人")
    run.add_argument("--config", default=None, help="配置文件路径")
    run.set_defaults(func=_run)

    sub.add_parser("doctor", help="环境诊断").set_defaults(func=_doctor)
    sub.add_parser("status", help="运行状态").set_defaults(func=_status)

    logs = sub.add_parser("logs", help="查看日志")
    logs.add_argument("--tail", type=int, default=50)
    logs.set_defaults(func=_logs)

    sub.add_parser("backup", help="创建备份").set_defaults(func=_backup)
    sub.add_parser("version", help="显示框架版本").set_defaults(func=_version)

    plugin = sub.add_parser("plugin", help="插件管理")
    plugin_sub = plugin.add_subparsers(dest="plugin_command")

    new = plugin_sub.add_parser("new", help="从示例模板生成插件")
    new.add_argument("name", help="新插件名")
    new.add_argument("--preset", default="dice", help="预设名")
    new.add_argument("--with-task", action="store_true", help="附带定时任务示例")
    new.add_argument("--with-listener", action="store_true", help="附带事件监听示例")
    new.add_argument("--with-web", action="store_true", help="附带 Web 路由示例")
    new.add_argument("--with-model", action="store_true", help="附带数据模型示例")
    new.set_defaults(func=_plugin_new)

    features_cmd = plugin_sub.add_parser("features", help="查看插件功能清单")
    features_cmd.add_argument("name", help="插件名")
    features_cmd.set_defaults(func=_plugin_features)

    check_cmd = plugin_sub.add_parser("check", help="静态校验插件清单与处理器")
    check_cmd.add_argument("name", help="插件名")
    check_cmd.set_defaults(func=_plugin_check)

    dev_cmd = plugin_sub.add_parser("dev", help="开发模式：文件变更自动重载")
    dev_cmd.add_argument("name", help="插件名")
    dev_cmd.set_defaults(func=_plugin_dev)

    test_cmd = plugin_sub.add_parser("test", help="运行插件自带测试")
    test_cmd.add_argument("name", help="插件名")
    test_cmd.set_defaults(func=_plugin_test)

    e2e_cmd = plugin_sub.add_parser("e2e", help="运行插件 e2e/ 端到端脚本")
    e2e_cmd.add_argument("name", help="插件名")
    e2e_cmd.set_defaults(func=_plugin_e2e)

    conflicts_cmd = plugin_sub.add_parser(
        "conflicts", help="扫描全部插件的命令冲突与解决策略"
    )
    conflicts_cmd.set_defaults(func=_plugin_conflicts)

    repo_cmd = plugin_sub.add_parser("repo", help="插件仓库（市场）")
    repo_sub = repo_cmd.add_subparsers(dest="repo_command")
    repo_sub.add_parser("list", help="列出仓库中的插件").set_defaults(
        func=_plugin_repo_list
    )
    repo_install = repo_sub.add_parser("install", help="安装仓库中的插件")
    repo_install.add_argument("id", help="插件 ID")
    repo_install.add_argument("--name", default=None, help="安装后的插件名（可选）")
    repo_install.add_argument(
        "--force", action="store_true", help="已存在时覆盖更新（旧包移入 .trash）"
    )
    repo_install.set_defaults(func=_plugin_repo_install)

    install = plugin_sub.add_parser("install", help="安装插件 zip")
    install.add_argument("zip", help="zip 路径")
    install.add_argument(
        "-y", "--yes", action="store_true", help="跳过警告确认直接安装"
    )
    install.set_defaults(func=_plugin_install)

    audit = plugin_sub.add_parser(
        "audit", help="安全审计 zip 或查看已安装插件审计记录"
    )
    audit.add_argument("zip", nargs="?", default=None, help="待审计的 zip 路径")
    audit.add_argument("--name", default=None, help="查看该插件的审计记录")
    audit.set_defaults(func=_plugin_audit)

    plugin_sub.add_parser("list", help="列出已安装插件").set_defaults(
        func=_plugin_list
    )

    reload_cmd = plugin_sub.add_parser("reload", help="重载插件")
    reload_cmd.add_argument("name")
    reload_cmd.set_defaults(func=_plugin_reload)

    unload_cmd = plugin_sub.add_parser("unload", help="卸载插件")
    unload_cmd.add_argument("name")
    unload_cmd.set_defaults(func=_plugin_unload)

    sub.add_parser("capabilities", help="列出框架能力").set_defaults(
        func=_capabilities
    )

    connections = sub.add_parser("connections", help="连接管理")
    connections_sub = connections.add_subparsers(dest="connection_command")
    connections_sub.add_parser("list", help="列出连接").set_defaults(
        func=_connections_list
    )
    add_cmd = connections_sub.add_parser("add", help="新增连接")
    add_cmd.add_argument("conn_id")
    add_cmd.add_argument("--protocol", default="onebot")
    add_cmd.add_argument("--version", default="v11")
    add_cmd.add_argument("--mode", default="reverse_ws")
    add_cmd.add_argument("--host", default="127.0.0.1")
    add_cmd.add_argument("--port", type=int, default=8080)
    add_cmd.add_argument("--path", default="")
    add_cmd.add_argument("--access-token", dest="access_token", default="")
    add_cmd.add_argument("--token", default="")
    add_cmd.add_argument("--api-base", dest="api_base", default="")
    add_cmd.set_defaults(func=_connections_add)
    test_conn = connections_sub.add_parser("test", help="测试连接")
    test_conn.add_argument("name")
    test_conn.set_defaults(func=_connections_test)

    scopes = sub.add_parser("scopes", help="监听环境策略")
    scopes_sub = scopes.add_subparsers(dest="scope_command")
    scopes_sub.add_parser("list", help="列出监听环境").set_defaults(
        func=_scopes_list
    )
    scopes_set = scopes_sub.add_parser(
        "set", help="设置功能开关（on/off/default）"
    )
    scopes_set.add_argument("key", help="功能键，如 dice.roll")
    scopes_set.add_argument("value", choices=["on", "off", "default"])
    scopes_set.add_argument("--scope", default="group:*", help="监听环境")
    scopes_set.set_defaults(func=_scopes_set)

    workflow = sub.add_parser("workflow", help="流程管理")
    workflow_sub = workflow.add_subparsers(dest="workflow_command")
    workflow_sub.add_parser("list", help="列出流程").set_defaults(func=_workflow_list)
    run_cmd = workflow_sub.add_parser("run", help="运行流程")
    run_cmd.add_argument("id", type=int)
    run_cmd.set_defaults(func=_workflow_run)

    return parser


def main() -> None:
    args = build_parser().parse_args()
    if not getattr(args, "func", None):
        build_parser().print_help()
        return
    code = args.func(args)
    if isinstance(code, int):
        sys.exit(code)


if __name__ == "__main__":
    sys.exit(main())
