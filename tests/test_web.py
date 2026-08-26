from __future__ import annotations

import asyncio
import re
import tempfile
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.bus import get_bus, reset_bus
from app.core.config import load_settings
from app.db.base import get_engine, init_db, reset_db_engine, session_factory
from app.web.app import create_app, ensure_default_admin


@pytest.mark.asyncio
async def test_web_login_and_dashboard() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = Path(tmp_dir) / "test.db"
        settings = load_settings()
        settings.config_path = str(Path(tmp_dir) / "config.yaml")
        settings.database.url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
        reset_db_engine()
        engine = get_engine(settings.database.url)
        await init_db(settings.database.url)
        await ensure_default_admin(settings)

        app = create_app(settings, plugin_manager=None)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/", follow_redirects=False)
            assert response.status_code == 303
            assert response.headers["location"] == "/login"

            login_page = await client.get("/login")
            assert login_page.status_code == 200
            assert "会话有效期" in login_page.text

            response = await client.post(
                "/login",
                data={"username": "admin", "password": "admin"},
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert response.cookies.get("ofbot2_session")

            response = await client.get("/")
            assert response.status_code == 200
            assert "仪表盘" in response.text
            assert "系统信息" in response.text
            assert "trend-days" in response.text
            assert "今日命令" in response.text
            assert "运行时长" in response.text
            assert "运行中任务" in response.text
            assert "失败任务" in response.text
            assert (
                'href="/executions?source=workflow&status=failed"'
                in response.text
            )
            assert "最近 Webhook 触发" in response.text
            assert "备份对比" in response.text
            assert "stat-link" in response.text
            assert "trend-empty" in response.text

            response = await client.get("/capabilities")
            assert response.status_code == 200

            from app.db.models import User

            async with session_factory()() as session:
                session.add(User(user_id="777", nickname="test_user"))
                await session.commit()
            scopes_page = await client.get("/scopes")
            assert scopes_page.status_code == 200
            assert "功能开关矩阵" in scopes_page.text
            assert "监听环境" in scopes_page.text
            match = re.search(
                r'name="csrf_token" value="([^"]+)"', scopes_page.text
            )
            assert match
            response = await client.post(
                "/scopes/add",
                data={"csrf_token": match.group(1), "group_id": "200"},
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert "group:200" in settings.runtime.scopes
            response = await client.post(
                "/scopes/group:200/blocked/add",
                data={
                    "csrf_token": match.group(1),
                    "user_ids": "999, 888，777",
                },
                follow_redirects=False,
            )
            assert response.status_code == 303
            blocked = settings.runtime.scopes["group:200"].blocked_users
            assert "999" in blocked
            assert "888" in blocked
            assert "777" in blocked
            response = await client.post(
                "/scopes/group:200/blocked/remove",
                data={
                    "csrf_token": match.group(1),
                    "user_id": "777",
                },
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert "777" not in settings.runtime.scopes["group:200"].blocked_users
            response = await client.post(
                "/scopes/group:200/feature",
                data={
                    "csrf_token": match.group(1),
                    "key": "system.core",
                    "value": "off",
                },
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert settings.runtime.scopes["group:200"].features["system.core"] is False
            assert (
                await client.get("/users", follow_redirects=False)
            ).status_code == 404
            blocked_page = await client.get("/scopes")
            assert "黑名单" in blocked_page.text

            setup_page = await client.get("/setup")
            assert setup_page.status_code == 200
            assert "环境自检" in setup_page.text
            assert "check-summary" in setup_page.text
            check_response = await client.get("/setup/check")
            assert check_response.status_code == 200
            checks = check_response.json()["checks"]
            names = [check["name"] for check in checks]
            assert "Python 版本" in names
            assert "数据库连接" in names
            assert "适配器连接" in names
            assert "近 24h 失败执行" in names
            assert "磁盘空间" in names
            assert "插件目录" in names
            assert all(check["status"] in {"pass", "fail", "warn", "info"} for check in checks)
            default_pw = next(
                check
                for check in checks
                if check["name"] == "默认密码已修改"
            )
            assert default_pw["href"] == "/account"
            response = await client.get("/backups")
            assert response.status_code == 200
            response = await client.get("/ai")
            assert response.status_code == 200
            match = re.search(r'name="csrf_token" value="([^"]+)"', response.text)
            assert match
            response = await client.post(
                "/ai/config",
                data={
                    "csrf_token": match.group(1),
                    "provider": "openai",
                    "api_key": "",
                    "base_url": "https://api.openai.com/v1",
                    "model": "gpt-4o-mini",
                },
                follow_redirects=False,
            )
            assert response.status_code == 303
            response = await client.get("/workflows")
            assert response.status_code == 200
            response = await client.get("/connections")
            assert response.status_code == 200
            response = await client.get("/records")
            assert response.status_code == 200
            response = await client.get("/state-machines")
            assert response.status_code == 200
            response = await client.get("/api-keys")
            assert response.status_code == 200
            api_keys_page = response
            response = await client.get("/webhooks")
            assert response.status_code == 200
            response = await client.get("/alerts")
            assert response.status_code == 200
            response = await client.get("/exports")
            assert response.status_code == 200
            response = await client.get("/files")
            assert response.status_code == 200
            match = re.search(r'name="csrf_token" value="([^"]+)"', api_keys_page.text)
            assert match
            response = await client.post(
                "/api-keys/add",
                data={"csrf_token": match.group(1), "key": "test-key"},
                follow_redirects=False,
            )
            assert response.status_code == 303
            response = await client.post(
                "/api-keys/remove",
                data={"csrf_token": match.group(1), "key": "test-key"},
                follow_redirects=False,
            )
            assert response.status_code == 303

            config_page = await client.get("/config")
            match = re.search(
                r'name="csrf_token" value="([^"]+)"', config_page.text
            )
            assert match
            response = await client.post(
                "/config",
                data={
                    "csrf_token": match.group(1),
                    "command_start": "#,!",
                    "log_level": "DEBUG",
                    "nickname": "BotA,BotB",
                    "superusers": "100,200",
                    "webhook_history_retention": "100",
                    "webhook_history_page_size": "10",
                    "export_job_retention": "30",
                    "export_job_retention_days": "7",
                    "export_retries": "2",
                    "auto_disable_workflows_after_failures": "3",
                    "auto_disable_after_failures": "5",
                },
                follow_redirects=False,
            )
            assert response.status_code == 303
            from app.core.commands import command_registry

            assert settings.basic.command_start == ["#", "!"]
            assert command_registry.command_start == ["#", "!"]
            assert settings.basic.nickname == ["BotA", "BotB"]
            assert settings.basic.superusers == ["100", "200"]
            assert settings.web.webhook_history_retention == 100
            assert settings.web.webhook_history_page_size == 10
            assert settings.web.export_job_retention == 30
            assert settings.web.export_job_retention_days == 7
            assert settings.web.export_retries == 2
            assert settings.web.auto_disable_workflows_after_failures == 3
            assert settings.scheduler.auto_disable_after_failures == 5
            from app.core.permissions import permission_manager

            assert permission_manager.get_principal("100").role == "superadmin"

            account_page = await client.get("/account")
            assert "后台账户管理" in account_page.text
            match = re.search(
                r'name="csrf_token" value="([^"]+)"', account_page.text
            )
            assert match
            response = await client.post(
                "/account/accounts/add",
                data={
                    "csrf_token": match.group(1),
                    "username": "testuser",
                    "password": "testpass123",
                    "permission_level": "0",
                },
                follow_redirects=False,
            )
            assert response.status_code == 303

            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as second_client:
                response = await second_client.post(
                    "/login",
                    data={"username": "testuser", "password": "testpass123"},
                    follow_redirects=False,
                )
                assert response.status_code == 303
                assert response.cookies.get("ofbot2_session")

        await engine.dispose()
        reset_db_engine()


@pytest.mark.asyncio
async def test_web_ai_and_plugin_config_routes() -> None:
    """AI 多 Provider、激活、测试与插件配置保存路由。"""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = Path(tmp_dir) / "test.db"
        settings = load_settings()
        settings.config_path = str(Path(tmp_dir) / "config.yaml")
        settings.database.url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
        reset_db_engine()
        engine = get_engine(settings.database.url)
        await init_db(settings.database.url)
        await ensure_default_admin(settings)

        app = create_app(settings, plugin_manager=None)
        from app.services.ai import AIService, MockAIProvider

        ai_service = AIService()
        ai_service.register(MockAIProvider())
        app.state.services["ai"] = ai_service
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/login",
                data={"username": "admin", "password": "admin"},
                follow_redirects=False,
            )

            ai_page = await client.get("/ai")
            match = re.search(r'name="csrf_token" value="([^"]+)"', ai_page.text)
            assert match
            csrf = match.group(1)

            response = await client.post(
                "/ai/config",
                data={
                    "csrf_token": csrf,
                    "provider": "ollama",
                    "api_key": "",
                    "base_url": "http://127.0.0.1:11434",
                    "model": "qwen2.5:7b",
                },
                follow_redirects=False,
            )
            assert response.status_code == 303

            response = await client.post(
                "/ai/activate",
                data={"csrf_token": csrf, "provider": "mock"},
                follow_redirects=False,
            )
            assert response.status_code == 303

            response = await client.post(
                "/ai/test",
                data={"csrf_token": csrf, "provider": "mock"},
            )
            assert response.status_code == 200
            assert response.json()["ok"] is True, response.text

            response = await client.post(
                "/plugins/template/config",
                data={
                    "csrf_token": csrf,
                    "config_json": '{"greeting": "hi"}',
                },
                follow_redirects=False,
            )
            assert response.status_code == 303

        await engine.dispose()
        reset_db_engine()


@pytest.mark.asyncio
async def test_web_all_pages_render() -> None:
    """所有后台页面登录后均应返回 200，避免模板回归。"""
    pages = [
        "/",
        "/stats",
        "/commands",
        "/setup",
        "/config",
        "/account",
        "/docs",
        "/docs/index",
        "/docs/readme",
        "/docs/dev",
        "/docs/api",
        "/docs/view/faq",
        "/docs/view/api",
        "/docs/presets",
        "/docs/changelog",
        "/plugins",
        "/capabilities",
        "/connections",
        "/records",
        "/state-machines",
        "/api-keys",
        "/webhooks",
        "/alerts",
        "/exports",
        "/files",
        "/backups",
        "/ai",
        "/workflows",
        "/executions",
        "/scopes",
        "/tasks",
        "/monitor",
        "/audit",
        "/logs",
    ]
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = Path(tmp_dir) / "test.db"
        settings = load_settings()
        settings.config_path = str(Path(tmp_dir) / "config.yaml")
        settings.database.url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
        reset_db_engine()
        engine = get_engine(settings.database.url)
        await init_db(settings.database.url)
        await ensure_default_admin(settings)

        app = create_app(settings, plugin_manager=None)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/login",
                data={"username": "admin", "password": "admin"},
                follow_redirects=False,
            )
            for page in pages:
                response = await client.get(page)
                assert response.status_code == 200, f"{page} -> {response.status_code}"
            app_js = await client.get("/static/js/app.js")
            assert app_js.status_code == 200
            assert "function initSelectAll" in app_js.text
            assert "function collectChecked" in app_js.text
            assert "function initExportButton" in app_js.text

        await engine.dispose()
        reset_db_engine()


@pytest.mark.asyncio
async def test_web_commands_page_lists_commands() -> None:
    """命令速查页应展示注册命令的名称、别名、说明与权限。"""
    from app.core.commands import command_registry

    async def dummy_handler(event, args, command_ctx) -> None:
        return None

    command_registry.register(
        "speedcheck",
        dummy_handler,
        aliases={"速查"},
        permission="bot.command",
        plugin_name="test_command_page",
        description="用于验证命令速查页的示例命令",
    )
    try:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
            db_path = Path(tmp_dir) / "test.db"
            settings = load_settings()
            settings.config_path = str(Path(tmp_dir) / "config.yaml")
            settings.database.url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
            reset_db_engine()
            engine = get_engine(settings.database.url)
            await init_db(settings.database.url)
            await ensure_default_admin(settings)

            app = create_app(settings, plugin_manager=None)
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                await client.post(
                    "/login",
                    data={"username": "admin", "password": "admin"},
                    follow_redirects=False,
                )
                page = await client.get("/commands")
                assert page.status_code == 200
                assert "命令速查" in page.text
                assert "speedcheck" in page.text
                assert "速查" in page.text
                assert "用于验证命令速查页的示例命令" in page.text
                assert "bot.command" in page.text

                filtered = await client.get(
                    "/commands", params={"q": "speedcheck"}
                )
                assert filtered.status_code == 200
                assert "speedcheck" in filtered.text
                filtered2 = await client.get(
                    "/commands", params={"q": "不存在的命令xyz"}
                )
                assert filtered2.status_code == 200
                assert "没有匹配的命令" in filtered2.text

                export_response = await client.get(
                    "/commands/export?plugin=test_command_page"
                )
                assert export_response.status_code == 200
                assert export_response.headers["content-type"].startswith(
                    "text/csv"
                )
                assert "speedcheck" in export_response.text
                assert "用于验证命令速查页的示例命令" in export_response.text
                export_all = await client.get("/commands/export")
                assert export_all.status_code == 200
                commands_page = await client.get("/commands")
                assert (
                    'href="/stats?command=speedcheck"'
                    in commands_page.text
                )

            await engine.dispose()
            reset_db_engine()
    finally:
        command_registry.unregister_plugin("test_command_page")


@pytest.mark.asyncio
async def test_web_logs_tail_and_page() -> None:
    """日志尾部读取与日志查看页渲染。"""
    from app.web.helpers import _tail_lines

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        sample = Path(tmp_dir) / "sample.log"
        sample.write_text(
            "\n".join(f"line{i}" for i in range(300)),
            encoding="utf-8",
        )
        tail = _tail_lines(sample, 50)
        assert len(tail.splitlines()) == 50
        assert tail.splitlines()[0] == "line250"
        assert _tail_lines(sample, 5000) == sample.read_text(
            encoding="utf-8"
        )
        assert _tail_lines(Path(tmp_dir) / "missing.log", 10) == ""

        db_path = Path(tmp_dir) / "test.db"
        settings = load_settings()
        settings.config_path = str(Path(tmp_dir) / "config.yaml")
        settings.database.url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
        reset_db_engine()
        engine = get_engine(settings.database.url)
        await init_db(settings.database.url)
        await ensure_default_admin(settings)

        app = create_app(settings, plugin_manager=None)
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            await client.post(
                "/login",
                data={"username": "admin", "password": "admin"},
                follow_redirects=False,
            )
            page = await client.get("/logs")
            assert page.status_code == 200
            assert "运行日志" in page.text
            assert "log-autorefresh" in page.text
            traversal = await client.get("/logs?file=../../config.yaml")
            assert traversal.status_code == 200

        await engine.dispose()
        reset_db_engine()


@pytest.mark.asyncio
async def test_web_records_alerts_workflow_scaffold() -> None:
    """记录编辑、告警切换、流程运行详情与 Web 插件脚手架路由。"""
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = Path(tmp_dir) / "test.db"
        settings = load_settings()
        settings.config_path = str(Path(tmp_dir) / "config.yaml")
        settings.database.url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
        reset_db_engine()
        engine = get_engine(settings.database.url)
        await init_db(settings.database.url)
        await ensure_default_admin(settings)

        from app.db.models import WorkflowRun
        from app.services.alerts import AlertService
        from app.services.records import (
            FieldSchema,
            RecordService,
            RecordTypeSchema,
            SchemaRegistry,
        )
        from app.services.scaffold import ScaffoldService

        app = create_app(settings, plugin_manager=None)
        schemas = SchemaRegistry()
        schemas.register(
            RecordTypeSchema("order", [FieldSchema("title", "string", True)])
        )
        records = RecordService(schemas)
        alerts = AlertService()
        alerts.add_rule("test_rule", "*", "")
        scaffold = ScaffoldService(
            root / "examples" / "plugins", Path(tmp_dir) / "plugins"
        )
        app.state.services["schema_registry"] = schemas
        app.state.services["records"] = records
        app.state.services["alerts"] = alerts
        app.state.services["scaffold"] = scaffold
        try:
            await get_bus().stop(clear=True)
        except Exception:
            pass
        reset_bus()

        record = await records.create("order", {"title": "test"})
        async with session_factory()() as session:
            run = WorkflowRun(
                workflow_id=1,
                status="succeeded",
                result={"steps": [{"action": "echo", "output": "hi"}]},
            )
            session.add(run)
            await session.commit()
            await session.refresh(run)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/login",
                data={"username": "admin", "password": "admin"},
                follow_redirects=False,
            )

            records_page = await client.get("/records")
            match = re.search(r'name="csrf_token" value="([^"]+)"', records_page.text)
            assert match
            assert "view-record-fields" in records_page.text
            assert "field-badges" in records_page.text
            assert "字段</span>" in records_page.text
            csrf = match.group(1)

            response = await client.post(
                f"/records/{record.id}/update",
                data={
                    "csrf_token": csrf,
                    "data_json": '{"title": "updated"}',
                },
                follow_redirects=False,
            )
            assert response.status_code == 303
            updated = await records.get(record.id)
            assert updated is not None and updated.data["title"] == "updated"

            response = await client.post(
                "/alerts/toggle",
                data={"csrf_token": csrf, "name": "test_rule"},
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert alerts.rules[0].enabled is False
            alerts_page = await client.get("/alerts")
            assert "data-alert-preset" in alerts_page.text
            assert "metric.cpu_high" in alerts_page.text
            assert "逗号或空格分隔" in alerts_page.text
            assert "target_private" in alerts_page.text
            assert "清除历史" in alerts_page.text
            assert "自动保留" in alerts_page.text
            assert "告警总数" in alerts_page.text
            assert "高频事件" in alerts_page.text
            assert "stats-days" in alerts_page.text
            ranged = await client.get("/alerts?stats_days=7")
            assert ranged.status_code == 200
            assert "告警总数" in ranged.text
            response = await client.post(
                "/alerts/add",
                data={
                    "csrf_token": csrf,
                    "name": "private_rule",
                    "event": "metric.cpu_high",
                    "target_group": "1,2",
                    "target_private": "10001, 10002",
                    "keyword": "",
                },
                follow_redirects=False,
            )
            assert response.status_code == 303
            private_rule = next(
                rule for rule in alerts.rules if rule.name == "private_rule"
            )
            assert private_rule.target_private == "10001, 10002"
            assert private_rule.target_group == "1,2"

            from sqlalchemy import func, select

            from app.db.models import AlertEvent

            async with session_factory()() as session:
                session.add(
                    AlertEvent(
                        rule_name="test_rule",
                        event="task.failed",
                        detail="boom",
                    )
                )
                session.add(
                    AlertEvent(
                        rule_name="test_rule",
                        event="workflow.failed",
                        detail="bad-flow（#1，run #7）：boom",
                    )
                )
                await session.commit()
            page = await client.get("/alerts?event=task.failed")
            assert page.status_code == 200
            assert "boom" in page.text
            assert "alert-export-btn" in page.text
            page = await client.get("/alerts?event=other_event")
            assert "boom" not in page.text
            linked = await client.get("/alerts?event=workflow.failed")
            assert 'href="/workflows/runs/7"' in linked.text
            export_response = await client.get(
                "/alerts/export?event=task.failed"
            )
            assert export_response.status_code == 200
            assert export_response.headers["content-type"].startswith(
                "text/csv"
            )
            assert "boom" in export_response.text

            from datetime import UTC, datetime, timedelta

            async with session_factory()() as session:
                session.add(
                    AlertEvent(
                        rule_name="old_rule",
                        event="x",
                        detail="old",
                        created_at=datetime.now(UTC) - timedelta(days=40),
                    )
                )
                await session.commit()
            await alerts.check("task.failed", "boom")
            async with session_factory()() as session:
                old_count = await session.scalar(
                    select(func.count())
                    .select_from(AlertEvent)
                    .where(AlertEvent.rule_name == "old_rule")
                )
                assert old_count == 0

            page = await client.get("/alerts")
            match = re.search(
                r'name="csrf_token" value="([^"]+)"', page.text
            )
            assert match
            response = await client.post(
                "/alerts/history/clear",
                data={
                    "csrf_token": match.group(1),
                    "start": "2000-01-01",
                    "end": "2099-12-31",
                },
                follow_redirects=False,
            )
            assert response.status_code == 303
            async with session_factory()() as session:
                remaining = await session.scalar(
                    select(func.count()).select_from(AlertEvent)
                )
                assert remaining == 0

            response = await client.get(f"/workflows/runs/{run.id}")
            assert response.status_code == 200
            assert "步骤输出" in response.text

            response = await client.post(
                "/plugins/new",
                data={
                    "csrf_token": csrf,
                    "name": "testplug",
                    "template": "dice",
                },
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert (Path(tmp_dir) / "plugins" / "testplug" / "plugin.json").exists()

        await engine.dispose()
        reset_db_engine()
        try:
            await get_bus().stop(clear=True)
        except Exception:
            pass
        reset_bus()


@pytest.mark.asyncio
async def test_web_api_keys_unauth_redirects_to_login() -> None:
    """未登录访问 /api-keys 应跳转登录页（此前被 /api 前缀误判为 API 路径）。"""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = Path(tmp_dir) / "test.db"
        settings = load_settings()
        settings.config_path = str(Path(tmp_dir) / "config.yaml")
        settings.database.url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
        settings.web.api_keys = ["test-key"]
        reset_db_engine()
        engine = get_engine(settings.database.url)
        await init_db(settings.database.url)
        await ensure_default_admin(settings)

        app = create_app(settings, plugin_manager=None)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 页面请求（HTML）：应 303 跳转登录页
            response = await client.get(
                "/api-keys",
                headers={"accept": "text/html"},
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert response.headers["location"] == "/login"

            # 真正的 API 路径（配置了 Key 但未携带）：保持 JSON 401，不跳转
            response = await client.get(
                "/api/v1/status",
                headers={"accept": "application/json"},
                follow_redirects=False,
            )
            assert response.status_code == 401
            assert response.headers["content-type"].startswith(
                "application/json"
            )
            response = await client.get(
                "/api/v1/status",
                headers={"x-api-key": "test-key"},
                follow_redirects=False,
            )
            assert response.status_code == 200

            # 登录后子页面 /backups/compare 应高亮「数据备份」菜单项
            await client.post(
                "/login",
                data={"username": "admin", "password": "admin"},
                follow_redirects=False,
            )
            compare_page = await client.get("/backups/compare")
            assert compare_page.status_code == 200
            assert (
                '<a href="/backups" class="active">数据备份</a>'
                in compare_page.text
            )

        await engine.dispose()
        reset_db_engine()


@pytest.mark.asyncio
async def test_web_reconnect_stats_and_bulk_delete() -> None:
    """适配器重连、统计页与记录批量删除路由。"""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = Path(tmp_dir) / "test.db"
        settings = load_settings()
        settings.config_path = str(Path(tmp_dir) / "config.yaml")
        settings.database.url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
        reset_db_engine()
        engine = get_engine(settings.database.url)
        await init_db(settings.database.url)
        await ensure_default_admin(settings)

        from app.db.models import CommandStat, Record
        from app.services.export import ExportService
        from app.services.records import (
            FieldSchema,
            RecordService,
            RecordTypeSchema,
            SchemaRegistry,
        )

        app = create_app(settings, plugin_manager=None)
        schemas = SchemaRegistry()
        schemas.register(
            RecordTypeSchema("order", [FieldSchema("title", "string", True)])
        )
        records = RecordService(schemas)
        app.state.services["schema_registry"] = schemas
        app.state.services["records"] = records
        app.state.services["export"] = ExportService(Path(tmp_dir) / "exports")

        class FakeAdapter:
            bot_id = "fake"

            def __init__(self):
                self.stopped = False
                self.started = False
                self.tested = False

            async def stop(self):
                self.stopped = True

            async def start(self):
                self.started = True

            async def test(self):
                self.tested = True
                return True, "ok"

            async def send_group_message(self, group_id, message):
                return True

            async def send_private_message(self, user_id, message):
                return True

        fake = FakeAdapter()
        from app.adapters.base import BotClient

        bot_client = BotClient()
        bot_client.register("fake", fake)
        bot_client.status["fake"] = "connected"
        bot_client.details["fake"] = {"last_heartbeat": 0}
        app.state.bot_client = bot_client
        app.state.adapters = [fake]
        app.state.adapter_tasks = []

        async with session_factory()() as session:
            for title in ("a", "b"):
                session.add(Record(record_type="order", data={"title": title}))
            session.add(CommandStat(user_id="100", command_name="/ping", success=True))
            from datetime import UTC, datetime, timedelta

            session.add(
                CommandStat(
                    user_id="100",
                    command_name="/ping",
                    success=True,
                    timestamp=datetime.now(UTC) - timedelta(days=1),
                )
            )
            await session.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/login",
                data={"username": "admin", "password": "admin"},
                follow_redirects=False,
            )

            page = await client.get("/connections")
            assert "心跳过期" in page.text
            assert "连接配置" in page.text
            match = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
            assert match
            response = await client.post(
                "/connections/fake/reconnect",
                data={"csrf_token": match.group(1)},
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert fake.stopped is True
            await asyncio.sleep(0.05)
            assert fake.started is True

            page = await client.get("/stats")
            assert page.status_code == 200
            assert "/ping" in page.text
            assert "stats-donut" in page.text
            assert "top-commands-table" in page.text
            assert "top-users-table" in page.text
            assert "top-groups-table" in page.text
            page = await client.get("/stats?days=1")
            assert page.status_code == 200
            page = await client.get("/stats?command=%2Fping")
            assert page.status_code == 200
            assert "/ping" in page.text
            assert "detail-trend" in page.text
            today = datetime.now(UTC).date().isoformat()
            page = await client.get(f"/stats?command=%2Fping&day={today}")
            assert page.status_code == 200
            assert "hourly-chart" in page.text

            response = await client.get("/stats/export?days=0")
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/csv")
            assert "/ping" in response.text
            response = await client.get(
                "/stats/export?command=%2Fping&days=30"
            )
            assert response.status_code == 200
            assert "bucket" in response.text

            page = await client.get("/records")
            match = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
            assert match
            assert "view-copy-json" in page.text
            assert "data-created" in page.text
            items = await records.list()
            assert len(items) == 2
            page = await client.get("/records?status=inactive")
            assert page.status_code == 200
            assert (
                len(re.findall(r'data-edit-record="', page.text)) == 0
            )
            page = await client.get("/records?status=active")
            assert len(re.findall(r'data-edit-record="', page.text)) == 2
            page = await client.get("/records?record_type=order")
            assert len(re.findall(r'data-edit-record="', page.text)) == 2
            page = await client.get("/records?record_type=nonexistent")
            assert len(re.findall(r'data-edit-record="', page.text)) == 0
            page = await client.get("/records?order=asc")
            assert page.status_code == 200
            assert 'value="asc" selected' in page.text
            response = await client.post(
                "/records/bulk-export",
                data={
                    "csrf_token": match.group(1),
                    "ids": [str(items[0].id), str(items[1].id)],
                    "fmt": "csv",
                },
            )
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/csv")
            response = await client.post(
                "/records/bulk-delete",
                data={
                    "csrf_token": match.group(1),
                    "ids": [str(items[0].id), str(items[1].id)],
                },
                follow_redirects=False,
            )
            assert response.status_code == 303
            remaining = await asyncio.wait_for(records.list(), timeout=5)
            assert remaining == []

            # 跨页全选：再建两条记录，select_all 删除
            async with session_factory()() as session:
                from app.db.models import Record

                session.add(Record(record_type="order", data={"title": "c"}))
                session.add(Record(record_type="order", data={"title": "d"}))
                await session.commit()
            response = await client.post(
                "/records/bulk-export",
                data={
                    "csrf_token": match.group(1),
                    "select_all": "on",
                    "record_type": "order",
                    "fmt": "json",
                },
            )
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("application/json")
            response = await client.post(
                "/records/bulk-delete",
                data={
                    "csrf_token": match.group(1),
                    "select_all": "on",
                    "record_type": "order",
                    "status": "active",
                },
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert await records.list() == []

            response = await client.post(
                "/connections/reconnect-all",
                data={"csrf_token": match.group(1)},
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert fake.started is True

            try:
                await get_bus().stop(clear=True)
            except Exception:
                pass
            reset_bus()
            response = await client.post(
                "/connections/fake/test",
                data={"csrf_token": match.group(1)},
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert fake.tested is True
            assert app.state.adapter_test_history.get("fake")

            response = await client.post(
                "/connections/test-all",
                data={"csrf_token": match.group(1)},
                follow_redirects=False,
            )
            assert response.status_code == 303
            response = await client.post(
                "/connections/send-test",
                data={
                    "csrf_token": match.group(1),
                    "group_id": "1",
                    "message": "hi",
                },
                follow_redirects=False,
            )
            assert response.status_code == 303
            response = await client.post(
                "/connections/send-test",
                data={
                    "csrf_token": match.group(1),
                    "group_id": "2",
                    "message": "hi",
                    "target_type": "private",
                },
                follow_redirects=False,
            )
            assert response.status_code == 303
            from app.db.models import AdapterTestLog

            async with session_factory()() as session:
                from sqlalchemy import func, select

                log_count = await session.scalar(
                    select(func.count()).select_from(AdapterTestLog)
                )
                assert log_count and log_count >= 1
            dashboard = await client.get("/")
            assert "较昨日" in dashboard.text

        await engine.dispose()
        reset_db_engine()
        try:
            await get_bus().stop(clear=True)
        except Exception:
            pass
        reset_bus()


@pytest.mark.asyncio
async def test_web_setup_wizard_and_export_retry() -> None:
    """设置向导保存与导出失败重试路由。"""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = Path(tmp_dir) / "test.db"
        settings = load_settings()
        settings.config_path = str(Path(tmp_dir) / "config.yaml")
        settings.database.url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
        reset_db_engine()
        engine = get_engine(settings.database.url)
        await init_db(settings.database.url)
        await ensure_default_admin(settings)

        from app.services.export import ExportService
        from app.services.records import (
            FieldSchema,
            RecordService,
            RecordTypeSchema,
            SchemaRegistry,
        )

        app = create_app(settings, plugin_manager=None)
        schemas = SchemaRegistry()
        schemas.register(
            RecordTypeSchema("order", [FieldSchema("title", "string", True)])
        )
        records = RecordService(schemas)
        export_service = ExportService(Path(tmp_dir) / "exports")
        reconfigure_calls = []

        async def fake_reconfigure():
            reconfigure_calls.append(True)
            return {"adapters": ["red"]}

        app.state.reconfigure_adapters = fake_reconfigure
        app.state.services["schema_registry"] = schemas
        app.state.services["records"] = records
        app.state.services["export"] = export_service
        async with session_factory()() as session:
            from app.db.models import Record

            session.add(Record(record_type="order", data={"title": "x"}))
            await session.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/login",
                data={"username": "admin", "password": "admin"},
                follow_redirects=False,
            )

            response = await client.post(
                "/login",
                data={"username": "admin", "password": "admin"},
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert response.headers["location"] == "/setup"

            page = await client.get("/setup")
            assert page.status_code == 200
            assert "设置向导" in page.text
            assert "password-strength-hint" in page.text
            match = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
            assert match
            csrf = match.group(1)

            response = await client.post(
                "/setup",
                data={
                    "csrf_token": csrf,
                    "current_password": "admin",
                    "new_password": "newpass123",
                    "protocol": "onebot",
                    "onebot_enabled": "on",
                    "onebot_mode": "reverse",
                    "onebot_host": "127.0.0.1",
                    "onebot_port": "6700",
                    "onebot_path": "/ws",
                },
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert settings.transport.protocol == "onebot"
            assert settings.transport.onebot.enabled is True
            assert reconfigure_calls == [True]
            from app.web.security import password_hasher

            async with session_factory()() as session:
                from sqlalchemy import select

                from app.db.models import WebAccount

                admin = await session.scalar(
                    select(WebAccount).where(WebAccount.username == "admin")
                )
                assert admin is not None
                assert password_hasher.verify_password("newpass123", admin.password_hash)

            response = await client.post(
                "/setup",
                data={
                    "csrf_token": csrf,
                    "protocol": "red",
                    "red_host": "127.0.0.1",
                    "red_port": "16530",
                    "red_token": "",
                },
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert response.headers["location"] == "/setup?error=1"

            job_id = "failedjob"
            app.state.export_jobs[job_id] = {
                "id": job_id,
                "record_type": "order",
                "fmt": "csv",
                "status": "failed",
                "message": "boom",
                "total": 0,
                "done": 0,
                "filename": None,
                "created_at": "2026-01-01T00:00:00",
            }
            response = await client.post(
                f"/exports/jobs/{job_id}/retry",
                data={"csrf_token": csrf},
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert app.state.export_jobs[job_id]["status"] == "done"
            assert app.state.export_jobs[job_id]["filename"]

            response = await client.post(
                "/exports/jobs/clear",
                data={"csrf_token": csrf},
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert app.state.export_jobs == {}

            class FlakyExport(ExportService):
                def __init__(self, *args, **kwargs):
                    super().__init__(*args, **kwargs)
                    self.failed_once = False

                def export_csv(self, rows, name):
                    if not self.failed_once:
                        self.failed_once = True
                        raise RuntimeError("transient failure")
                    return super().export_csv(rows, name)

            settings.web.export_retries = 0
            app.state.services["export"] = FlakyExport(Path(tmp_dir) / "exports2")
            response = await client.post(
                "/exports/create",
                data={
                    "csrf_token": csrf,
                    "record_type": "order",
                    "fmt": "csv",
                    "retries": "1",
                },
                follow_redirects=False,
            )
            assert response.status_code == 303
            jobs = list(app.state.export_jobs.values())
            assert jobs and jobs[-1]["status"] == "done"
            assert jobs[-1]["attempts"] == 1

        await engine.dispose()
        reset_db_engine()


@pytest.mark.asyncio
async def test_web_management_api_and_file_delete() -> None:
    """任务/告警/状态机/Webhook 管理 API 与导出/文件删除路由。"""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = Path(tmp_dir) / "test.db"
        settings = load_settings()
        settings.config_path = str(Path(tmp_dir) / "config.yaml")
        settings.database.url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
        reset_db_engine()
        engine = get_engine(settings.database.url)
        await init_db(settings.database.url)
        await ensure_default_admin(settings)

        from app.services.alerts import AlertService
        from app.services.export import ExportService
        from app.services.files import FileService
        from app.services.state_machine import StateMachineService
        from app.services.webhook import WebhookService

        app = create_app(settings, plugin_manager=None)
        export_service = ExportService(Path(tmp_dir) / "exports")
        file_service = FileService(Path(tmp_dir) / "files")
        app.state.services["export"] = export_service
        app.state.services["files"] = file_service
        app.state.services["alerts"] = AlertService()
        app.state.services["webhook"] = WebhookService()
        app.state.services["state_machine"] = StateMachineService()

        export_service.export_json([{"a": 1}], "smoke_export")
        file_service.save_bytes(b"hello", suffix=".txt")

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/login",
                data={"username": "admin", "password": "admin"},
                follow_redirects=False,
            )

            response = await client.post(
                "/api/v1/webhooks", json={"name": "api_hook"}
            )
            assert response.status_code == 200
            assert "api_hook" in settings.plugin_configs.get("webhooks", {})
            response = await client.get("/api/v1/webhooks")
            assert "api_hook" in response.json()["webhooks"]
            assert (await client.delete("/api/v1/webhooks/api_hook")).status_code == 200
            assert "api_hook" not in settings.plugin_configs.get("webhooks", {})

            response = await client.post(
                "/api/v1/alerts", json={"name": "api_rule", "event": "task.failed"}
            )
            assert response.status_code == 200
            saved_rules = settings.plugin_configs.get("alerts", {}).get("rules", [])
            assert any(r["name"] == "api_rule" for r in saved_rules)
            response = await client.post("/api/v1/alerts/api_rule/toggle")
            assert response.status_code == 200
            assert response.json()["enabled"] is False
            saved_rules = settings.plugin_configs.get("alerts", {}).get("rules", [])
            assert next(r for r in saved_rules if r["name"] == "api_rule")["enabled"] is False
            assert (await client.delete("/api/v1/alerts/api_rule")).status_code == 200
            saved_rules = settings.plugin_configs.get("alerts", {}).get("rules", [])
            assert not any(r["name"] == "api_rule" for r in saved_rules)

            from app.services.alerts import AlertService as AlertServiceCls

            keyword_alerts = AlertServiceCls()
            keyword_alerts.add_rule("kw_rule", "task.failed", "", keyword="db")
            assert await keyword_alerts.check("task.failed", "db connection lost")
            assert await keyword_alerts.check("task.failed", "no keyword here") == []
            keyword_alerts.add_rule(
                "multi_kw", "task.failed", "", keyword="db,redis"
            )
            assert await keyword_alerts.check("task.failed", "redis down")

            response = await client.post(
                "/api/v1/state-machines",
                json={
                    "name": "api_sm",
                    "transitions": [{"from": "a", "to": "b"}],
                },
            )
            assert response.status_code == 200
            assert (
                await client.delete("/api/v1/state-machines/api_sm")
            ).status_code == 200

            response = await client.post(
                "/api/v1/tasks",
                json={
                    "name": "api_task",
                    "task_type": "interval",
                    "interval_seconds": 60,
                    "group_id": "1",
                    "message": "hi",
                },
            )
            assert response.status_code == 200
            task_id = response.json()["task_id"]
            response = await client.get("/api/v1/tasks")
            assert any(t["task_id"] == task_id for t in response.json()["tasks"])
            assert (
                await client.post(f"/api/v1/tasks/{task_id}/run")
            ).status_code == 200
            response = await client.post(f"/api/v1/tasks/{task_id}/toggle")
            assert response.status_code == 200
            assert response.json()["enabled"] is False
            assert (await client.delete(f"/api/v1/tasks/{task_id}")).status_code == 200

            page = await client.get("/exports")
            match = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
            assert match
            response = await client.post(
                "/exports/smoke_export.json/delete",
                data={"csrf_token": match.group(1)},
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert export_service.list_files() == []

            page = await client.get("/files")
            match = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
            assert match
            file_name = file_service.list_files()[0]["name"]
            response = await client.post(
                f"/files/{file_name}/delete",
                data={"csrf_token": match.group(1)},
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert file_service.list_files() == []

            file_service.save_bytes(b"one", suffix=".txt")
            file_service.save_bytes(b"two", suffix=".txt")
            file_service.save_bytes(b"\x00\x01\x02binary", suffix=".bin")
            file_service.save_bytes(b"# Title\n\nhello", suffix=".md")
            file_service.save_bytes(
                b"\x89PNG\r\n\x1a\nbinary-ish", suffix=".png"
            )
            page = await client.get("/files")
            match = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
            assert match
            names = [f["name"] for f in file_service.list_files()]
            assert "modified" in file_service.list_files()[0]
            assert "data-lightbox" in page.text
            text_name = next(
                f["name"]
                for f in file_service.list_files()
                if f["name"].endswith(".txt")
            )
            preview = await client.get(f"/files/{text_name}/preview")
            assert preview.status_code == 200
            assert preview.json()["ok"] is True
            binary_name = next(
                f["name"]
                for f in file_service.list_files()
                if f["name"].endswith(".bin")
            )
            preview = await client.get(f"/files/{binary_name}/preview")
            assert preview.status_code == 200
            assert preview.json()["ok"] is False
            md_name = next(
                f["name"]
                for f in file_service.list_files()
                if f["name"].endswith(".md")
            )
            preview = await client.get(f"/files/{md_name}/preview")
            assert preview.status_code == 200
            assert preview.json()["html"].startswith("<h1>")
            response = await client.post(
                "/files/bulk-delete",
                data={"csrf_token": match.group(1), "names": names},
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert file_service.list_files() == []

        await engine.dispose()
        reset_db_engine()


@pytest.mark.asyncio
async def test_web_audit_filter_and_record_types_api() -> None:
    """审计筛选与记录类型 REST API。"""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = Path(tmp_dir) / "test.db"
        settings = load_settings()
        settings.config_path = str(Path(tmp_dir) / "config.yaml")
        settings.database.url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
        reset_db_engine()
        engine = get_engine(settings.database.url)
        await init_db(settings.database.url)
        await ensure_default_admin(settings)

        from app.db.models import AuditLog
        from app.services.export import ExportService
        from app.services.records import SchemaRegistry

        app = create_app(settings, plugin_manager=None)
        schemas = SchemaRegistry()
        app.state.services["schema_registry"] = schemas
        export_service = ExportService(Path(tmp_dir) / "exports")
        app.state.services["export"] = export_service
        async with session_factory()() as session:
            session.add(
                AuditLog(action="plugin.reloaded", actor="admin", target="x", success=True)
            )
            session.add(
                AuditLog(action="task.failed", actor="system", target="t", success=False)
            )
            await session.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/login",
                data={"username": "admin", "password": "admin"},
                follow_redirects=False,
            )

            page = await client.get("/audit?actor=admin")
            assert page.status_code == 200
            assert "plugin.reloaded" in page.text
            assert "task.failed" not in page.text

            page = await client.get("/audit?success=0")
            assert "task.failed" in page.text
            action_cells = re.findall(r'<td class="mono">([^<]+)</td>', page.text)
            assert "plugin.reloaded" not in action_cells

            response = await client.get("/audit/export?actor=admin")
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/csv")
            assert "plugin.reloaded" in response.text
            disposition = response.headers["content-disposition"]
            assert 'filename="audit_' in disposition and ".csv" in disposition
            response = await client.get("/audit/export?start=2000-01-01")
            range_disposition = response.headers["content-disposition"]
            assert "2000-01-01" in range_disposition

            page = await client.get("/audit")
            match = re.search(
                r'form\.set\("csrf_token", "([^"]+)"\)', page.text
            )
            assert match
            response = await client.post(
                "/audit/export-job",
                data={
                    "csrf_token": match.group(1),
                    "fmt": "csv",
                    "actor": "admin",
                },
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert response.headers["location"].startswith("/exports")
            files = export_service.list_files()
            assert files and files[0]["name"].startswith("audit_")
            page = await client.get("/exports")
            assert page.status_code == 200
            assert "audit" in page.text
            assert files[0]["name"] in page.text
            download = await client.get(
                f"/exports/{files[0]['name']}/download"
            )
            assert download.status_code == 200
            assert download.content.startswith(b"\xef\xbb\xbf")

            page = await client.get("/audit?start=2099-01-01")
            cells = re.findall(r'<td class="mono">([^<]+)</td>', page.text)
            assert "plugin.reloaded" not in cells and "task.failed" not in cells
            page = await client.get("/audit?start=2000-01-01")
            cells = re.findall(r'<td class="mono">([^<]+)</td>', page.text)
            assert "plugin.reloaded" in cells
            page = await client.get("/audit?page=2")
            assert page.status_code == 200

            response = await client.post(
                "/api/v1/record-types",
                json={
                    "name": "api_type",
                    "fields": [{"name": "title", "type": "string", "required": True}],
                },
            )
            assert response.status_code == 200
            assert response.json()["name"] == "api_type"

            response = await client.get("/api/v1/record-types")
            assert response.status_code == 200
            names = [t["name"] for t in response.json()["record_types"]]
            assert "api_type" in names

            response = await client.delete("/api/v1/record-types/api_type")
            assert response.status_code == 200
            response = await client.get("/api/v1/record-types")
            names = [t["name"] for t in response.json()["record_types"]]
            assert "api_type" not in names

        await engine.dispose()
        reset_db_engine()


@pytest.mark.asyncio
async def test_web_state_machine_and_metrics() -> None:
    """状态机流转展示/删除与监控计数器接口。"""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = Path(tmp_dir) / "test.db"
        settings = load_settings()
        settings.config_path = str(Path(tmp_dir) / "config.yaml")
        settings.database.url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
        reset_db_engine()
        engine = get_engine(settings.database.url)
        await init_db(settings.database.url)
        await ensure_default_admin(settings)

        from app.core.observability import metrics
        from app.services.state_machine import (
            StateMachine,
            StateMachineService,
            Transition,
        )

        app = create_app(settings, plugin_manager=None)
        sm_service = StateMachineService()
        machine = StateMachine("order_status")
        machine.add(Transition("pending", "paid"))
        sm_service.register(machine)
        app.state.services["state_machine"] = sm_service
        metrics.inc("commands_total", 5)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/login",
                data={"username": "admin", "password": "admin"},
                follow_redirects=False,
            )

            page = await client.get("/state-machines")
            assert page.status_code == 200
            assert "pending" in page.text and "paid" in page.text
            assert "machine-graph" in page.text
            assert "order_status" in page.text
            match = re.search(
                r'name="csrf_token" value="([^"]+)"', page.text
            )
            assert match
            response = await client.post(
                "/state-machines/order_status/delete",
                data={"csrf_token": match.group(1)},
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert sm_service.machines == {}

            status = await client.get("/api/v1/status")
            assert status.status_code == 200
            assert status.json()["metrics"]["commands_total"] == 5
            assert "thread_count" in status.json()["metrics"]
            monitor = await client.get("/monitor")
            assert "线程数" in monitor.text
            assert "进程数" in monitor.text
            assert "监控阈值" in monitor.text
            assert "cpu_threshold" in monitor.text
            match = re.search(
                r'name="csrf_token" value="([^"]+)"', monitor.text
            )
            assert match
            response = await client.post(
                "/monitor/thresholds",
                data={
                    "csrf_token": match.group(1),
                    "cpu_threshold": "90",
                    "memory_threshold": "95",
                },
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert settings.web.cpu_threshold == 90
            assert settings.web.memory_threshold == 95

            from app.db.models import MetricsSample

            async with session_factory()() as session:
                session.add(
                    MetricsSample(
                        cpu_percent=12.5,
                        memory_percent=34.2,
                        active_tasks=2,
                        threads=8,
                        processes=3,
                    )
                )
                await session.commit()
            history = await client.get(
                "/api/v1/metrics/history?hours=24"
            )
            assert history.status_code == 200
            points = history.json()["points"]
            assert any(
                point["cpu"] == 12.5 and point["memory"] == 34.2
                for point in points
            )
            monitor = await client.get("/monitor")
            assert "历史趋势" in monitor.text
            assert "history-chart" in monitor.text
            assert "history-export-btn" in monitor.text
            assert "history-stats" in monitor.text
            assert "峰值时间" in monitor.text
            export_response = await client.get(
                "/monitor/history/export?hours=24"
            )
            assert export_response.status_code == 200
            assert export_response.headers["content-type"].startswith(
                "text/csv"
            )
            assert "12.5" in export_response.text
            assert "34.2" in export_response.text

        await engine.dispose()
        reset_db_engine()


@pytest.mark.asyncio
async def test_web_stats_user_filter() -> None:
    """命令统计页支持按 QQ 用户筛选（用户页命令数跳转）。"""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = Path(tmp_dir) / "test.db"
        settings = load_settings()
        settings.config_path = str(Path(tmp_dir) / "config.yaml")
        settings.database.url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
        reset_db_engine()
        engine = get_engine(settings.database.url)
        await init_db(settings.database.url)
        await ensure_default_admin(settings)

        from app.db.models import CommandStat, User

        async with session_factory()() as session:
            session.add(
                CommandStat(
                    user_id="100", command_name="ping", success=True
                )
            )
            session.add(
                CommandStat(
                    user_id="200", command_name="ping", success=True
                )
            )
            session.add(User(user_id="100", command_count=1))
            await session.commit()

        app = create_app(settings, plugin_manager=None)
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            await client.post(
                "/login",
                data={"username": "admin", "password": "admin"},
                follow_redirects=False,
            )
            page = await client.get("/stats?user=100")
            assert page.status_code == 200
            assert "正在查看 QQ" in page.text
            assert '<span class="mono">100</span>' in page.text
            assert 'href="/commands?q=ping"' in page.text
            page_all = await client.get("/stats")
            assert "正在查看 QQ" not in page_all.text
            scopes_page = await client.get("/scopes")
            assert scopes_page.status_code == 200
            assert "功能开关矩阵" in scopes_page.text

        await engine.dispose()
        reset_db_engine()


@pytest.mark.asyncio
async def test_web_executions_unified_view() -> None:
    """统一执行历史：任务运行与流程运行合并展示。"""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = Path(tmp_dir) / "test.db"
        settings = load_settings()
        settings.config_path = str(Path(tmp_dir) / "config.yaml")
        settings.database.url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
        reset_db_engine()
        engine = get_engine(settings.database.url)
        await init_db(settings.database.url)
        await ensure_default_admin(settings)

        from app.db.models import Task, TaskRun, WorkflowRun

        async with session_factory()() as session:
            session.add(TaskRun(task_id="t1", status="succeeded"))
            session.add(
                WorkflowRun(
                    workflow_id=1,
                    status="failed",
                    result={"error": "boom"},
                )
            )
            session.add(
                Task(
                    task_id="t_disabled",
                    name="disabled-task",
                    type="interval",
                    interval_seconds=60,
                    params={"auto_disabled": "2026-08-01T00:00:00"},
                    enabled=False,
                )
            )
            session.add(
                TaskRun(task_id="t_disabled", status="failed")
            )
            await session.commit()

        app = create_app(settings, plugin_manager=None)
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            await client.post(
                "/login",
                data={"username": "admin", "password": "admin"},
                follow_redirects=False,
            )
            page = await client.get("/executions")
            assert page.status_code == 200
            assert "执行历史" in page.text
            assert "t1" in page.text
            assert "boom" in page.text
            assert 'href="/workflows/runs/' in page.text
            assert 'action="/workflows/1/run"' in page.text
            assert "自动停用" in page.text
            filtered = await client.get(
                "/executions?source=workflow&status=failed"
            )
            assert filtered.status_code == 200
            assert "t1" not in filtered.text
            export = await client.get(
                "/executions/export?source=task&status=succeeded"
            )
            assert export.status_code == 200
            assert export.headers["content-type"].startswith("text/csv")
            assert "t1" in export.text

        await engine.dispose()
        reset_db_engine()


@pytest.mark.asyncio
async def test_web_login_lockout() -> None:
    """连续失败达到阈值后锁定登录，锁定期间正确密码也被拒绝。"""
    from app.web.routers.auth import clear_login_states

    clear_login_states()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = Path(tmp_dir) / "test.db"
        settings = load_settings()
        settings.config_path = str(Path(tmp_dir) / "config.yaml")
        settings.database.url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
        settings.security.max_login_attempts = 3
        settings.security.login_lock_seconds = 1
        settings.security.login_failure_delay_seconds = 0
        reset_db_engine()
        engine = get_engine(settings.database.url)
        await init_db(settings.database.url)
        await ensure_default_admin(settings)

        app = create_app(settings, plugin_manager=None)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            for _ in range(3):
                response = await client.post(
                    "/login",
                    data={"username": "admin", "password": "wrong"},
                    follow_redirects=False,
                )
                assert response.status_code == 303
                assert response.headers["location"] == "/login?error=1"

            # 锁定期间：即使密码正确也被拒绝，并给出锁定提示
            response = await client.post(
                "/login",
                data={"username": "admin", "password": "admin"},
                follow_redirects=False,
            )
            assert response.headers["location"] == "/login?error=2"
            locked_page = await client.get("/login?error=2")
            assert "失败次数过多" in locked_page.text

            # 冷却期结束后可正常登录
            await asyncio.sleep(1.2)
            response = await client.post(
                "/login",
                data={"username": "admin", "password": "admin"},
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert response.cookies.get("ofbot2_session")

        await engine.dispose()
        reset_db_engine()
    clear_login_states()


@pytest.mark.asyncio
async def test_web_config_advanced_fields() -> None:
    """配置页高级字段保存并校验（含非法限流拒绝）。"""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = Path(tmp_dir) / "test.db"
        settings = load_settings()
        settings.config_path = str(Path(tmp_dir) / "config.yaml")
        settings.database.url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
        reset_db_engine()
        engine = get_engine(settings.database.url)
        await init_db(settings.database.url)
        await ensure_default_admin(settings)

        app = create_app(settings, plugin_manager=None)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/login",
                data={"username": "admin", "password": "admin"},
                follow_redirects=False,
            )
            config_page = await client.get("/config")
            match = re.search(
                r'name="csrf_token" value="([^"]+)"', config_page.text
            )
            assert match
            csrf = match.group(1)
            response = await client.post(
                "/config",
                data={
                    "csrf_token": csrf,
                    "command_start": "/",
                    "command_sep": ";",
                    "log_level": "INFO",
                    "nickname": "Bot",
                    "superusers": "100",
                    "log_retention_days": "20",
                    "log_max_files": "80",
                    "session_ttl_seconds": "7200",
                    "scheduler_timezone": "Asia/Shanghai",
                    "scheduler_max_instances": "2",
                    "scheduler_coalesce": "off",
                    "max_message_length": "1500",
                    "max_arg_length": "400",
                    "default_cooldown_seconds": "2",
                    "rate_limit_default": "30/minute",
                    "sensitive_words": "敏感,词",
                    "audit_retention_days": "60",
                    "login_failure_delay_seconds": "1",
                    "max_login_attempts": "3",
                    "login_lock_seconds": "120",
                    "heartbeat_stale_seconds": "200",
                    "alert_history_retention_days": "15",
                    "alert_min_interval_seconds": "5",
                },
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert settings.basic.log_retention_days == 20
            assert settings.basic.command_sep == [";"]
            assert settings.basic.log_max_files == 80
            assert settings.web.session_ttl_seconds == 7200
            assert settings.scheduler.max_instances == 2
            assert settings.scheduler.coalesce is False
            assert settings.security.max_message_length == 1500
            assert settings.security.max_arg_length == 400
            assert settings.security.default_cooldown_seconds == 2
            assert settings.security.rate_limit_default == "30/minute"
            assert settings.security.sensitive_words == ["敏感", "词"]
            assert settings.security.audit_retention_days == 60
            assert settings.security.login_failure_delay_seconds == 1
            assert settings.security.max_login_attempts == 3
            assert settings.security.login_lock_seconds == 120
            assert settings.security.heartbeat_stale_seconds == 200
            assert settings.web.alert_history_retention_days == 15
            assert settings.web.alert_min_interval_seconds == 5

            # 非法限流格式应拒绝并保持原值
            response = await client.post(
                "/config",
                data={
                    "csrf_token": csrf,
                    "command_start": "/",
                    "log_level": "INFO",
                    "nickname": "Bot",
                    "superusers": "100",
                    "rate_limit_default": "not-a-rate",
                },
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert response.headers["location"] == "/config?error=1"
            assert settings.security.rate_limit_default == "30/minute"

        await engine.dispose()
        reset_db_engine()


@pytest.mark.asyncio
async def test_web_plugin_install_upload() -> None:
    """Web 插件页支持 zip 上传安装（含失败拒绝与提示）。"""
    import io
    import json
    import zipfile

    from app.services.plugin_installer import PluginInstaller

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = Path(tmp_dir) / "test.db"
        plugins_dir = Path(tmp_dir) / "plugins"
        settings = load_settings()
        settings.config_path = str(Path(tmp_dir) / "config.yaml")
        settings.database.url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
        reset_db_engine()
        engine = get_engine(settings.database.url)
        await init_db(settings.database.url)
        await ensure_default_admin(settings)

        app = create_app(settings, plugin_manager=None)
        app.state.services["installer"] = PluginInstaller(plugins_dir)
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            await client.post(
                "/login",
                data={"username": "admin", "password": "admin"},
                follow_redirects=False,
            )
            page = await client.get("/plugins")
            assert "安装插件包" in page.text
            match = re.search(
                r'name="csrf_token" value="([^"]+)"', page.text
            )
            assert match
            csrf = match.group(1)

            # 合法 zip 安装成功
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as zf:
                zf.writestr(
                    "hello/plugin.json",
                    json.dumps(
                        {
                            "name": "hello",
                            "api_version": 1,
                            "version": "1.0.0",
                            "description": "x",
                            "author": "me",
                            "dependencies": {},
                        }
                    ),
                )
                zf.writestr(
                    "hello/__init__.py",
                    "def create_plugin():\n    return None\n",
                )
            response = await client.post(
                "/plugins/install",
                data={"csrf_token": csrf},
                files={
                    "file": ("hello.zip", buffer.getvalue(), "application/zip")
                },
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert (plugins_dir / "hello").exists()

            # 不合法 zip（api_version 不支持）被拒绝且给出明确提示
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as zf:
                zf.writestr(
                    "bad/plugin.json",
                    json.dumps(
                        {
                            "name": "bad",
                            "api_version": 99,
                            "version": "1.0.0",
                        }
                    ),
                )
            response = await client.post(
                "/plugins/install",
                data={"csrf_token": csrf},
                files={
                    "file": ("bad.zip", buffer.getvalue(), "application/zip")
                },
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert response.headers["location"].endswith("error=2")
            assert not (plugins_dir / "bad").exists()
            error_page = await client.get("/plugins?error=2")
            assert "安装失败" in error_page.text

        await engine.dispose()
        reset_db_engine()


@pytest.mark.asyncio
async def test_web_plugin_load_error_surfaced() -> None:
    """插件加载失败时，操作反馈展示具体错误信息。"""
    import json
    from urllib.parse import unquote

    from app.adapters.base import BotClient
    from app.core.cache import TTLCache
    from app.core.commands import CommandRegistry
    from app.core.permissions import PermissionManager
    from app.core.plugin import PluginManager
    from app.core.scheduler import SchedulerService
    from app.core.subscriptions import EventSubscriptionRegistry

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = Path(tmp_dir) / "test.db"
        plugins_dir = Path(tmp_dir) / "plugins"
        broken_dir = plugins_dir / "broken"
        broken_dir.mkdir(parents=True)
        (broken_dir / "plugin.json").write_text(
            json.dumps(
                {
                    "name": "broken",
                    "api_version": 1,
                    "version": "1.0.0",
                    "description": "broken",
                    "author": "me",
                    "entry": "missing_entry",
                }
            ),
            encoding="utf-8",
        )
        (broken_dir / "__init__.py").write_text(
            "# no create_plugin factory\n", encoding="utf-8"
        )

        settings = load_settings()
        settings.config_path = str(Path(tmp_dir) / "config.yaml")
        settings.database.url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
        reset_db_engine()
        engine = get_engine(settings.database.url)
        await init_db(settings.database.url)
        await ensure_default_admin(settings)

        manager = PluginManager(
            plugins_dir,
            commands=CommandRegistry(),
            db=None,
            scheduler=SchedulerService(),
            cache=TTLCache(),
            bot=BotClient(),
            permissions=PermissionManager(),
            services={},
            subscriptions=EventSubscriptionRegistry(),
        )
        app = create_app(settings, plugin_manager=manager)
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            await client.post(
                "/login",
                data={"username": "admin", "password": "admin"},
                follow_redirects=False,
            )
            page = await client.get("/plugins")
            match = re.search(
                r'name="csrf_token" value="([^"]+)"', page.text
            )
            assert match
            response = await client.post(
                "/plugins/broken/load",
                data={"csrf_token": match.group(1)},
                follow_redirects=False,
            )
            assert response.status_code == 303
            location = response.headers["location"]
            assert "error=" in location
            assert "加载失败" in unquote(location)

            # 错误信息在插件页展示（URL 解码后）
            error_page = await client.get(
                "/plugins" + location[location.index("?"):]
            )
            assert "加载失败" in error_page.text
            assert "missing_entry" in error_page.text

            # 失败状态已持久化：插件列表显示「错误」徽标与原因
            plugins_page = await client.get("/plugins")
            assert plugins_page.status_code == 200
            assert "missing_entry" in plugins_page.text
            assert ">错误<" in plugins_page.text

        await engine.dispose()
        reset_db_engine()


@pytest.mark.asyncio
async def test_web_task_run_disabled_rejected() -> None:
    """对禁用任务点「立即运行/重试」应明确提示，而非静默跳过。"""
    from urllib.parse import unquote

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = Path(tmp_dir) / "test.db"
        settings = load_settings()
        settings.config_path = str(Path(tmp_dir) / "config.yaml")
        settings.database.url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
        reset_db_engine()
        engine = get_engine(settings.database.url)
        await init_db(settings.database.url)
        await ensure_default_admin(settings)

        from app.db.models import Task

        async with session_factory()() as session:
            session.add(
                Task(
                    task_id="disabled_task",
                    name="disabled",
                    type="interval",
                    interval_seconds=60,
                    params={"group_id": "1", "message": "x"},
                    enabled=False,
                )
            )
            await session.commit()

        app = create_app(settings, plugin_manager=None)
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            await client.post(
                "/login",
                data={"username": "admin", "password": "admin"},
                follow_redirects=False,
            )
            page = await client.get("/tasks")
            match = re.search(
                r'name="csrf_token" value="([^"]+)"', page.text
            )
            assert match
            response = await client.post(
                "/tasks/disabled_task/run",
                data={"csrf_token": match.group(1)},
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert "已禁用" in unquote(response.headers["location"])

        await engine.dispose()
        reset_db_engine()


def test_web_webhook_history_replay() -> None:
    """Webhook 历史记录可一键重放（真实载荷再次触发）。"""
    import asyncio
    from urllib.parse import unquote

    async def run() -> None:
        from app.db.models import WebhookEvent
        from app.services.webhook import WebhookService

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
            db_path = Path(tmp_dir) / "test.db"
            settings = load_settings()
            settings.config_path = str(Path(tmp_dir) / "config.yaml")
            settings.database.url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
            reset_db_engine()
            engine = get_engine(settings.database.url)
            await init_db(settings.database.url)
            await ensure_default_admin(settings)

            service = WebhookService()
            service.register("wh1", {"event": "deploy"})
            async with session_factory()() as session:
                session.add(
                    WebhookEvent(
                        webhook_name="wh1",
                        payload={"event": "deploy", "env": "prod"},
                    )
                )
                session.add(
                    WebhookEvent(
                        webhook_name="wh1",
                        payload={"event": "other"},
                    )
                )
                await session.commit()

            app = create_app(settings, plugin_manager=None)
            app.state.services["webhook"] = service
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                await client.post(
                    "/login",
                    data={"username": "admin", "password": "admin"},
                    follow_redirects=False,
                )
                page = await client.get("/webhooks/wh1/history")
                assert "重放" in page.text
                match = re.search(
                    r'name="csrf_token" value="([^"]+)"', page.text
                )
                assert match
                csrf = match.group(1)
                history_before = len(service.history.get("wh1", []))

                response = await client.post(
                    "/webhooks/wh1/history/1/replay",
                    data={"csrf_token": csrf},
                    follow_redirects=False,
                )
                assert response.status_code == 303
                assert "重放" in unquote(response.headers["location"])
                assert "触发流程" in unquote(response.headers["location"])
                assert len(service.history.get("wh1", [])) == history_before + 1
                assert service.last_triggered.get("wh1")

                response = await client.post(
                    "/webhooks/wh1/history/2/replay",
                    data={"csrf_token": csrf},
                    follow_redirects=False,
                )
                assert "未触发流程" in unquote(
                    response.headers["location"]
                )

            await engine.dispose()
            reset_db_engine()
            from app.core.bus import get_bus, reset_bus

            try:
                await get_bus().stop(clear=True)
            except Exception:
                pass
            reset_bus()

    asyncio.run(run())


@pytest.mark.asyncio
async def test_web_account_error_surfaced() -> None:
    """密码修改失败时账户页展示具体原因。"""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = Path(tmp_dir) / "test.db"
        settings = load_settings()
        settings.config_path = str(Path(tmp_dir) / "config.yaml")
        settings.database.url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
        reset_db_engine()
        engine = get_engine(settings.database.url)
        await init_db(settings.database.url)
        await ensure_default_admin(settings)

        app = create_app(settings, plugin_manager=None)
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            await client.post(
                "/login",
                data={"username": "admin", "password": "admin"},
                follow_redirects=False,
            )
            page = await client.get("/account")
            match = re.search(
                r'name="csrf_token" value="([^"]+)"', page.text
            )
            assert match
            csrf = match.group(1)

            # 当前密码错误 → error=2
            response = await client.post(
                "/account",
                data={
                    "csrf_token": csrf,
                    "current_password": "wrong",
                    "new_password": "newpass123",
                },
                follow_redirects=False,
            )
            assert response.headers["location"] == "/account?error=2"
            assert "当前密码不正确" in (await client.get("/account?error=2")).text

            # 新密码过短 → error=1
            response = await client.post(
                "/account",
                data={
                    "csrf_token": csrf,
                    "current_password": "admin",
                    "new_password": "123",
                },
                follow_redirects=False,
            )
            assert response.headers["location"] == "/account?error=1"
            assert "新密码至少 6 位" in (await client.get("/account?error=1")).text

        await engine.dispose()
        reset_db_engine()


@pytest.mark.asyncio
async def test_web_files_bulk_download() -> None:
    """文件中心支持批量打包下载。"""
    import io
    import zipfile
    from urllib.parse import unquote

    from app.services.files import FileService

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = Path(tmp_dir) / "test.db"
        settings = load_settings()
        settings.config_path = str(Path(tmp_dir) / "config.yaml")
        settings.database.url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
        reset_db_engine()
        engine = get_engine(settings.database.url)
        await init_db(settings.database.url)
        await ensure_default_admin(settings)

        files_service = FileService(Path(tmp_dir) / "files")
        file_a = files_service.save_bytes(b"hello-a", suffix=".txt")
        file_b = files_service.save_bytes(b"hello-b", suffix=".txt")
        names = [
            file_a.relative_to(files_service.base_dir).as_posix(),
            file_b.relative_to(files_service.base_dir).as_posix(),
        ]

        app = create_app(settings, plugin_manager=None)
        app.state.services["files"] = files_service
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            await client.post(
                "/login",
                data={"username": "admin", "password": "admin"},
                follow_redirects=False,
            )
            page = await client.get("/files")
            assert "批量下载" in page.text
            match = re.search(
                r'name="csrf_token" value="([^"]+)"', page.text
            )
            assert match
            csrf = match.group(1)

            response = await client.post(
                "/files/bulk-download",
                data={"csrf_token": csrf, "names": names},
                follow_redirects=False,
            )
            assert response.status_code == 200
            assert response.headers["content-type"] == "application/zip"
            archive = zipfile.ZipFile(io.BytesIO(response.content))
            assert set(archive.namelist()) == set(names)

            # 未选择文件时给出提示
            response = await client.post(
                "/files/bulk-download",
                data={"csrf_token": csrf},
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert "请选择" in unquote(response.headers["location"])

        await engine.dispose()
        reset_db_engine()


@pytest.mark.asyncio
async def test_web_alert_test_notify() -> None:
    """告警规则「测试」按钮调用 notifier 发送测试通知。"""
    from types import SimpleNamespace

    class FakeAlerts:
        def __init__(self) -> None:
            self.rules = [
                SimpleNamespace(
                    name="r1", event="task.failed", target_group="1"
                )
            ]
            self.notifier = None
            self.sent: list[tuple[str, str]] = []

        async def _notify(self, rule: object, detail: str) -> None:
            self.sent.append((rule.name, detail))

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = Path(tmp_dir) / "test.db"
        settings = load_settings()
        settings.config_path = str(Path(tmp_dir) / "config.yaml")
        settings.database.url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
        reset_db_engine()
        engine = get_engine(settings.database.url)
        await init_db(settings.database.url)
        await ensure_default_admin(settings)

        app = create_app(settings, plugin_manager=None)
        fake = FakeAlerts()
        fake.notifier = fake._notify
        app.state.services["alerts"] = fake
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            await client.post(
                "/login",
                data={"username": "admin", "password": "admin"},
                follow_redirects=False,
            )
            page = await client.get("/alerts")
            assert "测试" in page.text
            match = re.search(
                r'name="csrf_token" value="([^"]+)"', page.text
            )
            assert match
            csrf = match.group(1)

            response = await client.post(
                "/alerts/r1/test",
                data={"csrf_token": csrf},
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert fake.sent and fake.sent[0][0] == "r1"
            assert "测试通知" in fake.sent[0][1]

            # 未配置通知通道时给出明确错误
            app.state.services["alerts"] = FakeAlerts()
            response = await client.post(
                "/alerts/r1/test",
                data={"csrf_token": csrf},
                follow_redirects=False,
            )
            assert "error=" in response.headers["location"]

        await engine.dispose()
        reset_db_engine()


@pytest.mark.asyncio
async def test_web_self_heal_center() -> None:
    """自愈中心聚合：当前停用实体、事件与统计。"""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = Path(tmp_dir) / "test.db"
        settings = load_settings()
        settings.config_path = str(Path(tmp_dir) / "config.yaml")
        settings.database.url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
        reset_db_engine()
        engine = get_engine(settings.database.url)
        await init_db(settings.database.url)
        await ensure_default_admin(settings)

        from app.db.models import AlertEvent, Task, Workflow

        async with session_factory()() as session:
            session.add(
                Task(
                    task_id="heal_task",
                    name="heal",
                    type="interval",
                    interval_seconds=60,
                    params={
                        "auto_disabled": "2026-08-01T00:00:00",
                        "auto_disabled_reason": "连续失败",
                    },
                    enabled=False,
                )
            )
            session.add(
                Task(
                    task_id="heal_done",
                    name="heal-done",
                    type="interval",
                    interval_seconds=60,
                    params={
                        "self_heal_cycles": [
                            {
                                "disabled": "2026-08-01T00:00:00",
                                "reenabled": "2026-08-02T00:00:00",
                            }
                        ]
                    },
                    enabled=True,
                )
            )
            session.add(
                Workflow(
                    name="heal_flow",
                    definition={
                        "auto_disabled": {
                            "reason": "连续失败",
                            "at": "2026-08-01T00:00:00",
                        }
                    },
                    enabled=False,
                )
            )
            session.add(
                AlertEvent(
                    rule_name="r",
                    event="task.auto_disabled",
                    detail="heal（heal_task）",
                )
            )
            await session.commit()

        app = create_app(settings, plugin_manager=None)
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            await client.post(
                "/login",
                data={"username": "admin", "password": "admin"},
                follow_redirects=False,
            )
            page = await client.get("/self-heal")
            assert page.status_code == 200
            assert "自愈中心" in page.text
            assert "heal_task" in page.text
            assert "heal_flow" in page.text
            assert "恢复率" in page.text
            assert "task.auto_disabled" in page.text
            assert "平均停用时长" in page.text
            assert "1 天 0 小时" in page.text

        await engine.dispose()
        reset_db_engine()


@pytest.mark.asyncio
async def test_web_record_state_machine_transition() -> None:
    """记录中心与状态机互联：记录行内按状态机流转状态。"""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = Path(tmp_dir) / "test.db"
        settings = load_settings()
        settings.config_path = str(Path(tmp_dir) / "config.yaml")
        settings.database.url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
        reset_db_engine()
        engine = get_engine(settings.database.url)
        await init_db(settings.database.url)
        await ensure_default_admin(settings)

        from app.services.records import (
            FieldSchema,
            RecordService,
            RecordTypeSchema,
            SchemaRegistry,
        )
        from app.services.state_machine import (
            StateMachine,
            StateMachineService,
            Transition,
        )

        app = create_app(settings, plugin_manager=None)
        schemas = SchemaRegistry()
        schemas.register(
            RecordTypeSchema("order", [FieldSchema("title", "string", True)])
        )
        records = RecordService(schemas)
        sm = StateMachineService()
        machine = StateMachine("order", initial="pending")
        machine.add(Transition("pending", "done"))
        sm.register(machine)
        app.state.services["schema_registry"] = schemas
        app.state.services["records"] = records
        app.state.services["state_machine"] = sm

        try:
            await get_bus().stop(clear=True)
        except Exception:
            pass
        reset_bus()
        record = await records.create("order", {"title": "hello"})
        await records.set_status(record.id, "pending")

        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            await client.post(
                "/login",
                data={"username": "admin", "password": "admin"},
                follow_redirects=False,
            )
            page = await client.get("/records")
            assert page.status_code == 200
            assert "流转" in page.text
            assert 'name="target"' in page.text
            match = re.search(
                r'name="csrf_token" value="([^"]+)"', page.text
            )
            assert match
            response = await client.post(
                f"/records/{record.id}/transition",
                data={"csrf_token": match.group(1), "target": "done"},
                follow_redirects=False,
            )
            assert response.status_code == 303
            updated = await records.get(record.id)
            assert updated is not None and updated.status == "done"

            response = await client.post(
                f"/records/{record.id}/transition",
                data={"csrf_token": match.group(1), "target": "done"},
                follow_redirects=False,
            )
            assert response.status_code == 303
            still = await records.get(record.id)
            assert still is not None and still.status == "done"

        await engine.dispose()
        reset_db_engine()
        try:
            await get_bus().stop(clear=True)
        except Exception:
            pass
        reset_bus()


@pytest.mark.asyncio
async def test_web_backups_and_webhook() -> None:
    """备份下载/删除与 Webhook 接收路由。"""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = Path(tmp_dir) / "test.db"
        settings = load_settings()
        settings.config_path = str(Path(tmp_dir) / "config.yaml")
        settings.database.url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
        reset_db_engine()
        engine = get_engine(settings.database.url)
        await init_db(settings.database.url)
        await ensure_default_admin(settings)

        from app.services.backup import BackupService
        from app.services.webhook import WebhookService

        app = create_app(settings, plugin_manager=None)
        backup_service = BackupService(Path(tmp_dir) / "backups")
        webhook_service = WebhookService()
        webhook_service.register("test_hook")
        app.state.services["backup"] = backup_service
        app.state.services["webhook"] = webhook_service

        source = Path(tmp_dir) / "config.yaml"
        source.write_text("dummy: 1\n", encoding="utf-8")
        backup_service.create_backup(source)
        backup_info = backup_service.list_backups()[0]
        backup_name = backup_info["name"]
        assert "size" in backup_info and "files" in backup_info
        source2 = Path(tmp_dir) / "config2.yaml"
        source2.write_text("other: 2\n", encoding="utf-8")
        backup_service.create_backup(source2)
        backups = backup_service.list_backups()
        diff = backup_service.compare(backups[0]["name"], backups[1]["name"])
        assert diff["only_in_a"] or diff["only_in_b"] or diff["changed"]
        assert "size_deltas" in diff

        restore_dir = Path(tmp_dir) / "restore"
        restore_dir.mkdir()
        results = backup_service.restore(
            backup_name, {"config.yaml": restore_dir / "config.yaml"}
        )
        assert results["config.yaml"] == "已恢复"
        assert (restore_dir / "config.yaml").read_text(encoding="utf-8") == "dummy: 1\n"
        rollback = backup_service.create_backup(source)
        backup_names = [item["name"] for item in backup_service.list_backups()]
        assert rollback.name in backup_names

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/login",
                data={"username": "admin", "password": "admin"},
                follow_redirects=False,
            )

            response = await client.get(f"/backups/{backup_name}/download")
            assert response.status_code == 200
            assert response.headers["content-type"] == "application/zip"
            response = await client.get(
                f"/backups/{backup_name}/file?path=config.yaml"
            )
            assert response.status_code == 200
            response = await client.get(
                f"/backups/{backup_name}/file?path=../../etc/passwd"
            )
            assert response.status_code == 404

            page = await client.get("/backups")
            assert "重启服务指引" in page.text
            assert "恢复指引" in page.text
            match = re.search(
                r'name="csrf_token" value="([^"]+)"', page.text
            )
            assert match
            response = await client.post(
                f"/backups/{backup_name}/delete",
                data={"csrf_token": match.group(1)},
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert backup_name not in [
                item["name"] for item in backup_service.list_backups()
            ]

            response = await client.post(
                "/backups/auto-toggle",
                data={"csrf_token": match.group(1)},
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert settings.scheduler.auto_backup_enabled is True
            response = await client.post(
                "/backups/auto-toggle",
                data={"csrf_token": match.group(1)},
                follow_redirects=False,
            )
            assert settings.scheduler.auto_backup_enabled is False
            response = await client.post(
                "/backups/auto-interval",
                data={"csrf_token": match.group(1), "hours": "12"},
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert settings.scheduler.backup_interval_hours == 12

            response = await client.post(
                "/webhook/test_hook",
                json={"test": True},
            )
            assert response.status_code == 200
            assert response.json() == {"success": True}

            webhook_service.register("filtered_hook", {"event": "ci.finished"})
            assert webhook_service.matches("filtered_hook", {"event": "ci.finished"})
            assert not webhook_service.matches("filtered_hook", {"event": "other"})
            response = await client.post(
                "/webhook/filtered_hook",
                json={"event": "ci.finished", "data": 1},
            )
            assert response.status_code == 200
            assert webhook_service.last_triggered.get("filtered_hook")
            assert webhook_service.history.get("filtered_hook")
            assert webhook_service.history["filtered_hook"][0]["payload"] == {
                "event": "ci.finished",
                "data": 1,
            }
            from app.db.models import WebhookEvent

            async with session_factory()() as session:
                from sqlalchemy import func, select

                event_count = await session.scalar(
                    select(func.count()).select_from(WebhookEvent)
                )
                assert event_count and event_count >= 2
            response = await client.get(
                "/webhooks/filtered_hook/history/export"
            )
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("application/json")
            response = await client.get(
                "/webhooks/filtered_hook/history/export?start=2099-01-01"
            )
            assert response.status_code == 404
            response = await client.get(
                "/webhooks/filtered_hook/history/export?start=2000-01-01"
            )
            assert response.status_code == 200
            assert "2000-01-01" in response.headers["content-disposition"]
            response = await client.get(
                "/webhooks/filtered_hook/history/export?page=1&start=2000-01-01"
            )
            assert response.status_code == 200
            assert "_p1" in response.headers["content-disposition"]
            response = await client.get("/webhooks/filtered_hook/history")
            assert response.status_code == 200
            assert "ci.finished" in response.text
            assert "history-page-go" in response.text
            page = await client.get(
                "/webhooks/filtered_hook/history?page_size=50"
            )
            assert page.status_code == 200
            assert 'value="50" selected' in page.text
            try:
                await get_bus().stop(clear=True)
            except Exception:
                pass
            reset_bus()
            response = await client.post(
                "/webhooks/filtered_hook/history/bulk-delete",
                data={
                    "csrf_token": match.group(1),
                    "ids": ["1"],
                },
                follow_redirects=False,
            )
            assert response.status_code == 303
            response = await client.post(
                "/webhooks/filtered_hook/history/clear",
                data={"csrf_token": match.group(1), "start": "2000-01-01"},
                follow_redirects=False,
            )
            assert response.status_code == 303
            async with session_factory()() as session:
                from sqlalchemy import func

                count = await session.scalar(
                    select(func.count())
                    .select_from(WebhookEvent)
                    .where(WebhookEvent.webhook_name == "filtered_hook")
                )
                assert count == 0
            webhook_service.register("range_hook")
            await webhook_service.handle("range_hook", {"n": 1})
            await webhook_service.handle("range_hook", {"n": 2})
            async with session_factory()() as session:
                count = await session.scalar(
                    select(func.count())
                    .select_from(WebhookEvent)
                    .where(WebhookEvent.webhook_name == "range_hook")
                )
                assert count == 2
            response = await client.post(
                "/webhooks/range_hook/history/bulk-delete",
                data={
                    "csrf_token": match.group(1),
                    "scope": "range",
                    "start": "2000-01-01",
                    "end": "2099-12-31",
                },
                follow_redirects=False,
            )
            assert response.status_code == 303
            async with session_factory()() as session:
                count = await session.scalar(
                    select(func.count())
                    .select_from(WebhookEvent)
                    .where(WebhookEvent.webhook_name == "range_hook")
                )
                assert count == 0
            page = await client.get("/webhooks")
            assert page.status_code == 200
            assert "webhook-test-preset" in page.text
            assert "whHistory" in page.text

            small = WebhookService(retention=2)
            small.register("small_hook")
            for i in range(3):
                await small.handle("small_hook", {"n": i})
            async with session_factory()() as session:
                count = await session.scalar(
                    select(func.count())
                    .select_from(WebhookEvent)
                    .where(WebhookEvent.webhook_name == "small_hook")
                )
                assert count == 2

        await engine.dispose()
        reset_db_engine()
        try:
            await get_bus().stop(clear=True)
        except Exception:
            pass
        reset_bus()


@pytest.mark.asyncio
async def test_web_exports_tasks_workflow_edit() -> None:
    """导出创建、任务立即运行、流程编辑与记录类型持久化路由。"""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = Path(tmp_dir) / "test.db"
        settings = load_settings()
        settings.config_path = str(Path(tmp_dir) / "config.yaml")
        settings.database.url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
        reset_db_engine()
        engine = get_engine(settings.database.url)
        await init_db(settings.database.url)
        await ensure_default_admin(settings)

        from app.db.models import Task
        from app.services.export import ExportService
        from app.services.records import (
            FieldSchema,
            RecordService,
            RecordTypeSchema,
            SchemaRegistry,
        )
        from app.services.workflow import WorkflowEngine

        app = create_app(settings, plugin_manager=None)
        schemas = SchemaRegistry()
        schemas.register(
            RecordTypeSchema("order", [FieldSchema("title", "string", True)])
        )
        records = RecordService(schemas)
        export_service = ExportService(Path(tmp_dir) / "exports")
        workflow_engine = WorkflowEngine()
        app.state.services["schema_registry"] = schemas
        app.state.services["records"] = records
        app.state.services["export"] = export_service
        app.state.services["workflow"] = workflow_engine

        from app.db.models import Record, TaskRun

        async with session_factory()() as session:
            session.add(Record(record_type="order", data={"title": "hello"}))
            await session.commit()
        async with session_factory()() as session:
            task = Task(
                task_id="t1",
                name="smoke",
                type="interval",
                interval_seconds=60,
                params={"group_id": "1", "message": "hi"},
                enabled=True,
            )
            session.add(task)
            await session.commit()
        workflow = await workflow_engine.create(
            "flow1", {"steps": [{"action": "echo", "params": {"text": "hi"}}]}
        )

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/login",
                data={"username": "admin", "password": "admin"},
                follow_redirects=False,
            )

            exports_page = await client.get("/exports")
            match = re.search(
                r'name="csrf_token" value="([^"]+)"', exports_page.text
            )
            assert match
            csrf = match.group(1)

            response = await client.post(
                "/exports/create",
                data={
                    "csrf_token": csrf,
                    "record_type": "order",
                    "fmt": "csv",
                },
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert list((Path(tmp_dir) / "exports").glob("records_order_*.csv"))

            jobs_response = await client.get("/exports/jobs")
            assert jobs_response.status_code == 200
            jobs = jobs_response.json()["jobs"]
            assert jobs and jobs[0]["status"] == "done"
            assert jobs[0]["actor"] == "admin"
            filtered = await client.get("/exports/jobs?actor=admin")
            assert filtered.status_code == 200
            assert all(j["actor"] == "admin" for j in filtered.json()["jobs"])
            filtered = await client.get("/exports/jobs?actor=nobody")
            assert filtered.json()["jobs"] == []
            exports_page = await client.get("/exports")
            assert "jobs-actor-filter" in exports_page.text
            assert (
                'href="/records?record_type=order"' in exports_page.text
            )
            from app.db.models import ExportJob

            async with session_factory()() as session:
                from sqlalchemy import func, select

                export_count = await session.scalar(
                    select(func.count()).select_from(ExportJob)
                )
                assert export_count and export_count >= 1

            retry_job = {
                "id": "retry1",
                "record_type": "order",
                "fmt": "csv",
                "status": "failed",
                "message": "模拟失败",
                "total": 0,
                "done": 0,
                "filename": None,
                "created_at": "",
                "actor": "admin",
                "attempts": 0,
                "retries": 0,
            }
            app.state.export_jobs["retry1"] = retry_job
            app.state.export_jobs["retry_audit"] = {
                "id": "retry_audit",
                "record_type": "audit",
                "fmt": "csv",
                "status": "failed",
                "message": "模拟审计失败",
                "total": 0,
                "done": 0,
                "filename": None,
                "created_at": "",
                "actor": "admin",
                "attempts": 0,
                "retries": 0,
            }
            response = await client.post(
                "/exports/jobs/retry-failed",
                data={"csrf_token": csrf},
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert app.state.export_jobs["retry1"]["status"] == "done"
            assert app.state.export_jobs["retry1"]["filename"]
            assert app.state.export_jobs["retry_audit"]["status"] == "failed"

            from app.web.export_jobs import _persist_export_job

            db_only_job = {
                "id": "db_retry",
                "record_type": "order",
                "fmt": "csv",
                "status": "failed",
                "message": "仅存在于数据库",
                "total": 0,
                "done": 0,
                "filename": None,
                "created_at": "",
                "actor": "admin",
                "attempts": 0,
                "retries": 0,
            }
            await _persist_export_job(db_only_job)
            app.state.export_jobs.pop("db_retry", None)
            response = await client.post(
                "/exports/jobs/db_retry/retry",
                data={"csrf_token": csrf},
                follow_redirects=False,
            )
            assert response.status_code == 303
            async with session_factory()() as session:
                row = await session.scalar(
                    select(ExportJob).where(
                        ExportJob.job_id == "db_retry"
                    )
                )
                assert row is not None and row.status == "done"

            from io import BytesIO
            from zipfile import ZipFile

            export_service.export_csv([{"a": 1}], "bulk_one")
            export_service.export_json([{"b": 2}], "bulk_two")
            files_page = await client.get("/exports")
            assert "exports-select-all" in files_page.text
            response = await client.post(
                "/exports/bulk-download",
                data={
                    "csrf_token": csrf,
                    "names": ["bulk_one.csv", "bulk_two.json"],
                },
                follow_redirects=False,
            )
            assert response.status_code == 200
            assert response.headers["content-type"] == "application/zip"
            archive = ZipFile(BytesIO(response.content))
            archive_names = archive.namelist()
            assert "bulk_one.csv" in archive_names
            assert "bulk_two.json" in archive_names
            response = await client.post(
                "/exports/bulk-download",
                data={"csrf_token": csrf, "all_files": "on"},
                follow_redirects=False,
            )
            assert response.status_code == 200
            response = await client.post(
                "/exports/bulk-delete",
                data={
                    "csrf_token": csrf,
                    "names": ["bulk_one.csv", "bulk_two.json"],
                },
                follow_redirects=False,
            )
            assert response.status_code == 303
            remaining_names = [
                item["name"] for item in export_service.list_files()
            ]
            assert "bulk_one.csv" not in remaining_names
            assert "bulk_two.json" not in remaining_names

            response = await client.post(
                "/tasks/t1/run",
                data={"csrf_token": csrf, "message": "custom"},
                follow_redirects=False,
            )
            assert response.status_code == 303
            export_response = await client.get("/tasks/export")
            assert export_response.status_code == 200
            assert export_response.headers["content-type"].startswith("text/csv")
            assert "t1" in export_response.text
            export_response = await client.get(
                "/tasks/export?task_id=t1&status=succeeded"
            )
            assert export_response.status_code == 200
            assert "t1" in export_response.text
            export_response = await client.get("/tasks/export?start=2000-01-01")
            assert export_response.status_code == 200
            page = await client.get("/tasks?runs_start=2000-01-01")
            assert page.status_code == 200
            async with session_factory()() as session:
                task = await session.get(Task, task.id)
                assert task is not None and task.status == "succeeded", (
                    task.params if task else "task missing"
                )

            response = await client.post(
                "/tasks/t1/edit",
                data={
                    "csrf_token": csrf,
                    "name": "edited_task",
                    "task_type": "interval",
                    "interval_seconds": "120",
                    "group_id": "2",
                    "message": "edited",
                    "params_json": '{"extra": "x"}',
                    "enabled": "on",
                },
                follow_redirects=False,
            )
            assert response.status_code == 303
            async with session_factory()() as session:
                task = await session.get(Task, task.id)
                assert task is not None and task.name == "edited_task"
                assert task.params.get("extra") == "x"
                assert task.interval_seconds == 120

            tasks_page = await client.get("/tasks")
            assert "run-detail-dialog" in tasks_page.text
            assert "task-type-row" in tasks_page.text
            assert "总运行次数" in tasks_page.text
            assert "task-select-all" in tasks_page.text
            assert "tasks-bulk-form" in tasks_page.text
            assert "runs-clear-form" in tasks_page.text

            async with session_factory()() as session:
                session.add(
                    Task(
                        task_id="t2",
                        name="bulk2",
                        type="interval",
                        interval_seconds=30,
                        params={},
                        enabled=True,
                    )
                )
                session.add(
                    Task(
                        task_id="t3",
                        name="bulk3",
                        type="interval",
                        interval_seconds=30,
                        params={},
                        enabled=True,
                    )
                )
                await session.commit()
            response = await client.post(
                "/tasks/bulk",
                data={
                    "csrf_token": csrf,
                    "action": "disable",
                    "ids": ["t2", "t3"],
                },
                follow_redirects=False,
            )
            assert response.status_code == 303
            async with session_factory()() as session:
                t2 = await session.scalar(
                    select(Task).where(Task.task_id == "t2")
                )
                assert t2 is not None and t2.enabled is False
                t3 = await session.scalar(
                    select(Task).where(Task.task_id == "t3")
                )
                assert t3 is not None and t3.enabled is False
            response = await client.post(
                "/tasks/bulk",
                data={
                    "csrf_token": csrf,
                    "action": "delete",
                    "ids": ["t2", "t3"],
                },
                follow_redirects=False,
            )
            assert response.status_code == 303
            async with session_factory()() as session:
                remaining = (
                    await session.scalars(
                        select(Task).where(Task.task_id.in_(["t2", "t3"]))
                    )
                ).all()
                assert remaining == []
            response = await client.post(
                "/tasks/runs/clear",
                data={
                    "csrf_token": csrf,
                    "start": "2000-01-01",
                    "end": "2099-12-31",
                    "status": "succeeded",
                },
                follow_redirects=False,
            )
            assert response.status_code == 303
            async with session_factory()() as session:
                runs_left = (
                    await session.scalars(
                        select(TaskRun).where(TaskRun.task_id == "t1")
                    )
                ).all()
                assert runs_left == []

            response = await client.get(f"/workflows/{workflow.id}/edit")
            assert response.status_code == 200
            assert "编辑流程" in response.text
            assert "wf-undo" in response.text
            assert "告警触发" in response.text
            assert "wf-record-helper" in response.text

            response = await client.post(
                f"/workflows/{workflow.id}/edit",
                data={
                    "csrf_token": csrf,
                    "name": "flow1_edited",
                    "steps_json": '[{"action": "echo", "params": {"text": "x"}}]',
                    "trigger_json": '{"type": "schedule", "cron": "0 8 * * *"}',
                },
                follow_redirects=False,
            )
            assert response.status_code == 303
            updated = await workflow_engine.get(workflow.id)
            assert updated is not None and updated.name == "flow1_edited"
            assert (
                updated.definition.get("trigger", {}).get("type") == "schedule"
            )

            response = await client.post(
                "/records/add",
                data={
                    "csrf_token": csrf,
                    "name": "order2",
                    "fields_json": '[{"name": "qty", "type": "integer"}]',
                },
                follow_redirects=False,
            )
            assert response.status_code == 303
            saved_types = settings.plugin_configs.get("records", {}).get("types", [])
            assert any(t.get("name") == "order2" for t in saved_types)

            response = await client.post(
                "/records/types/order2/delete",
                data={"csrf_token": csrf},
                follow_redirects=False,
            )
            assert response.status_code == 303
            saved_types = settings.plugin_configs.get("records", {}).get("types", [])
            assert not any(t.get("name") == "order2" for t in saved_types)

        await engine.dispose()
        reset_db_engine()
        try:
            await get_bus().stop(clear=True)
        except Exception:
            pass
        reset_bus()
