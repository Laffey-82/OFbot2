"""生成 README 展示用的 Web 后台截图（发布前手动运行，不进 CI）。

用法：py scripts/capture_screenshots.py
依赖：playwright（已安装 chromium）。输出到 docs/assets/screenshots/。
"""

from __future__ import annotations

import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import yaml
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docs" / "assets" / "screenshots"

PAGES: list[tuple[str, str]] = [
    ("login", "/login"),
    ("dashboard", "/"),
    ("connections", "/connections"),
    ("scopes", "/scopes"),
    ("plugin_market", "/plugins/repo"),
    ("workflow", "/workflows"),
]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _write_config(tmp: Path, port: int) -> Path:
    config = {
        "basic": {
            "log_level": "WARNING",
            "log_max_files": 3,
            "log_retention_days": 1,
        },
        "database": {"url": f"sqlite+aiosqlite:///{(tmp / 'shot.db').as_posix()}"},
        "web": {
            "host": "127.0.0.1",
            "port": port,
            "api_keys": [],
            "plugin_repo_url": "",  # 本地插件市场（离线可用）
        },
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
    path = tmp / "config.yaml"
    path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    return path


def _wait_ready(base: str, process: subprocess.Popen) -> None:
    deadline = time.time() + 30
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError("bot 进程提前退出")
        try:
            urllib.request.urlopen(f"{base}/login", timeout=1)
            return
        except Exception:
            time.sleep(0.3)
    raise RuntimeError("Web 服务未就绪")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        config_path = _write_config(Path(tmp_dir), port)
        process = subprocess.Popen(
            [sys.executable, str(ROOT / "main.py"), "--config", str(config_path)],
            cwd=str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            _wait_ready(base, process)
            with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page(
                    viewport={"width": 1440, "height": 900},
                    device_scale_factor=1,
                )
                page.add_init_script(
                    "localStorage.setItem('theme', 'light');"
                )
                page.goto(f"{base}/login")
                page.wait_for_load_state("networkidle")
                page.screenshot(
                    path=str(OUT_DIR / "login.png"), full_page=False
                )
                print("captured: login.png")

                page.fill('input[name="username"]', "admin")
                page.fill('input[name="password"]', "admin")
                page.click('button[type="submit"]')
                page.wait_for_url(
                    lambda url: "/login" not in url, timeout=10000
                )
                for name, route in PAGES[1:]:
                    page.goto(f"{base}{route}")
                    page.wait_for_load_state("networkidle")
                    if name == "scopes":
                        page.fill('input[name="group_id"]', "123456")
                        page.click(
                            'form[action="/scopes/add"] button[type="submit"]'
                        )
                        page.wait_for_load_state("networkidle")
                    if name == "plugin_market":
                        time.sleep(1.5)  # 等待本地市场渲染
                    page.screenshot(
                        path=str(OUT_DIR / f"{name}.png"), full_page=False
                    )
                    print(f"captured: {name}.png")
                browser.close()
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
    print(f"完成：截图已写入 {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
