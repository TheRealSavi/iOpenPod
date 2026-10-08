import logging
from collections.abc import Generator
from contextlib import contextmanager
from io import StringIO
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest

from iOpenPod.app.core.logging import ISSUE_TRACKER_URL, active_log_path, setup_logger


@contextmanager
def isolated_logging() -> Generator[logging.Logger, None, None]:
    root_logger = logging.getLogger()
    original_handlers = root_logger.handlers[:]
    original_levels = {
        logger: logger.level
        for logger in (
            root_logger,
            logging.getLogger("numba"),
            logging.getLogger("PIL"),
        )
    }
    root_logger.handlers.clear()
    try:
        yield root_logger
    finally:
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
            handler.close()
        root_logger.handlers.extend(original_handlers)
        for logger, level in original_levels.items():
            logger.setLevel(level)


@pytest.mark.parametrize("existing", ["none", "stream", "rotating"])
def test_setup_installs_own_log_once_and_preserves_foreign_handlers(
    tmp_path: Path, existing: str
) -> None:
    output = StringIO()
    foreign: logging.Handler | None = None
    if existing == "stream":
        foreign = logging.StreamHandler(output)
    elif existing == "rotating":
        foreign = RotatingFileHandler(tmp_path / "foreign.log", encoding="utf-8")
    with isolated_logging() as root_logger:
        if foreign is not None:
            root_logger.addHandler(foreign)

        log_path = tmp_path / "application" / "iopenpod.log"
        assert setup_logger(log_path) is root_logger
        configured_handlers = tuple(root_logger.handlers)
        assert setup_logger(tmp_path / "second.log") is root_logger
        assert tuple(root_logger.handlers) == configured_handlers
        assert not (tmp_path / "second.log").exists()
        assert active_log_path() == log_path

        root_logger.debug("diagnostic detail")
        root_logger.warning("reportable problem")
        logged = log_path.read_text(encoding="utf-8")
        assert logged.count("diagnostic detail") == 1
        assert logged.count("reportable problem") == 1
        assert logged.count(ISSUE_TRACKER_URL) == 1
        if foreign is not None:
            assert foreign in root_logger.handlers
            external_log = (
                output.getvalue()
                if existing == "stream"
                else (tmp_path / "foreign.log").read_text(encoding="utf-8")
            )
            assert external_log.count("diagnostic detail") == 1
            assert external_log.count("reportable problem") == 1


def test_setup_logger_suppresses_numba_debug_logging(tmp_path: Path) -> None:
    with isolated_logging():
        numba_logger = logging.getLogger("numba")
        numba_logger.setLevel(logging.DEBUG)

        root_logger = setup_logger(tmp_path / "iopenpod.log")

        assert root_logger.level == logging.DEBUG
        assert numba_logger.level == logging.INFO
        assert not numba_logger.isEnabledFor(logging.DEBUG)
        assert numba_logger.isEnabledFor(logging.INFO)


def test_logger_suggests_reporting_only_after_serious_records(tmp_path: Path) -> None:
    log_path = tmp_path / "iopenpod.log"

    with isolated_logging():
        setup_logger(log_path)
        logger = logging.getLogger("test.issue_reporting")

        logger.info("ordinary information")
        assert ISSUE_TRACKER_URL not in log_path.read_text(encoding="utf-8")

        logger.warning("warning")
        logger.error("severe error")
        logger.critical("crash")

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
