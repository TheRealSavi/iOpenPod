"""Album cover choices remain explicit, cancellable, and revision-bound."""

from collections.abc import Callable
from pathlib import Path
from threading import Event
from time import monotonic, sleep

import pytest
from PySide6.QtCore import QThreadPool, QTranslator
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QDialog, QLineEdit, QMenu, QPushButton, QWidget
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context

from iOpenPod.app.artwork_search import (
    ArtworkCandidate,
    ArtworkSearchClient,
    ArtworkSearchError,
    ArtworkSource,
)
from iOpenPod.app.artwork_search_controller import ArtworkSearchController
from iOpenPod.app.display_text import source_text
from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.GUI.dialogs.artwork_editor import ArtworkEditor
from iOpenPod.GUI.dialogs.artwork_search import ArtworkSearchDialog
from iOpenPod.GUI.dialogs.metadata_editor import MetadataEditorDialog
from iOpenPod.GUI.widgets.track_actions import TrackActions, TrackSelection
from iPodDB.library import (
    ArtworkAsset,
    ArtworkPixels,
    LibrarySnapshot,
    TimedArtworkAsset,
    TimedArtworkFrame,
    Track,
)

TRACKS = (
    Track(1, "One", "Artist", "Album", 1000),
    Track(2, "Two", "Artist", "Album", 1000, artwork_id=7),
)
CANDIDATE = ArtworkCandidate(
    ArtworkSource.ITUNES,
    "Album",
    "Artist",
    "https://music.apple.com/us/album/123",
    "https://is1.mzstatic.com/image.jpg",
)
PIXELS = ArtworkPixels(2, 2, bytes((10, 20, 30)) * 4)


def wait_for(predicate: Callable[[], bool]) -> None:
    deadline = monotonic() + 5
    while not predicate() and monotonic() < deadline:
        APPLICATION.processEvents()
        sleep(0.005)
    assert predicate()


class _Client(ArtworkSearchClient):
    def __init__(self) -> None:
        self.queries: list[str] = []
        self.blocked = Event()
        self.started = Event()
        self.fail = False

    def search(
        self,
        source: ArtworkSource,
        term: str,
        *,
        country: str = "US",
        token: str = "",
        checkpoint: Callable[[], None],
    ) -> tuple[ArtworkCandidate, ...]:
        self.queries.append(term)
        if term == "Blocked":
            self.started.set()
            assert self.blocked.wait(5)
        checkpoint()
        if self.fail:
            raise ArtworkSearchError("Test service unavailable")
        return (CANDIDATE,)

    def load(
        self, candidate: ArtworkCandidate, *, checkpoint: Callable[[], None]
    ) -> ArtworkPixels:
        checkpoint()
        return PIXELS


def _dialog(
    client: _Client | None = None,
) -> tuple[LibraryWorkspace, ArtworkSearchDialog]:
    workspace = LibraryWorkspace()
    workspace.load(LibrarySnapshot(TRACKS))
    return workspace, ArtworkSearchDialog(
        workspace,
        (1, 2),
        workspace.edit_revision,
        ArtworkSource.ITUNES,
        controller=ArtworkSearchController(client or _Client()),
    )


def _preview(dialog: ArtworkSearchDialog) -> None:
    dialog.search_button.click()
    wait_for(lambda: dialog.results.count() == 1)
    dialog.results.setCurrentRow(0)
    wait_for(dialog.apply_button.isEnabled)


@pytest.mark.parametrize("missing_only", [True, False])
def test_apply_assigns_preview_only_to_explicit_album_targets(
    missing_only: bool,
) -> None:
    workspace, dialog = _dialog()
    try:
        assert dialog.term.text() == "Artist Album"
        assert dialog.missing_only.isChecked()
        _preview(dialog)
        assert not workspace.dirty
        assert dialog.dimensions.text() == "2 x 2 pixels"
        dialog.missing_only.setChecked(missing_only)
        dialog.accept()
        assert dialog.result() == QDialog.DialogCode.Accepted
        assert workspace.tracks[0].artwork_id < 0
        assert workspace.tracks[1].artwork_id == (
            7 if missing_only else workspace.tracks[0].artwork_id
        )
        asset = workspace.artwork_assets[0]
        assert isinstance(asset, ArtworkAsset) and asset.pixels == PIXELS
    finally:
        dialog.reject()


def test_cancel_after_preview_keeps_library_unchanged() -> None:
    workspace, dialog = _dialog()
    _preview(dialog)
    dialog.reject()
    assert workspace.tracks == TRACKS and not workspace.dirty


