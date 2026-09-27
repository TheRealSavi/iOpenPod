"""One explicit Track selection and context menu for Library surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from time import monotonic
from typing import TYPE_CHECKING

from PySide6.QtCore import (
    QEvent,
    QItemSelection,
    QItemSelectionModel,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QPoint,
    QSortFilterProxyModel,
    Qt,
    Signal,
    Slot,
)
from PySide6.QtGui import QAction, QKeySequence, QMouseEvent, QPalette, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QSlider,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from iOpenPod.app.core.settings.definitions import (
    LIBRARY_DOUBLE_CLICK_SHORTCUT,
    LibraryDoubleClickShortcut,
)
from iOpenPod.app.library_workspace import EditRevision, LibraryWorkspace, TrackUpdate
from iOpenPod.app.metadata_fields import field_value
from iOpenPod.app.models.album_list_model import AlbumRole, AlbumSummary
from iOpenPod.app.models.collection_list_model import (
    CollectionSummary,
    collection_key_for_track,
)
from iOpenPod.app.models.track_order import album_track_sort_key
from iOpenPod.app.models.track_table_model import TrackRole
from iOpenPod.app.track_conversion import podcast_conversion_needed
from iOpenPod.app.track_playback_policy import requires_track_playback_policy
from iOpenPod.GUI.dialogs.metadata_editor import MetadataEditorDialog
from iOpenPod.GUI.dialogs.playlist_editor import PlaylistEditorDialog
from iOpenPod.GUI.presentation.icons import glyph_icon
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.track_table import TrackTable
from iPodDB.library import (
    ContentAdvisory,
    MediaKind,
    MetadataValue,
    PlaylistKind,
    PlaylistSortOrder,
    Track,
    TrackFieldEdit,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from iOpenPod.app.core.settings.service import SettingsService
    from iOpenPod.app.device_controller import DeviceController
    from iOpenPod.app.playback_controller import PlaybackController
    from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider


type ShortcutSpec = str | QKeySequence.StandardKey

_EDIT_SHORTCUT: ShortcutSpec = "Ctrl+E"
_COPY_SHORTCUT: ShortcutSpec = QKeySequence.StandardKey.Copy
_ENQUEUE_SHORTCUT: ShortcutSpec = "Ctrl+Q"
_PLAY_NEXT_SHORTCUT: ShortcutSpec = "Ctrl+Shift+Q"
_MOVE_UP_SHORTCUT: ShortcutSpec = "Ctrl+Up"
_MOVE_DOWN_SHORTCUT: ShortcutSpec = "Ctrl+Down"
_VOLUME_ZERO_MAGNET_THRESHOLD = 12


@dataclass(frozen=True, slots=True)
class TrackSelection:
    tracks: tuple[Track, ...]
    revision: EditRevision
    playlist_id: int | None = None
    entry_ids: tuple[str, ...] = ()
    reorderable: bool = False

    @property
    def track_ids(self) -> tuple[int, ...]:
        return tuple(dict.fromkeys(t.track_id for t in self.tracks))


@dataclass(frozen=True, slots=True)
class _DoubleClickSelection:
    view: QAbstractItemView
    index: QPersistentModelIndex
    indices: QItemSelection
    selection: TrackSelection
    pressed_at: float


class TrackActions(QObject):
    playlistCreated = Signal(int)
    trackExportRequested = Signal(object)

    def __init__(
        self,
        workspace: LibraryWorkspace,
        playback: PlaybackController,
        parent: QWidget,
        *,
        settings: SettingsService | None = None,
        device_controller: DeviceController | None = None,
        artwork_provider: ArtworkPixmapProvider | None = None,
    ) -> None:
        super().__init__(parent)
        self.workspace, self.playback, self.window = workspace, playback, parent
        self._settings = settings
        self._device_controller = device_controller
        self._artwork_provider = artwork_provider
        self._double_click_selection: _DoubleClickSelection | None = None

    def install(self, view: QAbstractItemView) -> None:
        view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        view.customContextMenuRequested.connect(self._menu_requested)
        view.doubleClicked.connect(self._double_clicked)
        view.viewport().installEventFilter(self)
        view.installEventFilter(self)
        for sequence, action in (
            (_EDIT_SHORTCUT, "edit"),
            (_COPY_SHORTCUT, "copy"),
            (_ENQUEUE_SHORTCUT, "enqueue"),
            (_PLAY_NEXT_SHORTCUT, "play_next"),
            (_MOVE_UP_SHORTCUT, "move_up"),
            (_MOVE_DOWN_SHORTCUT, "move_down"),
        ):
            shortcut = QShortcut(_key_sequence(sequence), view)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.setProperty("trackAction", action)
            shortcut.activated.connect(self._shortcut_activated)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.KeyPress:
            self._double_click_selection = None
        elif event.type() == QEvent.Type.MouseButtonPress and isinstance(
            event, QMouseEvent
        ):
            self._double_click_selection = None
            view = watched.parent()
            if (
                isinstance(view, QAbstractItemView)
                and event.button() == Qt.MouseButton.LeftButton
                and event.modifiers() == Qt.KeyboardModifier.NoModifier
            ):
                index = view.indexAt(event.position().toPoint())
                selection_model = view.selectionModel()
                if index.isValid() and selection_model.isSelected(index):
                    selection = self.selection(view)
                    if len(selection.tracks) > 1:
                        # Extended selection collapses on the first click's release.
                        # Retain its Track occurrences only for this double click.
                        self._double_click_selection = _DoubleClickSelection(
                            view,
                            QPersistentModelIndex(index),
                            selection_model.selection(),
                            selection,
                            monotonic(),
                        )
        return super().eventFilter(watched, event)

    @Slot(QModelIndex)
    def _double_clicked(self, index: QModelIndex) -> None:
        view = self.sender()
        if not isinstance(view, QAbstractItemView) or not index.isValid():
            return
        retained = self._double_click_selection
        self._double_click_selection = None
        if (
            retained is not None
            and retained.view is view
            and retained.index == index
            and monotonic() - retained.pressed_at
            <= QApplication.doubleClickInterval() / 1000
        ):
            self._guard(lambda: self._double_click_retained(retained))
            return
        selection_model = view.selectionModel()
        if not selection_model.isSelected(index):
            selection_model.setCurrentIndex(
                index,
                QItemSelectionModel.SelectionFlag.ClearAndSelect
                | QItemSelectionModel.SelectionFlag.Rows,
            )
        selection = self.selection(view)
        if selection.tracks:
            self._guard(lambda: self.double_click(selection))

    def _double_click_retained(self, retained: _DoubleClickSelection) -> None:
        self._require(retained.selection, editing=False)
        retained.view.selectionModel().select(
            retained.indices, QItemSelectionModel.SelectionFlag.ClearAndSelect
        )
        self.double_click(retained.selection)

    def double_click(self, selection: TrackSelection) -> None:
        """Apply the current preference to ordered, explicit Track occurrences."""

        action = LibraryDoubleClickShortcut(
            LIBRARY_DOUBLE_CLICK_SHORTCUT.default
            if self._settings is None
            else self._settings.get(LIBRARY_DOUBLE_CLICK_SHORTCUT)
        )
        match action:
            case LibraryDoubleClickShortcut.ADD_TO_QUEUE:
                self.enqueue(selection)
            case LibraryDoubleClickShortcut.PLAY_NEXT:
                self.play_next(selection)
            case LibraryDoubleClickShortcut.PLAY_NOW:
                self._require(selection, editing=False)
                self.playback.play_now(selection.tracks)
            case LibraryDoubleClickShortcut.EDIT:
                self.edit(selection)

    @Slot(QPoint)
    def _menu_requested(self, point: QPoint) -> None:
        view = self.sender()
        if isinstance(view, QAbstractItemView):
            self._show(view, point)

    @Slot()
    def _shortcut_activated(self) -> None:
        shortcut = self.sender()
        if not isinstance(shortcut, QShortcut):
            return
        view = shortcut.parent()
        if isinstance(view, QAbstractItemView):
            selection = self.selection(view)
            action = shortcut.property("trackAction")
            if action == "edit":
                self._guard(lambda: self.edit(selection))
            elif action == "copy":
                self.copy(selection)
            elif action == "enqueue" and selection.tracks:
                self._guard(lambda: self.enqueue(selection))
            elif action == "play_next" and selection.tracks:
                self._guard(lambda: self.play_next(selection))
            elif action in ("move_up", "move_down") and selection.reorderable:
                direction = "up" if action == "move_up" else "down"
                self._guard(lambda: self.entries(selection, direction))

    def selection(
        self, view: QAbstractItemView, point: QPoint | None = None
    ) -> TrackSelection:
        selection = view.selectionModel()
        if point is not None:
            index = view.indexAt(point)
            if not index.isValid():
                return TrackSelection((), self.workspace.edit_revision)
            if not selection.isSelected(index):
                selection.setCurrentIndex(
                    index,
                    QItemSelectionModel.SelectionFlag.ClearAndSelect
                    | QItemSelectionModel.SelectionFlag.Rows,
                )
        indices = sorted(
            selection.selectedRows()
            if isinstance(view, TrackTable)
            else selection.selectedIndexes(),
            key=lambda i: i.row(),
        )
        tracks: list[Track] = []
        entry_ids: list[str] = []
        playlist = (
            self.workspace.playlist(view.playlist_id)
            if isinstance(view, TrackTable) and view.playlist_id is not None
            else None
        )
        # The table omits dangling references, but retained Playlist entries do
        # not. Map its source rows through the same projection before editing an
        # occurrence, so a missing Track cannot shift removal onto another one.
        visible_entries = (
            ()
            if playlist is None
            else tuple(
                e
                for e in playlist.entries
                if self.workspace.track(e.track_id) is not None
            )
        )
        for index in indices:
            if isinstance(view, TrackTable):
                track = index.data(TrackRole.TRACK)
                if isinstance(track, Track):
                    tracks.append(track)
                model = view.model()
                source = (
                    model.mapToSource(index)
                    if isinstance(model, QSortFilterProxyModel)
                    else index
                )
                if (
                    playlist is not None
                    and playlist.kind is PlaylistKind.PLAYLIST
                    and 0 <= source.row() < len(visible_entries)
                ):
                    entry_ids.append(visible_entries[source.row()].entry_id)
            else:
                summary = index.data(AlbumRole.SUMMARY)
                if isinstance(summary, AlbumSummary):
                    tracks.extend(
                        sorted(
                            (
                                t
                                for t in self.workspace.tracks
                                if t.media_kind is MediaKind.MUSIC
                                and t.album_key == summary.key
                            ),
                            key=album_track_sort_key,
                        )
                    )
                elif isinstance(summary, CollectionSummary):
                    tracks.extend(
                        sorted(
                            (
                                t
                                for t in self.workspace.tracks
                                if collection_key_for_track(t, summary.kind)
                                == summary.key
                            ),
                            key=album_track_sort_key,
                        )
                    )
        if not isinstance(view, TrackTable):
            tracks = list({t.track_id: t for t in tracks}.values())
        reorderable = (
            isinstance(view, TrackTable)
            and playlist is not None
            and playlist.kind is PlaylistKind.PLAYLIST
            and playlist.sort_order
            in (PlaylistSortOrder.DEFAULT, PlaylistSortOrder.MANUAL)
            and view.horizontalHeader().sortIndicatorSection() < 0
            and view.model().rowCount() == len(playlist.entries)
        )
        return TrackSelection(
            tuple(tracks),
            self.workspace.edit_revision,
            None if playlist is None else playlist.playlist_id,
            tuple(entry_ids),
            reorderable,
        )

    def _show(self, view: QAbstractItemView, point: QPoint) -> None:
        selection = self.selection(view, point)
        if selection.tracks:
            menu = self.build_menu(selection)
            menu.exec(view.viewport().mapToGlobal(point))
            menu.deleteLater()

    @Slot(object, QPoint)
    def show_track(self, value: object, global_position: QPoint) -> None:
        """Show the shared context menu for one Track outside an item view."""

        if not isinstance(value, Track):
            return
        track = self.workspace.track(value.track_id)
        if track is None:
            return
        menu = self.build_menu(TrackSelection((track,), self.workspace.edit_revision))
        menu.exec(global_position)
        menu.deleteLater()

    def _guard(self, action: Callable[[], object]) -> None:
        try:
            action()
        except ValueError as error:
            QMessageBox.warning(
                self.window, self.tr("Library action unavailable"), str(error)
            )

    def _require(self, selection: TrackSelection, *, editing: bool = True) -> None:
        if editing:
            self.workspace.require_revision(selection.revision)
        elif selection.revision != self.workspace.edit_revision:
            raise ValueError("The Library changed. Select the tracks again.")
        if not selection.tracks or any(
            self.workspace.track(t.track_id) != t for t in selection.tracks
        ):
            raise ValueError("The selected tracks changed. Select them again.")

    def build_menu(self, selection: TrackSelection) -> QMenu:
        menu = QMenu(self.window)
        menu.setObjectName("trackContextMenu")
        editable = (
            bool(selection.tracks)
            and self.workspace.snapshot is not None
            and not self.workspace.locked
        )

        def add(
            parent: QMenu,
            text: str,
            action: Callable[[], object],
            *,
            enabled: bool = True,
            shortcut: ShortcutSpec | None = None,
        ) -> QAction:
            item = parent.addAction(text)
            item.setEnabled(enabled)
            if shortcut is not None:
                item.setShortcut(_key_sequence(shortcut))
                item.setShortcutVisibleInContextMenu(True)
            item.triggered.connect(lambda _checked=False: self._guard(action))
            return item

        add(
            menu,
            self.tr("Edit Metadata…"),
            lambda: self.edit(selection),
            enabled=editable,
            shortcut=_EDIT_SHORTCUT,
        )
        add(
            menu,
            self.tr("Convert to Podcast"),
            lambda: self.convert_to_podcast(selection),
            enabled=(
                editable
                and self._podcasts_supported()
                and any(podcast_conversion_needed(track) for track in selection.tracks)
            ),
        )
        chaptered = menu.addAction(self.tr("Convert to a single chaptered track"))
        chaptered.setEnabled(False)
        chaptered.setToolTip(self.tr("Chaptered-track conversion is coming later."))
        play_next = add(
            menu,
            self.tr("Play Next"),
            lambda: self.play_next(selection),
            enabled=bool(selection.tracks),
            shortcut=_PLAY_NEXT_SHORTCUT,
        )
        enqueue = add(
            menu,
            self.tr("Add to Queue"),
            lambda: self.enqueue(selection),
            enabled=bool(selection.tracks),
            shortcut=_ENQUEUE_SHORTCUT,
        )
        for item, glyph in ((play_next, "play-next"), (enqueue, "play-last")):
            item.setIcon(
                glyph_icon(
                    glyph,
                    LAYOUT.icon_size,
                    menu.palette().color(QPalette.ColorRole.Text),
                    menu.devicePixelRatioF(),
                )
            )
            item.setIconVisibleInMenu(True)
        menu.addSeparator()
        playlists = menu.addMenu(self.tr("Add to Playlist"))
        playlists.setEnabled(editable)
        add(playlists, self.tr("New Playlist…"), lambda: self.new_playlist(selection))
        regular = tuple(
            p for p in self.workspace.playlists if p.kind is PlaylistKind.PLAYLIST
        )
        if regular:
            playlists.addSeparator()
        for playlist in regular:
            add(
                playlists,
                playlist.name,
                partial(self.add_to_playlist, selection, playlist.playlist_id),
            )
        if selection.entry_ids:
            add(
                menu,
                self.tr("Remove from Playlist"),
                lambda: self.entries(selection, "remove"),
                enabled=editable,
            )
            add(
                menu,
                self.tr("Move Up"),
                lambda: self.entries(selection, "up"),
                enabled=editable and selection.reorderable,
                shortcut=_MOVE_UP_SHORTCUT,
            )
            add(
                menu,
                self.tr("Move Down"),
                lambda: self.entries(selection, "down"),
                enabled=editable and selection.reorderable,
                shortcut=_MOVE_DOWN_SHORTCUT,
            )
        menu.addSeparator()
        for path, title in (
            ("metadata.compilation", "Compilation"),
            ("metadata.skip_shuffle", "Skip When Shuffling"),
            ("metadata.remember_position", "Remember Playback Position"),
            ("metadata.checked", "Checked"),
        ):
            values = tuple(bool(field_value(t, path)) for t in selection.tracks)
            unanimous = len(set(values)) == 1
            item = menu.addAction(
                title + (self.tr(" (mixed)") if not unanimous else "")
            )
            item.setCheckable(True)
            item.setChecked(bool(values) and all(values))
            required_playback_flag = path in (
                "metadata.skip_shuffle",
                "metadata.remember_position",
            ) and all(requires_track_playback_policy(t) for t in selection.tracks)
            item.setEnabled(editable and not (required_playback_flag and all(values)))
            if required_playback_flag:
                item.setToolTip(
                    self.tr(
                        "Podcasts and videos keep their place and are skipped "
                        "when shuffling."
                    )
                )
            new_value = not all(values)
            item.triggered.connect(
                lambda _checked=False, p=path, v=new_value: self._guard(
                    lambda: self.apply(selection, p, v)
                )
            )
        for title, path, options in (
            (
                "Rating",
                "rating",
                tuple(
                    ("No Rating" if stars == 0 else "★" * stars, stars * 20)
                    for stars in range(6)
                ),
            ),
            (
                "Content Advisory",
                "metadata.content_advisory",
                tuple((a.value.capitalize(), a) for a in ContentAdvisory),
            ),
        ):
            submenu = menu.addMenu(title)
            submenu.setEnabled(editable)
            for label, value in options:
                item = submenu.addAction(label)
                item.setCheckable(True)
                item.setChecked(
                    all(field_value(t, path) == value for t in selection.tracks)
                )
                item.triggered.connect(
                    lambda _checked=False, p=path, v=value: self._guard(
                        lambda: self.apply(selection, p, v)
                    )
                )
        self._add_volume_menu(menu, selection, enabled=editable)
        menu.addSeparator()
        count = len(selection.track_ids)
        add(
            menu,
            self.tr("Remove {count} Track{suffix} from iPod").format(
                count=count,
                suffix="" if count == 1 else "s",
            ),
            lambda: self.remove_tracks(selection),
            enabled=editable,
        )
        add(
            menu,
            self.tr("Export…"),
            lambda: self.export(selection),
            enabled=editable,
        )
        add(
            menu,
            self.tr("Copy as Text"),
            lambda: self.copy(selection),
            shortcut=_COPY_SHORTCUT,
        )
        return menu

    def build_menu_for_tracks(self, tracks: tuple[Track, ...]) -> QMenu | None:
        """Build the shared menu for current workspace versions of device Tracks."""

        current_by_id: dict[int, Track] = {}
        for track in tracks:
            current = self.workspace.track(track.track_id)
            if current is not None:
                current_by_id.setdefault(current.track_id, current)
        if not current_by_id:
            return None
        return self.build_menu(
            TrackSelection(
                tuple(current_by_id.values()),
                self.workspace.edit_revision,
            )
        )

    def edit(self, selection: TrackSelection) -> None:
        self._require(selection)
        dialog = MetadataEditorDialog(
            self.workspace,
            selection.track_ids,
            self.window,
            artwork_provider=self._artwork_provider,
        )
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.open()

    def remove_tracks(self, selection: TrackSelection) -> None:
        self._require(selection)
        self.workspace.remove_tracks(selection.track_ids, selection.revision)

    def convert_to_podcast(self, selection: TrackSelection) -> None:
        self._require(selection)
        if not self._podcasts_supported():
            raise ValueError("This iPod does not support Podcasts.")
        self.workspace.convert_tracks_to_podcasts(
            selection.track_ids, selection.revision
        )

    def apply(self, selection: TrackSelection, path: str, value: MetadataValue) -> None:
        self._require(selection)
        self.workspace.apply_track_edits(
            tuple(
                TrackUpdate(i, (TrackFieldEdit(path, value),))
                for i in selection.track_ids
            ),
            selection.revision,
        )

    def add_to_playlist(self, selection: TrackSelection, playlist_id: int) -> None:
        self._require(selection)
        playlist = self.workspace.playlist(playlist_id)
        if playlist is None:
            raise ValueError("The destination Playlist is no longer available.")
        self.workspace.set_tracks(
            playlist_id, (*playlist.track_ids, *(t.track_id for t in selection.tracks))
        )

    def new_playlist(self, selection: TrackSelection) -> None:
        self._require(selection)
        dialog = PlaylistEditorDialog(PlaylistKind.PLAYLIST, parent=self.window)
        try:
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            self._require(selection)
            playlist = self.workspace.create(
                PlaylistKind.PLAYLIST,
                dialog.name.text(),
                description=dialog.description.text(),
                track_ids=tuple(t.track_id for t in selection.tracks),
                sort_order=dialog.sort_order,
            )
            self.playlistCreated.emit(playlist.playlist_id)
        finally:
            dialog.deleteLater()

    def entries(self, selection: TrackSelection, action: str) -> None:
        self._require(selection)
        if selection.playlist_id is None or (
            action != "remove" and not selection.reorderable
        ):
            raise ValueError("Use the Playlist's natural order to move entries.")
        self.workspace.edit_entries(
            selection.playlist_id, selection.entry_ids, action, selection.revision
        )

    def _add_volume_menu(
        self, menu: QMenu, selection: TrackSelection, *, enabled: bool
    ) -> None:
        volume_menu = menu.addMenu(self.tr("Volume Adjustment"))
        volume_menu.setObjectName("volumeAdjustmentMenu")
        volume_menu.setEnabled(enabled)
        native_values = {
            round(track.metadata.volume_adjustment_percent * 255 / 100)
            for track in selection.tracks
        }
        unanimous = next(iter(native_values)) if len(native_values) == 1 else None
        widget = self._volume_slider_widget(selection, unanimous)
        slider_action = QWidgetAction(volume_menu)
        slider_action.setDefaultWidget(widget)
        volume_menu.addAction(slider_action)

    def _volume_slider_widget(
        self, selection: TrackSelection, unanimous: int | None
    ) -> QWidget:
        widget = QWidget()
        widget.setObjectName("volumeAdjustmentWidget")
        widget.setMinimumWidth(230)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        value_label = QLabel(
            self.tr("Mixed values")
            if unanimous is None
            else self._volume_adjustment_label(unanimous)
        )
        value_label.setObjectName("volumeAdjustmentValueLabel")
        value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(value_label)

        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setObjectName("volumeAdjustmentSlider")
        slider.setAccessibleName(self.tr("Volume adjustment"))
        slider.setRange(-255, 255)
        slider.setSingleStep(1)
        slider.setPageStep(16)
        slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        slider.setTickInterval(64)
        slider.setTracking(False)
        slider.setValue(unanimous if unanimous is not None else 0)
        layout.addWidget(slider)

        scale = QHBoxLayout()
        scale.setContentsMargins(0, 0, 0, 0)
        scale.setSpacing(6)
        for text, alignment, stretch in (
            ("\N{MINUS SIGN}100%", Qt.AlignmentFlag.AlignLeft, 0),
            ("0%", Qt.AlignmentFlag.AlignCenter, 1),
            ("+100%", Qt.AlignmentFlag.AlignRight, 0),
        ):
            label = QLabel(text)
            label.setAlignment(alignment)
            scale.addWidget(label, stretch)
        layout.addLayout(scale)

        current_revision = [selection.revision]
        last_applied: list[int | None] = [unanimous]

        def show_value(value: int) -> None:
            value_label.setText(self._volume_adjustment_label(value))

        def magnetize(value: int) -> int:
            return 0 if abs(value) <= _VOLUME_ZERO_MAGNET_THRESHOLD else value

        def slider_moved(value: int) -> None:
            value = magnetize(value)
            if value == 0 and slider.sliderPosition() != 0:
                slider.blockSignals(True)
                slider.setSliderPosition(0)
                slider.blockSignals(False)
            show_value(value)

        def commit(value: int) -> None:
            value = magnetize(value)
            if slider.value() != value:
                slider.blockSignals(True)
                slider.setValue(value)
                slider.setSliderPosition(value)
                slider.blockSignals(False)
            show_value(value)
            if last_applied[0] == value:
                return
            self.workspace.apply_track_edits(
                tuple(
                    TrackUpdate(
                        track_id,
                        (
                            TrackFieldEdit(
                                "metadata.volume_adjustment_percent",
                                value / 255 * 100,
                            ),
                        ),
                    )
                    for track_id in selection.track_ids
                ),
                current_revision[0],
            )
            current_revision[0] = self.workspace.edit_revision
            last_applied[0] = value

        @Slot(int)
        def value_changed(value: int) -> None:
            self._guard(partial(commit, value))

        @Slot()
        def slider_released() -> None:
            self._guard(partial(commit, slider.value()))

        slider.sliderMoved.connect(slider_moved)
        slider.valueChanged.connect(value_changed)
        slider.sliderReleased.connect(slider_released)
        return widget

    def _podcasts_supported(self) -> bool:
        controller = self._device_controller
        active = None if controller is None else controller.active_ipod
        return active is None or active.profile.capabilities.audio.supports_podcasts

    @staticmethod
    def _volume_adjustment_label(value: int) -> str:
        if value == 0:
            return QApplication.translate("TrackActions", "No adjustment (0%)")
        percent = round(value / 255 * 100)
        return f"{percent:+d}%"

    def enqueue(self, selection: TrackSelection) -> None:
        self._require(selection, editing=False)
        for track in selection.tracks:
            self.playback.enqueue(track)

    def play_next(self, selection: TrackSelection) -> None:
        self._require(selection, editing=False)
        self.playback.play_next(selection.tracks)

    def export(self, selection: TrackSelection) -> None:
        self._require(selection, editing=False)
        self.trackExportRequested.emit(selection.tracks)

    def copy(self, selection: TrackSelection) -> None:
        QApplication.clipboard().setText(
            "\n".join("\t".join((t.title, t.artist, t.album)) for t in selection.tracks)
        )


def _key_sequence(shortcut: ShortcutSpec) -> QKeySequence:
    """Resolve platform bindings only after the GUI application exists."""

    return QKeySequence(shortcut)
