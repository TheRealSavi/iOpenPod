import logging
from pathlib import Path

from iOpenPod.app.core.logging import ISSUE_TRACKER_URL, setup_logger


def test_setup_logger_suppresses_numba_debug_logging(tmp_path: Path) -> None:
    numba_logger = logging.getLogger("numba")
    numba_logger.setLevel(logging.DEBUG)

    root_logger = setup_logger(tmp_path / "iopenpod.log")

    assert root_logger.level == logging.DEBUG
    assert numba_logger.level == logging.INFO
    assert not numba_logger.isEnabledFor(logging.DEBUG)
    assert numba_logger.isEnabledFor(logging.INFO)


def test_logger_suggests_reporting_only_after_serious_records(tmp_path: Path) -> None:
    root_logger = logging.getLogger()
    original_handlers = root_logger.handlers[:]
    original_level = root_logger.level
    log_path = tmp_path / "iopenpod.log"

    root_logger.handlers.clear()
    try:
        setup_logger(log_path)
        logger = logging.getLogger("test.issue_reporting")

        logger.info("ordinary information")
        assert ISSUE_TRACKER_URL not in log_path.read_text(encoding="utf-8")

        logger.warning("warning")
        logger.error("severe error")
        logger.critical("crash")
    finally:
        configured_handlers = root_logger.handlers[:]
        root_logger.handlers.clear()
        for handler in configured_handlers:
            handler.close()
        root_logger.handlers.extend(original_handlers)
        root_logger.setLevel(original_level)

    suggestions = [
        line
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if ISSUE_TRACKER_URL in line
    ]

    assert len(suggestions) == 3
    assert all(" | INFO | " in line for line in suggestions)
    assert "this warning" in suggestions[0]
    assert "this severe error" in suggestions[1]
    assert "this crash" in suggestions[2]
