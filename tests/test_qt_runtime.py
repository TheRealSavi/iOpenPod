from __future__ import annotations

import os

from iopenpod.application.qt_runtime import (
    configure_qt_multimedia_logging,
    linux_qt_dependency_error,
    quiet_native_stderr,
)


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


def test_linux_qt_dependency_error_reports_missing_xcb_runtime_libraries() -> None:
    def missing_library(_name: str) -> str | None:
        return None

    def cannot_load(_name: str) -> object:
        raise OSError("missing")

    message = linux_qt_dependency_error(
        platform="linux",
        environ={},
        find_library=missing_library,
        load_library=cannot_load,
    )

    assert message is not None
    assert "Qt is missing Linux desktop libraries" in message
    assert "libxcb-cursor0" in message
    assert "libxcb-xkb1" in message
    assert "xcb-util-cursor" in message
    assert "libxcb" in message
    assert "QT_QPA_PLATFORM=wayland iopenpod" in message


def test_linux_qt_dependency_error_passes_when_xcb_libraries_are_loadable() -> None:
    def found_library(name: str) -> str:
        return f"lib{name}.so.0"

    def can_load(_name: str) -> object:
        return object()

    assert (
        linux_qt_dependency_error(
            platform="linux",
            environ={},
            find_library=found_library,
            load_library=can_load,
        )
        is None
    )


def test_linux_qt_dependency_error_skips_explicit_wayland_platform() -> None:
    def cannot_load(_name: str) -> object:
        raise OSError("missing")

    assert (
        linux_qt_dependency_error(
            platform="linux",
            environ={"QT_QPA_PLATFORM": "wayland"},
            find_library=lambda _name: None,
            load_library=cannot_load,
        )
        is None
    )
