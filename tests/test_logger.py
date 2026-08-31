import os
import time

from app.core.logger import get_logger, prune_log_files, set_log_level, setup_logging


def test_logger_basic() -> None:
    setup_logging("INFO")
    logger = get_logger("test-logger")
    assert logger.name == "test-logger"
    set_log_level("DEBUG")


def test_prune_log_files_covers_rotated_and_legacy(tmp_path, monkeypatch) -> None:
    """清理规则覆盖轮转后缀与历史遗留格式，并按文件数上限收敛。"""
    monkeypatch.setattr(
        "app.core.logger._ensure_log_dir", lambda: tmp_path
    )
    now = time.time()
    names = [
        "ofbot2-100.log",
        "ofbot2-100.log.1",
        "ofbot2.log",
        "bot.log",
        "bot_2026-02-25.log",
        "web-stdout.log",
        "diag_fh.log",
        "keep.log",
    ]
    for name in names:
        path = tmp_path / name
        path.write_text("x", encoding="utf-8")
        os.utime(path, (now, now))

    old = tmp_path / "ofbot2-200.log"
    old.write_text("x", encoding="utf-8")
    os.utime(old, (now - 30 * 86400, now - 30 * 86400))

    removed = prune_log_files(retention_days=14, max_files=60)
    assert removed == 1
    assert not old.exists()
    assert (tmp_path / "ofbot2-100.log.1").exists()
    assert (tmp_path / "bot.log").exists()
    assert (tmp_path / "keep.log").exists()

    for i in range(10):
        path = tmp_path / f"ofbot2-3{i}.log"
        path.write_text("x", encoding="utf-8")
        os.utime(path, (now - i, now - i))
    removed2 = prune_log_files(retention_days=14, max_files=5)
    assert removed2 >= 6
    assert len(list(tmp_path.glob("ofbot2-*.log"))) <= 5
