"""Behavioral tests for the external playlist file review dialog."""

from collections.abc import Callable
from pathlib import Path
from time import monotonic

import pytest
from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox, QPushButton, QTableView
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context

from iOpenPod.app.host_media_fingerprint import FpcalcFingerprinter
from iOpenPod.app.host_media_folders import create_host_media_folder
from iOpenPod.app.host_media_library import PlaylistExternalReference
from iOpenPod.GUI import main_window as main_window_module
from iOpenPod.GUI.dialogs.external_playlist_files import (
    ExternalPlaylistFilesDialog,
)
from storage import HostPath


def _reference(
    tmp_path: Path,
    name: str,
    *,
    available: bool,
) -> PlaylistExternalReference:
    return PlaylistExternalReference(
        target=HostPath(tmp_path / name),
        playlists=(HostPath(tmp_path / "Mix.m3u8"),),
        available=available,
    )


def test_external_playlist_files_can_be_accepted_individually_or_in_bulk(
    tmp_path: Path,
) -> None:
    available = _reference(tmp_path, "Available.mp3", available=True)
    unavailable = _reference(tmp_path, "Missing.mp3", available=False)
    dialog = ExternalPlaylistFilesDialog((available, unavailable))

    try:
        APPLICATION.processEvents()
        assert dialog.accepted_paths == frozenset()
        table = dialog.findChild(QTableView, "externalPlaylistFilesTable")
        accept_all = dialog.findChild(QPushButton, "acceptAllPlaylistFiles")
        deny_all = dialog.findChild(QPushButton, "denyAllPlaylistFiles")
        assert table is not None
        assert accept_all is not None
        assert deny_all is not None
        model = table.model()

        assert model.setData(
            model.index(0, 0),
            Qt.CheckState.Checked,
            Qt.ItemDataRole.CheckStateRole,
        )
        assert dialog.accepted_paths == frozenset({available.target})
        assert not model.setData(
            model.index(1, 0),
            Qt.CheckState.Checked,
            Qt.ItemDataRole.CheckStateRole,
        )

        deny_all.click()
        assert dialog.accepted_paths == frozenset()
        accept_all.click()
        assert dialog.accepted_paths == frozenset({available.target})
    finally:
        dialog.close()


@pytest.mark.parametrize("decision", ["accept", "deny", "cancel"])
def test_scan_opens_real_confirmation_before_reading_external_media(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, decision: str
) -> None:
    selected = tmp_path / "Selected"
    selected.mkdir()
    external = tmp_path / "External.wav"
    external.write_bytes(b"unrecognized audio still gets scan diagnostics")
    (selected / "Mix.m3u8").write_text("../External.wav", encoding="utf-8")
    reads: list[HostPath] = []
    reviews: list[bool] = []

    def fingerprint(
        _self: FpcalcFingerprinter, source: HostPath, *, checkpoint: Callable[[], None]
    ) -> str:
        checkpoint()
        reads.append(source)
        return "1,2,3"

    monkeypatch.setattr(FpcalcFingerprinter, "fingerprint", fingerprint)

    class ReviewDialog(ExternalPlaylistFilesDialog):
        def exec(self) -> int:
            reviews.append(True)
            assert reads == []
            assert self.accepted_paths == frozenset()
            if decision == "accept":
                button = self.findChild(QPushButton, "acceptAllPlaylistFiles")
                assert button is not None
                button.click()
            QTimer.singleShot(0, self.reject if decision == "cancel" else self.accept)
            return super().exec()

    monkeypatch.setattr(main_window_module, "ExternalPlaylistFilesDialog", ReviewDialog)

    def acknowledge_information(*_args: object) -> QMessageBox.StandardButton:
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "information", acknowledge_information)
    context = build_context()
    window = main_window_module.MainWindow(context, auto_discover=False)
    try:
        controller = context.host_media_controller
        assert controller.start((create_host_media_folder(selected),))
        deadline = monotonic() + 5
        while controller.busy and monotonic() < deadline:
            APPLICATION.processEvents()
            QTest.qWait(5)
        assert not controller.busy
        assert reviews == [True]
        if decision == "cancel":
            assert controller.latest_library is None
        else:
            library = controller.latest_library
            assert library is not None
            assert library.audio_count == (1 if decision == "accept" else 0)
            assert len(library.snapshot.playlists[0].entries) == (
                1 if decision == "accept" else 0
            )
        assert len(reads) == (1 if decision == "accept" else 0)
        assert not controller.awaiting_external_decisions
    finally:
        window.close()
        context.shutdown()
        window.deleteLater()
        APPLICATION.sendPostedEvents(window, QEvent.Type.DeferredDelete)
