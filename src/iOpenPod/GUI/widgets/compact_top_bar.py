"""Compact Library navigation with the shared, editable Playlist tree."""

from PySide6.QtCore import QEvent, QObject, QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QCursor,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QHideEvent,
    QIcon,
    QKeyEvent,
    QMouseEvent,
    QPalette,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QMenu,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QTreeView,
    QVBoxLayout,
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


class _DeviceHoverMenu(QFrame):
    """Offer device actions on hover without grabbing clicks on the image."""

    def __init__(self, trigger: ActionButton, actions: tuple[QAction, ...]) -> None:
        super().__init__(
            trigger, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
        )
        self.setObjectName("compactDeviceHoverMenu")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._trigger = trigger
        self._dismiss = QTimer(self)
        self._dismiss.setSingleShot(True)
        self._dismiss.setInterval(180)
        self._dismiss.timeout.connect(self._dismiss_if_outside)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            LAYOUT.space_2xs, LAYOUT.space_2xs, LAYOUT.space_2xs, LAYOUT.space_2xs
        )
        layout.setSpacing(LAYOUT.space_3xs)
        for action in actions:
            button = QToolButton(self)
            button.setProperty("deviceMenuAction", True)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.setIconSize(QSize(LAYOUT.icon_size, LAYOUT.icon_size))
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.setDefaultAction(action)
            layout.addWidget(button)
            action.triggered.connect(self.hide)
        trigger.installEventFilter(self)
        self.installEventFilter(self)

    def _open(self) -> None:
        self._dismiss.stop()
        if self.isVisible() or not self._trigger.isEnabled():
            return
        self.ensurePolished()
        self.adjustSize()
        screen = self._trigger.screen().availableGeometry()
        position = self._trigger.mapToGlobal(QPoint(0, self._trigger.height()))
        position.setX(
            max(screen.left(), min(position.x(), screen.right() - self.width() + 1))
        )
        if position.y() + self.height() > screen.bottom() + 1:
            position.setY(
                max(
                    screen.top(),
                    self._trigger.mapToGlobal(QPoint()).y() - self.height(),
                )
            )
        self.move(position)
        self.show()
        application = QApplication.instance()
        if application is not None:
            application.installEventFilter(self)

    def _dismiss_if_outside(self) -> None:
        position = QCursor.pos()
        if not self.rect().contains(self.mapFromGlobal(position)) and not (
            self._trigger.rect().contains(self._trigger.mapFromGlobal(position))
        ):
            self.hide()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._trigger and event.type() == QEvent.Type.Enter:
            if QApplication.activePopupWidget() is None:
                self._open()
        elif watched is self and event.type() == QEvent.Type.Enter:
            self._dismiss.stop()
        elif watched in (self, self._trigger) and event.type() == QEvent.Type.Leave:
            self._dismiss.start()
        elif self.isVisible():
            if watched is self._trigger and event.type() == QEvent.Type.ToolTip:
                return True
            if (
                event.type() == QEvent.Type.KeyPress
                and isinstance(event, QKeyEvent)
                and event.key() == Qt.Key.Key_Escape
            ):
                self.hide()
                return True
            if (
                event.type() == QEvent.Type.ApplicationDeactivate
                or (
                    event.type() == QEvent.Type.MouseButtonPress
                    and isinstance(watched, QWidget)
                    and watched is not self
                    and not self.isAncestorOf(watched)
                )
                or (
                    watched is self._trigger
                    and event.type()
                    in {
                        QEvent.Type.Hide,
                        QEvent.Type.Move,
                        QEvent.Type.Resize,
                        QEvent.Type.EnabledChange,
                    }
                )
                or (
                    watched is self._trigger.window()
                    and event.type() in {QEvent.Type.Move, QEvent.Type.Resize}
                )
            ):
                self.hide()
        return super().eventFilter(watched, event)

    def hideEvent(self, event: QHideEvent) -> None:
        self._dismiss.stop()
        application = QApplication.instance()
        if application is not None:
            application.removeEventFilter(self)
        super().hideEvent(event)


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


