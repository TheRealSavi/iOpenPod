"""Compact Library navigation with the shared, editable Playlist tree."""

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QCursor,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QHideEvent,
    QIcon,
    QPalette,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QScrollArea,
    QSizePolicy,
    QTreeView,
    QWidget,
)

from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.models.device import ActiveIPod, DeviceDiscovery
from iOpenPod.app.models.library_drag import TrackSelectionMimeData
from iOpenPod.GUI.navigation import PageId, page_label, page_supported
from iOpenPod.GUI.presentation.device_images import device_pixmap
from iOpenPod.GUI.presentation.i18n.text import tag_changes_available_text
from iOpenPod.GUI.presentation.icons import glyph_icon
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.hover_dropdown import (
    DropdownOpenMode,
    HoverDropdown,
    HoverDropdownGroup,
)
from iOpenPod.GUI.widgets.playlist_tree import PlaylistTree
from iOpenPod.GUI.widgets.themed_buttons import ActionButton, ActionButtonKind
from iPodDB.library import PlaylistKind

_AUDIO_PAGES = (
    PageId.ALBUMS,
    PageId.ARTISTS,
    PageId.GENRES,
    PageId.TRACKS,
    PageId.GENIUS,
    PageId.PODCASTS,
    PageId.AUDIOBOOKS,
)
_VIDEO_PAGES = (
    PageId.MOVIES,
    PageId.TV_SHOWS,
    PageId.MUSIC_VIDEOS,
    PageId.VIDEOS,
)
_MAINTENANCE_PAGES = (PageId.BACKUPS, PageId.NORMALIZE_TAGS)
_PAGE_GLYPHS = {
    PageId.ALBUMS: "album",
    PageId.ARTISTS: "user",
    PageId.GENRES: "grid",
    PageId.TRACKS: "music",
    PageId.GENIUS: "atom",
    PageId.PODCASTS: "broadcast",
    PageId.AUDIOBOOKS: "book",
    PageId.MOVIES: "film",
    PageId.TV_SHOWS: "monitor",
    PageId.MUSIC_VIDEOS: "video",
    PageId.VIDEOS: "video",
    PageId.BACKUPS: "box",
    PageId.NORMALIZE_TAGS: "check-circle",
}
_PLAYLIST_GLYPHS = {
    PlaylistKind.PLAYLIST.value: "playlist",
    PlaylistKind.SMART.value: "smart-playlist",
    PlaylistKind.FOLDER.value: "folder",
}
_SPRING_DELAY_MS = 500


class _NavigationButton(ActionButton):
    """Only the shell's current page changes a navigation selection."""

    def nextCheckState(self) -> None:
        pass


