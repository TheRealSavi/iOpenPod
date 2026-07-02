from __future__ import annotations

import os

from app_core.qt_runtime import configure_qt_multimedia_logging, quiet_native_stderr


def test_configure_qt_multimedia_logging_appends_targeted_ffmpeg_rules(monkeypatch) -> None:
    monkeypatch.setenv("QT_LOGGING_RULES", "qt.qpa.*=false")

    configure_qt_multimedia_logging()

    rules = os.environ["QT_LOGGING_RULES"].split(";")
    assert "qt.qpa.*=false" in rules
    assert "qt.multimedia.ffmpeg*.debug=false" in rules
    assert "qt.multimedia.ffmpeg*.info=false" in rules
    assert "qt.multimedia.ffmpeg*.warning=false" in rules


def test_configure_qt_multimedia_logging_is_idempotent(monkeypatch) -> None:
    monkeypatch.delenv("QT_LOGGING_RULES", raising=False)

    configure_qt_multimedia_logging()
    first = os.environ["QT_LOGGING_RULES"]
    configure_qt_multimedia_logging()

    assert os.environ["QT_LOGGING_RULES"] == first


def test_quiet_native_stderr_suppresses_fd_writes(capfd) -> None:
    os.write(2, b"before\n")
    with quiet_native_stderr():
        os.write(2, b"hidden\n")
    os.write(2, b"after\n")

    captured = capfd.readouterr()
    assert "before" in captured.err
    assert "after" in captured.err
    assert "hidden" not in captured.err
