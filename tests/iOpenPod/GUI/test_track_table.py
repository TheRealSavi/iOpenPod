"""Behavioral tests for the Track table's contextual column controls."""

from math import ceil
from typing import Any, ClassVar

from PySide6.QtCore import QItemSelectionModel, QMimeData, QPoint, Qt
from PySide6.QtGui import QAction, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QMenu,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
)
from pytest import MonkeyPatch

from iOpenPod.app.artwork_controller import ArtworkController
from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.core.settings.stores import (
    DeviceSettingsStore,
    GlobalSettingsStore,
)
from iOpenPod.app.host_media_library import HostMediaCacheStats, HostMediaLibrary
from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.models.artwork import ArtworkImage, ArtworkRequest
from iOpenPod.app.models.library_drag import TrackSelectionMimeData
from iOpenPod.app.models.library_filter_models import TrackFilterProxyModel
from iOpenPod.app.models.sync_selection import SyncSelection
from iOpenPod.app.models.track_table_model import TrackColumn, TrackTableModel
from iOpenPod.app.sync_plan import SyncPlan
from iOpenPod.GUI.delegates.track_artwork_delegate import TrackArtworkDelegate
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.presentation.track_drag_preview import (
    render_single_track_drag_preview,
    render_track_count_drag_preview,
)
from iOpenPod.GUI.widgets import track_table as track_table_module
from iOpenPod.GUI.widgets.track_table import TrackTable
from iPodDB.library import LibrarySnapshot, Track, TrackMetadata


def _application() -> QApplication:
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    return QApplication([])


APPLICATION = _application()


class _RecordingDrag:
    instances: ClassVar[list["_RecordingDrag"]] = []

    def __init__(self, source: TrackTable) -> None:
        self.source = source
        self.mime_data: QMimeData | None = None
        self.pixmap = QPixmap()
        self.hot_spot = QPoint()
        self.action = Qt.DropAction.IgnoreAction
        self.instances.append(self)

    def setMimeData(self, mime_data: QMimeData) -> None:
        self.mime_data = mime_data

    def setPixmap(self, pixmap: QPixmap) -> None:
        self.pixmap = pixmap

    def setHotSpot(self, hot_spot: QPoint) -> None:
        self.hot_spot = hot_spot

    def exec(self, action: Qt.DropAction) -> Qt.DropAction:
        self.action = action
        return action


class _RecordingArtworkLoader:
    def __init__(self, image: ArtworkImage | None = None) -> None:
        self.requests: list[ArtworkRequest] = []
        self.image = image

    def load_artwork(self, request: ArtworkRequest) -> ArtworkImage | None:
        self.requests.append(request)
        return self.image


class _TestTrackTable(TrackTable):
    """Expose controlled test seams without widening TrackTable's public API."""

    def __init__(
        self,
        model: TrackFilterProxyModel,
        settings: SettingsService,
        theme_manager: ThemeManager,
        artwork_provider: ArtworkPixmapProvider,
        artwork_controller: ArtworkController,
        artwork_loader: _RecordingArtworkLoader,
        table_id: str,
    ) -> None:
        super().__init__(
            model,
            settings,
            theme_manager,
            artwork_provider,
            table_id,
        )
        self.artwork_loader = artwork_loader
        self._artwork_provider = artwork_provider
        self._artwork_controller = artwork_controller

    def build_column_menu(self, position: QPoint) -> QMenu:
        return self._build_column_menu(position)

    def set_column_visible(self, column: TrackColumn, visible: bool) -> None:
        self._set_column_visible(column, visible)

    def close(self) -> bool:
        self._artwork_provider.shutdown()
        self._artwork_controller.shutdown()
        return super().close()