class _PlaylistPopup(QFrame):
    """A bounded tree popup; drag-open windows never grab the active drag."""

    def __init__(self, workspace: LibraryWorkspace, button: _PlaylistButton) -> None:
        super().__init__(button, Qt.WindowType.Popup)
        self.setObjectName("compactPlaylistPopup")
        self._workspace = workspace
        self._button = button
        self._drag_data: TrackSelectionMimeData | None = None
        self._drag_watch = QTimer(self)
        self._drag_watch.setInterval(100)
        self._drag_watch.timeout.connect(self._check_drag)
        self._leave_timer = QTimer(self)
        self._leave_timer.setSingleShot(True)
        self._leave_timer.setInterval(_SPRING_DELAY_MS)
        self._leave_timer.timeout.connect(self.hide)

        self.tree = PlaylistTree(
            workspace, self, show_add_button=False, show_heading=False
        )
        self.tree.activated.connect(self._activated)
        self.tree.createRequested.connect(self.hide)
        self.tree.editRequested.connect(self.hide)
        self.tree.removeRequested.connect(self.hide)
        self._new = ActionButton(parent=self, kind=ActionButtonKind.QUIET, glyph="plus")
        self._new.setObjectName("compactNewPlaylist")
        self._new.setMenu(self.tree.creation_menu)
        self._scroll = QScrollArea(self)
        self._scroll.setObjectName("compactPlaylistScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setWidget(self.tree)
        view = self.tree.findChild(QTreeView, "playlistTree")
        if view is not None:
            view.expanded.connect(self._schedule_resize)
            view.collapsed.connect(self._schedule_resize)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            LAYOUT.space_2xs, LAYOUT.space_2xs, LAYOUT.space_2xs, LAYOUT.space_2xs
        )
        layout.setSpacing(LAYOUT.space_2xs)
        layout.addWidget(self._new)
        layout.addWidget(self._scroll, 1)
        workspace.changed.connect(self._workspace_changed)
        self.retranslate_ui()

    def open(self, data: TrackSelectionMimeData | None = None) -> None:
        self.hide()
        dragging = data is not None
        # Qt.Popup grabs the pointer. A nonactivating Tool window lets the native
        # drag continue from its source into the same Playlist view as the sidebar.
        flags = (
            Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
            if dragging
            else Qt.WindowType.Popup
        )
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, dragging)
        self._drag_data = data
        self._resize_to_contents()
        application = QApplication.instance()
        if application is not None:
            application.installEventFilter(self)
        # The hover coordinator installs its filter on Show, so heading clicks
        # are consumed before this popup's outside-click dismissal sees them.
        self.show()
        if dragging:
            self._drag_watch.start()
        else:
            view = self.tree.findChild(QTreeView, "playlistTree")
            if view is not None:
                view.setFocus(Qt.FocusReason.PopupFocusReason)

    def _schedule_resize(self) -> None:
        QTimer.singleShot(0, self, self._resize_to_contents)

    def _resize_to_contents(self) -> None:
        screen = self._button.screen().availableGeometry()
        width = min(320, screen.width())
        layout = self.layout()
        assert layout is not None
        margins = layout.contentsMargins()
        content_height = (
            self._new.sizeHint().height()
            + self.tree.sizeHint().height()
            + layout.spacing()
            + margins.top()
            + margins.bottom()
            + 2 * (self.frameWidth() + self._scroll.frameWidth())
        )
        height = min(420, max(96, content_height), screen.height())
        self.resize(width, height)
        position = self._button.mapToGlobal(QPoint(0, self._button.height()))
        position.setX(max(screen.left(), min(position.x(), screen.right() - width + 1)))
        if position.y() + height > screen.bottom() + 1:
            position.setY(
                max(screen.top(), self._button.mapToGlobal(QPoint()).y() - height)
            )
        self.move(position)

    def hideEvent(self, event: QHideEvent) -> None:
        self._drag_watch.stop()
        self._leave_timer.stop()
        self._drag_data = None
        application = QApplication.instance()
        if application is not None:
            application.removeEventFilter(self)
        super().hideEvent(event)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            event.type() == QEvent.Type.KeyPress
            and isinstance(event, QKeyEvent)
            and event.key() == Qt.Key.Key_Escape
            and QApplication.activePopupWidget() in (None, self)
        ):
            self.hide()
            return True
        if (
            event.type() == QEvent.Type.MouseButtonPress
            and isinstance(watched, QWidget)
            and watched is not self
            and not self.isAncestorOf(watched)
        ):
            self.hide()
        if event.type() == QEvent.Type.ApplicationDeactivate:
            self.hide()
        if self._drag_data is not None:
            if event.type() in {QEvent.Type.Drop, QEvent.Type.MouseButtonRelease}:
                QTimer.singleShot(0, self, self.hide)
            elif isinstance(event, QDragMoveEvent) and isinstance(watched, QWidget):
                point = watched.mapToGlobal(event.position().toPoint())
                inside = self.geometry().contains(
                    point
                ) or self._button.rect().contains(self._button.mapFromGlobal(point))
                if inside:
                    self._leave_timer.stop()
                elif not self._leave_timer.isActive():
                    self._leave_timer.start()
        return super().eventFilter(watched, event)

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
        self._new.setEnabled(
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
            self.hide()

    def retranslate_ui(self) -> None:
        self._new.setText(self.tr("New"))
        self._new.setAccessibleName(self.tr("New Playlist"))
        self._workspace_changed()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)


