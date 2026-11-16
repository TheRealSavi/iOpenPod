"""Manual scrobbling entry point, persisted option, and real sign-in UI signals."""

from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QWidget,
)
from tests.iOpenPod.app.services.test_library_resources import build_device
from tests.iOpenPod.app.test_library_write_controller import wait_for
from tests.iOpenPod.app.test_listenbrainz_feedback import MBID, FeedbackTransport
from tests.iOpenPod.app.test_scrobbling import MemoryCredentials
from tests.iOpenPod.app.test_scrobbling_clients import TransportStub
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context

from iOpenPod.app.core.settings.definitions import BACK_SYNC_RATINGS
from iOpenPod.app.scrobbling.clients import LastFmClient, ListenBrainzClient
from iOpenPod.app.scrobbling.controller import ScrobbleController
from iOpenPod.app.scrobbling.models import ScrobbleProgress, ScrobbleResult, Service
from iOpenPod.app.scrobbling.queue import ScrobbleQueue
from iOpenPod.app.scrobbling.service import ScrobbleService
from iOpenPod.app.scrobbling.settings import (
    LASTFM_USERNAME,
    LISTENBRAINZ_USERNAME,
    SCROBBLE_DURING_SYNC,
    SCROBBLE_RATINGS,
)
from iOpenPod.GUI.main_window import MainWindow
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iOpenPod.GUI.widgets.scrobbling_settings import ScrobblingSettings
from iOpenPod.GUI.widgets.settings_editor import SettingsEditor
from iOpenPod.GUI.widgets.sidebar import Sidebar
from iOpenPod.GUI.widgets.sync_settings import SyncSettings
from storage import AtomicHostFile


def test_manual_status_retains_typed_counts_and_cancel_action() -> None:
    context = build_context()
    window = MainWindow(context, auto_discover=False)
    controller = window.findChild(ScrobbleController)
    assert controller is not None
    try:
        controller.progress.emit(
            ScrobbleProgress("capture", "Capturing iPod star ratings…")
        )
        status = context.status.current_status
        assert status is not None and status.progress is not None
        assert status.progress.total == 0
        controller.progress.emit(
            ScrobbleProgress(
                "lastfm.ratings",
                "Sending Last.fm ratings…",
                22,
                168,
                "Artist — Song",
                "ratings",
            )
        )
        status = context.status.current_status
        assert status is not None and status.progress is not None
        assert (status.progress.current, status.progress.total) == (22, 168)
        assert status.progress.detail == "Artist — Song"
        assert status.action is not None and status.action.key == "cancel"
        controller._completed(ScrobbleResult(feedback_accepted=168), "")  # pyright: ignore[reportPrivateUsage]
        status = context.status.current_status
        assert status is not None and status.progress is None
        assert status.action is not None and status.action.key == "details"
    finally:
        window.close()
        context.shutdown()
        APPLICATION.processEvents()


def test_manual_report_uses_a_short_status_and_scrollable_details() -> None:
    context = build_context()
    window = MainWindow(context, auto_discover=False)
    controller = window.findChild(ScrobbleController)
    assert controller is not None
    result = ScrobbleResult(
        3,
        42,
        issues=("Last.fm report\n" + "Rejected Track details\n" * 60,),
        adjusted=3,
        notices=(
            "Last.fm submission dates adjusted; original playback dates retained.",
        ),
    )
    try:
        controller._completed(result, "")  # pyright: ignore[reportPrivateUsage]
        status = context.status.current_status
        assert status is not None and status.source == "scrobbling"
        assert status.message == result.summary
        assert status.action is not None and status.action.key == "details"
        context.status.request_action("scrobbling", "details")
        APPLICATION.processEvents()
        dialog = window.findChild(QDialog, "scrobbleReport")
        assert dialog is not None and dialog.isVisible()
        report = dialog.findChild(QPlainTextEdit, "scrobbleReportText")
        assert report is not None and report.isReadOnly()
        assert "Rejected Track details" in report.toPlainText()
        assert "Last.fm submission dates adjusted" in report.toPlainText()
        assert "3 dates adjusted" in status.message
        assert report.verticalScrollBar().maximum() > 0
        assert dialog.height() <= 650
        dialog.close()
    finally:
        window.close()
        context.shutdown()
        APPLICATION.processEvents()


