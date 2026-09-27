"""Reusable, persistently configurable Track table."""

from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    QEventLoop,
    QModelIndex,
    QPoint,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QMenu,
    QTableView,
    QWidget,
)

from iOpenPod.app.core.settings.definitions import table_header_state
from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.models.library_drag import TrackSelectionMimeData
from iOpenPod.app.models.library_filter_models import TrackFilterProxyModel
from iOpenPod.app.models.track_columns import (
    TrackColumn,
    track_column_default_visible,
    track_column_default_width,
    track_column_groups,
)
from iOpenPod.app.models.track_table_model import TrackRole, TrackTableModel
from iOpenPod.GUI.delegates.track_artwork_delegate import TrackArtworkDelegate
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.presentation.i18n.text import track_count_text
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.presentation.track_drag_preview import (
    drag_preview_hot_spot,
    render_single_track_drag_preview,
    render_track_count_drag_preview,
)

_COLUMN_WIDTH_SAMPLE_LIMIT = 200
_MAXIMUM_FITTED_COLUMN_WIDTH = 480
_DRAG_ARTWORK_WAIT_MS = 150


class TrackTable(QTableView):
    """A sortable, movable-header view with no populated cell widgets."""

    currentTrackChanged = Signal(object)
    trackActivated = Signal(object)

    def __init__(
        self,
        model: TrackFilterProxyModel,
        settings: SettingsService,
        theme_manager: ThemeManager,
        artwork_provider: ArtworkPixmapProvider,
        table_id: str,
        parent: QWidget | None = None,
        *,
        context_columns: frozenset[TrackColumn] = frozenset(),
        default_sort_column: int = -1,
    ) -> None:
        super().__init__(parent)
        self._track_model = model
        source = model.sourceModel()
        self._sync_selection_enabled = (
            isinstance(source, TrackTableModel) and source.sync_selection_enabled
        )
        self._theme_manager = theme_manager
        self._artwork_provider = artwork_provider
        self.playlist_id: int | None = None
        self._library_workspace: LibraryWorkspace | None = None
        self._settings = settings
        self._context_columns = context_columns
        self._default_sort_column = default_sort_column
        self._header_setting = table_header_state(table_id)
        self.setObjectName(
            "trackTable" if table_id == "albums-tracks" else f"{table_id}TrackTable"
        )
        self.setProperty("trackTable", True)
        self.setProperty("tableId", table_id)
        self.setAccessibleName(self.tr("Tracks"))
        self.setModel(model)
        self.setItemDelegateForColumn(
            TrackColumn.ARTWORK,
            TrackArtworkDelegate(theme_manager, artwork_provider, self),
        )
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerItem)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.setWordWrap(False)
        self.setShowGrid(False)
        self.setCornerButtonEnabled(False)

        vertical_header = self.verticalHeader()
        vertical_header.hide()
        vertical_header.setDefaultSectionSize(LAYOUT.track_row_height)
        vertical_header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)

        header = self.horizontalHeader()
        header.setMinimumHeight(LAYOUT.track_table_header_height)
        header.setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        header.setSectionsClickable(True)
        header.setSectionsMovable(True)
        header.setHighlightSections(False)
        header.setCascadingSectionResizes(False)
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(44)
        header.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        for column in TrackColumn:
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)

        self._apply_default_header_layout()
        retained_state = settings.get(self._header_setting)
        restored_layout = not retained_state.isEmpty() and header.restoreState(
            retained_state
        )
        if not restored_layout or header.sortIndicatorSection() < 0:
            header.setSortIndicator(default_sort_column, Qt.SortOrder.AscendingOrder)
        self.setColumnHidden(TrackColumn.TITLE, False)
        self._apply_sync_selection_column()
        self.setSortingEnabled(True)

        self._header_save_timer = QTimer(self)
        self._header_save_timer.setSingleShot(True)
        self._header_save_timer.setInterval(250)
        self._header_save_timer.timeout.connect(self.save_layout)
        header.sectionMoved.connect(self._schedule_layout_save)
        header.sectionResized.connect(self._schedule_layout_save)
        header.sortIndicatorChanged.connect(self._schedule_layout_save)
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self._show_column_menu)

        selection_model = self.selectionModel()
        selection_model.currentChanged.connect(self._current_changed)
        self.doubleClicked.connect(self._activated)
        theme_manager.effectiveThemeChanged.connect(self._theme_changed)
        artwork_provider.artworkChanged.connect(self._artwork_changed)
        artwork_provider.cleared.connect(self._artwork_cache_cleared)
        if isinstance(source, TrackTableModel):
            source.syncSelectionEnabledChanged.connect(self._set_sync_selection_enabled)

    def set_library_workspace(self, workspace: LibraryWorkspace) -> None:
        self._library_workspace = workspace
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setToolTip(
            self.tr("Drag selected Tracks to a Playlist, the Queue, or the Player.")
        )

    def startDrag(self, supported_actions: Qt.DropAction) -> None:
        workspace = self._library_workspace
        if workspace is None or workspace.locked:
            return
        tracks = tuple(
            track
            for index in sorted(
                self.selectionModel().selectedRows(), key=lambda i: i.row()
            )
            if (track := self._track_model.track_at(index)) is not None
        )
        if not tracks:
            return
        ids = tuple(track.track_id for track in tracks)
        workspace_revision = (workspace.generation, workspace.revision)
        ratio = self.devicePixelRatioF()
        if len(tracks) == 1:
            track = tracks[0]
            self._await_drag_artwork(track.artwork_id, ratio)
            if (
                workspace is not self._library_workspace
                or workspace.locked
                or workspace_revision != (workspace.generation, workspace.revision)
            ):
                return
            pixmap = render_single_track_drag_preview(
                track,
                title=track.title
                or QCoreApplication.translate("LibraryLabels", "Untitled Track"),
                artist=track.artist
                or QCoreApplication.translate("LibraryLabels", "Unknown Artist"),
                album=track.album
                or QCoreApplication.translate("LibraryLabels", "Unknown Album"),
                base_font=self.font(),
                tokens=self._theme_manager.tokens,
                artwork_provider=self._artwork_provider,
                device_pixel_ratio=ratio,
            )
        else:
            pixmap = render_track_count_drag_preview(
                track_count_text(len(tracks)),
                base_font=self.font(),
                tokens=self._theme_manager.tokens,
                device_pixel_ratio=ratio,
            )
        drag = QDrag(self)
        drag.setMimeData(TrackSelectionMimeData(workspace, ids))
        drag.setPixmap(pixmap)
        drag.setHotSpot(drag_preview_hot_spot(pixmap))
        drag.exec(Qt.DropAction.CopyAction)

    def _await_drag_artwork(
        self,
        artwork_id: int,
        device_pixel_ratio: float,
    ) -> None:
        """Give a newly requested cover a short window before fixing the drag image."""

        if artwork_id <= 0:
            return
        loop = QEventLoop(self)

        def artwork_changed(changed_id: int) -> None:
            if changed_id == artwork_id:
                loop.quit()

        self._artwork_provider.artworkChanged.connect(artwork_changed)
        try:
            if (
                self._artwork_provider.pixmap(
                    artwork_id,
                    LAYOUT.playback_row_artwork_size,
                    device_pixel_ratio,
                )
                is not None
            ):
                return
            timeout = QTimer(loop)
            timeout.setSingleShot(True)
            timeout.setInterval(_DRAG_ARTWORK_WAIT_MS)
            timeout.timeout.connect(loop.quit)
            timeout.start()
            loop.exec(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        finally:
            self._artwork_provider.artworkChanged.disconnect(artwork_changed)

    def save_layout(self) -> None:
        """Persist column order, sizes, visibility, and sort state for this table."""

        self._settings.set_global(
            self._header_setting, self.horizontalHeader().saveState()
        )

    def reset_layout(self) -> None:
        """Restore useful bounded defaults without scanning every Track value."""

        header = self.horizontalHeader()
        for logical_index in range(header.count()):
            visual_index = header.visualIndex(logical_index)
            if visual_index != logical_index:
                header.moveSection(visual_index, logical_index)
        self._apply_default_header_layout()
        self.sortByColumn(self._default_sort_column, Qt.SortOrder.AscendingOrder)
        self.save_layout()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.setAccessibleName(self.tr("Tracks"))
        super().changeEvent(event)

    def _current_changed(
        self,
        current: QModelIndex,
        _previous: QModelIndex,
    ) -> None:
        track = self._track_model.track_at(current)
        if track is not None:
            self.currentTrackChanged.emit(track)

    def _activated(self, index: QModelIndex) -> None:
        track = self._track_model.track_at(index)
        if track is not None:
            self.trackActivated.emit(track)

    def _apply_default_header_layout(self) -> None:
        for column in TrackColumn:
            self.setColumnWidth(column, track_column_default_width(column))
            self.setColumnHidden(
                column,
                not (
                    track_column_default_visible(column)
                    or column in self._context_columns
                ),
            )
        header = self.horizontalHeader()
        artwork_visual_index = header.visualIndex(TrackColumn.ARTWORK)
        if artwork_visual_index != 0:
            header.moveSection(artwork_visual_index, 0)
        if TrackColumn.PLAYLIST_POSITION in self._context_columns:
            position_visual_index = header.visualIndex(TrackColumn.PLAYLIST_POSITION)
            if position_visual_index != 1:
                header.moveSection(position_visual_index, 1)
        self._apply_sync_selection_column()

    def _set_sync_selection_enabled(self, enabled: bool) -> None:
        self._sync_selection_enabled = enabled
        self._apply_sync_selection_column()

    def _apply_sync_selection_column(self) -> None:
        self.setColumnHidden(
            TrackColumn.SYNC_SELECTION, not self._sync_selection_enabled
        )
        if self._sync_selection_enabled:
            header = self.horizontalHeader()
            header.moveSection(header.visualIndex(TrackColumn.SYNC_SELECTION), 0)

    def _theme_changed(self, _theme: str) -> None:
        self.viewport().update()

    def _artwork_changed(self, artwork_id: int) -> None:
        """Repaint only matching visible artwork cells after an async load."""

        if self.isColumnHidden(TrackColumn.ARTWORK):
            return
        model = self.model()
        first_row = self.rowAt(0)
        if first_row < 0:
            return
        last_row = self.rowAt(max(0, self.viewport().height() - 1))
        if last_row < 0:
            last_row = model.rowCount() - 1
        for row in range(first_row, last_row + 1):
            index = model.index(row, TrackColumn.ARTWORK)
            if index.data(TrackRole.ARTWORK_ID) == artwork_id:
                self.viewport().update(self.visualRect(index))

    def _artwork_cache_cleared(self) -> None:
        self.viewport().update()

    def _schedule_layout_save(self, *_args: object) -> None:
        self._header_save_timer.start()

    def _show_column_menu(self, position: QPoint) -> None:
        menu = self._build_column_menu(position)
        menu.exec(self.horizontalHeader().mapToGlobal(position))

    def _build_column_menu(self, position: QPoint) -> QMenu:
        """Build the Original-style task hierarchy for one header position."""

        menu = QMenu(self)
        menu.setAccessibleName(self.tr("Track column options"))
        header = self.horizontalHeader()
        clicked_logical = header.logicalIndexAt(position)
        try:
            clicked_column = TrackColumn(clicked_logical)
        except ValueError:
            clicked_column = None

        if clicked_column is not None:
            label = self._column_label(clicked_column)
            hide = menu.addAction(self.tr('Hide "{column}"').format(column=label))
            hide.setEnabled(
                clicked_column not in (TrackColumn.TITLE, TrackColumn.SYNC_SELECTION)
                and self._visible_column_count() > 1
            )
            hide.triggered.connect(
                lambda _checked=False, column=clicked_column: self._set_column_visible(
                    column, False
                )
            )
            menu.addSeparator()

            resize = menu.addAction(self.tr("Resize Column to Fit"))
            resize.triggered.connect(
                lambda _checked=False, column=clicked_column: (
                    self._resize_column_to_fit(column)
                )
            )

        resize_all = menu.addAction(self.tr("Resize All Columns to Fit"))
        resize_all.triggered.connect(self._resize_all_columns_to_fit)
        menu.addSeparator()

        add_menu = menu.addMenu(self.tr("Add Column"))
        any_available = False
        for group_label, columns in track_column_groups():
            hidden_columns = tuple(
                column
                for column in columns
                if column is not TrackColumn.SYNC_SELECTION
                and self.isColumnHidden(column)
            )
            if not hidden_columns:
                continue
            any_available = True
            group_menu = add_menu.addMenu(self.tr(group_label))
            for column in hidden_columns:
                show = group_menu.addAction(self._column_label(column))
                show.triggered.connect(
                    lambda _checked=False, column=column: self._set_column_visible(
                        column, True
                    )
                )

        if not any_available:
            all_shown = add_menu.addAction(self.tr("(all columns shown)"))
            all_shown.setEnabled(False)

        menu.addSeparator()
        reset = menu.addAction(self.tr("Reset Columns"))
        reset.triggered.connect(self.reset_layout)
        return menu

    def _set_column_visible(self, column: TrackColumn, visible: bool) -> None:
        if column is TrackColumn.SYNC_SELECTION:
            return
        if column is TrackColumn.TITLE and not visible:
            return
        hidden = not visible
        if self.isColumnHidden(column) == hidden:
            return
        self.setColumnHidden(column, hidden)
        self.save_layout()

    def _resize_column_to_fit(self, column: TrackColumn) -> None:
        self.setColumnWidth(column, self._fitted_column_width(column))
        self.save_layout()

    def _resize_all_columns_to_fit(self, _checked: bool = False) -> None:
        for column in TrackColumn:
            if not self.isColumnHidden(column):
                self.setColumnWidth(column, self._fitted_column_width(column))
        self.save_layout()

    def _fitted_column_width(self, column: TrackColumn) -> int:
        """Measure a representative row sample so large Libraries stay responsive."""

        header = self.horizontalHeader()
        horizontal_padding = 2 * LAYOUT.space_sm
        header_width = (
            header.fontMetrics().horizontalAdvance(self._column_label(column))
            + horizontal_padding
            + LAYOUT.icon_size
        )
        content_width = 0
        model = self.model()
        for row in self._sampled_rows(model.rowCount()):
            value = model.data(
                model.index(row, column),
                Qt.ItemDataRole.DisplayRole,
            )
            if value is not None:
                content_width = max(
                    content_width,
                    self.fontMetrics().horizontalAdvance(str(value))
                    + horizontal_padding,
                )
        desired_width = max(header_width, content_width)
        return max(
            header.minimumSectionSize(),
            min(_MAXIMUM_FITTED_COLUMN_WIDTH, desired_width),
        )

    @staticmethod
    def _sampled_rows(row_count: int) -> range | tuple[int, ...]:
        if row_count <= _COLUMN_WIDTH_SAMPLE_LIMIT:
            return range(row_count)
        step = (row_count - 1) / (_COLUMN_WIDTH_SAMPLE_LIMIT - 1)
        return tuple(
            round(sample * step) for sample in range(_COLUMN_WIDTH_SAMPLE_LIMIT)
        )

    def _column_label(self, column: TrackColumn) -> str:
        label = self.model().headerData(
            column,
            Qt.Orientation.Horizontal,
            Qt.ItemDataRole.DisplayRole,
        )
        return "" if label is None else str(label)

    def _visible_column_count(self) -> int:
        return sum(not self.isColumnHidden(column) for column in TrackColumn)
