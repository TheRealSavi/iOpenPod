"""Reusable filtered Track-table pages."""

from PySide6.QtCore import QEvent, Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.models.library_filter_models import TrackFilterProxyModel
from iOpenPod.app.models.track_table_model import TrackTableModel
from iOpenPod.GUI.navigation import PageId, page_label
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.widgets.library_toolbar import LibraryToolbar
from iOpenPod.GUI.widgets.track_table import TrackTable
from iPodDB.library import MediaKind


class TrackPage(QWidget):
    """Present one stable media subset in its own configurable table."""

    currentTrackChanged = Signal(object)
    trackActivated = Signal(object)

    def __init__(
        self,
        tracks: TrackTableModel,
        settings: SettingsService,
        theme_manager: ThemeManager,
        artwork_provider: ArtworkPixmapProvider,
        page_id: PageId,
        table_id: str,
        media_kinds: tuple[MediaKind, ...] | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._page_id = page_id
        self.setObjectName(f"{page_id.value}Page")

        self._proxy = TrackFilterProxyModel(tracks, self)
        self._proxy.set_media_kinds(media_kinds)
        self._toolbar = LibraryToolbar(self)
        self._toolbar.set_namespace(page_id.value)
        self._table = TrackTable(
            self._proxy,
            settings,
            theme_manager,
            artwork_provider,
            table_id,
            self,
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._toolbar)
        layout.addWidget(self._table, 1)

        self._toolbar.queryChanged.connect(self._proxy.set_query)
        self._table.currentTrackChanged.connect(self.currentTrackChanged.emit)
        self._table.trackActivated.connect(self.trackActivated.emit)
        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        label = page_label(self._page_id)
        self._toolbar.retranslate_ui()
        self._toolbar.configure(
            grid_title=label,
            grid_search_label=self.tr("Search %1").replace("%1", label),
            supports_list=False,
        )

    def select_track(self, track_id: int) -> bool:
        """Reveal a diagnostic's Track using the existing table and inspector."""
        self._toolbar.set_query("")
        for row in range(self._proxy.rowCount()):
            index = self._proxy.index(row, 0)
            track = self._proxy.track_at(index)
            if track is not None and track.track_id == track_id:
                self._table.selectRow(row)
                self._table.scrollTo(index)
                self._table.setFocus()
                return True
        return False

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)


__all__ = ["TrackPage"]