@pytest.mark.parametrize("change", ["reload", "lock", "disconnect"])
def test_library_changes_invalidate_preview(change: str) -> None:
    workspace, dialog = _dialog()
    try:
        _preview(dialog)
        if change == "reload":
            workspace.load(
                LibrarySnapshot((Track(1, "Other", "Other", "Other", 1000),))
            )
        elif change == "lock":
            workspace.set_locked(True)
        else:
            workspace.load(None)
        assert not dialog.apply_button.isEnabled()
        assert not dialog.search_button.isEnabled()
        dialog.accept()
        assert dialog.result() != QDialog.DialogCode.Accepted
        assert not workspace.dirty
    finally:
        dialog.reject()


def test_provider_change_discards_preview_and_enables_token_field() -> None:
    workspace, dialog = _dialog()
    try:
        _preview(dialog)
        dialog.provider.setCurrentIndex(1)
        assert dialog.results.count() == 0
        assert not dialog.apply_button.isEnabled()
        assert dialog.token.isEnabled() and not dialog.region.isEnabled()
        assert not workspace.dirty
        dialog.token.setText("test-secret")
        dialog.reject()
        assert not dialog.token.text()
    finally:
        dialog.reject()


def test_request_failure_displays_error_without_changing_library() -> None:
    client = _Client()
    client.fail = True
    workspace, dialog = _dialog(client)
    try:
        dialog.search_button.click()
        wait_for(lambda: dialog.status.text() == "Test service unavailable")
        assert not dialog.apply_button.isEnabled() and not workspace.dirty
    finally:
        dialog.reject()


@pytest.mark.parametrize(
    "language,title,http_message",
    [
        ("de", "Albumcover suchen", "Der Coverdienst hat HTTP 503 zurückgegeben."),
        (
            "es",
            "Buscar portada del álbum",
            "El servicio de portadas devolvió HTTP 503.",
        ),
    ],
)
def test_dialog_and_provider_errors_use_shipped_translations(
    language: str, title: str, http_message: str
) -> None:
    translator = QTranslator()
    catalogs = (
        Path(__file__).resolve().parents[3]
        / "src/iOpenPod/GUI/presentation/i18n/translations"
    )
    assert translator.load(str(catalogs / f"iopenpod_{language}.qm"))
    APPLICATION.installTranslator(translator)
    workspace, dialog = _dialog()
    try:
        assert dialog.windowTitle() == title
        dialog._failed(
            source_text("The artwork service returned HTTP {status}.", status="503")
        )
        assert dialog.status.text() == http_message
        assert not workspace.dirty
    finally:
        dialog.reject()
        APPLICATION.removeTranslator(translator)


def test_menu_is_available_for_one_complete_album_and_disabled_when_locked() -> None:
    context = build_context()
    context.library_workspace.load(
        LibrarySnapshot((*TRACKS, Track(3, "Three", "Other", "Other", 1000)))
    )
    window = QWidget()
    actions = TrackActions(
        context.library_workspace, context.playback_controller, window
    )
    try:
        for tracks, present in (
            (TRACKS, True),
            (TRACKS[:1], False),
            ((*TRACKS, context.library_workspace.tracks[2]), False),
        ):
            menu = actions.build_menu(
                TrackSelection(tracks, context.library_workspace.edit_revision)
            )
            matches = [a for a in menu.actions() if a.text() == "Find Album Artwork…"]
            assert bool(matches) == present
            if present:
                submenu = matches[0].menu()
                assert isinstance(submenu, QMenu)
                assert [a.text() for a in submenu.actions()] == [
                    "iTunes Store…",
                    "Discogs…",
                ]
                submenu.actions()[0].trigger()
                dialog = window.findChild(ArtworkSearchDialog)
                assert dialog is not None
                assert dialog.term.text() == "Artist Album"
                dialog.reject()
            menu.deleteLater()
        context.library_workspace.set_locked(True)
        menu = actions.build_menu(
            TrackSelection(TRACKS, context.library_workspace.edit_revision)
        )
        assert not next(
            a for a in menu.actions() if a.text() == "Find Album Artwork…"
        ).isEnabled()
    finally:
        window.close()
        context.shutdown()


def test_controller_discards_old_completion_after_a_new_request() -> None:
    client = _Client()
    controller = ArtworkSearchController(client)
    completed = QSignalSpy(controller.finished)
    try:
        controller.search(ArtworkSource.ITUNES, "Blocked", country="US", token="")
        wait_for(client.started.is_set)
        controller.search(ArtworkSource.ITUNES, "New", country="US", token="")
        wait_for(lambda: completed.count() == 1)
        client.blocked.set()
        assert QThreadPool.globalInstance().waitForDone(5000)
        APPLICATION.processEvents()
        assert completed.count() == 1
    finally:
        client.blocked.set()
        controller.shutdown()


def test_closing_dialog_does_not_wait_for_network_and_late_result_cannot_edit() -> None:
    client = _Client()
    workspace, dialog = _dialog(client)
    dialog.term.setText("Blocked")
    dialog.search_button.click()
    wait_for(client.started.is_set)
    try:
        before = monotonic()
        dialog.reject()
        assert monotonic() - before < 0.5
        assert not workspace.dirty
    finally:
        client.blocked.set()
        assert QThreadPool.globalInstance().waitForDone(5000)
        APPLICATION.processEvents()
    assert dialog.results.count() == 0 and not workspace.dirty


