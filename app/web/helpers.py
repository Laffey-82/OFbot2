"""纯函数 / 可独立测试的 Web 助手（无 app 闭包依赖）。"""

from __future__ import annotations

import functools
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select

from app.core.config import Settings
from app.core.logger import get_logger
from app.db.base import session_factory
from app.db.models import WebAccount
from app.web.security import password_hasher

logger = get_logger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def apply_security_settings(settings: Settings) -> None:
    """把配置中的安全字段重建为运行中的 SecurityPolicy（即时生效）。"""
    from app.core.commands import command_registry
    from app.core.security import SecurityPolicy

    policy = SecurityPolicy(
        max_message_length=settings.security.max_message_length,
        max_arg_length=settings.security.max_arg_length,
        default_cooldown_seconds=settings.security.default_cooldown_seconds,
        rate_limit_default=settings.security.rate_limit_default,
        sensitive_words=settings.security.sensitive_words,
        blocked_users=settings.security.blocked_users,
    )
    command_registry.set_security(policy)


def safe_zip_arcname(name: str) -> str:
    """zip 打包安全归档名：去除路径分隔与 .. 段，防 zip-slip。"""
    cleaned = str(name or "").replace("\\", "/").lstrip("/")
    parts = [part for part in cleaned.split("/") if part not in ("", ".", "..")]
    return "/".join(parts) or "file"


def nav_active(request: Any, path: str) -> str:
    """侧边栏菜单高亮：精确匹配或子页面前缀匹配。"""
    current = request.url.path
    if current == path:
        return "active"
    if path != "/" and current.startswith(path.rstrip("/") + "/"):
        return "active"
    return ""


def _parse_date_range(
    start: str, end: str
) -> tuple[datetime | None, datetime | None]:
    """解析日期范围筛选参数，结束日期自动补到当天 23:59:59。"""
    start_dt = end_dt = None
    if start:
        try:
            start_dt = datetime.fromisoformat(start)
        except ValueError:
            start_dt = None
    if end:
        try:
            end_dt = datetime.fromisoformat(end).replace(
                hour=23, minute=59, second=59
            )
        except ValueError:
            end_dt = None
    return start_dt, end_dt


def _tail_lines(path: Path, lines: int) -> str:
    """读取文件末尾 N 行（对大文件使用尾部 seek，避免整读）。"""
    lines = max(1, min(2000, lines))
    try:
        with path.open("rb") as file:
            file.seek(0, os.SEEK_END)
            size = file.tell()
            if size == 0:
                return ""
            block = 8192
            data = b""
            while size > 0 and data.count(b"\n") < lines:
                read = min(block, size)
                size -= read
                file.seek(size)
                data = file.read(read) + data
            text = data.decode("utf-8", errors="replace")
            return "\n".join(text.splitlines()[-lines:])
    except OSError:
        return ""


def render_markdown_light(text: str) -> str:
    """轻量 Markdown → HTML：标题、代码块、列表、行内代码、粗体、段落。"""
    import html
    import re

    lines = text.splitlines()
    out: list[str] = []
    in_code = False
    code_lines: list[str] = []
    for line in lines:
        if line.strip().startswith("```"):
            if in_code:
                out.append(
                    '<pre class="code-block">'
                    + html.escape("\n".join(code_lines))
                    + "</pre>"
                )
                code_lines = []
                in_code = False
            else:
                in_code = True
            continue
        if in_code:
            code_lines.append(line)
            continue
        stripped = line.strip()
        if stripped.startswith("### "):
            out.append(f"<h3>{html.escape(stripped[4:])}</h3>")
        elif stripped.startswith("## "):
            out.append(f"<h2>{html.escape(stripped[3:])}</h2>")
        elif stripped.startswith("# "):
            out.append(f"<h1>{html.escape(stripped[2:])}</h1>")
        elif stripped.startswith("- "):
            out.append(f"<li>{html.escape(stripped[2:])}</li>")
        elif not stripped:
            out.append("")
        else:
            escaped = html.escape(stripped)
            escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
            escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
            out.append(f"<p>{escaped}</p>")
    if in_code and code_lines:
        out.append(
            '<pre class="code-block">'
            + html.escape("\n".join(code_lines))
            + "</pre>"
        )
    return "\n".join(out)


def humanize_uptime(seconds: float) -> str:
    seconds = int(seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days} 天 {hours} 小时"
    if hours:
        return f"{hours} 小时 {minutes} 分"
    if minutes:
        return f"{minutes} 分 {secs} 秒"
    return f"{secs} 秒"


def humanize_bytes(size: int) -> str:
    size = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def humanize_datetime(timestamp: float) -> str:
    try:
        return datetime.fromtimestamp(timestamp).strftime(
            "%Y-%m-%d %H:%M"
        )
    except (OSError, ValueError, OverflowError):
        return "—"

def flash_redirect(
    url: str, *, message: str = "", error: str = ""
) -> RedirectResponse:
    """303 跳转并携带一次性提示消息（msg / error）。"""
    params: list[str] = []
    if message:
        params.append(f"msg={quote(message)}")
    if error:
        params.append(f"error={error}")
    if params:
        url = f"{url}{'&' if '?' in url else '?'}{'&'.join(params)}"
    return RedirectResponse(url, status_code=303)
async def ensure_default_admin(settings: Settings) -> None:
    async with session_factory()() as session:
        count = await session.scalar(select(func.count()).select_from(WebAccount))
        if count:
            return
        session.add(
            WebAccount(
                username="admin",
                password_hash=password_hasher.hash_password("admin"),
                permission_level=2,
                can_manage_users=True,
                can_manage_plugins=True,
                can_manage_tasks=True,
                can_view_monitor=True,
            )
        )
        await session.commit()
        logger.warning("default admin account created: admin/admin; change it immediately")


async def admin_uses_default_password() -> bool:
    async with session_factory()() as session:
        admin = await session.scalar(
            select(WebAccount).where(WebAccount.username == "admin")
        )
        if admin is None:
            return False
        return password_hasher.verify_password("admin", admin.password_hash)


def _task_executor(task_id: str, app: FastAPI, message_override: str = ""):
    """Web 触发任务执行：委托 runtime._execute_task，统一指标、审计与断路器逻辑。"""
    from app.runtime import _execute_task

    settings = getattr(app.state, "settings", None)
    auto_disable = (
        getattr(settings.scheduler, "auto_disable_after_failures", 0)
        if settings is not None
        else 0
    )
    return functools.partial(
        _execute_task,
        task_id,
        bot_client=getattr(app.state, "bot_client", None),
        scheduler=None,
        auto_disable_after_failures=auto_disable,
        message_override=message_override,
    )


