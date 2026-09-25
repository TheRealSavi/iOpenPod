"""Switch shared Library browsers between split and whole-page Track layouts."""

from PySide6.QtCore import QByteArray, QTimer, Signal
from PySide6.QtWidgets import QFrame, QStackedWidget, QVBoxLayout, QWidget

from iOpenPod.app.core.settings.definitions import (
    IPOD_LIBRARY_VIEW_MODE,
    IPodLibraryViewMode,
    SettingDefinition,
)
from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.models.album_list_model import AlbumSummary
from iOpenPod.app.models.collection_list_model import CollectionSummary
from iOpenPod.app.models.library_filter_models import TrackFilterProxyModel
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.widgets.collection_detail import CollectionDetailPage
from iOpenPod.GUI.widgets.library_toolbar import LibraryToolbar
from iOpenPod.GUI.widgets.track_list_header import LibrarySplitter
from iOpenPod.GUI.widgets.track_table import TrackTable


class LibraryContent(QStackedWidget):
    """Retain the browser and table while changing only their presentation."""

    backRequested = Signal()

    def __init__(
        self,
        browser: QWidget,
        table: TrackTable,
        proxy: TrackFilterProxyModel,
        toolbar: LibraryToolbar,
        settings: SettingsService,
        theme_manager: ThemeManager,
        artwork_provider: ArtworkPixmapProvider,
        parent: QWidget,
        *,
        selection_mode: bool,
        follow_ipod_view_mode: bool,
        splitter_name: str = "librarySplitter",
        splitter_setting: SettingDefinition[QByteArray] | None = None,
    ) -> None:
        super().__init__(parent)
        self._browser = browser
        self._table = table
        self._proxy = proxy
        self._toolbar = toolbar
        self._settings = settings
        self._theme_manager = theme_manager
        self._artwork_provider = artwork_provider
        self._selection_mode = selection_mode
        self._splitter_name = splitter_name
        self._splitter_setting = splitter_setting
        self._splitter_state = (
            settings.get(splitter_setting)
            if splitter_setting is not None
            else QByteArray()
        )
        self._splitter: LibrarySplitter | None = None
        self._browser_layout: QVBoxLayout | None = None
        self._track_layout: QVBoxLayout | None = None
        self._detail: CollectionDetailPage | None = None
        self._title: str | None = None
        self._artwork_id = 0
        self._whole_page_table = False
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(250)
        self._save_timer.timeout.connect(self._save_splitter_state)
        self._set_whole_page_table(
            selection_mode
            or (
                follow_ipod_view_mode
                and settings.get(IPOD_LIBRARY_VIEW_MODE)
                == IPodLibraryViewMode.WHOLE_PAGE_TABLE.value
            )
        )
        if follow_ipod_view_mode and not selection_mode:
            settings.settingChanged.connect(self._setting_changed)

    @property
    def whole_page_table(self) -> bool:
        return self._whole_page_table

    @property
    def detail_open(self) -> bool:
        return self._detail is not None and self.currentWidget() is self._detail

    def open_detail(self, summary: AlbumSummary | CollectionSummary) -> None:
        if self._whole_page_table and self._detail is not None:
            self._detail.set_context(summary)
            self._toolbar.hide()
            self.setCurrentWidget(self._detail)

    def show_browser(self) -> None:
        if self._whole_page_table:
            self.setCurrentWidget(self._browser)
        self._toolbar.show()

    def set_track_context(self, title: str | None, artwork_id: int) -> None:
        self._title = title
        self._artwork_id = artwork_id
        if self._splitter is not None:
            self._splitter.track_header.set_context(title, artwork_id)

    def retranslate_ui(self) -> None:
        if self._splitter is not None:
            self._splitter.track_header.retranslate_ui()
        if self._detail is not None:
            self._detail.retranslate_ui()

    def _setting_changed(self, key: str, value: object) -> None:
        if key == IPOD_LIBRARY_VIEW_MODE.key:
            whole_page = value == IPodLibraryViewMode.WHOLE_PAGE_TABLE.value
            if whole_page != self._whole_page_table:
                self._set_whole_page_table(whole_page)

    def _set_whole_page_table(self, enabled: bool) -> None:
        if self._splitter is not None and not self._whole_page_table:
            self._splitter_state = self._splitter.saveState()
            if self._save_timer.isActive():
                self._save_splitter_state()
        self._save_timer.stop()
        self._whole_page_table = enabled
        self._proxy.set_query("")
        if self._detail is not None:
            self._detail.clear_query()
        if self._splitter is not None:
            self._splitter.track_header.set_query("")

        if enabled:
            if self._detail is None:
                self._detail = CollectionDetailPage(
                    self._table,
                    self._proxy,
                    self._theme_manager,
                    self._artwork_provider,
                    self,
                    selection_mode=self._selection_mode,
                )
                self.addWidget(self._detail)
                self._detail.backRequested.connect(self.backRequested.emit)
            else:
                self._detail.set_table(self._table)
            self.addWidget(self._browser)
            self.setCurrentWidget(self._browser)
        else:
            if self._splitter is None:
                self._splitter = LibrarySplitter(
                    self._theme_manager, self._artwork_provider, self
                )
                self._splitter.setObjectName(self._splitter_name)
                browser_panel = QWidget(self._splitter)
                self._browser_layout = QVBoxLayout(browser_panel)
                self._browser_layout.setContentsMargins(0, 0, 0, 0)
                self._browser_layout.setSpacing(0)
                self._splitter.addWidget(browser_panel)
                track_panel = QFrame(self._splitter)
                track_panel.setObjectName("trackListPanel")
                self._track_layout = QVBoxLayout(track_panel)
                self._track_layout.setContentsMargins(0, 0, 0, 0)
                self._track_layout.setSpacing(0)
                self._splitter.addWidget(track_panel)
                self._splitter.track_header.queryChanged.connect(self._proxy.set_query)
                self._splitter.splitterMoved.connect(self._splitter_moved)
                self.addWidget(self._splitter)
            self.removeWidget(self._browser)
            assert self._browser_layout is not None
            self._browser_layout.addWidget(self._browser)
            assert self._track_layout is not None
            self._track_layout.addWidget(self._table, 1)
            self._splitter.setStretchFactor(0, 3)
            self._splitter.setStretchFactor(1, 2)
            self._splitter.setSizes([480, 300])
            if not self._splitter_state.isEmpty():
                self._splitter.restoreState(self._splitter_state)
            self.set_track_context(self._title, self._artwork_id)
            self.setCurrentWidget(self._splitter)
        self._browser.show()
        self._table.show()
        self._toolbar.show()

    def _splitter_moved(self, _position: int, _index: int) -> None:
        if not self._whole_page_table and self._splitter_setting is not None:
            self._save_timer.start()

    def _save_splitter_state(self) -> None:
        if self._splitter is None or self._whole_page_table:
            return
        self._splitter_state = self._splitter.saveState()
        if self._splitter_setting is not None:
            self._settings.set_global(self._splitter_setting, self._splitter_state)