def _metadata_search(editor: MetadataEditorDialog) -> ArtworkSearchDialog:
    button = editor.findChild(QPushButton, "findTrackArtwork")
    assert button is not None and button.isEnabled()
    button.click()
    dialog = editor.findChild(ArtworkSearchDialog)
    assert dialog is not None
    # The integration uses the actual nested dialog, with deterministic provider
    # pixels delivered through the same result handlers as background requests.
    dialog._finished((CANDIDATE,))
    dialog.results.blockSignals(True)
    dialog.results.setCurrentRow(0)
    dialog.results.blockSignals(False)
    dialog._candidate = CANDIDATE
    dialog._finished(PIXELS)
    assert dialog.apply_button.isEnabled()
    assert dialog.apply_button.text() == "Use Artwork"
    assert dialog.missing_only.isHidden()
    return dialog


@pytest.mark.parametrize("apply", [True, False])
@pytest.mark.parametrize("track_ids", [(1,), (1, 2)])
def test_metadata_search_stages_cover_until_metadata_apply(
    apply: bool, track_ids: tuple[int, ...]
) -> None:
    workspace = LibraryWorkspace()
    workspace.load(LibrarySnapshot(TRACKS))
    revision = workspace.edit_revision
    editor = MetadataEditorDialog(workspace, track_ids)
    try:
        title = editor.rows["title"].editor
        assert isinstance(title, QLineEdit)
        title.setText("Edited title")
        search = _metadata_search(editor)
        assert search.term.text() == "Artist Album"
        search.accept()
        artwork = editor.findChild(ArtworkEditor)
        assert artwork is not None and artwork.is_modified()
        assert workspace.edit_revision == revision and not workspace.dirty
        assert title.text() == "Edited title"
        if apply:
            editor.accept()
            assert workspace.tracks[0].title == "Edited title"
            assert workspace.tracks[0].artwork_id < 0
            if len(track_ids) == 1:
                assert workspace.tracks[1] == TRACKS[1]
            else:
                assert workspace.tracks[1].artwork_id == workspace.tracks[0].artwork_id
                assert workspace.tracks[1].title == "Edited title"
        else:
            editor.reject()
            assert workspace.tracks == TRACKS and not workspace.dirty
    finally:
        editor.reject()


def test_cancelling_metadata_search_preserves_previous_pending_image() -> None:
    workspace = LibraryWorkspace()
    workspace.load(LibrarySnapshot(TRACKS))
    editor = MetadataEditorDialog(workspace, (1,))
    artwork = editor.findChild(ArtworkEditor)
    assert artwork is not None
    previous = ArtworkPixels(1, 1, b"\xff\x00\x00")
    try:
        artwork.set_pending_artwork(previous)
        before = artwork.edit()
        search = _metadata_search(editor)
        search.reject()
        assert artwork.edit() == before and not workspace.dirty
        editor.accept()
        asset = workspace.artwork_assets[0]
        assert isinstance(asset, ArtworkAsset) and asset.pixels == previous
    finally:
        editor.reject()


def test_metadata_search_preserves_other_pending_timed_frames() -> None:
    workspace = LibraryWorkspace()
    workspace.load(LibrarySnapshot((TRACKS[0],)))
    editor = MetadataEditorDialog(workspace, (1,))
    artwork = editor.findChild(ArtworkEditor)
    assert artwork is not None
    later = ArtworkPixels(1, 1, b"\x00\x00\xff")
    try:
        artwork.set_pending_artwork(ArtworkPixels(1, 1, b"\xff\x00\x00"))
        artwork.add_pending_artwork(later, 15000)
        artwork._entries.setCurrentIndex(0)
        search = _metadata_search(editor)
        search.accept()
        editor.accept()
        asset = workspace.artwork_assets[0]
        assert isinstance(asset, TimedArtworkAsset)
        assert asset.frames == (
            TimedArtworkFrame(0, PIXELS),
            TimedArtworkFrame(15000, later),
        )
    finally:
        editor.reject()


def test_metadata_search_invalidates_after_library_reload() -> None:
    workspace = LibraryWorkspace()
    workspace.load(LibrarySnapshot(TRACKS))
    editor = MetadataEditorDialog(workspace, (1,))
    try:
        search = _metadata_search(editor)
        workspace.load(LibrarySnapshot((Track(1, "Other", "Other", "Other", 1000),)))
        search.accept()
        artwork = editor.findChild(ArtworkEditor)
        assert artwork is not None and not artwork.is_modified()
        assert not workspace.dirty
    finally:
        editor.reject()