class _PlaylistButton(_NavigationButton):
    """Spring-open on a current Track drag without becoming a drop target itself."""

    dragOpenRequested = Signal(object)

    def __init__(self, workspace: LibraryWorkspace, parent: QWidget) -> None:
        super().__init__(parent=parent, kind=ActionButtonKind.QUIET)
        self._workspace = workspace
        self._data: TrackSelectionMimeData | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(_SPRING_DELAY_MS)
        self._timer.timeout.connect(self._open)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        self._accept_hover(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        self._accept_hover(event)

    def _accept_hover(self, event: QDragMoveEvent) -> None:
        data = event.mimeData()
        if isinstance(data, TrackSelectionMimeData) and data.belongs_to(
            self._workspace
        ):
            if self._data is not data:
                self._data = data
                self._timer.start()
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            self._cancel()
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._cancel()
        event.accept()

    def dropEvent(self, event: QDropEvent) -> None:
        self._cancel()
        event.ignore()

    def hideEvent(self, event: QHideEvent) -> None:
        self._cancel()
        super().hideEvent(event)

    def _cancel(self) -> None:
        self._timer.stop()
        self._data = None

    def _open(self) -> None:
        data = self._data
        if data is not None and data.belongs_to(self._workspace):
            self.dragOpenRequested.emit(data)


class _PlaylistPopup(HoverDropdown):
    """Playlist content; the shared dropdown owns all ordinary interaction."""

    def __init__(
        self,
        workspace: LibraryWorkspace,
        button: _PlaylistButton,
        group: HoverDropdownGroup,
    ) -> None:
        super().__init__(button, group)
        self.setObjectName("compactPlaylistPopup")
        self._workspace = workspace
        self._drag_data: TrackSelectionMimeData | None = None
        self._drag_watch = QTimer(self)
        self._drag_watch.setInterval(100)
        self._drag_watch.timeout.connect(self._check_drag)
        self.dismissed.connect(self._stop_drag)
        self.tree = PlaylistTree(
            workspace,
            self,
            show_add_button=False,
            show_heading=False,
            select_on_navigation=False,
        )
        self.tree.activated.connect(self._activated)
        self.tree.createRequested.connect(self.hide)
        self.tree.editRequested.connect(self.hide)
        self.tree.removeRequested.connect(self.hide)
        self._new_action = QAction(self)
        self._new_action.setProperty("dropdownGlyph", "plus")
        self._new_action.setIcon(
            glyph_icon(
                "plus",
                LAYOUT.icon_size,
                self.palette().color(QPalette.ColorRole.Text),
                self.devicePixelRatioF(),
            )
        )
        self._new_action.setMenu(self.tree.creation_menu)
        self._new = self.add_item(self._new_action)
        self._new.setObjectName("compactNewPlaylist")
        self._scroll = QScrollArea(self)
        self._scroll.setObjectName("compactPlaylistScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setWidget(self.tree)
        view = self.tree.findChild(QTreeView, "playlistTree")
        assert view is not None
        self.set_item_view(view)
        view.expanded.connect(self._schedule_resize)
        view.collapsed.connect(self._schedule_resize)
        self.content_layout.addWidget(self._scroll, 1)
        workspace.changed.connect(self._workspace_changed)
        self.retranslate_ui()

    def open_drag(self, data: TrackSelectionMimeData) -> None:
        if not data.belongs_to(self._workspace):
            return
        self.group.close()
        self._drag_data = data
        self.group.open(self, DropdownOpenMode.DRAG)
        self._drag_watch.start()

    def _stop_drag(self) -> None:
        self._drag_watch.stop()
        self._drag_data = None

    def _schedule_resize(self) -> None:
        QTimer.singleShot(0, self, self.fit)

    def fit(self) -> None:
        self.ensurePolished()
        screen = self.trigger.screen().availableGeometry()
        margins = self.content_layout.contentsMargins()
        height = (
            self._new.sizeHint().height()
            + self.tree.sizeHint().height()
            + self.content_layout.spacing()
            + margins.top()
            + margins.bottom()
            + 2 * (self.frameWidth() + self._scroll.frameWidth())
        )
        self.resize(
            min(320, screen.width()), min(420, max(96, height), screen.height())
        )
        self.place()

    def _check_drag(self) -> None:
        data = self._drag_data
        if (
            data is None
            or not data.belongs_to(self._workspace)
            or not QApplication.mouseButtons()
        ):
            self.hide()
            return
        # PlaylistTree deliberately lets its containing surface own scrolling.
        # Its native view edges lie outside a long popup, so spring drags need
        # to scroll at the visible scroll-area edges instead.
        viewport = self._scroll.viewport()
        point = viewport.mapFromGlobal(QCursor.pos())
        if not viewport.rect().contains(point):
            return
        edge = LAYOUT.control_height_compact
        delta = 0
        if point.y() < edge:
            delta = point.y() - edge
        elif point.y() >= viewport.height() - edge:
            delta = point.y() - (viewport.height() - edge) + 1
        if delta:
            scrollbar = self._scroll.verticalScrollBar()
            scrollbar.setValue(scrollbar.value() + delta)

    def _workspace_changed(self) -> None:
        self._new_action.setEnabled(
            self._workspace.snapshot is not None and not self._workspace.locked
        )
        if self._drag_data is not None and not self._drag_data.belongs_to(
            self._workspace
        ):
            self.hide()
        self._schedule_resize()

    def _activated(self, playlist_id: int) -> None:
        playlist = self._workspace.playlist(playlist_id)
        if playlist is not None and playlist.kind is not PlaylistKind.FOLDER:
            self.group.close(restore_focus=True)

    def retranslate_ui(self) -> None:
        self._new_action.setText(self.tr("New"))
        self._new.setAccessibleName(self.tr("New Playlist"))
        self._workspace_changed()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)


class CompactTopBar(QFrame):
    """Present the shell's navigation intents in one shallow horizontal strip."""

    pageRequested = Signal(str)
    chooseDeviceRequested = Signal()
    syncRequested = Signal()
    scrobbleRequested = Signal()
    reviewChangesRequested = Signal()
    ejectRequested = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        playlists: LibraryWorkspace,
        theme: ThemeManager | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("compactTopBar")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._theme = theme
        self._active_ipod: ActiveIPod | None = None
        self._busy = False
        self._eject_available = False
        self._normalization_count = 0
        self._actions: dict[PageId, QAction] = {}
        self._direct: dict[PageId, ActionButton] = {}

        self._left = QWidget(self)
        left = self._row(self._left)
        self._device = self._button("compactDeviceSummary", self._left)
        self._device.setIconSize(QSize(28, 28))
        self._device.setFixedWidth(LAYOUT.control_height)
        self._dropdowns = HoverDropdownGroup(self)
        self._device_menu = HoverDropdown(self._device, self._dropdowns)
        self._device_menu.setObjectName("compactDeviceMenu")
        self._summary = QAction(self._device_menu)
        self._summary.setCheckable(True)
        self._summary.triggered.connect(
            lambda: self.pageRequested.emit(PageId.DEVICE_SUMMARY.value)
        )
        self._eject = QAction(self._device_menu)
        self._choose = QAction(self._device_menu)
        for action in (self._summary, self._eject, self._choose):
            self._device_menu.add_item(action)
        self._choose.triggered.connect(self.chooseDeviceRequested.emit)
        self._eject.triggered.connect(self.ejectRequested.emit)
        self._sync = self._button("compactSyncWithHost", self._left)
        self._sync.setCheckable(False)
        self._sync.clicked.connect(self.syncRequested.emit)
        self._choose_button = self._button("compactChooseDevice", self._left)
        self._choose_button.setCheckable(False)
        self._choose_button.clicked.connect(self.chooseDeviceRequested.emit)
        left.addWidget(self._device)
        left.addWidget(self._sync)
        left.addWidget(self._choose_button)
        left.addStretch(1)

        self._center = QWidget(self)
        self._center.setObjectName("compactNavigation")
        center = self._row(self._center)
        self._audio = self._button("compactAudio", self._center)
        self._audio_menu = self._page_menu(self._audio, _AUDIO_PAGES)
        self._video = self._button("compactVideo", self._center)
        self._video_menu = self._page_menu(self._video, _VIDEO_PAGES)
        self._playlists = _PlaylistButton(playlists, self._center)
        self._configure_button(self._playlists, "compactPlaylists")
        self._playlist_popup = _PlaylistPopup(
            playlists, self._playlists, self._dropdowns
        )
        self.playlist_tree = self._playlist_popup.tree
        self._playlists.dragOpenRequested.connect(self._playlist_popup.open_drag)
        center.addWidget(self._audio)
        center.addWidget(self._video)
        center.addWidget(self._playlists)
        for page_id in (PageId.START, PageId.PHOTOS, PageId.GAMES):
            name = "Welcome" if page_id is PageId.START else page_id.value.title()
            button = self._button(f"compact{name}", self._center)
            button.clicked.connect(
                lambda _checked=False, page_id=page_id: self.pageRequested.emit(
                    page_id.value
                )
            )
            self._direct[page_id] = button
            center.addWidget(button)

        self._right = QWidget(self)
        right = self._row(self._right)
        right.addStretch(1)
        self._maintenance = self._button("compactMaintenance", self._right)
        self._maintenance_menu = self._page_menu(self._maintenance, _MAINTENANCE_PAGES)
        self._scrobble = QAction(self._maintenance_menu)
        self._scrobble.setEnabled(False)
        self._scrobble.triggered.connect(self.scrobbleRequested.emit)
        self._review = QAction(self._maintenance_menu)
        self._review.setEnabled(False)
        self._review.triggered.connect(self.reviewChangesRequested.emit)
        self._maintenance_menu.add_item(self._scrobble)
        self._maintenance_menu.add_item(self._review)
        self._settings = self._button(
            "compactSettings", self._right, glyph="settings-sliders"
        )
        self._settings.setFixedWidth(LAYOUT.control_height_compact)
        self._settings.clicked.connect(
            lambda: self.pageRequested.emit(PageId.SETTINGS.value)
        )
        right.addWidget(self._maintenance)
        right.addWidget(self._settings)

        self._layout = QGridLayout(self)
        self._layout.setContentsMargins(
            LAYOUT.space_xs, LAYOUT.space_2xs, LAYOUT.space_xs, LAYOUT.space_2xs
        )
        self._layout.setHorizontalSpacing(LAYOUT.space_xs)
        self._layout.setVerticalSpacing(0)
        self._layout.addWidget(self._left, 0, 0)
        self._layout.addWidget(self._center, 0, 1)
        self._layout.addWidget(self._right, 0, 2)
        self._layout.setColumnStretch(0, 1)
        self._layout.setColumnStretch(2, 1)
        for menu in (
            self._audio_menu,
            self._video_menu,
            self._maintenance_menu,
            self._device_menu,
            self.playlist_tree.creation_menu,
        ):
            menu.aboutToShow.connect(self._refresh_menu_icons)
        if theme is not None:
            theme.deviceArtworkChanged.connect(self._refresh_device_image)
        self.retranslate_ui()
        self.set_active_ipod(None)
        self.set_review_visible(False)
        self.set_current_page(PageId.START)
        self._refresh_menu_icons()

    @staticmethod
    def _row(parent: QWidget) -> QHBoxLayout:
        layout = QHBoxLayout(parent)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(LAYOUT.space_2xs)
        return layout

    def _button(
        self, name: str, parent: QWidget, *, glyph: str | None = None
    ) -> ActionButton:
        button = _NavigationButton(
            parent=parent, kind=ActionButtonKind.QUIET, glyph=glyph
        )
        self._configure_button(button, name)
        return button

    @staticmethod
    def _configure_button(button: ActionButton, name: str) -> None:
        button.setObjectName(name)
        button.setProperty("compactNavigation", True)
        button.setFixedHeight(LAYOUT.control_height_compact)
        button.setCheckable(True)

    def _page_menu(
        self, button: ActionButton, pages: tuple[PageId, ...]
    ) -> HoverDropdown:
        menu = HoverDropdown(button, self._dropdowns)
        for page_id in pages:
            action = QAction(page_label(page_id), menu)
            menu.add_item(action)
            action.setData(page_id.value)
            action.setCheckable(True)
            action.triggered.connect(
                lambda _checked=False, page_id=page_id: self.pageRequested.emit(
                    page_id.value
                )
            )
            self._actions[page_id] = action
        return menu

    def _refresh_menu_icons(self) -> None:
        for page_id, action in self._actions.items():
            self._set_action_glyph(action, _PAGE_GLYPHS[page_id])
        for action, glyph in (
            (self._summary, "ipod"),
            (self._choose, "ipod"),
            (self._eject, "eject"),
            (self._scrobble, "broadcast"),
            (self._review, "list"),
        ):
            self._set_action_glyph(action, glyph)
        for action in self.playlist_tree.creation_menu.actions():
            kind = action.data()
            creation_glyph = (
                _PLAYLIST_GLYPHS.get(kind) if isinstance(kind, str) else None
            )
            if creation_glyph is not None:
                self._set_action_glyph(action, creation_glyph)

    @staticmethod
    def _set_action_glyph(action: QAction, glyph: str) -> None:
        action.setProperty("dropdownGlyph", glyph)
        menu = action.parent()
        assert isinstance(menu, QWidget)
        action.setIcon(
            glyph_icon(
                glyph,
                LAYOUT.icon_size,
                menu.palette().color(QPalette.ColorRole.Text),
                menu.devicePixelRatioF(),
            )
        )
        action.setIconVisibleInMenu(True)

    def set_current_page(self, page_id: PageId) -> None:
        self._dropdowns.close()
        self._settings.setChecked(page_id is PageId.SETTINGS)
        self._summary.setChecked(page_id is PageId.DEVICE_SUMMARY)
        for candidate, action in self._actions.items():
            action.setChecked(candidate is page_id)
        for candidate, button in self._direct.items():
            button.setChecked(candidate is page_id)
        if page_id is not PageId.PLAYLISTS:
            self.playlist_tree.clear_selection()

    def set_active_ipod(self, active_ipod: ActiveIPod | None) -> None:
        self._dropdowns.close()
        self._active_ipod = active_ipod
        self._sync.setEnabled(active_ipod is not None)
        self._sync.setVisible(active_ipod is not None)
        self._choose_button.setVisible(active_ipod is None)
        self._actions[PageId.NORMALIZE_TAGS].setEnabled(active_ipod is not None)
        for page_id, action in self._actions.items():
            action.setVisible(self.page_available(page_id))
        for page_id, button in self._direct.items():
            button.setVisible(self.page_available(page_id))
        self._video.setVisible(any(self.page_available(page) for page in _VIDEO_PAGES))
        self._audio.setVisible(any(self.page_available(page) for page in _AUDIO_PAGES))
        self._playlists.setVisible(self.page_available(PageId.PLAYLISTS))
        if active_ipod is None:
            self.set_normalization_count(0)
        self._refresh_device_image()
        self._refresh_device_actions()
        self._balance_columns()

    def page_available(self, page_id: PageId) -> bool:
        active = self._active_ipod
        return page_supported(
            page_id, active.profile if active is not None else None
        ) or (
            page_id is PageId.GENIUS
            and bool(active and (active.genius.collections or active.genius.issues))
        )

    def set_device_discovery(self, discovery: DeviceDiscovery) -> None:
        del discovery

    def set_device_busy(self, busy: bool) -> None:
        self._busy = busy
        self._refresh_device_actions()

    def set_scrobble_available(self, available: bool) -> None:
        self._scrobble.setEnabled(available)

    def set_eject_available(self, available: bool) -> None:
        self._eject_available = available
        self._refresh_device_actions()

    def set_review_available(self, available: bool) -> None:
        self._review.setEnabled(available)

    def set_review_visible(self, visible: bool) -> None:
        self._review.setVisible(visible)

    def set_normalization_count(self, count: int) -> None:
        self._normalization_count = max(0, count)
        label = page_label(PageId.NORMALIZE_TAGS)
        self._actions[PageId.NORMALIZE_TAGS].setText(
            f"{label} ({self._normalization_count})"
            if self._normalization_count
            else label
        )
        self._actions[PageId.NORMALIZE_TAGS].setToolTip(
            tag_changes_available_text(self._normalization_count)
            if self._normalization_count
            else self.tr("Check your Library for more consistent tags.")
        )

    def _refresh_device_actions(self) -> None:
        active = self._active_ipod
        self._summary.setEnabled(active is not None)
        self._choose.setEnabled(not self._busy)
        self._choose_button.setEnabled(not self._busy)
        self._eject.setEnabled(active is not None and self._eject_available)
        self._device.setEnabled(active is not None or not self._busy)
        self._device.setToolTip(
            self.tr("Device") + f" · {active.display_name}"
            if active is not None
            else self.tr("Device actions")
        )
        self._device.setAccessibleName(self.tr("Device"))
        self._sync.setToolTip(
            "" if active is not None else self.tr("Select an Active iPod before Sync.")
        )

    def _refresh_device_image(self) -> None:
        active = self._active_ipod
        self._device.setIcon(
            QIcon(
                device_pixmap(
                    active.profile.product_image
                    if active is not None
                    else "iPodGeneric.png",
                    28,
                    self.devicePixelRatioF(),
                    itunes_107=self._theme is not None
                    and self._theme.itunes_107_artwork,
                )
            )
        )

    def _balance_columns(self) -> None:
        wing = max(self._left.sizeHint().width(), self._right.sizeHint().width())
        self._layout.setColumnMinimumWidth(0, wing)
        self._layout.setColumnMinimumWidth(2, wing)

    def retranslate_ui(self) -> None:
        self._audio.setText(self.tr("Audio") + " ▾")
        self._dropdowns.retranslate_ui()
        self._audio.setAccessibleName(self.tr("Audio"))
        self._video.setText(self.tr("Video") + " ▾")
        self._video.setAccessibleName(self.tr("Video"))
        self._playlists.setText(self.tr("Playlists") + " ▾")
        self._playlists.setAccessibleName(page_label(PageId.PLAYLISTS))
        self._maintenance.setText(self.tr("Maintenance") + " ▾")
        self._maintenance.setAccessibleName(self.tr("Maintenance"))
        self._settings.setAccessibleName(page_label(PageId.SETTINGS))
        self._settings.setToolTip(page_label(PageId.SETTINGS))
        self._sync.setText(self.tr("Sync with Host"))
        self._scrobble.setText(self.tr("Scrobble Now"))
        self._review.setText(self.tr("Review Changes"))
        self._summary.setText(page_label(PageId.DEVICE_SUMMARY))
        self._choose.setText(self.tr("Choose Device"))
        self._choose_button.setText(self.tr("Choose Device"))
        self._eject.setText(self.tr("Eject"))
        for page_id, action in self._actions.items():
            action.setText(page_label(page_id))
        for page_id, button in self._direct.items():
            button.setText(page_label(page_id))
        self.set_normalization_count(self._normalization_count)
        self._refresh_device_actions()
        self._balance_columns()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        elif event.type() in {
            QEvent.Type.DevicePixelRatioChange,
            QEvent.Type.ScreenChangeInternal,
        }:
            self._refresh_device_image()
            self._refresh_menu_icons()
        elif event.type() in {
            QEvent.Type.FontChange,
            QEvent.Type.StyleChange,
            QEvent.Type.PaletteChange,
        }:
            QTimer.singleShot(0, self, self._balance_columns)
            QTimer.singleShot(0, self, self._refresh_menu_icons)
        super().changeEvent(event)

    def hideEvent(self, event: QHideEvent) -> None:
        self._dropdowns.close()
        super().hideEvent(event)
