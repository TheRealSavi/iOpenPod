from collections.abc import Callable
from time import monotonic

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from iOpenPod.app.core.status import (
    ApplicationStatus,
    StatusAction,
    StatusMessage,
    StatusProgress,
)


def _application() -> QApplication:
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    return QApplication([])


APPLICATION = _application()


def _wait_until(predicate: Callable[[], bool]) -> None:
    deadline = monotonic() + 1.0
    while not predicate() and monotonic() < deadline:
        QTest.qWait(10)
    assert predicate()


def test_status_messages_restore_by_source_then_fall_back_to_default() -> None:
    status = ApplicationStatus(APPLICATION)
    messages: list[str] = []
    status.messageChanged.connect(messages.append)

    status.set_default("546 Tracks · iPod Classic")
    status.show("podcasts", "Updating Podcasts…")
    status.show("playback", "Could not play Track")
    status.clear("playback")
    status.clear("podcasts")

    assert messages == [
        "546 Tracks · iPod Classic",
        "Updating Podcasts…",
        "Could not play Track",
        "Updating Podcasts…",
        "546 Tracks · iPod Classic",
    ]
    assert status.current_message == "546 Tracks · iPod Classic"


def test_timed_status_does_not_clear_a_newer_message_from_the_same_source() -> None:
    status = ApplicationStatus(APPLICATION)
    status.set_default("Ready")
    status.show("playback", "First failure", timeout_ms=10)
    status.show("playback", "New failure")

    QTest.qWait(20)

    assert status.current_message == "New failure"


def test_timed_status_restores_the_default_message() -> None:
    status = ApplicationStatus(APPLICATION)
    status.set_default("Ready")
    status.show("playback", "Temporary failure", timeout_ms=10)

    _wait_until(lambda: status.current_message == "Ready")

    assert status.current_message == "Ready"


def test_active_messages_are_source_owned_snapshots_and_notify_hidden_changes() -> None:
    status = ApplicationStatus()
    snapshots: list[tuple[StatusMessage, ...]] = []
    status.activeMessagesChanged.connect(
        lambda: snapshots.append(status.active_messages)
    )
    status.set_default("Ready")
    status.show("backup", "Working…")
    status.show("analysis", "Working…")
    snapshot = status.active_messages
    status.show("backup", "Capturing 2 of 10 files…")

    assert snapshot == (
        StatusMessage("backup", "Working…"),
        StatusMessage("analysis", "Working…"),
    )
    assert status.active_messages == (
        StatusMessage("backup", "Capturing 2 of 10 files…"),
        StatusMessage("analysis", "Working…"),
    )
    assert status.current_message == "Working…"
    assert len(snapshots) == 3
    status.show("analysis", "Working…")
    status.clear("unknown")
    assert len(snapshots) == 3
    status.clear("backup")
    status.clear("analysis")
    assert snapshots[-1] == ()
    assert status.current_message == "Ready"


def test_progress_and_actions_follow_their_source_and_reject_stale_clicks() -> None:
    status = ApplicationStatus()
    snapshots: list[tuple[StatusMessage, ...]] = []
    current: list[StatusMessage | None] = []
    requests: list[tuple[str, str]] = []

    def record_action(source: str, key: str) -> None:
        requests.append((source, key))

    status.activeMessagesChanged.connect(
        lambda: snapshots.append(status.active_messages)
    )
    status.currentStatusChanged.connect(lambda: current.append(status.current_status))
    status.actionRequested.connect(record_action)
    cancel = StatusAction("cancel", "Cancel")

    status.show("backup", "Capturing…", progress=StatusProgress(75, 100, "song.m4a"))
    status.show("chaptered", "Encoding…", progress=StatusProgress(), action=cancel)
    status.request_action("chaptered", "cancel")
    status.show("chaptered", "Checking…", progress=StatusProgress(), action=cancel)
    status.clear("chaptered")
    status.request_action("chaptered", "cancel")

    assert requests == [("chaptered", "cancel")]
    assert snapshots[0][0].progress == StatusProgress(75, 100, "song.m4a")
    assert snapshots[1][-1].action == cancel
    assert current[-1] == StatusMessage(
        "backup", "Capturing…", StatusProgress(75, 100, "song.m4a")
    )


def test_status_rotates_automatically_without_progress_updates_starving_peers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("iOpenPod.app.core.status._ROTATION_INTERVAL_MS", 30)
    status = ApplicationStatus()
    messages: list[str] = []
    status.messageChanged.connect(messages.append)
    status.set_default("Ready")
    status.show("backup", "Backup")
    status.show("analysis", "Analysis")
    status.show("podcasts", "Podcasts")
    # This source updates faster than the rotation interval.
    progress = QTimer()
    progress.setInterval(5)
    progress.timeout.connect(lambda: status.show("podcasts", "Podcasts"))
    progress.start()
    try:
        _wait_until(lambda: len(messages) >= 7)
        assert messages[:7] == [
            "Ready",
            "Backup",
            "Analysis",
            "Podcasts",
            "Backup",
            "Analysis",
            "Podcasts",
        ]
        status.clear("analysis")
        status.clear("podcasts")
        progress.stop()
        assert status.current_message == "Backup"
        messages.clear()
        QTest.qWait(60)
        assert messages == []
        status.clear("backup")
        assert status.current_message == "Ready"
    finally:
        progress.stop()


def test_clearing_visible_message_advances_and_hidden_removal_preserves_position() -> (
    None
):
    status = ApplicationStatus()
    status.show("one", "One")
    status.show("two", "Two")
    status.show("three", "Three")
    # Advance deterministically without waiting for the production timer.
    status._rotate()  # pyright: ignore[reportPrivateUsage]
    assert status.current_message == "One"
    status.clear("three")
    assert status.current_message == "One"
    status.clear("one")
    assert status.current_message == "Two"


def test_expiration_removes_only_the_timed_source_from_rotation() -> None:
    status = ApplicationStatus()
    status.show("backup", "Backup")
    status.show("playback", "Temporary failure", timeout_ms=10)
    # Expire the timed source while another source is visible.
    status._rotate()  # pyright: ignore[reportPrivateUsage]
    _wait_until(lambda: len(status.active_messages) == 1)
    assert status.active_messages == (StatusMessage("backup", "Backup"),)
    assert status.current_message == "Backup"
    status.show("playback", "Old failure", timeout_ms=10)
    status.show("playback", "New failure")
    QTest.qWait(20)
    assert status.active_messages[-1] == StatusMessage("playback", "New failure")
    status.clear("backup")
    status.clear("playback")
