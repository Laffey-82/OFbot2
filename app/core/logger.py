from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"

_configured = False


def _ensure_log_dir() -> Path:
    root = Path(__file__).resolve().parents[2]
    log_dir = root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def prune_log_files(
    retention_days: int = 14, max_files: int = 60
) -> int:
    """清理 logs/ 下进程级日志（ofbot2-*.log），返回删除数量。

    规则：超过保留天数的删除；若仍超出文件数上限，按修改时间删除最旧的。
    """
    from datetime import UTC, datetime, timedelta

    log_dir = _ensure_log_dir()
    files = [
        path
        for path in log_dir.glob("ofbot2-*.log")
        if path.is_file()
    ]
    if not files:
        return 0
    files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    cutoff = datetime.now(UTC) - timedelta(days=max(1, retention_days))
    removed = 0
    survivors: list[Path] = []
    for path in files:
        age = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        if age < cutoff:
            try:
                path.unlink()
                removed += 1
            except OSError:
                survivors.append(path)
        else:
            survivors.append(path)
    for path in survivors[max_files:]:
        try:
            path.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def setup_logging(level: str = "INFO", *, file_level: str = "DEBUG") -> None:
    global _configured
    if _configured:
        return

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    formatter = logging.Formatter(LOG_FORMAT)

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(getattr(logging, level.upper(), logging.INFO))
    console.setFormatter(formatter)
    root_logger.addHandler(console)

    log_dir = _ensure_log_dir()
    file_handler = RotatingFileHandler(
        log_dir / f"ofbot2-{os.getpid()}.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(getattr(logging, file_level.upper(), logging.DEBUG))
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    _configured = True


def set_log_level(level: str) -> None:
    logging.getLogger().setLevel(getattr(logging, level.upper(), logging.INFO))
    for handler in logging.getLogger().handlers:
        if isinstance(handler, logging.StreamHandler) and not isinstance(
            handler, RotatingFileHandler
        ):
            handler.setLevel(getattr(logging, level.upper(), logging.INFO))


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_kv(logger: logging.Logger, level: str, message: str, **kwargs: Any) -> None:
    getattr(logger, level.lower(), logger.info)(
        "%s | %s",
        message,
        " ".join(f"{k}={v}" for k, v in kwargs.items()),
    )
