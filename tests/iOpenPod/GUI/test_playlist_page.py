"""Playlist browsing and editing preserve occurrences and imported Smart rules."""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import cast

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QTreeView,
    QWidget,
)
from tests.iOpenPod.GUI.application_shell_test_support import (
    APPLICATION,
    build_context,
)

from device_registry import DEFAULT_DEVICE_REGISTRY, IdentificationStatus
from iOpenPod.app.context import AppContext
from iOpenPod.app.library_export import PlaylistExportMode, PlaylistFileType
from iOpenPod.app.models.device import (
    ActiveIPod,
    DeviceCandidate,
    DeviceCandidateId,
    DeviceReadiness,
)
from iOpenPod.app.models.library_filter_models import TrackFilterProxyModel
from iOpenPod.app.models.track_columns import TrackColumn
from iOpenPod.GUI.dialogs.playlist_editor import PlaylistEditorDialog
from iOpenPod.GUI.dialogs.playlist_export import PlaylistExportDialog
from iOpenPod.GUI.main_window import MainWindow
from iOpenPod.GUI.navigation import PageId
from iOpenPod.GUI.pages.playlist_page import PlaylistPage
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iOpenPod.GUI.widgets.playlist_artwork_banner import PlaylistArtworkBanner
from iOpenPod.GUI.widgets.search_field import SearchField
from iOpenPod.GUI.widgets.sidebar import Sidebar
from iOpenPod.GUI.widgets.themed_buttons import ActionButton, ActionButtonKind
from iOpenPod.GUI.widgets.track_table import TrackTable
from iPodDB.library import (
    LibrarySnapshot,
    Playlist,
    PlaylistKind,
    PlaylistSortOrder,
    SmartField,
    SmartMatch,
    SmartOperator,
    SmartPlaylist,
    SmartPlaylistReference,
    SmartRule,
    SmartRuleGroup,
    Track,
    playlist_entries,
)
from storage import FileFingerprint

_TRACKS = (
    Track(1, "Zulu", "One artist", "An album", 120_000),
    Track(2, "Alpha", "Another artist", "An album", 180_000),
    Track(3, "Beta", "Third artist", "An album", 90_000),
)
_ORIGINAL = Playlist(10, "Road trip", entries=playlist_entries((3, 1, 1, 2)))


@dataclass(frozen=True)
class _Browser:
    context: AppContext
    page: PlaylistPage
    snapshot: LibrarySnapshot


@pytest.fixture
def browser() -> Iterator[_Browser]:
    context = build_context()
    snapshot = LibrarySnapshot(_TRACKS, (_ORIGINAL,))
    context.track_model.replace_tracks(snapshot.tracks)
    context.library_workspace.load(snapshot)
    artwork = ArtworkPixmapProvider(context.artwork_controller)
    page = PlaylistPage(
        context.library_workspace,
        context.settings,
        context.theme_manager,
        artwork,
    )
    page.resize(1000, 700)
    page.show()
    page.select_playlist(10)
    APPLICATION.processEvents()
    try:
        yield _Browser(context, page, snapshot)
    finally:
        page.close()
        context.shutdown()
        artwork.deleteLater()
        page.deleteLater()
        APPLICATION.processEvents()


def _visible_ids(page: PlaylistPage) -> tuple[int, ...]:
    model = _table(page).model()
    assert isinstance(model, TrackFilterProxyModel)
    return tuple(
        track.track_id
        for row in range(model.rowCount())
        if (track := model.track_at(model.index(row, 0))) is not None
    )


def _table(page: PlaylistPage) -> TrackTable:
    table = page.findChild(TrackTable, "playlistsTrackTable")
    assert table is not None
    return table


def _search(page: PlaylistPage, query: str) -> None:
    search = page.findChild(SearchField, "playlistsSearch")
    assert search is not None
    search.set_query(query)
    search.queryChanged.emit(query)


def _label(page: PlaylistPage, name: str) -> QLabel:
    label = page.findChild(QLabel, name)
    assert label is not None
    return label


def _selected_playlist_id(page: PlaylistPage) -> int | None:
    return page.selected_playlist_id


def _playlist(browser: _Browser, playlist_id: int = 10) -> Playlist:
    playlist = browser.context.library_workspace.playlist(playlist_id)
    assert playlist is not None
    return playlist


def _button(page: PlaylistPage, name: str) -> ActionButton:
    button = page.findChild(ActionButton, name)
    assert button is not None
    return button


def _banner(page: PlaylistPage) -> PlaylistArtworkBanner:
    banner = page.findChild(PlaylistArtworkBanner, "playlistArtworkBanner")
    assert banner is not None
    return banner


