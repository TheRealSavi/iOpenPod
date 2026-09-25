"""Persistent source-list navigation and Active iPod placeholder."""

from dataclasses import dataclass

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from device_registry import DeviceProfile
from iOpenPod.app.library_workspace import EditRevision, LibraryWorkspace
from iOpenPod.app.models.device import ActiveIPod, DeviceDiscovery
from iOpenPod.GUI.navigation import PageId, page_label
from iOpenPod.GUI.presentation.device_images import device_pixmap
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.playlist_tree import PlaylistTree
from iOpenPod.GUI.widgets.themed_buttons import (
    ActionButton,
    ActionButtonKind,
    IconButton,
    NavigationButton,
)


@dataclass(frozen=True, slots=True)
class _NavigationDefinition:
    page_id: PageId
    glyph: str


_MAINTENANCE = (
    _NavigationDefinition(PageId.BACKUPS, "box"),
    _NavigationDefinition(PageId.NORMALIZE_TAGS, "check-circle"),
)

_LIBRARY = (
    _NavigationDefinition(PageId.ALBUMS, "album"),
    _NavigationDefinition(PageId.ARTISTS, "user"),
    _NavigationDefinition(PageId.GENRES, "grid"),
    _NavigationDefinition(PageId.TRACKS, "music"),
    _NavigationDefinition(PageId.PHOTOS, "photo"),
    _NavigationDefinition(PageId.PODCASTS, "broadcast"),
    _NavigationDefinition(PageId.AUDIOBOOKS, "book"),
    _NavigationDefinition(PageId.MOVIES, "film"),
    _NavigationDefinition(PageId.TV_SHOWS, "monitor"),
    _NavigationDefinition(PageId.MUSIC_VIDEOS, "video"),
    _NavigationDefinition(PageId.VIDEOS, "video"),
)
_VIDEO_PAGES = frozenset(
    {
        PageId.MOVIES,
        PageId.TV_SHOWS,
        PageId.MUSIC_VIDEOS,
        PageId.VIDEOS,
    }
)


