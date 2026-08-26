from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from app.core.config import load_settings

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_version_consistency() -> None:
    """版本号单一来源：app.__version__ 与 pyproject 一致，静态资源版本用模板变量。"""
    import tomllib

    from app import __version__

    pyproject = tomllib.loads(
        (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert pyproject["project"]["version"] == __version__

    changelog = (PROJECT_ROOT / "docs/CHANGELOG.md").read_text(
        encoding="utf-8"
    )
    head = next(
        line for line in changelog.splitlines() if line.startswith("## v")
    )
    import re

    match = re.search(r"v(\d+\.\d+\.\d+)", head)
    assert match is not None
    assert match.group(1) == __version__

    base = (PROJECT_ROOT / "app/web/templates/base.html").read_text(
        encoding="utf-8"
    )
    assert "?v={{ static_version('css/app.css') }}" in base
    assert "?v={{ static_version('js/app.js') }}" in base


def test_css_theme_contract() -> None:
    """浅色/深色主题契约与侧边栏层级回归（防止菜单/主题缺陷复发）。"""
    css = (PROJECT_ROOT / "app/web/static/css/app.css").read_text(
        encoding="utf-8"
    )
    assert ":root {" in css
    assert '[data-theme="dark"]' in css
    # 核心主题变量在两种主题下都有定义
    assert "--bg:" in css
    assert "--card:" in css
    assert "--text:" in css
    assert "--nav-bg:" in css
    # 浅色主题侧边栏为浅色（默认值）
    assert "--nav-bg: #ffffff" in css
    # 移动端侧边栏层级高于遮罩（z-index 61 > 50）
    assert "z-index: 61;" in css
    assert "z-index: 50;" in css
    # 登录页浮动主题按钮与暗色补充样式
    assert ".login-theme-toggle" in css
    assert '[data-theme="dark"] .check-summary.summary-ok' in css
    assert '[data-theme="dark"] tbody tr:hover' in css


def test_frontend_robustness_contract() -> None:
    """前端脚本必须对受限环境（沙箱 iframe）安全：localStorage 与历史记录访问不得拖垮 UI。"""
    js = (PROJECT_ROOT / "app/web/static/js/app.js").read_text(
        encoding="utf-8"
    )
    assert "const safeStorage =" in js
    assert "function safeInit" in js
    # 全局脚本中不允许直接裸调 localStorage（必须走 safeStorage 封装）
    assert "window.localStorage" in js
    bare = js.count("localStorage.getItem") + js.count("localStorage.setItem")
    assert bare == 2  # 仅 safeStorage 封装内部的两处调用
    assert js.index("const safeStorage") < js.index("localStorage.getItem")
    # history.replaceState 必须有异常保护
    assert "history.replaceState" in js
    assert 'catch (err) {\n      // 受限环境' in js
    # 主题切换后图表重绘机制
    assert "__ofbot2Redraw" in js
    assert "requestRedraw" in js

    for page in ("dashboard.html", "monitor.html", "stats.html", "stats_command.html"):
        page_html = (PROJECT_ROOT / "app/web/templates" / page).read_text(
            encoding="utf-8"
        )
        assert "__ofbot2RedrawCallbacks" in page_html

    base = (PROJECT_ROOT / "app/web/templates/base.html").read_text(
        encoding="utf-8"
    )
    # 首帧主题预应用脚本
    assert 'var theme = window.localStorage.getItem("theme")' in base
    assert "prefers-color-scheme: dark" in base
    # 菜单高亮使用 nav_active（支持子页面）
    assert 'class="{{ nav_active(request,' in base
    # 静态资源带版本号，避免浏览器缓存旧脚本
    assert "/static/css/app.css?v=" in base
    assert "/static/js/app.js?v=" in base


def test_all_page_routers_build() -> None:
    """全部页面路由模块均可构建并注册路由（拆分回归冒烟）。"""
    from fastapi.templating import Jinja2Templates

    from app.web.routers import (
        ai_workflow,
        alerts,
        audit_ops,
        auth,
        backups,
        config_pages,
        connections,
        core,
        data,
        docs_pages,
        executions_ops,
        exports,
        files,
        monitoring,
        plugins,
        scopes,
        stats,
        tasks,
        webhooks,
    )

    app = FastAPI()
    settings = load_settings()
    templates = Jinja2Templates(
        directory=str(PROJECT_ROOT / "app/web/templates")
    )
    builders = [
        core,
        auth,
        stats,
        config_pages,
        docs_pages,
        plugins,
        connections,
        data,
        webhooks,
        alerts,
        exports,
        files,
        backups,
        ai_workflow,
        scopes,
        tasks,
        monitoring,
        audit_ops,
        executions_ops,
    ]
    for module in builders:
        router = module.build_router(
            app=app, settings=settings, templates=templates
        )
        assert router.routes, f"{module.__name__} 未注册任何路由"
        app.include_router(router)
    assert len(app.routes) > 30