def test_column_menu_matches_the_original_task_oriented_structure() -> None:
    table = _track_table()

    try:
        table.resize(900, 320)
        table.show()
        APPLICATION.processEvents()

        menu = table.build_column_menu(_header_position(table, TrackColumn.ARTIST))
        assert _labels(menu) == (
            'Hide "Artist"',
            None,
            "Resize Column to Fit",
            "Resize All Columns to Fit",
            None,
            "Add Column",
            None,
            "Reset Columns",
        )

        add_menu = _submenu(_action(menu, "Add Column"))
        assert _labels(add_menu) == (
            "Core Metadata",
            "Playback and Stats",
            "Audio Quality",
            "Dates",
            "Sort Overrides",
            "Video and TV",
            "Podcast",
            "Chapters",
            "Gapless",
            "Flags",
            "Artwork",
            "Identifiers",
            "Other",
            "Playlist",
        )

        core_menu = _submenu(_action(add_menu, "Core Metadata"))
        playback_menu = _submenu(_action(add_menu, "Playback and Stats"))
        quality_menu = _submenu(_action(add_menu, "Audio Quality"))
        assert "Album Artist" in _labels(core_menu)
        assert "Composer" in _labels(core_menu)
        assert "Unscrobbled Plays" in _labels(playback_menu)
        assert "Plays" in _labels(playback_menu)
        assert "Sample Rate" in _labels(quality_menu)
        assert "Bitrate" in _labels(quality_menu)

        _action(menu, 'Hide "Artist"').trigger()
        assert table.isColumnHidden(TrackColumn.ARTIST)

        updated = table.build_column_menu(_header_position(table, TrackColumn.TITLE))
        title_hide = _action(updated, 'Hide "Title"')
        assert not title_hide.isEnabled()
        updated_add_menu = _submenu(_action(updated, "Add Column"))
        core_menu = _submenu(_action(updated_add_menu, "Core Metadata"))
        _action(core_menu, "Artist").trigger()
        assert not table.isColumnHidden(TrackColumn.ARTIST)
    finally:
        table.close()


def test_column_menu_resize_actions_fit_visible_content_and_persist() -> None:
    table = _track_table()

    try:
        table.resize(900, 320)
        table.show()
        APPLICATION.processEvents()
        table.setColumnWidth(TrackColumn.ARTIST, 44)

        menu = table.build_column_menu(_header_position(table, TrackColumn.ARTIST))
        _action(menu, "Resize Column to Fit").trigger()

        assert table.columnWidth(TrackColumn.ARTIST) > 44

        for column in TrackColumn:
            table.setColumnHidden(column, False)
        complete = table.build_column_menu(_header_position(table, TrackColumn.ARTIST))
        add_menu = _submenu(_action(complete, "Add Column"))
        placeholder = _action(add_menu, "(all columns shown)")
        assert not placeholder.isEnabled()
    finally:
        table.close()


def test_current_header_state_restores_optional_visibility_and_sorting() -> None:
    table_id = "expanded-header-test"
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    table = _track_table(settings, table_id)
    try:
        table.set_column_visible(TrackColumn.SAMPLE_RATE, True)
        table.sortByColumn(TrackColumn.SAMPLE_RATE, Qt.SortOrder.DescendingOrder)
        QTest.qWait(300)
    finally:
        table.close()

    restored = _track_table(settings, table_id)
    try:
        header = restored.horizontalHeader()
        assert not restored.isColumnHidden(TrackColumn.SAMPLE_RATE)
        assert header.sortIndicatorSection() == TrackColumn.SAMPLE_RATE
        assert header.sortIndicatorOrder() is Qt.SortOrder.DescendingOrder
        model = restored.model()
        assert isinstance(model, TrackFilterProxyModel)
        assert model.sortColumn() == TrackColumn.SAMPLE_RATE
        assert model.sortOrder() is Qt.SortOrder.DescendingOrder
    finally:
        restored.close()


def test_artwork_is_a_real_configurable_column_with_its_own_delegate() -> None:
    table = _track_table()

    try:
        assert not table.isColumnHidden(TrackColumn.ARTWORK)
        assert table.horizontalHeader().visualIndex(TrackColumn.ARTWORK) == 0
        assert isinstance(
            table.itemDelegateForColumn(TrackColumn.ARTWORK),
            TrackArtworkDelegate,
        )

        table.set_column_visible(TrackColumn.ARTWORK, False)
        menu = table.build_column_menu(_header_position(table, TrackColumn.TITLE))
        add_menu = _submenu(_action(menu, "Add Column"))
        artwork_menu = _submenu(_action(add_menu, "Artwork"))
        _action(artwork_menu, "Artwork").trigger()

        assert not table.isColumnHidden(TrackColumn.ARTWORK)
    finally:
        table.close()


