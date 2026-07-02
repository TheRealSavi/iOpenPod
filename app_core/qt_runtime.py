"""Small Qt runtime helpers that must run before selected Qt modules load."""

from __future__ import annotations

import contextlib
import os
import sys
from collections.abc import Iterator

_QT_FFMPEG_QUIET_RULES = (
    "qt.multimedia.ffmpeg*.debug=false",
    "qt.multimedia.ffmpeg*.info=false",
    "qt.multimedia.ffmpeg*.warning=false",
)


def configure_qt_multimedia_logging() -> None:
    """Suppress Qt/FFmpeg probe chatter while leaving other Qt logs alone."""

    existing = os.environ.get("QT_LOGGING_RULES", "").strip()
    parts = [part.strip() for part in existing.replace("\n", ";").split(";") if part.strip()]
    for rule in _QT_FFMPEG_QUIET_RULES:
        if rule not in parts:
            parts.append(rule)
    os.environ["QT_LOGGING_RULES"] = ";".join(parts)


configure_qt_multimedia_logging()


@contextlib.contextmanager
def quiet_native_stderr() -> Iterator[None]:
    """Temporarily mute native stderr writes from C/C++ libraries."""

    try:
        sys.stderr.flush()
    except (AttributeError, OSError, ValueError):
        yield
        return

    stderr_fd = 2
    try:
        saved_fd = os.dup(stderr_fd)
    except OSError:
        yield
        return

    try:
        with open(os.devnull, "w", encoding="utf-8") as sink:
            os.dup2(sink.fileno(), stderr_fd)
            yield
    finally:
        try:
            os.dup2(saved_fd, stderr_fd)
        finally:
            os.close(saved_fd)
