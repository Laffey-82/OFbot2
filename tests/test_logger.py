from app.core.logger import get_logger, set_log_level, setup_logging


def test_logger_basic() -> None:
    setup_logging("INFO")
    logger = get_logger("test-logger")
    assert logger.name == "test-logger"
    set_log_level("DEBUG")