def test_visible_artwork_is_preloaded_at_drag_preview_resolution() -> None:
    table = _track_table()

    try:
        table.set_column_visible(TrackColumn.ARTWORK, False)
        table.resize(900, 320)
        table.show()
        QTest.qWait(50)
        assert table.artwork_loader.requests == []

        table.set_column_visible(TrackColumn.ARTWORK, True)
        _wait_for_artwork_request(table.artwork_loader)

        expected_target = ceil(
            LAYOUT.playback_row_artwork_size * max(1.0, table.devicePixelRatioF())
        )
        assert table.artwork_loader.requests == [ArtworkRequest(64, expected_target)]
    finally:
        table.close()


def test_single_track_drag_uses_a_queue_inspired_metadata_preview(
    monkeypatch: MonkeyPatch,
) -> None:
    track = Track(1, "Human", "The Killers", "Day & Age", 245_000)
    table = _track_table(tracks=(track,))
    captured: dict[str, str] = {}

    def record_preview(rendered_track: Track, **kwargs: Any) -> QPixmap:
        assert rendered_track is track
        captured.update(
            title=kwargs["title"],
            artist=kwargs["artist"],
            album=kwargs["album"],
        )
        return render_single_track_drag_preview(rendered_track, **kwargs)

    monkeypatch.setattr(track_table_module, "QDrag", _RecordingDrag)
    monkeypatch.setattr(
        track_table_module,
        "render_single_track_drag_preview",
        record_preview,
    )
    _RecordingDrag.instances.clear()

    try:
        table.set_library_workspace(LibraryWorkspace())
        table.selectRow(0)
        table.startDrag(Qt.DropAction.CopyAction)

        drag = _RecordingDrag.instances[-1]
        assert captured == {
            "title": "Human",
            "artist": "The Killers",
            "album": "Day & Age",
        }
        assert isinstance(drag.mime_data, TrackSelectionMimeData)
        assert drag.mime_data.track_ids == (1,)
        assert not drag.pixmap.isNull()
        assert drag.pixmap.width() / drag.pixmap.devicePixelRatio() == 328
        assert drag.pixmap.height() / drag.pixmap.devicePixelRatio() == 72
        assert drag.hot_spot == QPoint(LAYOUT.space_sm, LAYOUT.space_sm)
        assert drag.action is Qt.DropAction.CopyAction
    finally:
        table.close()


def test_first_track_drag_waits_for_its_asynchronously_loaded_artwork(
    monkeypatch: MonkeyPatch,
) -> None:
    artwork = ArtworkImage(
        cache_key="drag-preview:64:green",
        artwork_id=64,
        format_id=1061,
        width=2,
        height=2,
        rgb888=bytes((0, 255, 0)) * 4,
    )
    track = Track(1, "Human", "The Killers", "Day & Age", 245_000, artwork_id=64)
    table = _track_table(tracks=(track,), artwork_image=artwork)
    monkeypatch.setattr(track_table_module, "QDrag", _RecordingDrag)
    _RecordingDrag.instances.clear()

    try:
        table.set_library_workspace(LibraryWorkspace())
        table.selectRow(0)
        table.startDrag(Qt.DropAction.CopyAction)

        drag = _RecordingDrag.instances[-1]
        ratio = drag.pixmap.devicePixelRatio()
        artwork_center = drag.pixmap.toImage().pixelColor(
            round(33 * ratio),
            round(35 * ratio),
        )
        assert artwork_center.green() == 255
        assert artwork_center.red() == 0
        assert artwork_center.blue() == 0
        expected_target = ceil(
            LAYOUT.playback_row_artwork_size * max(1.0, table.devicePixelRatioF())
        )
        assert table.artwork_loader.requests == [ArtworkRequest(64, expected_target)]
    finally:
        table.close()


