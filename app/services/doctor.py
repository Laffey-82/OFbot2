from __future__ import annotations

import platform
import shutil
import socket
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from app.db.base import get_engine, session_factory
from app.db.models import TaskRun, WebAccount, WorkflowRun
from app.web.security import password_hasher


async def run_environment_checks(
    settings: Any,
    *,
    app_state: Any = None,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    """执行环境自检，供 Web 设置向导与 CLI doctor 共用。

    每项检查返回：name / status（pass|fail|warn|info）/ detail / 可选 href 与 href_label。
    """
    root = root or Path(__file__).resolve().parents[2]
    checks: list[dict[str, Any]] = []

    try:
        get_engine(settings.database.url)
    except Exception:
        pass

    py_ok = sys.version_info >= (3, 11)
    checks.append(
        {
            "name": "Python 版本",
            "status": "pass" if py_ok else "fail",
            "detail": f"当前 {platform.python_version()}（需要 >= 3.11）",
        }
    )

    config_path = Path(settings.config_path) if settings.config_path else root / "config.yaml"
    config_ok = True
    try:
        with config_path.open("a", encoding="utf-8"):
            pass
    except Exception:
        config_ok = False
    checks.append(
        {
            "name": "配置文件可写",
            "status": "pass" if config_ok else "fail",
            "detail": str(config_path),
        }
    )

    data_dir = root / "data"
    data_ok = data_dir.exists()
    if data_ok:
        try:
            probe = data_dir / ".ofbot2_write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except Exception:
            data_ok = False
    checks.append(
        {
            "name": "数据目录可写",
            "status": "pass" if data_ok else "fail",
            "detail": str(data_dir),
        }
    )

    try:
        usage = shutil.disk_usage(data_dir)
        free_gb = usage.free / (1024**3)
        low = usage.free < 500 * 1024 * 1024
        checks.append(
            {
                "name": "磁盘空间",
                "status": "warn" if low else "pass",
                "detail": (
                    f"剩余 {free_gb:.1f} GB（数据目录 {data_dir}）"
                    + ("，偏低，导出 / 备份可能失败" if low else "")
                ),
            }
        )
    except Exception as exc:
        checks.append(
            {
                "name": "磁盘空间",
                "status": "info",
                "detail": f"无法检测：{exc}",
            }
        )

    plugins_dir = root / "plugins"
    plugin_valid = 0
    plugin_issues: list[str] = []
    plugin_manifests: dict[str, dict[str, Any]] = {}
    if plugins_dir.exists():
        for child in sorted(plugins_dir.iterdir()):
            if not child.is_dir():
                continue
            if child.name.startswith(("__", ".")):
                continue
            manifest_path = child / "plugin.json"
            if not manifest_path.exists():
                plugin_issues.append(f"{child.name}（缺 plugin.json）")
                continue
            try:
                import json

                manifest = json.loads(
                    manifest_path.read_text(encoding="utf-8")
                )
                if manifest.get("name") != child.name:
                    plugin_issues.append(f"{child.name}（name 与目录不一致）")
                elif manifest.get("api_version") != 1:
                    plugin_issues.append(f"{child.name}（api_version 不支持）")
                else:
                    plugin_valid += 1
                    plugin_manifests[child.name] = manifest
            except Exception:
                plugin_issues.append(f"{child.name}（plugin.json 解析失败）")
    enabled_plugins = {
        name
        for name, value in (settings.plugins or {}).items()
        if value
    }
    for name, manifest in plugin_manifests.items():
        for dependency in sorted((manifest.get("dependencies") or {}).keys()):
            if dependency not in plugin_manifests:
                plugin_issues.append(f"{name}（缺少依赖 {dependency}）")
            elif dependency not in enabled_plugins:
                plugin_issues.append(f"{name}（依赖 {dependency} 未启用）")
    checks.append(
        {
            "name": "插件目录",
            "status": (
                "warn"
                if plugin_issues
                else ("pass" if plugins_dir.exists() else "info")
            ),
            "detail": f"{plugin_valid} 个合法插件"
            + (
                f"，{len(plugin_issues)} 个异常：{'、'.join(plugin_issues[:5])}"
                if plugin_issues
                else ""
            ),
            **(
                {"href": "/plugins", "href_label": "去查看"}
                if plugin_issues
                else {}
            ),
        }
    )

    db_ok = False
    db_detail = "数据库连接失败"
    try:
        async with session_factory()() as session:
            await session.execute(select(1))
        db_ok = True
        db_detail = "连接正常"
    except Exception as exc:
        db_detail = str(exc)
    checks.append(
        {
            "name": "数据库连接",
            "status": "pass" if db_ok else "fail",
            "detail": db_detail,
        }
    )

    try:
        async with session_factory()() as session:
            account_count = (
                await session.scalar(
                    select(func.count()).select_from(WebAccount)
                )
            ) or 0
        checks.append(
            {
                "name": "数据库表已初始化",
                "status": "pass",
                "detail": f"Web 账户表正常（{account_count} 条）",
            }
        )
    except Exception:
        checks.append(
            {
                "name": "数据库表已初始化",
                "status": "fail",
                "detail": "表结构缺失，请重启服务完成初始化",
            }
        )

    default_password = False
    try:
        async with session_factory()() as session:
            admin = await session.scalar(
                select(WebAccount).where(WebAccount.username == "admin")
            )
        if admin is not None and password_hasher.verify_password(
            "admin", admin.password_hash
        ):
            default_password = True
    except Exception:
        pass
    checks.append(
        {
            "name": "默认密码已修改",
            "status": "warn" if default_password else "pass",
            "detail": (
                "仍在使用默认 admin/admin，请尽快修改"
                if default_password
                else "已修改"
            ),
            **(
                {"href": "/account", "href_label": "去修改"}
                if default_password
                else {}
            ),
        }
    )

    protocol = settings.transport.protocol
    if protocol == "red":
        red_token = getattr(settings.transport.red, "token", "")
        red_ok = bool(red_token and red_token.strip())
        checks.append(
            {
                "name": "Red 协议配置",
                "status": "pass" if red_ok else "fail",
                "detail": (
                    "已设置 Token"
                    if red_ok
                    else "Token 未设置，需填写后重启"
                ),
                **(
                    {"href": "/config", "href_label": "去配置"}
                    if not red_ok
                    else {}
                ),
            }
        )
    else:
        checks.append(
            {
                "name": "OneBot 协议配置",
                "status": "pass",
                "detail": (
                    f"模式 {settings.transport.onebot.mode}，"
                    f"{'已启用' if settings.transport.onebot.enabled else '未启用'}"
                ),
            }
        )

    ai_service = getattr(app_state, "services", {}).get("ai") if app_state else None
    if ai_service is not None:
        real = [name for name in ai_service.providers if name != "mock"]
        checks.append(
            {
                "name": "AI Provider",
                "status": "pass" if real else "warn",
                "detail": (
                    "、".join(real)
                    if real
                    else "未配置真实 Provider，AI 命令将返回提示"
                ),
                **(
                    {"href": "/ai", "href_label": "去配置"}
                    if not real
                    else {}
                ),
            }
        )
    else:
        checks.append(
            {
                "name": "AI Provider",
                "status": "info",
                "detail": "服务未运行，跳过（启动后可在 Web 查看）",
            }
        )

    port_in_use = True
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", settings.web.port))
        port_in_use = False
    except OSError:
        port_in_use = True
    checks.append(
        {
            "name": "Web 端口",
            "status": "info",
            "detail": (
                f"端口 {settings.web.port} 已被本服务监听（正常）"
                if port_in_use
                else f"端口 {settings.web.port} 当前未被监听"
            ),
        }
    )

    bot_client = getattr(app_state, "bot_client", None) if app_state else None
    adapters = getattr(bot_client, "status", {}) if bot_client else {}
    if adapters:
        connected = sum(1 for value in adapters.values() if value == "connected")
        checks.append(
            {
                "name": "适配器连接",
                "status": "pass" if connected else "warn",
                "detail": (
                    f"{connected}/{len(adapters)} 个适配器已连接"
                    if connected
                    else "尚未连接，请检查协议配置后重启"
                ),
                **(
                    {"href": "/connections", "href_label": "去查看"}
                    if not connected
                    else {}
                ),
            }
        )
    else:
        checks.append(
            {
                "name": "适配器连接",
                "status": "info",
                "detail": (
                    "无适配器实例，保存配置并重启后生效"
                    if app_state is not None
                    else "服务未运行，跳过（启动后可在 Web 查看）"
                ),
            }
        )

    from datetime import timedelta

    try:
        cutoff = datetime.now(UTC) - timedelta(hours=24)
        async with session_factory()() as session:
            workflow_failed = (
                await session.scalar(
                    select(func.count())
                    .select_from(WorkflowRun)
                    .where(
                        WorkflowRun.status == "failed",
                        WorkflowRun.created_at >= cutoff,
                    )
                )
            ) or 0
            task_failed = (
                await session.scalar(
                    select(func.count())
                    .select_from(TaskRun)
                    .where(
                        TaskRun.status == "failed",
                        TaskRun.created_at >= cutoff,
                    )
                )
            ) or 0
        total_failed = workflow_failed + task_failed
        checks.append(
            {
                "name": "近 24h 失败执行",
                "status": "pass" if total_failed == 0 else "warn",
                "detail": (
                    "流程失败 0 / 任务失败 0"
                    if total_failed == 0
                    else f"流程失败 {workflow_failed} / 任务失败 {task_failed}，建议到执行历史处理"
                ),
                **(
                    {
                        "href": "/executions?status=failed",
                        "href_label": "去处理",
                    }
                    if total_failed
                    else {}
                ),
            }
        )
    except Exception:
        checks.append(
            {
                "name": "近 24h 失败执行",
                "status": "info",
                "detail": "查询失败，跳过",
            }
        )

    return checks
