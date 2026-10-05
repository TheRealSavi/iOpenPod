import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

ISSUE_TRACKER_URL = "https://github.com/TheRealSavi/iOpenPod/issues"
_REPORT_ISSUE_MESSAGE = (
    "If this %s indicates a problem with iOpenPod, please report an issue at %s"
)


class _ReportIssueSuggestionHandler(logging.Handler):
    """Follow serious log records with the issue-reporting suggestion."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno >= logging.CRITICAL:
            event = "crash"
        elif record.levelno >= logging.ERROR:
            event = "severe error"
        else:
            event = "warning"
        logging.getLogger(__name__).info(
            _REPORT_ISSUE_MESSAGE,
            event,
            ISSUE_TRACKER_URL,
        )


def active_log_path() -> Path | None:
    """Return the file currently used by the application's rotating log handler."""
    for handler in logging.getLogger().handlers:
        if isinstance(handler, RotatingFileHandler):
            return Path(handler.baseFilename)
    return None


def setup_logger(log_path: str | Path) -> logging.Logger:
    """One time logger setup for iOpenPod."""

    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    logging.getLogger("numba").setLevel(logging.INFO)
    logging.getLogger("PIL").setLevel(logging.INFO)

    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    file_handler = RotatingFileHandler(
        log_path, maxBytes=5 * 0x0400**2, backupCount=5, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    logger.addHandler(_ReportIssueSuggestionHandler())

    return logger