def test_multi_track_drag_preview_shows_only_the_selection_count(
    monkeypatch: MonkeyPatch,
) -> None:
    tracks = (
        Track(1, "First", "Artist", "Album", 180_000),
        Track(2, "Second", "Artist", "Album", 200_000),
    )
    table = _track_table(tracks=tracks)
    labels: list[str] = []

    def record_preview(text: str, **kwargs: Any) -> QPixmap:
        labels.append(text)
        return render_track_count_drag_preview(text, **kwargs)

    monkeypatch.setattr(track_table_module, "QDrag", _RecordingDrag)
    monkeypatch.setattr(
        track_table_module,
        "render_track_count_drag_preview",
        record_preview,
    )
    _RecordingDrag.instances.clear()

    try:
        table.set_library_workspace(LibraryWorkspace())
        selection = table.selectionModel()
        flags = (
            QItemSelectionModel.SelectionFlag.Select
            | QItemSelectionModel.SelectionFlag.Rows
        )
        selection.select(table.model().index(0, 0), flags)
        selection.select(table.model().index(1, 0), flags)
        table.startDrag(Qt.DropAction.CopyAction)

        drag = _RecordingDrag.instances[-1]
        assert labels == ["2 Tracks"]
        assert isinstance(drag.mime_data, TrackSelectionMimeData)
        assert drag.mime_data.track_ids == (1, 2)
        assert not drag.pixmap.isNull()
        assert drag.pixmap.height() / drag.pixmap.devicePixelRatio() == 44
        assert drag.action is Qt.DropAction.CopyAction
    finally:
        table.close()


def test_sync_checkbox_click_selects_and_deselects_track() -> None:
    track = Track(
        1,
        "First",
        "Artist",
        "Album",
        180_000,
        metadata=TrackMetadata(location="/host/first.mp3"),
    )
    selection = SyncSelection()
    selection.reset(
        HostMediaLibrary(
            LibrarySnapshot(tracks=(track,)), (), (), HostMediaCacheStats()
        ),
        SyncPlan(()),
    )
    table = _track_table(tracks=(track,), sync_selection=selection)
    try:
        table.resize(900, 320)
        table.show()
        APPLICATION.processEvents()
        assert not table.isColumnHidden(TrackColumn.SYNC_SELECTION)
        assert table.horizontalHeader().visualIndex(TrackColumn.SYNC_SELECTION) == 0
        title = table.model().index(0, TrackColumn.TITLE)
        assert title.data() == "First"
        assert title.data(Qt.ItemDataRole.CheckStateRole) is None
        assert not title.flags() & Qt.ItemFlag.ItemIsUserCheckable
        index = table.model().index(0, TrackColumn.SYNC_SELECTION)
        option = QStyleOptionViewItem()
        option.initFrom(table)
        delegate = table.itemDelegateForIndex(index)
        assert isinstance(delegate, QStyledItemDelegate)
        delegate.initStyleOption(option, index)
        option.rect = table.visualRect(index)
        indicator = table.style().subElementRect(
            QStyle.SubElement.SE_ItemViewItemCheckIndicator, option, table
        )
        assert not indicator.isEmpty()
        QTest.mouseClick(
            table.viewport(), Qt.MouseButton.LeftButton, pos=indicator.center()
        )
        assert selection.track_check_state(1) == Qt.CheckState.Checked
        checked_image = table.viewport().grab(table.visualRect(index)).toImage()
        QTest.mouseClick(
            table.viewport(), Qt.MouseButton.LeftButton, pos=indicator.center()
        )
        assert selection.track_check_state(1) == Qt.CheckState.Unchecked
        unchecked_image = table.viewport().grab(table.visualRect(index)).toImage()
        assert checked_image != unchecked_image
        table.setCurrentIndex(index)
        QTest.keyClick(table, Qt.Key.Key_Space)
        assert selection.track_check_state(1) == Qt.CheckState.Checked
        QTest.keyClick(table, Qt.Key.Key_Space)
        assert selection.track_check_state(1) == Qt.CheckState.Unchecked
        QTest.mouseClick(
            table.viewport(),
            Qt.MouseButton.LeftButton,
            pos=table.visualRect(title).center(),
        )
        assert selection.track_check_state(1) == Qt.CheckState.Unchecked
    finally:
        table.close()


