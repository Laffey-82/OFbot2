from __future__ import annotations

import io
import json
import re
import shutil
import zipfile
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.services.plugin_repo import PluginRepoService


def _plugin_files(name: str = "demo") -> dict[str, bytes]:
    return {
        "plugin.json": json.dumps(
            {
                "name": name,
                "api_version": 1,
                "version": "1.0.0",
                "description": "demo plugin",
                "author": "tester",
                "dependencies": {},
            },
            ensure_ascii=False,
        ).encode("utf-8"),
        "__init__.py": b"from app.core.plugin import Plugin, PluginContext\n\n"
        b"class DemoPlugin(Plugin):\n"
        b"    def setup(self, ctx):\n"
        b"        pass\n\n"
        b"def create_plugin():\n"
        b"    return DemoPlugin()\n",
    }


def _zip_bytes(name: str = "demo") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, content in _plugin_files(name).items():
            archive.writestr(f"{name}/{path}", content)
    return buffer.getvalue()


def _make_local_repo(repo_dir, name: str = "demo", version: str = "1.0.0") -> dict:
    packages = repo_dir / "packages"
    packages.mkdir(parents=True)
    (packages / f"{name}.zip").write_bytes(_zip_bytes(name))
    registry = {
        "format_version": 1,
        "plugins": [
            {
                "id": name,
                "name": name,
                "version": version,
                "description": "demo plugin",
                "author": "tester",
                "category": "general",
                "zip_url": str(packages / f"{name}.zip"),
            }
        ],
    }
    (repo_dir / "registry.json").write_text(
        json.dumps(registry, ensure_ascii=False), encoding="utf-8"
    )
    return registry


@pytest.mark.asyncio
async def test_local_mode_list_and_install(tmp_path) -> None:
    repo_dir = tmp_path / "plugin-repo"
    plugins_dir = tmp_path / "plugins"
    _make_local_repo(repo_dir)
    service = PluginRepoService(
        plugins_dir, repo_dir
    )
    plugins = await service.list_plugins()
    assert len(plugins) == 1
    assert plugins[0].id == "demo"

    installed = await service.install("demo")
    assert installed.name == "demo"
    assert (installed / "plugin.json").exists()

    with pytest.raises(KeyError):
        await service.get_plugin("not_exist")


@pytest.mark.asyncio
async def test_url_mode_list_install_and_cache(tmp_path) -> None:
    repo_dir = tmp_path / "plugin-repo"
    plugins_dir = tmp_path / "plugins"
    calls = {"count": 0}
    zip_data = _zip_bytes("demo")

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if request.url.path.endswith("registry.json"):
            return httpx.Response(
                200,
                json={
                    "format_version": 1,
                    "plugins": [
                        {
                            "id": "demo",
                            "name": "demo",
                            "version": "1.0.0",
                            "description": "demo",
                            "author": "tester",
                            "category": "general",
                            "zip_url": "https://example.com/packages/demo.zip",
                        }
                    ],
                },
            )
        if request.url.path.endswith("demo.zip"):
            return httpx.Response(200, content=zip_data)
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = PluginRepoService(
        plugins_dir,
        repo_dir,
        repo_url="https://example.com/registry.json",
        token="secret",
        client=client,
    )
    plugins = await service.list_plugins()
    assert plugins[0].id == "demo"
    assert calls["count"] == 1
    # 短缓存：第二次不请求网络
    await service.list_plugins()
    assert calls["count"] == 1

    installed = await service.install("demo")
    assert (installed / "plugin.json").exists()
    await client.aclose()


