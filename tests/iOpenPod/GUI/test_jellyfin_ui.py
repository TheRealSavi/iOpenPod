"""Jellyfin sign-in and play count sync through the real Settings controls."""

from pathlib import Path

from PySide6.QtWidgets import QLineEdit, QPushButton
from tests.iOpenPod.app.services.test_library_resources import build_device
from tests.iOpenPod.app.test_jellyfin_client import USER, FakeJellyfin, item
from tests.iOpenPod.app.test_jellyfin_play_counts import MemoryTokens
from tests.iOpenPod.app.test_library_write_controller import wait_for
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context

from iOpenPod.app.jellyfin.client import JellyfinClient
from iOpenPod.app.jellyfin.controller import JellyfinController
from iOpenPod.app.jellyfin.models import PlayCountResult
from iOpenPod.app.jellyfin.service import PlayCountService
from iOpenPod.app.jellyfin.settings import (
    JELLYFIN_DEVICE_ID,
    JELLYFIN_SERVER_URL,
    JELLYFIN_USERNAME,
)
from iOpenPod.app.jellyfin.state import PlayCountStore
from iOpenPod.GUI.widgets.jellyfin_settings import JellyfinSettings
from storage import AtomicHostFile


def test_sign_in_sync_and_disconnect_through_settings(tmp_path: Path) -> None:
    device = build_device(tmp_path)
    context = build_context(device_coordinator=device.coordinator)
    server = FakeJellyfin([item("a" * 32, "Track 1", count=3)])
    client = JellyfinClient(server)
    tokens = MemoryTokens(None)
    controller = JellyfinController(
        PlayCountService(
            device.coordinator,
            PlayCountStore(AtomicHostFile(tmp_path / "play-counts.json")),
            tokens,
            client=client,
        ),
        tokens,
        context.settings,
        context.device_controller,
        lambda: False,
        client=client,
    )
    widget = JellyfinSettings(context.settings, controller)
    widget.show()
    try:
        address = widget.findChild(QLineEdit, "jellyfinServer")
        username = widget.findChild(QLineEdit, "jellyfinUsername")
        password = widget.findChild(QLineEdit, "jellyfinPassword")
        connect = widget.findChild(QPushButton, "connectJellyfin")
        sync = widget.findChild(QPushButton, "syncJellyfinPlayCounts")
        assert address is not None and username is not None and password is not None
        assert connect is not None and sync is not None
        assert password.echoMode() is QLineEdit.EchoMode.Password
        assert not sync.isVisible()
        address.setText("jellyfin.local:8096")
        username.setText("alice")
        password.setText("secret")
        connect.click()
        wait_for(lambda: not controller.busy)
        assert context.settings.get(JELLYFIN_USERNAME) == "alice"
        assert context.settings.get(JELLYFIN_SERVER_URL) == "http://jellyfin.local:8096"
        assert context.settings.get(JELLYFIN_DEVICE_ID)
        assert tokens.value is not None and tokens.value.user_id == USER
        assert password.text() == "" and not password.isVisible()
        assert sync.isVisible() and sync.isEnabled()

        sync.click()
        assert context.device_controller.busy
        wait_for(lambda: not controller.busy)
        result = controller.last_result
        assert isinstance(result, PlayCountResult) and result.ipod_updated == 1
        # Other features may briefly reserve the iPod once it is released.
        wait_for(lambda: not context.device_controller.busy)
        active = context.device_controller.active_ipod
        assert active is not None and active is result.active
        assert {t.title: t.play_count for t in active.library.tracks} == {
            "Track 1": 3,
            "Track 2": 0,
        }

        disconnect = widget.findChild(QPushButton, "disconnectJellyfin")
        assert disconnect is not None
        disconnect.click()
        wait_for(lambda: not controller.busy)
        assert context.settings.get(JELLYFIN_USERNAME) == ""
        assert tokens.value is None
        assert not sync.isVisible()
    finally:
        controller.shutdown()
        widget.close()
        context.shutdown()
        device.coordinator.close()
        APPLICATION.processEvents()


def test_sync_is_refused_while_library_edits_are_unsaved(tmp_path: Path) -> None:
    device = build_device(tmp_path)
    context = build_context(device_coordinator=device.coordinator)
    tokens = MemoryTokens(None)
    controller = JellyfinController(
        PlayCountService(
            device.coordinator,
            PlayCountStore(AtomicHostFile(tmp_path / "play-counts.json")),
            tokens,
            client=JellyfinClient(FakeJellyfin()),
        ),
        tokens,
        context.settings,
        context.device_controller,
        lambda: True,
    )
    messages: list[str] = []
    controller.message.connect(messages.append)
    try:
        context.settings.set_global(JELLYFIN_USERNAME, "alice")
        assert not controller.sync_now()
        assert messages == [
            "Save or discard your Library changes before syncing play counts."
        ]
        assert not controller.busy and not context.device_controller.busy
    finally:
        controller.shutdown()
        context.shutdown()
        device.coordinator.close()
        APPLICATION.processEvents()