def test_maintenance_button_is_an_action_and_sync_option_persists() -> None:
    context = build_context()
    parent = QWidget()
    try:
        sidebar = Sidebar(parent)
        button = sidebar.findChild(QPushButton, "scrobbleNow")
        assert button is not None and button.text() == "Scrobble now"
        assert not button.isEnabled() and not button.isCheckable()
        requests = QSignalSpy(sidebar.scrobbleRequested)
        sidebar.set_scrobble_available(True)
        button.click()
        assert requests.count() == 1
        sync = SyncSettings(context.settings, parent)
        combo = sync.findChild(AppComboBox, "scrobbleDuringSync")
        assert combo is not None and combo.currentData() is True
        combo.setCurrentIndex(combo.findData(False))
        assert context.settings.get(SCROBBLE_DURING_SYNC) is False
        rebuilt = SyncSettings(context.settings, parent)
        saved = rebuilt.findChild(AppComboBox, "scrobbleDuringSync")
        assert saved is not None and saved.currentData() is False
    finally:
        parent.close()
        context.shutdown()


def test_scrobble_rating_setting_is_opt_in_independent_and_device_overridable() -> None:
    context = build_context()
    parent = QWidget()
    editor = SettingsEditor(context.settings, parent)
    try:
        settings = context.settings
        widget = SyncSettings(settings, parent, editor=editor)
        combo = widget.findChild(AppComboBox, "scrobbleRatings")
        assert combo is not None and combo.currentData() is False
        assert (
            sum(
                label.text() == "Scrobble Ratings"
                for label in widget.findChildren(QLabel)
            )
            == 1
        )
        assert widget.findChild(AppComboBox, "listenbrainzRatings") is None
        assert widget.findChild(AppComboBox, "lastfmRatings") is None
        settings.set_global(SCROBBLE_DURING_SYNC, False)
        combo.setCurrentIndex(combo.findData(True))
        assert settings.get(SCROBBLE_RATINGS)
        assert not settings.get(BACK_SYNC_RATINGS)
        assert not settings.get(SCROBBLE_DURING_SYNC)
        changes = QSignalSpy(settings.settingChanged)
        widget.retranslate_ui()
        assert changes.count() == 0
        settings.load_device("one", {SCROBBLE_RATINGS.key: False})
        assert not settings.get(SCROBBLE_RATINGS)
        editor.set_device(True)
        assert combo.currentData() is False
        editor.set_device(False)
        assert combo.currentData() is True
        rebuilt = SyncSettings(settings, parent)
        saved = rebuilt.findChild(AppComboBox, "scrobbleRatings")
        assert saved is not None and saved.currentData() is True
    finally:
        parent.close()
        context.shutdown()


@pytest.mark.parametrize("enabled", [False, True])
def test_manual_scrobbling_uses_rating_setting_even_when_sync_scrobbling_is_off(
    tmp_path: Path, enabled: bool
) -> None:
    device = build_device(tmp_path)
    context = build_context(device_coordinator=device.coordinator)
    library = device.active.library
    device.save(
        device.prepare(
            replace(
                library,
                tracks=tuple(
                    replace(song, rating=100, artist="Artist", title="Song")
                    for song in library.tracks
                ),
            )
        )
    )
    context.device_controller.finish_library_save(device.active)
    context.settings.set_global(LISTENBRAINZ_USERNAME, "alice")
    context.settings.set_global(LASTFM_USERNAME, "alice")
    context.settings.set_global(SCROBBLE_RATINGS, enabled)
    context.settings.set_global(SCROBBLE_DURING_SYNC, False)
    transport = FeedbackTransport()
    lastfm_transport = FeedbackTransport()
    for _ in library.tracks:
        transport.responses.extend([{"recording_mbid": MBID}, {"status": "ok"}])
        lastfm_transport.responses.append({"status": "ok"})
    credentials = MemoryCredentials()
    service = ScrobbleService(
        device.coordinator,
        ScrobbleQueue(AtomicHostFile(tmp_path / "queue.json")),
        credentials,
        clients=lambda service: (
            LastFmClient(lastfm_transport)
            if service is Service.LASTFM
            else ListenBrainzClient(transport)
        ),
    )
    controller = ScrobbleController(
        service, credentials, context.settings, context.device_controller
    )
    progress = QSignalSpy(controller.progress)
    try:
        assert controller.scrobble_now()
        # A worker uses the captured choice, independent of later settings edits.
        context.settings.set_global(SCROBBLE_RATINGS, not enabled)
        wait_for(lambda: not controller.busy)
        assert controller.last_result is not None
        assert controller.last_result.feedback_accepted == (
            2 * len(library.tracks) if enabled else 0
        )
        assert bool(transport.calls) == enabled
        assert bool(lastfm_transport.calls) == enabled
        events = [progress.at(index)[0] for index in range(progress.count())]
        assert all(isinstance(event, ScrobbleProgress) for event in events)
        if enabled:
            for name in ("lastfm", "listenbrainz"):
                ratings = [
                    event for event in events if event.phase == f"{name}.ratings"
                ]
                assert ratings[-1].completed == ratings[-1].total == len(library.tracks)
    finally:
        controller.shutdown()
        context.shutdown()
        device.coordinator.close()