def test_playlist_opens_in_source_order_with_repeated_track_occurrences(
    browser: _Browser,
) -> None:
    assert _visible_ids(browser.page) == (3, 1, 1, 2)
    assert _table(browser.page).horizontalHeader().sortIndicatorSection() == -1
    assert "4 track" in _label(browser.page, "pageMeta").text()
    assert browser.page.findChild(QLabel, "playlistSessionNotice") is None
    assert browser.page.findChild(ActionButton, "resetPlaylistDrafts") is None
    table = _table(browser.page)
    assert not table.isColumnHidden(TrackColumn.PLAYLIST_POSITION)
    assert tuple(
        table.model().index(row, TrackColumn.PLAYLIST_POSITION).data()
        for row in range(table.model().rowCount())
    ) == ("1", "2", "3", "4")


def test_playlist_banner_uses_one_representative_per_album_and_ignores_search(
    browser: _Browser,
) -> None:
    tracks = (
        Track(1, "One", "Artist", "Shared", 120_000, artwork_id=0),
        Track(2, "Two", "Artist", "Shared", 120_000, artwork_id=101),
        Track(3, "Three", "Artist", "Another", 120_000, artwork_id=202),
    )
    playlist = Playlist(77, "Covers", entries=playlist_entries((1, 2, 3)))
    browser.context.library_workspace.load(LibrarySnapshot(tracks, (playlist,)))
    browser.page.select_playlist(playlist.playlist_id)

    banner = _banner(browser.page)
    assert set(banner.artwork_ids) == {101, 202}

    _search(browser.page, "No matching track")

    assert set(banner.artwork_ids) == {101, 202}


