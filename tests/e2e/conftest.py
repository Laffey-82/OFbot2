from __future__ import annotations

import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="session")
def web_url(tmp_path_factory) -> str:
    """以子进程启动真实 bot（随机端口 + 临时数据库），返回 Web 根地址。"""
    tmp = tmp_path_factory.mktemp("e2e")
    port = _free_port()
    config = {
        "basic": {
            "log_level": "WARNING",
            "log_max_files": 3,
            "log_retention_days": 1,
        },
        "database": {
            "url": f"sqlite+aiosqlite:///{(tmp / 'e2e.db').as_posix()}"
        },
        "web": {"host": "127.0.0.1", "port": port, "api_keys": []},
        "transport": {
            "connections": [
                {
                    "id": "napcat_main",
                    "protocol": "onebot",
                    "version": "v11",
                    "mode": "reverse_ws",
                    "enabled": False,
                    "host": "127.0.0.1",
                    "port": port + 1,
                    "path": "/onebot/v11/ws",
                }
            ]
        },
        "plugins": {"system": True, "template": True},
    }
    config_path = tmp / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(config, allow_unicode=True), encoding="utf-8"
    )
    process = subprocess.Popen(
        [sys.executable, str(ROOT / "main.py"), "--config", str(config_path)],
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 30
        while time.time() < deadline:
            if process.poll() is not None:
                raise RuntimeError("bot process exited before web server ready")
            try:
                urllib.request.urlopen(f"{base}/login", timeout=1)
                break
            except Exception:
                time.sleep(0.3)
        else:
            raise RuntimeError("web server did not become ready")
        yield base
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


@pytest.fixture(autouse=True)
def _no_browser_errors(page) -> None:
    """页面未捕获异常 / console error 直接判失败。"""
    errors: list[str] = []

    def _on_pageerror(error) -> None:
        errors.append(f"pageerror: {error}")

    def _on_console(message) -> None:
        if message.type == "error":
            errors.append(f"console: {message.text}")

    page.on("pageerror", _on_pageerror)
    page.on("console", _on_console)
    yield
    assert not errors, "浏览器端 JS 错误:\n" + "\n".join(errors)


def login(page, base: str) -> None:
    """登录默认 admin/admin 并等待进入后台。"""
    page.goto(f"{base}/login")
    page.fill('input[name="username"]', "admin")
    page.fill('input[name="password"]', "admin")
    page.click('button[type="submit"]')
    page.wait_for_url(
        lambda url: "/login" not in url, timeout=10000
    )