class _DropdownHover(QObject):
    """Keep headings inert to clicks, including while Qt popups grab the mouse."""

    opening = Signal()

    def __init__(
        self, parent: QWidget, menus: dict[ActionButton, QMenu | _PlaylistPopup]
    ) -> None:
        super().__init__(parent)
        self._menus = menus
        self._active: ActionButton | None = None
        self._blocked: ActionButton | None = None
        self._opening_on_hover = False
        self._pointer_active = False
        self._dismiss = QTimer(self)
        self._dismiss.setSingleShot(True)
        self._dismiss.setInterval(180)
        self._dismiss.timeout.connect(self._dismiss_if_outside)
        for button, popup in menus.items():
            button.installEventFilter(self)
            popup.installEventFilter(self)

    def close(self) -> None:
        self._close_other_menus(None)

    def _open(self, button: ActionButton) -> None:
        if (
            button is self._blocked
            or not button.isEnabled()
            or not button.isVisible()
            or QApplication.mouseButtons()
        ):
            return
        popup = self._menus[button]
        current = QApplication.activePopupWidget()
        if current is not None and not any(
            current is menu or current in menu.findChildren(QMenu)
            for menu in self._menus.values()
        ):
            return
        self._dismiss.stop()
        self._pointer_active = True
        if popup.isVisible():
            return
        self.close()
        self._opening_on_hover = True
        try:
            if isinstance(popup, QMenu):
                popup.popup(button.mapToGlobal(QPoint(0, button.height())))
            else:
                popup.open()
        finally:
            self._opening_on_hover = False

    def _watch(self, button: ActionButton) -> None:
        if self._active is button:
            return
        self._close_other_menus(button)
        self._active = button
        self._blocked = None
        self._pointer_active = self._opening_on_hover
        self._dismiss.stop()
        self.opening.emit()
        application = QApplication.instance()
        if application is not None:
            application.installEventFilter(self)

    def _close_other_menus(self, button: ActionButton | None) -> None:
        for other, popup in self._menus.items():
            if other is not button:
                for nested in popup.findChildren(QMenu):
                    nested.hide()
                popup.hide()

    def _button_at(self, position: QPoint) -> ActionButton | None:
        return next(
            (
                button
                for button in self._menus
                if button.isVisible()
                and button.isEnabled()
                and button.rect().contains(button.mapFromGlobal(position))
            ),
            None,
        )

    def _inside_active(self, position: QPoint) -> bool:
        button = self._active
        if button is None:
            return False
        popup = self._menus[button]
        nested = QApplication.activePopupWidget()
        return (
            button.rect().contains(button.mapFromGlobal(position))
            or popup.rect().contains(popup.mapFromGlobal(position))
            # Keep the Playlist New/context menus usable, including by keyboard.
            or (nested is not None and nested in popup.findChildren(QMenu))
        )

    def _dismiss_if_outside(self) -> None:
        if (
            self._active is not None
            and self._pointer_active
            and not self._inside_active(QCursor.pos())
        ):
            self.close()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            event.type()
            in {
                QEvent.Type.MouseButtonPress,
                QEvent.Type.MouseButtonRelease,
                QEvent.Type.MouseButtonDblClick,
            }
            and isinstance(event, QMouseEvent)
            and self._button_at(event.globalPosition().toPoint()) is not None
        ):
            event.accept()
            return True
        if isinstance(watched, ActionButton) and watched in self._menus:
            if event.type() == QEvent.Type.Enter:
                self._open(watched)
            elif event.type() == QEvent.Type.Leave:
                if self._button_at(QCursor.pos()) is not watched:
                    self._blocked = None
                if self._active is not None and self._pointer_active:
                    self._dismiss.start()
        for button, popup in self._menus.items():
            if watched is popup:
                if event.type() == QEvent.Type.Show:
                    # The drag popup owns its own lifetime and never grabs input.
                    if popup.windowType() == Qt.WindowType.Popup:
                        self._watch(button)
                elif event.type() == QEvent.Type.Hide and self._active is button:
                    self._blocked = self._button_at(QCursor.pos())
                    self._active = None
                    self._dismiss.stop()
                    application = QApplication.instance()
                    if application is not None:
                        application.removeEventFilter(self)
        if self._active is not None:
            if event.type() == QEvent.Type.MouseMove and isinstance(event, QMouseEvent):
                if not event.buttons():
                    self._pointer_active = True
                    position = event.globalPosition().toPoint()
                    hovered_button = self._button_at(position)
                    if hovered_button is not self._blocked:
                        self._blocked = None
                    if hovered_button is not None:
                        previous = self._active
                        self._open(hovered_button)
                        if self._active is not previous:
                            return True
                    elif self._inside_active(position):
                        self._dismiss.stop()
                    elif not self._dismiss.isActive():
                        self._dismiss.start()
            elif event.type() == QEvent.Type.Leave and self._pointer_active:
                self._dismiss.start()
            elif event.type() == QEvent.Type.KeyPress:
                self._pointer_active = False
                self._dismiss.stop()
            elif event.type() == QEvent.Type.ApplicationDeactivate:
                self.close()
        return super().eventFilter(watched, event)


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
        self._current_page = PageId.ALBUMS
        self._actions: dict[PageId, QAction] = {}
        self._direct: dict[PageId, ActionButton] = {}

        self._left = QWidget(self)
        left = self._row(self._left)
        self._device = self._button("compactDeviceSummary", self._left)
        self._device.setIconSize(QSize(28, 28))
        self._device.setFixedWidth(LAYOUT.control_height)
        self._device.clicked.connect(self._device_clicked)
        self._device_menu = QMenu(self._device)
        self._eject = self._device_menu.addAction("")
        self._choose = self._device_menu.addAction("")
        self._device_hover_menu = _DeviceHoverMenu(
            self._device, (self._eject, self._choose)
        )
        self._choose.triggered.connect(self.chooseDeviceRequested.emit)
        self._eject.triggered.connect(self.ejectRequested.emit)
        self._device.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._device.installEventFilter(self)
        self._device.customContextMenuRequested.connect(self._show_device_menu)
        self._sync = self._button("compactSyncWithHost", self._left)
        self._sync.setCheckable(False)
        self._sync.clicked.connect(self.syncRequested.emit)
        left.addWidget(self._device)
        left.addWidget(self._sync)
        left.addStretch(1)

        self._center = QWidget(self)
        self._center.setObjectName("compactNavigation")
        center = self._row(self._center)
        self._audio = self._button("compactAudio", self._center)
        self._audio.setMenu(self._page_menu(self._audio, _AUDIO_PAGES))
        self._video = self._button("compactVideo", self._center)
        self._video.setMenu(self._page_menu(self._video, _VIDEO_PAGES))
        self._playlists = _PlaylistButton(playlists, self._center)
        self._configure_button(self._playlists, "compactPlaylists")
        self._playlist_popup = _PlaylistPopup(playlists, self._playlists)
        self.playlist_tree = self._playlist_popup.tree
        self._playlists.clicked.connect(self._toggle_playlists)
        self._playlists.dragOpenRequested.connect(self._playlist_popup.open)
        center.addWidget(self._audio)
        center.addWidget(self._video)
        center.addWidget(self._playlists)
        for page_id in (PageId.PHOTOS, PageId.GAMES):
            button = self._button(f"compact{page_id.value.title()}", self._center)
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
        self._scrobble = self._maintenance_menu.addAction("")
        self._scrobble.setEnabled(False)
        self._scrobble.triggered.connect(self.scrobbleRequested.emit)
        self._review_separator = self._maintenance_menu.addSeparator()
        self._review = self._maintenance_menu.addAction("")
        self._review.setEnabled(False)
        self._review.triggered.connect(self.reviewChangesRequested.emit)
        self._maintenance.setMenu(self._maintenance_menu)
        self._settings = self._button(
            "compactSettings", self._right, glyph="settings-sliders"
        )
        self._settings.setFixedWidth(LAYOUT.control_height_compact)
        self._settings.clicked.connect(
            lambda: self.pageRequested.emit(PageId.SETTINGS.value)
        )
        right.addWidget(self._maintenance)
        right.addWidget(self._settings)

        self._dropdown_hover = _DropdownHover(
            self,
            {
                self._audio: self._audio.menu(),
                self._video: self._video.menu(),
                self._playlists: self._playlist_popup,
                self._maintenance: self._maintenance_menu,
            },
        )
        self._dropdown_hover.opening.connect(self._device_hover_menu.hide)

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
            self._audio.menu(),
            self._video.menu(),
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
        self.set_current_page(PageId.ALBUMS)
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

    def _page_menu(self, button: ActionButton, pages: tuple[PageId, ...]) -> QMenu:
        menu = QMenu(button)
        for page_id in pages:
            action = menu.addAction(page_label(page_id))
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
        menu = action.parent()
        assert isinstance(menu, QMenu)
        action.setIcon(
            glyph_icon(
                glyph,
                LAYOUT.icon_size,
                menu.palette().color(QPalette.ColorRole.Text),
                menu.devicePixelRatioF(),
            )
        )
        action.setIconVisibleInMenu(True)

    def _toggle_playlists(self) -> None:
        if self._playlist_popup.isVisible():
            self._playlist_popup.hide()
        else:
            self._playlist_popup.open()
        self._playlists.setChecked(self._current_page is PageId.PLAYLISTS)

    def _show_device_menu(self, point: QPoint) -> None:
        self._device_hover_menu.hide()
        self._device_menu.popup(self._device.mapToGlobal(point))

    def _device_clicked(self) -> None:
        self._device_hover_menu.hide()
        if self._active_ipod is not None:
            self.pageRequested.emit(PageId.DEVICE_SUMMARY.value)
        elif not self._busy:
            self.chooseDeviceRequested.emit()
        self._device.setChecked(self._current_page is PageId.DEVICE_SUMMARY)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            watched is self._device
            and event.type() == QEvent.Type.KeyPress
            and isinstance(event, QKeyEvent)
            and (
                event.key() == Qt.Key.Key_Menu
                or (
                    event.key() == Qt.Key.Key_F10
                    and bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
                )
            )
        ):
            self._show_device_menu(QPoint(0, self._device.height()))
            event.accept()
            return True
        return super().eventFilter(watched, event)

    def set_current_page(self, page_id: PageId) -> None:
        self._current_page = page_id
        self._audio.setChecked(page_id in _AUDIO_PAGES)
        self._video.setChecked(page_id in _VIDEO_PAGES)
        self._playlists.setChecked(page_id is PageId.PLAYLISTS)
        self._maintenance.setChecked(page_id in _MAINTENANCE_PAGES)
        self._settings.setChecked(page_id is PageId.SETTINGS)
        self._device.setChecked(page_id is PageId.DEVICE_SUMMARY)
        for candidate, action in self._actions.items():
            action.setChecked(candidate is page_id)
        for candidate, button in self._direct.items():
            button.setChecked(candidate is page_id)
        if page_id is not PageId.PLAYLISTS:
            self.playlist_tree.clear_selection()

    def set_active_ipod(self, active_ipod: ActiveIPod | None) -> None:
        self._device_hover_menu.hide()
        self._dropdown_hover.close()
        self._active_ipod = active_ipod
        self._sync.setEnabled(active_ipod is not None)
        self._actions[PageId.NORMALIZE_TAGS].setEnabled(active_ipod is not None)
        for page_id, action in self._actions.items():
            action.setVisible(self.page_available(page_id))
        for page_id, button in self._direct.items():
            button.setVisible(self.page_available(page_id))
        self._video.setVisible(any(self.page_available(page) for page in _VIDEO_PAGES))
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
        self._review_separator.setVisible(visible)

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
        self._choose.setEnabled(not self._busy)
        self._eject.setEnabled(active is not None and self._eject_available)
        self._device.setEnabled(active is not None or not self._busy)
        self._device.setToolTip(
            self.tr("Open device summary") + f" · {active.display_name}"
            if active is not None
            else self.tr("Choose iPod…")
        )
        self._device.setAccessibleName(
            self.tr("Open device summary")
            if active is not None
            else self.tr("Choose iPod…")
        )
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
        self._audio.setText(self.tr("Audio"))
        self._video.setText(self.tr("Video"))
        self._playlists.setText(self.tr("Playlists") + " ▾")
        self._playlists.setAccessibleName(page_label(PageId.PLAYLISTS))
        self._maintenance.setText(self.tr("Maintenance"))
        self._settings.setAccessibleName(page_label(PageId.SETTINGS))
        self._settings.setToolTip(page_label(PageId.SETTINGS))
        self._sync.setText(self.tr("Sync with Host"))
        self._scrobble.setText(self.tr("Scrobble Now"))
        self._review.setText(self.tr("Review Changes"))
        self._choose.setText(self.tr("Choose Device"))
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
        self._device_hover_menu.hide()
        self._playlist_popup.hide()
        for menu in (
            self._audio.menu(),
            self._video.menu(),
            self._maintenance_menu,
            self._device_menu,
        ):
            menu.hide()
        super().hideEvent(event)