def test_sync_column_follows_selection_mode_and_preserves_saved_metadata_layout() -> (
    None
):
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    table_id = "sync-column-layout-test"
    table = _track_table(settings, table_id)
    try:
        assert table.isColumnHidden(TrackColumn.SYNC_SELECTION)
        table.setColumnWidth(TrackColumn.TITLE, 310)
        table.set_column_visible(TrackColumn.ARTIST, False)
        table.save_layout()
    finally:
        table.close()

    table = _track_table(settings, table_id, sync_selection=SyncSelection())
    try:
        assert not table.isColumnHidden(TrackColumn.SYNC_SELECTION)
        assert table.horizontalHeader().visualIndex(TrackColumn.SYNC_SELECTION) == 0
        assert table.columnWidth(TrackColumn.TITLE) == 310
        assert table.isColumnHidden(TrackColumn.ARTIST)
        table.reset_layout()
        assert not table.isColumnHidden(TrackColumn.SYNC_SELECTION)
        assert table.horizontalHeader().visualIndex(TrackColumn.SYNC_SELECTION) == 0
        table.save_layout()
    finally:
        table.close()

    table = _track_table(settings, table_id)
    try:
        assert table.isColumnHidden(TrackColumn.SYNC_SELECTION)
        proxy = table.model()
        assert isinstance(proxy, TrackFilterProxyModel)
        source = proxy.sourceModel()
        assert isinstance(source, TrackTableModel)
        source.set_sync_selection(SyncSelection())
        assert not table.isColumnHidden(TrackColumn.SYNC_SELECTION)
        source.set_sync_selection(None)
        assert table.isColumnHidden(TrackColumn.SYNC_SELECTION)
    finally:
        table.close()


def _track_table(
    settings: SettingsService | None = None,
    table_id: str = "context-menu-test",
    *,
    tracks: tuple[Track, ...] | None = None,
    artwork_image: ArtworkImage | None = None,
    sync_selection: SyncSelection | None = None,
) -> _TestTrackTable:
    source = TrackTableModel()
    source.set_sync_selection(sync_selection)
    source.replace_tracks(
        tracks
        or (
            Track(
                1,
                "A title long enough to measure",
                "An unusually descriptive artist name",
                "An album",
                180_000,
                artwork_id=64,
            ),
        )
    )
    proxy = TrackFilterProxyModel(source)
    resolved_settings = settings or SettingsService(
        GlobalSettingsStore(), DeviceSettingsStore()
    )
    artwork_loader = _RecordingArtworkLoader(artwork_image)
    artwork_controller = ArtworkController(artwork_loader)
    artwork_provider = ArtworkPixmapProvider(artwork_controller)
    theme_manager = ThemeManager(APPLICATION, resolved_settings)
    return _TestTrackTable(
        proxy,
        resolved_settings,
        theme_manager,
        artwork_provider,
        artwork_controller,
        artwork_loader,
        table_id,
    )


def _wait_for_artwork_request(loader: _RecordingArtworkLoader) -> None:
    for _attempt in range(100):
        if loader.requests:
            return
        QTest.qWait(10)
    raise AssertionError("visible artwork cell did not request its thumbnail")


def _header_position(table: TrackTable, column: TrackColumn) -> QPoint:
    header = table.horizontalHeader()
    return QPoint(
        header.sectionViewportPosition(column) + 4,
        max(1, header.height() // 2),
    )


def _labels(menu: QMenu) -> tuple[str | None, ...]:
    return tuple(
        None if action.isSeparator() else action.text() for action in menu.actions()
    )


def _action(menu: QMenu, text: str) -> QAction:
    return next(action for action in menu.actions() if action.text() == text)


def _submenu(action: QAction) -> QMenu:
    menu = action.menu()
    assert isinstance(menu, QMenu)
    return menu
