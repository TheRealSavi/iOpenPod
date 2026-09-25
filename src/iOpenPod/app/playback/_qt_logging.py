"""Keep Qt Multimedia's FFmpeg diagnostics out of application output."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Generator
from contextlib import contextmanager
from threading import Lock

from PySide6.QtCore import (
    QLoggingCategory,
    QMessageLogContext,
    QtMsgType,
    qInstallMessageHandler,
)

_FFMPEG_MESSAGE_PREFIX = "FFmpeg log:"
_FFMPEG_CATEGORY_PREFIX = "qt.multimedia.ffmpeg"
_FFMPEG_FILTER_RULES = (
    "qt.multimedia.ffmpeg=false",
    "qt.multimedia.ffmpeg.*=false",
)

_QtMessageHandler = Callable[[QtMsgType, QMessageLogContext, str], object]

_configuration_lock = Lock()
_handler_installed = False
_previous_handler: _QtMessageHandler | None = None


@contextmanager
def quiet_qt_ffmpeg_initialization() -> Generator[None, None, None]:
    """Initialize Qt's FFmpeg plugin with diagnostics safely redirected."""

    with _configuration_lock:
        _install_diagnostic_filter()
        previous_debug = os.environ.get("QT_FFMPEG_DEBUG")
        # Qt otherwise leaves FFmpeg's default logger attached directly to stderr.
        # Enabling its bridge routes those native messages through our Qt handler.
        os.environ["QT_FFMPEG_DEBUG"] = "1"
        try:
            yield
        finally:
            if previous_debug is None:
                os.environ.pop("QT_FFMPEG_DEBUG", None)
            else:
                os.environ["QT_FFMPEG_DEBUG"] = previous_debug


def _install_diagnostic_filter() -> None:
    global _handler_installed, _previous_handler

    if _handler_installed:
        return
    configured_rules = os.environ.get("QT_LOGGING_RULES", "").strip()
    rules = "\n".join(
        rule for rule in (configured_rules, *_FFMPEG_FILTER_RULES) if rule
    )
    QLoggingCategory.setFilterRules(rules)
    _previous_handler = qInstallMessageHandler(_qt_message_handler)
    _handler_installed = True


def _qt_message_handler(
    message_type: QtMsgType,
    context: QMessageLogContext,
    message: str,
) -> None:
    if _is_ffmpeg_diagnostic(context, message):
        return
    if _previous_handler is not None:
        _previous_handler(message_type, context, message)
        return
    logger_name = "qt" if context.category == "default" else context.category
    logging.getLogger(logger_name).log(
        _python_log_level(message_type),
        "%s",
        message,
    )


def _is_ffmpeg_diagnostic(context: QMessageLogContext, message: str) -> bool:
    if context.category.startswith(_FFMPEG_CATEGORY_PREFIX):
        return True
    normalized = message.lstrip()
    if normalized.startswith('"'):
        normalized = normalized[1:]
    return normalized.startswith(_FFMPEG_MESSAGE_PREFIX)


def _python_log_level(message_type: QtMsgType) -> int:
    if message_type is QtMsgType.QtDebugMsg:
        return logging.DEBUG
    if message_type is QtMsgType.QtInfoMsg:
        return logging.INFO
    if message_type is QtMsgType.QtWarningMsg:
        return logging.WARNING
    if message_type is QtMsgType.QtCriticalMsg:
        return logging.ERROR
    return logging.CRITICAL