class _DeviceIcon(QLabel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("deviceIcon")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedSize(
            LAYOUT.sidebar_device_image_size,
            LAYOUT.sidebar_device_image_size,
        )
        self._image_name = "iPodGeneric.png"
        self._refresh_icon()

    def set_product_image(self, image_name: str) -> None:
        if image_name == self._image_name:
            return
        self._image_name = image_name
        self._refresh_icon()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() in {
            QEvent.Type.DevicePixelRatioChange,
            QEvent.Type.ScreenChangeInternal,
        }:
            self._refresh_icon()
        super().changeEvent(event)

    def _refresh_icon(self) -> None:
        self.setPixmap(
            device_pixmap(
                self._image_name,
                LAYOUT.sidebar_device_image_size,
                self.devicePixelRatioF(),
            )
        )


class DeviceCard(QFrame):
    """Display discovery or Active iPod state without exposing Host paths."""

    chooseRequested = Signal()
    ejectRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("deviceCard")
        self._active_ipod: ActiveIPod | None = None
        self._discovery = DeviceDiscovery(candidates=())
        self._busy = False
        self._eject_available = False
        self._workspace: LibraryWorkspace | None = None
        self._rename_revision: EditRevision | None = None

        self._icon = _DeviceIcon(self)
        self._name = QPushButton(self)
        self._name.setObjectName("deviceName")
        self._name.clicked.connect(self.start_rename)
        self._name_edit = QLineEdit(self)
        self._name_edit.setObjectName("renameIPod")
        self._name_edit.setAccessibleName(self.tr("iPod name"))
        self._name_edit.editingFinished.connect(self._finish_rename)
        self._name_edit.installEventFilter(self)
        self._rename_apply = IconButton(
            "check-circle", self.tr("Apply iPod name"), self
        )
        self._rename_apply.setObjectName("renameIPodApply")
        self._rename_apply.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._rename_apply.clicked.connect(self._finish_rename)
        self._rename_cancel = IconButton("x", self.tr("Cancel renaming"), self)
        self._rename_cancel.setObjectName("renameIPodCancel")
        self._rename_cancel.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._rename_cancel.clicked.connect(self._cancel_rename)

        rename_row = QHBoxLayout()
        rename_row.setContentsMargins(0, 0, 0, 0)
        rename_row.setSpacing(LAYOUT.space_2xs)
        rename_row.addWidget(self._name_edit, 1)
        rename_row.addWidget(self._rename_apply)
        rename_row.addWidget(self._rename_cancel)

        self._rename_feedback = QLabel(self)
        self._rename_feedback.setObjectName("renameIPodFeedback")
        self._rename_feedback.setWordWrap(True)
        self._rename_feedback.setTextFormat(Qt.TextFormat.PlainText)
        self._rename_panel = QWidget(self)
        self._rename_panel.setObjectName("renameIPodPanel")
        rename_layout = QVBoxLayout(self._rename_panel)
        rename_layout.setContentsMargins(0, 0, 0, 0)
        rename_layout.setSpacing(LAYOUT.space_2xs)
        rename_layout.addLayout(rename_row)
        rename_layout.addWidget(self._rename_feedback)
        self._rename_panel.hide()
        self._model = QLabel(self)
        self._model.setObjectName("deviceModel")
        self._eject = IconButton("eject", self.tr("Eject Active iPod"), self)
        self._eject.setObjectName("ejectActiveIPod")
        self._eject.clicked.connect(self.ejectRequested.emit)
        self._eject.setEnabled(False)
        self._eject.setToolTip(self.tr("No Active iPod is loaded."))

        identity = QVBoxLayout()
        identity.setContentsMargins(0, 0, 0, 0)
        identity.setSpacing(0)
        identity.addWidget(self._name)
        identity.addWidget(self._model)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(LAYOUT.space_xs)
        header.addWidget(self._icon)
        header.addLayout(identity, 1)
        header.addWidget(self._eject)

        self._summary = QLabel(self)
        self._summary.setObjectName("deviceSummary")
        self._storage_label = QLabel(self)
        self._storage_label.setObjectName("deviceMetricLabel")
        self._storage_value = QLabel("—", self)
        self._storage_value.setObjectName("deviceMetricValue")

        storage_labels = QHBoxLayout()
        storage_labels.setContentsMargins(0, 0, 0, 0)
        storage_labels.addWidget(self._storage_label)
        storage_labels.addStretch(1)
        storage_labels.addWidget(self._storage_value)

        self._storage = QProgressBar(self)
        self._storage.setObjectName("deviceStorage")
        self._storage.setRange(0, 100)
        self._storage.setValue(0)
        self._storage.setTextVisible(False)
        self._storage.setFixedHeight(6)

        self._database_label = QLabel(self)
        self._database_label.setObjectName("deviceMetricLabel")
        self._database_value = QLabel("—", self)
        self._database_value.setObjectName("deviceDatabaseValue")

        database_labels = QHBoxLayout()
        database_labels.setContentsMargins(0, 0, 0, 0)
        database_labels.addWidget(self._database_label)
        database_labels.addStretch(1)
        database_labels.addWidget(self._database_value)

        self._database = QProgressBar(self)
        self._database.setObjectName("deviceDatabase")
        self._database.setRange(0, 100)
        self._database.setValue(0)
        self._database.setTextVisible(False)
        self._database.setFixedHeight(6)

        self._choose = ActionButton(parent=self, kind=ActionButtonKind.QUIET)
        self._choose.clicked.connect(self.chooseRequested.emit)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            LAYOUT.space_sm,
            LAYOUT.space_sm,
            LAYOUT.space_sm,
            LAYOUT.space_sm,
        )
        layout.setSpacing(LAYOUT.space_xs)
        layout.addLayout(header)
        layout.addWidget(self._rename_panel)
        layout.addWidget(self._summary)
        layout.addLayout(storage_labels)
        layout.addWidget(self._storage)
        layout.addLayout(database_labels)
        layout.addWidget(self._database)
        layout.addWidget(self._choose)
        self.retranslate_ui()

    def set_discovery(self, discovery: DeviceDiscovery) -> None:
        self._discovery = discovery
        self._refresh_state()

    def set_active_ipod(self, active_ipod: ActiveIPod | None) -> None:
        self._cancel_rename()
        self._active_ipod = active_ipod
        self._refresh_state()

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._choose.setEnabled(not busy)
        self._refresh_state()

    def set_eject_available(self, available: bool) -> None:
        self._eject_available = available
        self._refresh_state()

    def retranslate_ui(self) -> None:
        self._storage_label.setText(self.tr("Storage"))
        self._storage.setAccessibleName(self.tr("Storage"))
        self._database_label.setText(self.tr("Database"))
        self._database.setAccessibleName(self.tr("Database"))
        self._choose.setText(self.tr("Choose iPod…"))
        self._name_edit.setAccessibleName(self.tr("iPod name"))
        self._rename_apply.setAccessibleName(self.tr("Apply iPod name"))
        self._rename_apply.setToolTip(self.tr("Apply iPod name"))
        self._rename_cancel.setAccessibleName(self.tr("Cancel renaming"))
        self._rename_cancel.setToolTip(self.tr("Cancel renaming"))
        self._eject.setAccessibleName(self.tr("Eject Active iPod"))
        self._refresh_state()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

    def _refresh_state(self) -> None:
        active = self._active_ipod
        if active is None:
            self._cancel_rename()
            self._name.setEnabled(False)
            self._icon.set_product_image("iPodGeneric.png")
            self._name.setText(self.tr("No Active iPod"))
            if self._busy:
                self._model.setText(self.tr("Looking for connected iPods…"))
            elif self._discovery.candidates:
                count = len(self._discovery.candidates)
                self._model.setText(self.tr("%n device(s) found", None, count))
            else:
                self._model.setText(self.tr("Connect an iPod to get started"))
            self._summary.setText(self.tr("Choose a device to load its library."))
            self._storage_value.setText("—")
            self._storage.setValue(0)
            self._database_value.setText("—")
            self._database.setValue(0)
            self._eject.setToolTip(self.tr("No Active iPod is loaded."))
            self._eject.setEnabled(False)
            return

        self._icon.set_product_image(active.profile.product_image)
        self._name.setText(active.display_name)
        self._draft_changed()
        self._model.setText(
            self.tr("%1 · %2")
            .replace("%1", active.profile.display_name)
            .replace("%2", active.profile.model_number)
        )
        track_count = len(active.library.tracks)
        track_text = self.tr("%n Tracks", None, track_count)
        duration_ms = sum(track.length_ms for track in active.library.tracks)
        hours = duration_ms / 3_600_000
        self._summary.setText(
            self.tr("%1 · %2 hours")
            .replace("%1", track_text)
            .replace("%2", f"{hours:.1f}")
        )
        candidate = active.candidate
        self._storage_value.setText(
            self.tr("%1 of %2 used")
            .replace("%1", _format_bytes(candidate.used_bytes))
            .replace("%2", _format_bytes(candidate.total_bytes))
        )
        percent = (
            round(candidate.used_bytes * 100 / candidate.total_bytes)
            if candidate.total_bytes > 0
            else 0
        )
        self._storage.setValue(max(0, min(100, percent)))
        database_size = active.database_fingerprint.size
        database_limit = active.profile.capabilities.database.max_database_bytes
        self._database_value.setText(
            self.tr("%1 of %2 used")
            .replace("%1", _format_bytes(database_size))
            .replace("%2", _format_bytes(database_limit))
        )
        database_percent = (
            round(database_size * 100 / database_limit) if database_limit > 0 else 0
        )
        self._database.setValue(max(0, min(100, database_percent)))
        self._eject.setEnabled(self._eject_available)
        self._eject.setToolTip(
            self.tr("Safely eject this iPod")
            if self._eject_available
            else self.tr(
                "Safe eject is unavailable while another iPod operation is active."
            )
        )

    def set_workspace(self, workspace: LibraryWorkspace) -> None:
        self._workspace = workspace
        workspace.changed.connect(self._draft_changed)
        self._draft_changed()

    def _draft_changed(self) -> None:
        workspace = self._workspace
        if (
            workspace is not None
            and self._rename_revision is not None
            and self._rename_revision.generation != workspace.generation
        ):
            self._cancel_rename()
        available = (
            workspace is not None
            and workspace.snapshot is not None
            and not workspace.locked
            and not self._busy
        )
        self._name.setEnabled(available)
        self._name.setToolTip(self.tr("Click to rename your iPod") if available else "")
        if (
            workspace is not None
            and workspace.snapshot is not None
            and self._rename_revision is None
        ):
            self._name.setText(self._workspace_device_name())
        self._name.setAccessibleName(
            self.tr("Rename %1").replace("%1", self._name.text())
            if available
            else self._name.text()
        )
        if not available:
            self._cancel_rename()

    def start_rename(self) -> None:
        workspace = self._workspace
        if (
            workspace is None
            or workspace.snapshot is None
            or workspace.locked
            or self._busy
        ):
            return
        self._rename_revision = workspace.edit_revision
        self._name_edit.setText(self._name.text())
        self._set_rename_error(None)
        self._name.setText(self.tr("Rename iPod"))
        self._name.setEnabled(False)
        self._rename_panel.show()
        self._name_edit.selectAll()
        self._name_edit.setFocus()

    def _cancel_rename(self) -> None:
        self._rename_revision = None
        self._rename_panel.hide()
        self._set_rename_error(None)
        self._name.setText(self._workspace_device_name())
        workspace = self._workspace
        self._name.setEnabled(
            workspace is not None
            and workspace.snapshot is not None
            and not workspace.locked
            and not self._busy
        )

    def _finish_rename(self) -> None:
        revision, workspace = self._rename_revision, self._workspace
        if revision is None or workspace is None:
            return
        name = self._name_edit.text().strip()
        try:
            workspace.rename_device(name, revision)
        except ValueError as error:
            self._set_rename_error(str(error))
            self._name_edit.setFocus()
            return
        self._cancel_rename()

    def _set_rename_error(self, message: str | None) -> None:
        has_error = message is not None
        self._name_edit.setProperty("error", has_error)
        self._rename_feedback.setProperty("error", has_error)
        self._rename_feedback.setText(message or "")
        self._rename_feedback.setVisible(has_error)
        for widget in (self._name_edit, self._rename_feedback):
            style = widget.style()
            style.unpolish(widget)
            style.polish(widget)
            widget.update()

    def _workspace_device_name(self) -> str:
        workspace = self._workspace
        if workspace is not None and workspace.snapshot is not None:
            return workspace.device_name or (
                self._active_ipod.display_name if self._active_ipod is not None else ""
            )
        return self._name.text()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._name_edit and event.type() == QEvent.Type.KeyPress:
            from PySide6.QtGui import QKeyEvent

            if isinstance(event, QKeyEvent) and event.key() == Qt.Key.Key_Escape:
                self._cancel_rename()
                return True
        return super().eventFilter(watched, event)