def test_service_sign_in_credentials_are_masked_validated_and_disconnected(
    tmp_path: Path,
) -> None:
    context = build_context()
    credentials = MemoryCredentials()
    credentials.values.clear()
    service = ScrobbleService(
        context.device_coordinator,
        ScrobbleQueue(AtomicHostFile(tmp_path / "queue.json")),
        credentials,
    )
    lf = LastFmClient(
        TransportStub(
            {"token": "auth-token"},
            {"session": {"name": "alice", "key": "private-session"}},
        )
    )
    lb = ListenBrainzClient(TransportStub({"valid": True, "user_name": "alice"}))
    controller = ScrobbleController(
        service,
        credentials,
        context.settings,
        context.device_controller,
        lastfm=lf,
        listenbrainz=lb,
    )
    widget = ScrobblingSettings(context.settings, controller)
    widget.show()
    try:
        # Avoid opening a real browser; observe the auth URL on the controller.
        controller.authorizationRequested.disconnect()
        authorization = QSignalSpy(controller.authorizationRequested)
        key = widget.findChild(QLineEdit, "lastfmApiKey")
        secret = widget.findChild(QLineEdit, "lastfmApiSecret")
        token = widget.findChild(QLineEdit, "listenbrainzToken")
        assert key is not None and secret is not None and token is not None
        for control in (key, secret, token):
            assert control.echoMode() is QLineEdit.EchoMode.Password
        key.setText("api-key")
        secret.setText("shared-secret")
        button = widget.findChild(QPushButton, "connectLastfm")
        assert button is not None
        button.click()
        wait_for(lambda: not controller.busy)
        assert authorization.count() == 1 and controller.awaiting_authorization
        finish = widget.findChild(QPushButton, "finishLastfm")
        assert finish is not None and finish.isVisible()
        finish.click()
        wait_for(lambda: not controller.busy)
        assert context.settings.get(LASTFM_USERNAME) == "alice"
        assert credentials.values[Service.LASTFM].token == "private-session"
        assert key.text() == secret.text() == ""
        token.setText("private-token")
        connect = widget.findChild(QPushButton, "connectListenbrainz")
        assert connect is not None
        connect.click()
        wait_for(lambda: not controller.busy)
        assert context.settings.get(LISTENBRAINZ_USERNAME) == "alice"
        assert credentials.values[Service.LISTENBRAINZ].token == "private-token"
        assert token.text() == ""
        disconnect = widget.findChild(QPushButton, "disconnectListenbrainz")
        assert disconnect is not None
        disconnect.click()
        wait_for(lambda: not controller.busy)
        assert context.settings.get(LISTENBRAINZ_USERNAME) == ""
        assert Service.LISTENBRAINZ not in credentials.values
        assert context.settings.get(LASTFM_USERNAME) == "alice"
    finally:
        controller.shutdown()
        widget.close()
        context.shutdown()
        APPLICATION.processEvents()
