from __future__ import annotations

import pytest
from playwright.sync_api import expect

from tests.e2e.conftest import login

pytestmark = pytest.mark.e2e


def test_login_and_dashboard(page, web_url) -> None:
    """未登录访问跳转登录页，登录后进入仪表盘。"""
    page.goto(f"{web_url}/")
    assert "/login" in page.url
    login(page, web_url)
    page.goto(f"{web_url}/")
    expect(page.locator("text=仪表盘").first).to_be_visible()


def test_connections_page(page, web_url) -> None:
    """连接中心展示默认连接。"""
    login(page, web_url)
    page.goto(f"{web_url}/connections")
    expect(page.locator("text=napcat_main").first).to_be_visible()


def test_scopes_add_group(page, web_url) -> None:
    """监听环境页可添加群。"""
    login(page, web_url)
    page.goto(f"{web_url}/scopes")
    page.fill('input[name="group_id"]', "123456")
    page.click('form[action="/scopes/add"] button[type="submit"]')
    page.wait_for_url(f"{web_url}/scopes", timeout=10000)
    expect(page.locator("text=group:123456").first).to_be_visible(timeout=10000)


def test_plugins_page_lists_plugins(page, web_url) -> None:
    """插件页列出内置插件。"""
    login(page, web_url)
    page.goto(f"{web_url}/plugins")
    expect(page.locator("text=system").first).to_be_visible()
    expect(page.locator("text=template").first).to_be_visible()


def test_tasks_create_interval_task(page, web_url) -> None:
    """新建 interval 任务并出现在任务列表。"""
    login(page, web_url)
    page.goto(f"{web_url}/tasks")
    page.fill('input[name="name"]', "e2e-任务")
    page.select_option('select[name="task_type"]', "interval")
    page.fill('input[name="interval_seconds"]', "60")
    page.fill('input[name="group_id"]', "200")
    page.fill('input[name="message"]', "hello e2e")
    page.click('form[action="/tasks/add"] button[type="submit"]')
    page.wait_for_url(f"{web_url}/tasks", timeout=10000)
    expect(page.locator("text=e2e-任务").first).to_be_visible(timeout=10000)


def test_workflows_create(page, web_url) -> None:
    """新建流程并出现在列表。"""
    login(page, web_url)
    page.goto(f"{web_url}/workflows")
    page.fill("#wf-name", "e2e-flow")
    page.click('form[action="/workflows/create"] button[type="submit"]')
    page.wait_for_url(f"{web_url}/workflows", timeout=10000)
    expect(page.locator("text=e2e-flow").last).to_be_visible(timeout=10000)