@pytest.mark.asyncio
async def test_url_mode_unauthorized_message(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "nope"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = PluginRepoService(
        tmp_path / "plugins",
        tmp_path / "plugin-repo",
        repo_url="https://example.com/registry.json",
        client=client,
    )
    with pytest.raises(RuntimeError, match="plugin_repo_token"):
        await service.list_plugins()
    await client.aclose()


@pytest.mark.asyncio
async def test_local_mode_fallback_scan_zips(tmp_path) -> None:
    """无 registry.json 时回退扫描 packages/*.zip。"""
    repo_dir = tmp_path / "plugin-repo"
    (repo_dir / "packages").mkdir(parents=True)
    (repo_dir / "packages" / "demo.zip").write_bytes(_zip_bytes("demo"))
    service = PluginRepoService(
        tmp_path / "plugins", repo_dir
    )
    plugins = await service.list_plugins()
    assert plugins[0].id == "demo"


@pytest.mark.asyncio
async def test_web_plugin_market_page_and_install(tmp_path) -> None:
    """Web 插件市场页渲染与一键安装（注入本地仓库服务）。"""
    from app.core.config import load_settings
    from app.db.base import get_engine, init_db, reset_db_engine
    from app.web.app import create_app, ensure_default_admin

    repo_dir = tmp_path / "plugin-repo"
    plugins_dir = tmp_path / "plugins"
    _make_local_repo(repo_dir)

    settings = load_settings()
    settings.config_path = str(tmp_path / "config.yaml")
    settings.database.url = (
        f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}"
    )
    reset_db_engine()
    engine = get_engine(settings.database.url)
    await init_db(settings.database.url)
    await ensure_default_admin(settings)

    app = create_app(settings, plugin_manager=None)
    app.state.plugin_repo_service = PluginRepoService(plugins_dir, repo_dir)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post(
            "/login",
            data={"username": "admin", "password": "admin"},
            follow_redirects=False,
        )
        page = await client.get("/plugins/repo")
        assert page.status_code == 200
        assert "插件市场" in page.text
        assert "demo" in page.text
        match = re.search(
            r'name="csrf_token" value="([^"]+)"', page.text
        )
        assert match
        response = await client.post(
            "/plugins/repo/install",
            data={"csrf_token": match.group(1), "plugin_id": "demo"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert (plugins_dir / "demo" / "plugin.json").exists()

    await engine.dispose()
    reset_db_engine()


@pytest.mark.asyncio
async def test_plugin_repo_seed_plugins_load(tmp_path) -> None:
    """插件仓库内置插件均可被框架加载并注册命令/监听/任务。"""
    from app.adapters.base import BotClient
    from app.core.bus import get_bus, reset_bus
    from app.core.cache import TTLCache
    from app.core.commands import CommandRegistry
    from app.core.permissions import PermissionManager
    from app.core.plugin import PluginManager
    from app.core.scheduler import SchedulerService
    from app.core.subscriptions import EventSubscriptionRegistry
    from app.services.records import RecordService, SchemaRegistry

    repo = Path(__file__).resolve().parents[1] / "plugin-repo" / "plugins"
    plugins_dir = tmp_path / "plugins"
    expected = set()
    for category in sorted(repo.iterdir()):
        for src in sorted(category.iterdir()):
            if not (src / "plugin.json").exists():
                continue
            shutil.copytree(
                src,
                plugins_dir / src.name,
                ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"),
            )
            expected.add(src.name)
    assert expected == {
        "dice",
        "welcome",
        "keyword_reply",
        "schedule_message",
        "signin",
        "todo",
    }
    scheduler = SchedulerService()
    manager = PluginManager(
        plugins_dir,
        commands=CommandRegistry(),
        db=None,
        scheduler=scheduler,
        cache=TTLCache(),
        bot=BotClient(),
        permissions=PermissionManager(),
        services={},
        subscriptions=EventSubscriptionRegistry(),
        records=RecordService(SchemaRegistry()),
    )
    enabled = {name: True for name in expected}
    loaded = manager.load_enabled(
        enabled, {name: {} for name in expected}
    )
    assert {item.name for item in loaded} == expected
    for name in ("roll", "signin", "todo", "签到", "待办"):
        assert name in manager.commands._commands
    for name in list(manager.loaded):
        await manager.unload_plugin(name)
    scheduler.shutdown()
    try:
        await get_bus().stop(clear=True)
    except Exception:
        pass
    reset_bus()


@pytest.mark.asyncio
async def test_plugin_repo_install_replace_and_update_flag(tmp_path) -> None:
    """覆盖更新安装：旧版本归档，市场页标记可更新。"""
    from app.core.config import load_settings
    from app.db.base import get_engine, init_db, reset_db_engine
    from app.web.app import create_app, ensure_default_admin

    repo_dir = tmp_path / "plugin-repo"
    plugins_dir = tmp_path / "plugins"
    _make_local_repo(repo_dir, version="1.1.0")
    # 预装旧版本 1.0.0
    old = plugins_dir / "demo"
    old.mkdir(parents=True)
    (old / "plugin.json").write_text(
        json.dumps(
            {
                "name": "demo",
                "api_version": 1,
                "version": "1.0.0",
                "dependencies": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (old / "__init__.py").write_text(
        "from app.core.plugin import Plugin, PluginContext\n"
        "class DemoPlugin(Plugin):\n"
        "    def setup(self, ctx):\n"
        "        pass\n\n"
        "def create_plugin():\n"
        "    return DemoPlugin()\n",
        encoding="utf-8",
    )

    service = PluginRepoService(plugins_dir, repo_dir)
    assert service.installed_version("demo") == "1.0.0"
    await service.install("demo", replace=True)
    assert service.installed_version("demo") == "1.0.0"  # zip 内清单版本
    assert any((plugins_dir / ".trash").glob("demo-*"))

    settings = load_settings()
    settings.config_path = str(tmp_path / "config.yaml")
    settings.database.url = (
        f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}"
    )
    reset_db_engine()
    engine = get_engine(settings.database.url)
    await init_db(settings.database.url)
    await ensure_default_admin(settings)
    app = create_app(settings, plugin_manager=None)
    app.state.plugin_repo_service = PluginRepoService(plugins_dir, repo_dir)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post(
            "/login",
            data={"username": "admin", "password": "admin"},
            follow_redirects=False,
        )
        page = await client.get("/plugins/repo")
        assert "可更新" in page.text
        match = re.search(
            r'name="csrf_token" value="([^"]+)"', page.text
        )
        assert match
        response = await client.post(
            "/plugins/repo/install",
            data={
                "csrf_token": match.group(1),
                "plugin_id": "demo",
                "replace": "1",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

    await engine.dispose()
    reset_db_engine()