class Sidebar(QFrame):
    """Compose reusable device, action, and page-navigation surfaces."""

    pageRequested = Signal(str)
    chooseDeviceRequested = Signal()
    syncRequested = Signal()
    reviewChangesRequested = Signal()
    ejectRequested = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        playlists: LibraryWorkspace | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("appSidebar")
        self.setFixedWidth(LAYOUT.sidebar_width)
        self._buttons: dict[PageId, NavigationButton] = {}
        self._definitions = (*_MAINTENANCE, *_LIBRARY)
        self._button_group = QButtonGroup(self)
        self._button_group.setExclusive(True)
        self._active_profile: DeviceProfile | None = None
        self._normalization_count = 0

        self._device_card = DeviceCard(self)
        if playlists is not None:
            self._device_card.set_workspace(playlists)
        self._device_card.chooseRequested.connect(self.chooseDeviceRequested.emit)
        self._device_card.ejectRequested.connect(self.ejectRequested.emit)
        self._sync = ActionButton(parent=self, kind=ActionButtonKind.PRIMARY)
        self._sync.setObjectName("syncWithHost")
        self._sync.setEnabled(False)
        self._sync.setToolTip(self.tr("Select an Active iPod before Sync."))
        self._sync.clicked.connect(self.syncRequested.emit)
        self._review = ActionButton(parent=self)
        self._review.setObjectName("reviewLibraryChanges")
        self._review.setEnabled(False)
        self._review.clicked.connect(self.reviewChangesRequested.emit)

        self._maintenance_label = QLabel(self)
        self._maintenance_label.setObjectName("sidebarSectionLabel")
        self._library_label = QLabel(self)
        self._library_label.setObjectName("sidebarSectionLabel")

        navigation = QWidget(self)
        navigation.setObjectName("sidebarNavigation")
        navigation_layout = QVBoxLayout(navigation)
        navigation_layout.setContentsMargins(
            LAYOUT.space_xs,
            LAYOUT.space_xs,
            LAYOUT.space_xs,
            LAYOUT.space_xs,
        )
        navigation_layout.setSpacing(LAYOUT.space_3xs)
        navigation_layout.addWidget(self._maintenance_label)
        for definition in _MAINTENANCE:
            navigation_layout.addWidget(self._make_button(definition))
        normalize = self._buttons[PageId.NORMALIZE_TAGS]
        normalize.setObjectName("normalizationNavigation")
        self._normalization_badge = QLabel(normalize)
        self._normalization_badge.setObjectName("normalizationBadge")
        self._normalization_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._normalization_badge.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        badge_layout = QHBoxLayout(normalize)
        badge_layout.setContentsMargins(0, 0, LAYOUT.space_xs, 0)
        badge_layout.addStretch(1)
        badge_layout.addWidget(
            self._normalization_badge, 0, Qt.AlignmentFlag.AlignVCenter
        )
        self._normalization_badge.hide()
        navigation_layout.addSpacing(LAYOUT.space_sm)
        navigation_layout.addWidget(self._library_label)
        self.playlist_tree = (
            PlaylistTree(playlists, navigation) if playlists is not None else None
        )
        for definition in _LIBRARY:
            navigation_layout.addWidget(self._make_button(definition))
            if definition.page_id is PageId.TRACKS and self.playlist_tree is not None:
                navigation_layout.addWidget(self.playlist_tree)
        navigation_layout.addStretch(1)

        scroll = QScrollArea(self)
        scroll.setObjectName("sidebarScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(navigation)
        self._settings = self._make_button(
            _NavigationDefinition(PageId.SETTINGS, "settings-sliders")
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            LAYOUT.space_xs,
            LAYOUT.space_xs,
            LAYOUT.space_xs,
            LAYOUT.space_xs,
        )
        layout.setSpacing(LAYOUT.space_xs)
        layout.addWidget(self._device_card)
        layout.addWidget(self._sync)
        layout.addWidget(self._review)
        layout.addWidget(scroll, 1)
        layout.addWidget(self._settings)
        self.set_current_page(PageId.ALBUMS)
        self.retranslate_ui()

    def set_current_page(self, page_id: PageId) -> None:
        if page_id is not PageId.PLAYLISTS and self.playlist_tree is not None:
            self.playlist_tree.clear_selection()
        self._button_group.setExclusive(False)
        for candidate, button in self._buttons.items():
            button.setChecked(candidate is page_id)
        self._button_group.setExclusive(True)

    def set_device_discovery(self, discovery: DeviceDiscovery) -> None:
        self._device_card.set_discovery(discovery)

    def set_active_ipod(self, active_ipod: ActiveIPod | None) -> None:
        self._device_card.set_active_ipod(active_ipod)
        self._active_profile = active_ipod.profile if active_ipod is not None else None
        self._sync.setEnabled(active_ipod is not None)
        self._sync.setToolTip(
            ""
            if active_ipod is not None
            else self.tr("Select an Active iPod before Sync.")
        )
        self._buttons[PageId.NORMALIZE_TAGS].setEnabled(active_ipod is not None)
        if active_ipod is None:
            self.set_normalization_count(0)
        self._refresh_page_visibility()

    def page_available(self, page_id: PageId) -> bool:
        """Return whether the current Active iPod exposes one route."""

        button = self._buttons.get(page_id)
        return button is None or not button.isHidden()

    def set_device_busy(self, busy: bool) -> None:
        self._device_card.set_busy(busy)

    def set_eject_available(self, available: bool) -> None:
        self._device_card.set_eject_available(available)

    def retranslate_ui(self) -> None:
        self._sync.setText(self.tr("Sync with Host"))
        if not self._sync.isEnabled():
            self._sync.setToolTip(self.tr("Select an Active iPod before Sync."))
        self._review.setText(self.tr("Review Changes"))
        self._maintenance_label.setText(self.tr("Maintenance"))
        self._library_label.setText(self.tr("Library"))
        for definition in self._definitions:
            self._buttons[definition.page_id].setText(page_label(definition.page_id))
        self._settings.setText(page_label(PageId.SETTINGS))
        self.set_normalization_count(self._normalization_count)

    def set_review_available(self, available: bool) -> None:
        self._review.setEnabled(available)

    def set_review_visible(self, visible: bool) -> None:
        self._review.setVisible(visible)

    def set_normalization_count(self, count: int) -> None:
        """Show the number of suggested tag edits, hiding a zero or unknown count."""
        self._normalization_count = max(0, count)
        count = self._normalization_count
        self._normalization_badge.setText(str(count) if count <= 99 else "99+")
        self._normalization_badge.setVisible(count > 0)
        button = self._buttons[PageId.NORMALIZE_TAGS]
        detail = (
            self.tr("%1 tag changes available").replace("%1", f"{count:,}")
            if count > 0
            else self.tr("Check your Library for more consistent tags.")
        )
        button.setToolTip(detail)
        button.setAccessibleName(f"{page_label(PageId.NORMALIZE_TAGS)}. {detail}")

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

    def _make_button(self, definition: _NavigationDefinition) -> NavigationButton:
        button = NavigationButton(
            page_label(definition.page_id), definition.glyph, self
        )
        button.setProperty("pageId", definition.page_id.value)
        button.clicked.connect(
            lambda _checked=False, page_id=definition.page_id: self.pageRequested.emit(
                page_id.value
            )
        )
        self._button_group.addButton(button)
        self._buttons[definition.page_id] = button
        return button

    def _refresh_page_visibility(self) -> None:
        profile = self._active_profile
        for page_id, button in self._buttons.items():
            button.setVisible(_page_supported(page_id, profile))


def _format_bytes(byte_count: int) -> str:
    value = float(max(0, byte_count))
    units = ("B", "KB", "MB", "GB", "TB")
    unit = units[0]
    for candidate in units:
        unit = candidate
        if value < 1024 or candidate == units[-1]:
            break
        value /= 1024
    precision = 0 if unit == "B" else 1
    return f"{value:.{precision}f} {unit}"


def _page_supported(page_id: PageId, profile: DeviceProfile | None) -> bool:
    if page_id in _VIDEO_PAGES:
        return profile is not None and profile.capabilities.video.supported
    if page_id is PageId.PHOTOS:
        return profile is not None and profile.capabilities.artwork.supports_photos
    if page_id is PageId.PODCASTS:
        return profile is not None and profile.capabilities.audio.supports_podcasts
    return True