def test_playlist_banner_paints_track_backed_placeholder_artwork(
    browser: _Browser,
) -> None:
    banner = _banner(browser.page)
    image = banner.grab().toImage()
    background = browser.context.theme_manager.tokens.window.casefold()

    sampled_colors = {
        image.pixelColor(x, y).name().casefold()
        for x in range(image.width() // 2, image.width(), 8)
        for y in range(0, max(1, image.height() * 2 // 3), 8)
    }

    assert sampled_colors - {background}


def test_playlist_export_button_requests_the_complete_saved_occurrence_order(
    browser: _Browser,
) -> None:
    requested: list[tuple[str, tuple[Track, ...]]] = []

    def capture_request(name: str, value: object) -> None:
        assert isinstance(value, tuple)
        requested.append((name, cast("tuple[Track, ...]", value)))

    browser.page.playlistExportRequested.connect(capture_request)
    _search(browser.page, "Zulu")

    _button(browser.page, "exportPlaylist").click()

    assert requested == [
        ("Road trip", (_TRACKS[2], _TRACKS[0], _TRACKS[0], _TRACKS[1]))
    ]


def test_playlist_export_dialog_offers_portable_copy_and_major_formats() -> None:
    dialog = PlaylistExportDialog(4)
    try:
        initial_mode = dialog.mode
        assert initial_mode is PlaylistExportMode.COPY_TRACKS
        assert dialog.selected_file_type is PlaylistFileType.M3U8
        assert {
            PlaylistFileType(str(dialog.file_type.itemData(index)))
            for index in range(dialog.file_type.count())
        } == set(PlaylistFileType)
        dialog.device_references.setChecked(True)
        selected_mode = dialog.mode
        assert selected_mode is PlaylistExportMode.DEVICE_REFERENCES
    finally:
        dialog.deleteLater()


def test_editor_applies_playlist_sort_order_and_refreshes_visible_positions(
    browser: _Browser, monkeypatch: pytest.MonkeyPatch
) -> None:
    from iOpenPod.GUI.widgets.app_combo_box import AppComboBox

    def choose_title(dialog: PlaylistEditorDialog) -> int:
        sort_order = next(
            combo
            for combo in dialog.findChildren(AppComboBox)
            if combo.accessibleName() == "Playlist sort order"
        )
        sort_order.setCurrentIndex(sort_order.findData(PlaylistSortOrder.TITLE.value))
        dialog.accept()
        return dialog.result()

    monkeypatch.setattr(PlaylistEditorDialog, "exec", choose_title)

    browser.page.edit_playlist(10)

    playlist = _playlist(browser)
    assert playlist.sort_order is PlaylistSortOrder.TITLE
    assert playlist.track_ids == (2, 3, 1, 1)
    assert tuple(entry.position for entry in playlist.entries) == (0, 1, 2, 3)
    assert _visible_ids(browser.page) == (2, 3, 1, 1)


def test_folder_editor_places_and_applies_the_sort_order_control(
    browser: _Browser, monkeypatch: pytest.MonkeyPatch
) -> None:
    from iOpenPod.GUI.widgets.app_combo_box import AppComboBox

    workspace = browser.context.library_workspace
    workspace.load(
        LibrarySnapshot(
            _TRACKS,
            (Playlist(10, "My Lil Folder", PlaylistKind.FOLDER),),
        )
    )
    browser.page.select_playlist(10)

    def choose_title(dialog: PlaylistEditorDialog) -> int:
        sort_order = next(
            combo
            for combo in dialog.findChildren(AppComboBox)
            if combo.accessibleName() == "Playlist sort order"
        )
        form = dialog.findChild(QFormLayout)
        assert form is not None
        sort_item = form.itemAt(2, QFormLayout.ItemRole.FieldRole)
        assert sort_item is not None and sort_item.widget() is sort_order
        sort_order.setCurrentIndex(sort_order.findData(PlaylistSortOrder.TITLE.value))
        dialog.accept()
        return dialog.result()

    monkeypatch.setattr(PlaylistEditorDialog, "exec", choose_title)

    browser.page.edit_playlist(10)

    folder = workspace.playlist(10)
    assert folder is not None
    assert folder.sort_order is PlaylistSortOrder.TITLE


@pytest.mark.parametrize("kind", tuple(PlaylistKind))
def test_playlist_pages_offer_contextual_actions_in_the_header(
    browser: _Browser,
    kind: PlaylistKind,
) -> None:
    workspace = browser.context.library_workspace
    workspace.load(LibrarySnapshot(_TRACKS, (Playlist(10, "Collection", kind),)))
    page = browser.page
    page.select_playlist(10)
    APPLICATION.processEvents()
    buttons = page.findChildren(ActionButton)
    assert not any(
        button.text() in {"New…", "Add Tracks…", "Move Up", "Move Down"}
        for button in buttons
    )
    assert not page.findChildren(QListWidget)
    edit = _button(page, "editPlaylist")
    evaluate = _button(page, "evaluateSmartPlaylist")
    remove = _button(page, "removePlaylist")
    queue = _button(page, "queuePlaylist")
    play_next = _button(page, "playNextPlaylist")
    assert edit.isVisible() and remove.isVisible() and queue.isVisible()
    assert play_next.isVisible() and not play_next.isEnabled()
    assert not play_next.icon().isNull() and not queue.icon().isNull()
    assert evaluate.isVisible() is (kind is PlaylistKind.SMART)
    assert evaluate.text() == "Evaluate now"
    assert remove.kind is ActionButtonKind.DANGER
    assert remove.text() == (
        "Remove Folder…" if kind is PlaylistKind.FOLDER else "Remove Playlist…"
    )
    assert (
        queue.mapTo(page, QPoint(queue.width(), 0)).x()
        == page.width() - LAYOUT.space_lg
    )
    assert queue.mapTo(page, QPoint()).x() > edit.mapTo(page, QPoint()).x()
    assert not queue.isEnabled()
    empty = _label(page, "playlistEmpty")
    assert empty.isVisible()
    assert "Add Tracks" not in empty.text() and "using New" not in empty.text()


def test_evaluate_now_refreshes_smart_playlist_saved_tracks(browser: _Browser) -> None:
    smart = SmartPlaylist(
        rules=SmartRuleGroup(
            rules=(SmartRule(SmartField.ARTIST, SmartOperator.IS, "One artist"),)
        )
    )
    original = Playlist(
        10,
        "Imported",
        PlaylistKind.SMART,
        entries=playlist_entries((3, 2)),
        smart=smart,
    )
    workspace = browser.context.library_workspace
    workspace.load(LibrarySnapshot(_TRACKS, (original,)))
    browser.page.select_playlist(original.playlist_id)

    _button(browser.page, "evaluateSmartPlaylist").click()

    assert _playlist(browser).track_ids == (1,)
    assert _visible_ids(browser.page) == (1,)
    assert workspace.dirty


def test_evaluate_now_is_disabled_for_read_only_smart_rules(
    browser: _Browser,
) -> None:
    original = Playlist(
        10,
        "Imported",
        PlaylistKind.SMART,
        entries=playlist_entries((3, 2)),
        smart=SmartPlaylist(editable=False),
    )
    browser.context.library_workspace.load(LibrarySnapshot(_TRACKS, (original,)))
    browser.page.select_playlist(original.playlist_id)

    evaluate = _button(browser.page, "evaluateSmartPlaylist")

    assert evaluate.isVisible()
    assert not evaluate.isEnabled()
    assert "cannot be evaluated" in evaluate.toolTip()


def test_remove_button_confirms_and_stages_playlist_removal(
    browser: _Browser, monkeypatch: pytest.MonkeyPatch
) -> None:
    prompt: list[tuple[str, str]] = []

    def confirm(
        _parent: QWidget,
        title: str,
        text: str,
        _buttons: QMessageBox.StandardButton,
        _default: QMessageBox.StandardButton,
    ) -> QMessageBox.StandardButton:
        prompt.append((title, text))
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", confirm)

    _button(browser.page, "removePlaylist").click()

    workspace = browser.context.library_workspace
    assert prompt and prompt[0][0] == "Remove Playlist"
    assert prompt[0][1] == f"Remove '{_ORIGINAL.name}'?"
    assert workspace.playlist(_ORIGINAL.playlist_id) is None
    assert workspace.delete_omissions and workspace.dirty
    assert workspace.snapshot is browser.snapshot
    assert browser.page.selected_playlist_id is None


def test_remove_folder_confirmation_warns_that_children_are_also_removed(
    browser: _Browser, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = Playlist(20, "Trips", PlaylistKind.FOLDER)
    child = Playlist(21, "Road trip", parent_id=folder.playlist_id)
    workspace = browser.context.library_workspace
    workspace.load(LibrarySnapshot(_TRACKS, (folder, child)))
    browser.page.select_playlist(folder.playlist_id)
    prompt: list[str] = []

    def cancel(
        _parent: QWidget,
        _title: str,
        text: str,
        _buttons: QMessageBox.StandardButton,
        _default: QMessageBox.StandardButton,
    ) -> QMessageBox.StandardButton:
        prompt.append(text)
        return QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(QMessageBox, "question", cancel)

    _button(browser.page, "removePlaylist").click()

    assert prompt and "will also be removed" in prompt[0]
    assert workspace.playlist(folder.playlist_id) is folder
    assert workspace.playlist(child.playlist_id) is child


def test_folder_table_aggregates_nested_playlists_and_saved_smart_membership(
    browser: _Browser,
) -> None:
    folder_id = 2**63 + 401
    nested_id = 2**63 + 402
    smart_id = 2**64 - 9
    folder = Playlist(folder_id, "Weekend", PlaylistKind.FOLDER)
    playlists = (
        folder,
        Playlist(
            20, "Saturday", parent_id=folder_id, entries=playlist_entries((3, 1, 1))
        ),
        Playlist(nested_id, "Sunday", PlaylistKind.FOLDER, parent_id=folder_id),
        Playlist(
            smart_id,
            "Saved mix",
            PlaylistKind.SMART,
            parent_id=nested_id,
            entries=playlist_entries((2, 1)),
            smart=SmartPlaylist(),
        ),
        Playlist(30, "Outside", entries=playlist_entries((1, 3))),
    )
    workspace = browser.context.library_workspace
    workspace.load(LibrarySnapshot(_TRACKS, playlists))
    page = browser.page
    page.select_playlist(folder_id)

    assert _visible_ids(page) == (3, 1, 2)
    assert _table(page).isVisible()
    assert "3 tracks" in _label(page, "pageMeta").text()
    assert _label(page, "pageTitle").text() == "Weekend"
    assert _banner(page).artwork_ids == (0, 0, 0)
    queued: list[Track] = []
    page.trackActivated.connect(queued.append)
    _button(page, "queuePlaylist").click()
    assert tuple(track.track_id for track in queued) == (3, 1, 2)

    _table(page).sortByColumn(TrackColumn.TITLE, Qt.SortOrder.DescendingOrder)
    assert _visible_ids(page) == (1, 3, 2)
    _search(page, "Alpha")
    assert _visible_ids(page) == (2,)
    queued.clear()
    _button(page, "queuePlaylist").click()
    assert tuple(track.track_id for track in queued) == (2,)
    _search(page, "No matching track")
    assert not _button(page, "queuePlaylist").isEnabled()

    page.select_playlist(folder_id)
    workspace.move(smart_id, None)
    assert _visible_ids(page) == (3, 1)
    assert "2 tracks" in _label(page, "pageMeta").text()
    page.select_playlist(smart_id)
    assert _visible_ids(page) == (2, 1)
    assert _label(page, "pageTitle").text() == "Saved mix"


def test_queue_sends_visible_tracks_including_duplicate_occurrences(
    browser: _Browser,
) -> None:
    queued: list[Track] = []
    browser.page.trackActivated.connect(queued.append)

    _button(browser.page, "queuePlaylist").click()

    assert tuple(track.track_id for track in queued) == (3, 1, 1, 2)
    assert not browser.context.library_workspace.dirty

    queued.clear()
    _search(browser.page, "Zulu")
    _button(browser.page, "queuePlaylist").click()
    assert tuple(track.track_id for track in queued) == (1, 1)


def test_play_next_sends_visible_occurrences_as_one_ordered_batch(
    browser: _Browser,
) -> None:
    batches: list[tuple[Track, ...]] = []
    browser.page.playNextRequested.connect(batches.append)
    button = _button(browser.page, "playNextPlaylist")

    button.click()
    assert tuple(track.track_id for track in batches.pop()) == (3, 1, 1, 2)
    _table(browser.page).sortByColumn(TrackColumn.TITLE, Qt.SortOrder.AscendingOrder)
    button.click()
    assert tuple(track.track_id for track in batches.pop()) == (2, 3, 1, 1)
    _search(browser.page, "Zulu")
    button.click()
    assert tuple(track.track_id for track in batches.pop()) == (1, 1)
    _search(browser.page, "No matching track")
    assert not button.isEnabled()
    browser.page.select_playlist(None)
    assert button.isHidden()
    assert not browser.context.library_workspace.dirty


def test_playlist_play_next_is_connected_to_the_application_queue() -> None:
    context = build_context()
    context.library_workspace.load(LibrarySnapshot(_TRACKS, (_ORIGINAL,)))
    context.track_model.replace_tracks(_TRACKS)
    window = MainWindow(context, auto_discover=False)
    try:
        page = window.findChild(PlaylistPage)
        assert page is not None
        page.select_playlist(10)
        controller = context.playback_controller
        controller.enqueue(_TRACKS[1])
        controller.enqueue(_TRACKS[2])

        _button(page, "playNextPlaylist").click()

        assert controller.current_track == _TRACKS[1]
        assert tuple(e.track.track_id for e in controller.queue_model.entries) == (
            3,
            1,
            1,
            2,
            3,
        )
    finally:
        window.close()
        context.shutdown()


@pytest.mark.parametrize(
    "rule",
    (
        SmartRule(SmartField.ARTIST, SmartOperator.IS, " The "),
        SmartRule(SmartField.ARTIST, SmartOperator.IS_NOT, ""),
        SmartRule(SmartField.RATING, SmartOperator.IS, 81),
        SmartRule(SmartField.RATING, SmartOperator.BETWEEN, 1, 99),
    ),
)
def test_name_only_smart_edit_preserves_exact_rules_and_saved_membership(
    browser: _Browser, monkeypatch: pytest.MonkeyPatch, rule: SmartRule
) -> None:
    smart = SmartPlaylist(rules=SmartRuleGroup(rules=(rule,)))
    original = Playlist(
        10,
        "Imported",
        PlaylistKind.SMART,
        entries=playlist_entries((3, 1)),
        smart=smart,
    )
    browser.context.library_workspace.load(LibrarySnapshot(_TRACKS, (original,)))
    browser.page.select_playlist(10)

    def rename(dialog: PlaylistEditorDialog) -> int:
        dialog.name.setText("Renamed")
        dialog.accept()
        return dialog.result()

    monkeypatch.setattr(PlaylistEditorDialog, "exec", rename)

    browser.page.edit_playlist(10)

    updated = _playlist(browser)
    assert updated.name == "Renamed"
    assert updated.smart == smart
    assert updated.track_ids == original.track_ids
    assert browser.page.findChild(QLabel, "playlistRulesSummary") is None


def test_rating_editor_uses_stars_and_converts_to_exact_shared_rating() -> None:
    original = Playlist(
        10,
        "Favorites",
        PlaylistKind.SMART,
        smart=SmartPlaylist(
            rules=SmartRuleGroup(
                rules=(SmartRule(SmartField.RATING, SmartOperator.GREATER_THAN, 81),)
            )
        ),
    )
    dialog = PlaylistEditorDialog(PlaylistKind.SMART, original)
    try:
        values = [
            line
            for line in dialog.findChildren(QLineEdit)
            if line.accessibleName() == "Rule value"
        ]
        assert len(values) == 1
        assert values[0].text() == "4.05"
        values[0].setText("4.5")

        dialog.accept()

        assert dialog.result() == QDialog.DialogCode.Accepted
        assert dialog.smart is not None
        assert dialog.smart.rules.rules == (
            SmartRule(SmartField.RATING, SmartOperator.GREATER_THAN, 90),
        )
    finally:
        dialog.deleteLater()


def test_playlist_rule_editor_uses_named_playlist_choices() -> None:
    source = Playlist(10, "Road trip", entries=playlist_entries((1, 3)))
    smart = SmartPlaylist(
        rules=SmartRuleGroup(
            rules=(
                SmartRule(
                    SmartField.PLAYLIST,
                    SmartOperator.IS,
                    SmartPlaylistReference(10),
                ),
            )
        )
    )
    original = Playlist(11, "From road trip", PlaylistKind.SMART, smart=smart)
    dialog = PlaylistEditorDialog(
        PlaylistKind.SMART,
        original,
        playlists=(source, original),
    )
    try:
        choice = next(
            combo
            for combo in dialog.findChildren(AppComboBox)
            if combo.accessibleName() == "Rule choice"
        )

        assert choice.currentText() == "Road trip"
        assert choice.currentData() == 10
        dialog.accept()
        assert dialog.result() == QDialog.DialogCode.Accepted
        assert dialog.smart is smart
    finally:
        dialog.deleteLater()


def test_nested_smart_rules_are_editable_and_survive_a_name_change() -> None:
    nested = SmartRuleGroup(
        SmartMatch.ANY,
        (SmartRule(SmartField.ARTIST, SmartOperator.IS, "One artist"),),
    )
    smart = SmartPlaylist(rules=SmartRuleGroup(rules=(nested,)))
    original = Playlist(10, "Nested mix", PlaylistKind.SMART, smart=smart)
    dialog = PlaylistEditorDialog(PlaylistKind.SMART, original)
    try:
        add_rule = next(
            button
            for button in dialog.findChildren(ActionButton)
            if button.text() == "Add Rule"
        )
        assert add_rule.isEnabled()
        assert not any(
            "cannot be edited" in label.text() for label in dialog.findChildren(QLabel)
        )
        dialog.name.setText("Renamed mix")

        dialog.accept()

        assert dialog.result() == QDialog.DialogCode.Accepted
        assert dialog.smart is smart
    finally:
        dialog.deleteLater()


def test_smart_rule_groups_alternate_surface_by_nesting_depth() -> None:
    deepest = SmartRuleGroup(
        rules=(SmartRule(SmartField.ALBUM, SmartOperator.IS, "Blue"),)
    )
    nested = SmartRuleGroup(SmartMatch.ANY, (deepest,))
    smart = SmartPlaylist(rules=SmartRuleGroup(rules=(nested,)))
    dialog = PlaylistEditorDialog(
        PlaylistKind.SMART,
        Playlist(10, "Nested mix", PlaylistKind.SMART, smart=smart),
    )
    try:
        groups = {
            int(widget.property("ruleGroupDepth")): widget
            for widget in dialog.findChildren(QWidget, "smartRuleGroup")
        }

        assert set(groups) == {0, 1, 2}
        assert groups[0].property("ruleGroupTone") == "base"
        assert groups[1].property("ruleGroupTone") == "alternate"
        assert groups[2].property("ruleGroupTone") == "base"
        assert all(
            group.sizePolicy().verticalPolicy() is QSizePolicy.Policy.Maximum
            for group in groups.values()
        )
        assert all(
            row.sizePolicy().verticalPolicy() is QSizePolicy.Policy.Fixed
            for row in dialog.findChildren(QWidget, "smartRuleRow")
        )
        assert all(
            button.property("kind") == ActionButtonKind.DANGER.value
            for button in dialog.findChildren(ActionButton)
            if button.text().startswith("Remove")
        )
    finally:
        dialog.deleteLater()


@pytest.mark.parametrize("kind", tuple(PlaylistKind))
def test_blank_names_keep_the_editor_open(kind: PlaylistKind) -> None:
    dialog = PlaylistEditorDialog(kind)
    try:
        dialog.name.setText("  \t")

        dialog.accept()

        assert dialog.result() != QDialog.DialogCode.Accepted
        error = dialog.findChild(QLabel, "playlistEditorError")
        assert error is not None and "name" in error.text()
    finally:
        dialog.deleteLater()


@pytest.mark.parametrize("kind", tuple(PlaylistKind))
def test_creation_uses_the_selected_folder_and_selects_the_new_item(
    browser: _Browser, monkeypatch: pytest.MonkeyPatch, kind: PlaylistKind
) -> None:
    workspace = browser.context.library_workspace
    folder = workspace.create(PlaylistKind.FOLDER, "Travel")
    browser.page.select_playlist(folder.playlist_id)

    def accept(dialog: PlaylistEditorDialog) -> int:
        dialog.name.setText("New item")
        dialog.description.setText("A session draft")
        dialog.accept()
        return dialog.result()

    monkeypatch.setattr(PlaylistEditorDialog, "exec", accept)

    browser.page.create_playlist(kind)

    selected = browser.page.selected_playlist_id
    assert selected is not None
    created = _playlist(browser, selected)
    assert created.name == "New item"
    assert created.description == "A session draft"
    assert created.kind == kind
    assert created.parent_id == folder.playlist_id
    if kind is PlaylistKind.SMART:
        assert created.track_ids == (1, 2, 3)
    assert browser.snapshot.playlists == (_ORIGINAL,)


@pytest.mark.parametrize("editing", (False, True))
def test_device_change_while_editor_is_open_cannot_apply_an_obsolete_edit(
    browser: _Browser, monkeypatch: pytest.MonkeyPatch, editing: bool
) -> None:
    replacement = Playlist(10, "Another iPod", entries=playlist_entries((2,)))
    snapshot = LibrarySnapshot(_TRACKS, (replacement,))

    def accept_after_device_change(dialog: PlaylistEditorDialog) -> int:
        dialog.name.setText("Old session intent")
        browser.context.library_workspace.load(snapshot)
        dialog.accept()
        return dialog.result()

    monkeypatch.setattr(PlaylistEditorDialog, "exec", accept_after_device_change)

    if editing:
        browser.page.edit_playlist(10)
    else:
        browser.page.create_playlist(PlaylistKind.PLAYLIST)

    assert browser.context.library_workspace.playlists == (replacement,)
    assert browser.page.selected_playlist_id is None
    assert not browser.context.library_workspace.dirty


def test_explicit_smart_rule_edit_updates_saved_membership(
    browser: _Browser, monkeypatch: pytest.MonkeyPatch
) -> None:
    smart = SmartPlaylist(
        rules=SmartRuleGroup(
            rules=(SmartRule(SmartField.ARTIST, SmartOperator.IS, "One artist"),)
        )
    )
    original = Playlist(
        10,
        "Imported",
        PlaylistKind.SMART,
        entries=playlist_entries((3, 1)),
        smart=smart,
    )
    browser.context.library_workspace.load(LibrarySnapshot(_TRACKS, (original,)))
    browser.page.select_playlist(10)

    def edit_rules(dialog: PlaylistEditorDialog) -> int:
        value = next(
            line
            for line in dialog.findChildren(QLineEdit)
            if line.accessibleName() == "Rule value"
        )
        value.setText("Third artist")
        dialog.accept()
        return dialog.result()

    monkeypatch.setattr(PlaylistEditorDialog, "exec", edit_rules)

    browser.page.edit_playlist(10)

    assert _playlist(browser).track_ids == (3,)
    assert _visible_ids(browser.page) == (3,)
    assert original.track_ids == (3, 1)


def test_playlist_dropdown_keeps_library_navigation_and_only_items_open_pages() -> None:
    context = build_context()
    context.track_model.replace_tracks(_TRACKS)
    context.library_workspace.load(LibrarySnapshot(_TRACKS, (_ORIGINAL,)))
    window = MainWindow(context, auto_discover=False)
    window.show()
    APPLICATION.processEvents()
    try:
        sidebar = window.findChild(Sidebar, "appSidebar")
        page = window.findChild(PlaylistPage, "playlistsPage")
        assert sidebar is not None and page is not None
        tree = sidebar.playlist_tree
        assert tree is not None
        toggle = sidebar.findChild(QPushButton, "playlistSectionToggle")
        view = sidebar.findChild(QTreeView, "playlistTree")
        pages = window.findChild(QStackedWidget, "pageStack")
        albums = next(
            button
            for button in sidebar.findChildren(QPushButton)
            if button.property("pageId") == PageId.ALBUMS.value
        )
        assert toggle is not None and view is not None and pages is not None
        library_page = pages.currentWidget()
        assert not view.isVisible()
        assert not any(
            button.text() == "All Playlists"
            or button.property("pageId") == PageId.PLAYLISTS.value
            for button in sidebar.findChildren(QPushButton)
        )
        toggle.click()
        assert view.isVisible()
        assert albums.isVisible() and albums.isChecked()
        assert pages.currentWidget() is library_page
        sidebar.pageRequested.emit(PageId.PLAYLISTS.value)
        assert pages.currentWidget() is library_page
        assert _selected_playlist_id(page) is None

        tree.select_playlist(10)
        assert _selected_playlist_id(page) == 10
        assert pages.currentWidget() is page
        assert albums.isVisible() and not albums.isChecked()
        toggle.click()
        assert not view.isVisible()
        assert pages.currentWidget() is page
        assert _selected_playlist_id(page) == 10
        toggle.click()
        assert view.isVisible()
        assert tree.current_playlist_id == 10

        albums.click()
        assert not view.currentIndex().isValid()
        assert _selected_playlist_id(page) is None
        assert view.isVisible()
        assert pages.currentWidget() is library_page
        tree.select_playlist(10)
        assert _selected_playlist_id(page) == 10
        assert view.isVisible()

        folder = context.library_workspace.create(PlaylistKind.FOLDER, "Travel")
        tree.select_playlist(folder.playlist_id)
        assert _label(page, "pageTitle").text() == "Travel"
        assert pages.currentWidget() is page
        context.library_workspace.reset_changes()
        assert _selected_playlist_id(page) is None
        assert pages.currentWidget() is library_page
        assert albums.isChecked()

        tree.select_playlist(10)
        context.library_workspace.load(None)
        assert _selected_playlist_id(page) is None
        assert pages.currentWidget() is library_page
    finally:
        window.close()
        context.shutdown()
        window.deleteLater()
        APPLICATION.processEvents()


def test_sidebar_creation_from_library_opens_a_top_level_playlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = build_context()
    context.library_workspace.load(LibrarySnapshot(_TRACKS, (_ORIGINAL,)))
    window = MainWindow(context, auto_discover=False)
    try:
        sidebar = window.findChild(Sidebar, "appSidebar")
        page = window.findChild(PlaylistPage, "playlistsPage")
        assert sidebar is not None and page is not None
        folder = context.library_workspace.create(PlaylistKind.FOLDER, "Travel")
        page.select_playlist(folder.playlist_id)
        sidebar.pageRequested.emit(PageId.ALBUMS.value)
        toggle = sidebar.findChild(QPushButton, "playlistSectionToggle")
        add = sidebar.findChild(QToolButton, "newPlaylistButton")
        assert toggle is not None and add is not None
        toggle.setChecked(False)

        def accept(dialog: PlaylistEditorDialog) -> int:
            dialog.name.setText("New mix")
            dialog.accept()
            return dialog.result()

        monkeypatch.setattr(PlaylistEditorDialog, "exec", accept)
        add.menu().actions()[0].trigger()

        selected = page.selected_playlist_id
        assert selected is not None
        created = context.library_workspace.playlist(selected)
        assert created is not None and created.name == "New mix"
        assert created.parent_id is None
        assert toggle.isChecked()
        assert sidebar.playlist_tree is not None
        assert sidebar.playlist_tree.current_playlist_id == selected
    finally:
        window.close()
        context.shutdown()
        window.deleteLater()
        APPLICATION.processEvents()


@pytest.mark.parametrize(
    ("device_name", "expected"),
    (
        ("  My travel iPod  ", "My travel iPod"),
        ("", "Mounted iPod"),
        ("   ", "Mounted iPod"),
    ),
)
def test_active_ipod_name_prefers_the_master_playlist_then_candidate_label(
    device_name: str, expected: str
) -> None:
    profile = next(
        profile
        for profile in DEFAULT_DEVICE_REGISTRY.profiles
        if profile.model_number == "MB565"
    )
    candidate = DeviceCandidate(
        id=DeviceCandidateId("name-test"),
        display_name="Mounted iPod",
        host_description="USB iPod",
        bus="usb",
        identification_status=IdentificationStatus.EXACT,
        readiness=DeviceReadiness.READY,
        profile=profile,
        total_bytes=80_000_000_000,
        available_bytes=40_000_000_000,
    )
    active = ActiveIPod(
        candidate=candidate,
        profile=profile,
        library=LibrarySnapshot(device_name=device_name),
        database_name="iTunesDB",
        database_fingerprint=FileFingerprint(
            size=1000,
            modified_ns=0,
            device=0,
            inode=0,
            sha256="0" * 64,
        ),
    )
    sidebar = Sidebar()
    try:
        sidebar.set_active_ipod(active)
        name_action = sidebar.findChild(QPushButton, "deviceName")
        assert name_action is not None

        assert active.display_name == expected
        assert name_action.text() == expected
    finally:
        sidebar.deleteLater()


def test_relative_date_editor_keeps_exact_seconds_and_accepts_friendly_units() -> None:
    from iOpenPod.GUI.widgets.app_combo_box import AppComboBox

    smart = SmartPlaylist(
        rules=SmartRuleGroup(
            rules=(SmartRule(SmartField.DATE_ADDED, SmartOperator.IN_LAST, 604800),)
        )
    )
    dialog = PlaylistEditorDialog(
        PlaylistKind.SMART, Playlist(10, "Recent", PlaylistKind.SMART, smart=smart)
    )
    try:
        value = next(
            line
            for line in dialog.findChildren(QLineEdit)
            if line.accessibleName() == "Rule value"
        )
        units = next(
            combo
            for combo in dialog.findChildren(AppComboBox)
            if combo.accessibleName() == "Rule time unit"
        )
        assert value.text() == "1" and units.currentData() == 604800
        dialog.accept()
        assert dialog.smart is smart
        units.setCurrentIndex(units.findData(86400))
        value.setText("2.5")
        dialog.accept()
        assert dialog.smart and dialog.smart.rules.rules == (
            SmartRule(SmartField.DATE_ADDED, SmartOperator.IN_LAST, 216000),
        )
    finally:
        dialog.deleteLater()


@pytest.mark.parametrize("value", ("1e9999999", "NaN", "-1", "0.0000001"))
def test_invalid_relative_period_stays_in_editor_with_an_error(value: str) -> None:
    smart = SmartPlaylist(
        rules=SmartRuleGroup(
            rules=(SmartRule(SmartField.DATE_ADDED, SmartOperator.IN_LAST, 604800),)
        )
    )
    dialog = PlaylistEditorDialog(
        PlaylistKind.SMART, Playlist(10, "Recent", PlaylistKind.SMART, smart=smart)
    )
    try:
        line = next(
            line
            for line in dialog.findChildren(QLineEdit)
            if line.accessibleName() == "Rule value"
        )
        line.setText(value)
        dialog.accept()
        assert dialog.result() != QDialog.DialogCode.Accepted
        assert dialog.smart is smart
    finally:
        dialog.deleteLater()


def test_editor_rejects_changes_made_after_dialog_opens(
    browser: _Browser, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = browser.context.library_workspace

    def delayed_edit(dialog: PlaylistEditorDialog) -> int:
        dialog.name.setText("Stale name")
        workspace.rename(10, "Newer edit")
        dialog.accept()
        return dialog.result()

    monkeypatch.setattr(PlaylistEditorDialog, "exec", delayed_edit)
    browser.page.edit_playlist(10)
    assert _playlist(browser).name == "Newer edit"
