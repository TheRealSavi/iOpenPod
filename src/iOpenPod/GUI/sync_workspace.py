# Hallmark · macrostructure: Narrative Workflow · genre: modern-minimal
# theme: iOpenPod · structure: stage rail · focused work surface · persistent actions
# pre-emit critique: P5 H5 E5 S5 R5 V5
"""Full-window Host Sync workflow composed inside the existing QMainWindow."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from PySide6.QtCore import QCoreApplication, QEvent, QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.core.settings.transcoding import read_transcoder_settings
from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.models.sync_selection import SyncSelection
from iOpenPod.app.sync_storage import SyncStorageProjection
from iOpenPod.GUI.host_library_browser import HostLibraryBrowser
from iOpenPod.GUI.navigation import PageId, page_label
from iOpenPod.GUI.pages.sync_execution_page import SyncExecutionPage
from iOpenPod.GUI.pages.sync_plan_page import SyncPlanPage
from iOpenPod.GUI.presentation.i18n.text import english_count_fallback
from iOpenPod.GUI.presentation.i18n.workflow import workflow_text
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.eta_label import EtaLabel
from iOpenPod.GUI.widgets.host_scan_issues import HostScanIssues
from iOpenPod.GUI.widgets.playlist_tree import PlaylistTree
from iOpenPod.GUI.widgets.sync_storage_bar import SyncStorageBar
from iOpenPod.GUI.widgets.themed_buttons import (
    ActionButton,
    ActionButtonKind,
    NavigationButton,
)

if TYPE_CHECKING:
    from iOpenPod.app.core.settings.service import SettingsService
    from iOpenPod.app.host_media_library import HostMediaLibrary
    from iOpenPod.app.library_sync_helper import IPodMediaLibrary
    from iOpenPod.app.models.device import ActiveIPod
    from iOpenPod.app.sync_execution import PlaylistSyncChange
    from iOpenPod.app.sync_plan import SyncPlan
    from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
    from iOpenPod.GUI.presentation.theme.manager import ThemeManager


class SyncStage(StrEnum):
    SOURCES = "sources"
    SCANNING = "scanning"
    SELECT = "select"
    REVIEW = "review"
    SYNC = "sync"


_STAGES = (
    (SyncStage.SOURCES, "1"),
    (SyncStage.SELECT, "2"),
    (SyncStage.REVIEW, "3"),
    (SyncStage.SYNC, "4"),
)

_LIBRARY_NAVIGATION = (
    (PageId.ALBUMS, "album"),
    (PageId.ARTISTS, "user"),
    (PageId.GENRES, "grid"),
    (PageId.TRACKS, "music"),
    (PageId.PHOTOS, "photo"),
    (PageId.PODCASTS, "broadcast"),
    (PageId.AUDIOBOOKS, "book"),
    (PageId.MOVIES, "film"),
    (PageId.TV_SHOWS, "monitor"),
    (PageId.MUSIC_VIDEOS, "video"),
    (PageId.VIDEOS, "video"),
)


class _ScanPage(QWidget):
    cancelRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("syncScanPage")
        self._title = QLabel(self)
        self._title.setObjectName("syncScanTitle")
        self._detail = QLabel(self)
        self._progress_detail = ""
        self._progress_path = ""
        self._detail.setObjectName("syncScanDetail")
        self._detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._detail.setWordWrap(True)
        self._progress = QProgressBar(self)
        self._progress.setObjectName("syncScanProgress")
        self._progress.setTextVisible(True)
        self.eta = EtaLabel(self)
        self.eta.setObjectName("syncScanEta")
        self.eta.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cancel = ActionButton(parent=self, kind=ActionButtonKind.SECONDARY)
        cancel.setObjectName("cancelSyncScan")
        cancel.clicked.connect(self.cancelRequested.emit)
        self._cancel = cancel

        panel = QFrame(self)
        panel.setObjectName("syncScanPanel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(
            LAYOUT.space_xl,
            LAYOUT.space_xl,
            LAYOUT.space_xl,
            LAYOUT.space_xl,
        )
        panel_layout.setSpacing(LAYOUT.space_md)
        panel_layout.addWidget(self._title, 0, Qt.AlignmentFlag.AlignCenter)
        panel_layout.addWidget(self._detail)
        panel_layout.addWidget(self._progress)
        panel_layout.addWidget(self.eta)
        panel_layout.addWidget(cancel, 0, Qt.AlignmentFlag.AlignCenter)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.setContentsMargins(
            LAYOUT.space_2xl,
            LAYOUT.space_2xl,
            LAYOUT.space_2xl,
            LAYOUT.space_2xl,
        )
        layout.addStretch(1)
        layout.addWidget(panel)
        layout.addStretch(1)
        self.retranslate_ui()

    def set_progress(
        self,
        detail: str,
        *,
        path: str = "",
        completed: int = 0,
        total: int = 0,
        phase: str = "scan",
    ) -> None:
        self._progress_detail = detail
        self._progress_path = path
        self._render_detail()
        self.eta.set_progress(phase, completed, total if total > 0 else None)
        if total > 0:
            self._progress.setRange(0, total)
            self._progress.setValue(min(completed, total))
        else:
            self._progress.setRange(0, 0)

    def retranslate_ui(self) -> None:
        self._title.setText(self.tr("Scanning the Host Media Library"))
        self._cancel.setText(self.tr("Cancel Scan"))
        self._render_detail()

    def _render_detail(self) -> None:
        detail = workflow_text(self._progress_detail)
        if self._progress_path:
            detail += "\n" + self._progress_path
        self._detail.setText(detail)


class _SyncLibraryNavigation(QFrame):
    pageRequested = Signal(str)

    def __init__(
        self,
        playlists: LibraryWorkspace,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("syncLibraryNavigation")
        self.setFixedWidth(LAYOUT.sidebar_width)
        self._buttons: dict[PageId, NavigationButton] = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._heading = QLabel(self)
        self._heading.setObjectName("sidebarSectionLabel")

        contents = QWidget(self)
        contents_layout = QVBoxLayout(contents)
        contents_layout.setContentsMargins(
            LAYOUT.space_xs,
            LAYOUT.space_xs,
            LAYOUT.space_xs,
            LAYOUT.space_xs,
        )
        contents_layout.setSpacing(LAYOUT.space_3xs)
        contents_layout.addWidget(self._heading)
        self.playlist_tree = PlaylistTree(
            playlists, contents, show_add_button=False, show_context_menu=False
        )
        self.playlist_tree.setObjectName("syncPlaylistSidebar")
        self.playlist_tree.set_drag_drop_enabled(False)
        for page_id, glyph in _LIBRARY_NAVIGATION:
            button = NavigationButton(page_label(page_id), glyph, contents)
            button.setProperty("syncPageId", page_id.value)
            button.clicked.connect(
                lambda _checked=False, value=page_id.value: self.pageRequested.emit(
                    value
                )
            )
            self._group.addButton(button)
            self._buttons[page_id] = button
            contents_layout.addWidget(button)
            if page_id is PageId.TRACKS:
                contents_layout.addWidget(self.playlist_tree)
        contents_layout.addStretch(1)

        scroll = QScrollArea(self)
        scroll.setObjectName("syncLibraryNavigationScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(contents)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll)
        self.retranslate_ui()

    def set_available_pages(self, pages: frozenset[PageId]) -> None:
        for page_id, button in self._buttons.items():
            button.setVisible(page_id in pages)

    def set_current_page(self, page_id: PageId) -> None:
        self._group.setExclusive(False)
        for candidate, button in self._buttons.items():
            button.setChecked(candidate is page_id)
        self._group.setExclusive(True)
        if page_id is not PageId.PLAYLISTS:
            self.playlist_tree.clear_selection()

    def retranslate_ui(self) -> None:
        self._heading.setText(self.tr("HOST MEDIA"))
        for page_id, button in self._buttons.items():
            button.setText(page_label(page_id))


class SyncWorkspace(QWidget):
    """Keep source scanning, selection, and Review in one app surface."""

    scanCancelRequested = Signal()
    executeRequested = Signal()
    executionCancelRequested = Signal()
    playlistReconciliationChanged = Signal()
    exitRequested = Signal()

    def __init__(
        self,
        settings: SettingsService,
        theme_manager: ThemeManager,
        artwork_provider: ArtworkPixmapProvider,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("syncWorkspace")
        self._stage = SyncStage.SCANNING
        self._podcast_execution = False
        self._settings = settings
        self._theme_manager = theme_manager
        self._artwork_provider = artwork_provider
        self._host_workspace = LibraryWorkspace(self)
        self._host_workspace.set_locked(True)
        self.selection = SyncSelection(self)
        self._storage_projection: SyncStorageProjection | None = None
        self._playlist_preview: tuple[PlaylistSyncChange, ...] = ()
        self._storage_bar = SyncStorageBar(theme_manager, self)
        self.browser: HostLibraryBrowser | None = None

        self._title = QLabel(self)
        self._title.setObjectName("syncWorkspaceTitle")
        self._stage_labels: dict[SyncStage, QLabel] = {}
        stage_row = QHBoxLayout()
        stage_row.setContentsMargins(0, 0, 0, 0)
        stage_row.setSpacing(LAYOUT.space_xs)
        stage_row.addWidget(self._title)
        stage_row.addStretch(1)
        for stage, number in _STAGES:
            indicator = QLabel(self)
            indicator.setObjectName("syncStageIndicator")
            indicator.setProperty("stage", stage.value)
            indicator.setProperty("number", number)
            self._stage_labels[stage] = indicator
            stage_row.addWidget(indicator)

        header = QFrame(self)
        header.setObjectName("syncWorkspaceHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(
            LAYOUT.space_lg,
            LAYOUT.space_sm,
            LAYOUT.space_lg,
            LAYOUT.space_sm,
        )
        header_layout.addLayout(stage_row)

        self._scan = _ScanPage(self)
        self._library_stack = QStackedWidget(self)
        self._library_stack.setObjectName("syncLibraryStack")

        self._library_navigation = _SyncLibraryNavigation(
            self._host_workspace,
            self,
        )
        selection_body = QFrame(self)
        selection_body.setObjectName("syncSelectionBody")
        selection_layout = QHBoxLayout(selection_body)
        selection_layout.setContentsMargins(0, 0, 0, 0)
        selection_layout.setSpacing(0)
        selection_layout.addWidget(self._library_navigation)
        selection_layout.addWidget(self._library_stack, 1)

        self._selection_summary = QLabel(self)
        self._selection_summary.setObjectName("syncSelectionSummary")
        self._selection_exit = ActionButton(
            parent=self,
            kind=ActionButtonKind.SECONDARY,
        )
        self._selection_exit.setObjectName("exitSyncSelection")
        self._review_button = ActionButton(
            parent=self,
            kind=ActionButtonKind.PRIMARY,
        )
        self._review_button.setObjectName("reviewSyncSelection")
        selection_footer = self._footer(
            self._selection_summary,
            self._selection_exit,
            self._review_button,
        )
        selection_page = QWidget(self)
        selection_page.setObjectName("syncSelectionPage")
        selection_page_layout = QVBoxLayout(selection_page)
        selection_page_layout.setContentsMargins(0, 0, 0, 0)
        selection_page_layout.setSpacing(0)
        selection_page_layout.addWidget(selection_body, 1)
        selection_page_layout.addWidget(selection_footer)

        self._review = SyncPlanPage(self)
        self.execution = SyncExecutionPage(self)
        self._execution_available = False
        self._podcast_count = 0
        self._back = ActionButton(parent=self, kind=ActionButtonKind.SECONDARY)
        self._back.setObjectName("backToSyncSelection")
        self._execute = ActionButton(parent=self, kind=ActionButtonKind.PRIMARY)
        self._execute.setObjectName("executeSync")
        self._execute.setEnabled(False)
        self._review_summary = QLabel(self)
        self._review_summary.setObjectName("syncReviewSummary")
        self._review_summary.setWordWrap(True)
        self._reconcile_playlists = QCheckBox(self)
        self._reconcile_playlists.setObjectName("reconcileSyncPlaylists")
        self._reconcile_playlists.setChecked(True)
        self._playlist_detail = QLabel(self)
        self._playlist_detail.setObjectName("syncPlaylistReviewDetail")
        self._playlist_detail.setWordWrap(True)
        self._podcast_detail = QLabel(self)
        self._podcast_detail.setObjectName("syncPodcastReviewDetail")
        self._podcast_detail.setWordWrap(True)
        self._podcast_detail.setVisible(False)
        self._playlist_changes = QPlainTextEdit(self)
        self._playlist_changes.setObjectName("syncPlaylistReviewChanges")
        self._playlist_changes.setReadOnly(True)
        self._playlist_changes.setTabChangesFocus(True)
        self._playlist_changes.setMaximumHeight(150)
        self._playlist_changes.setMinimumHeight(64)
        self._playlist_changes.setVisible(False)
        playlist_review = QFrame(self)
        playlist_review.setObjectName("syncPlaylistReview")
        playlist_layout = QVBoxLayout(playlist_review)
        playlist_layout.setContentsMargins(
            LAYOUT.space_lg, LAYOUT.space_sm, LAYOUT.space_lg, LAYOUT.space_sm
        )
        playlist_layout.setSpacing(LAYOUT.space_xs)
        playlist_heading = QHBoxLayout()
        playlist_heading.addWidget(self._reconcile_playlists)
        playlist_heading.addWidget(self._playlist_detail, 1)
        playlist_layout.addLayout(playlist_heading)
        playlist_layout.addWidget(self._playlist_changes)
        playlist_layout.addWidget(self._podcast_detail)
        self._review_cancel = ActionButton(parent=self)
        self._review_cancel.setObjectName("cancelSyncReview")
        review_footer = self._footer(
            self._review.review_actions,
            self._review_summary,
            self._back,
            self._review_cancel,
            self._execute,
        )
        self._review.review_actions.show()
        review_page = QWidget(self)
        review_page.setObjectName("syncReviewPage")
        review_layout = QVBoxLayout(review_page)
        review_layout.setContentsMargins(0, 0, 0, 0)
        review_layout.setSpacing(0)
        review_layout.addWidget(self._review, 1)
        review_layout.addWidget(playlist_review)
        review_layout.addWidget(review_footer)

        self._content = QStackedWidget(self)
        self._content.setObjectName("syncWorkspaceContent")
        self._content.addWidget(self._scan)
        self._content.addWidget(selection_page)
        self._content.addWidget(review_page)
        self._content.addWidget(self.execution)
        self._stage_pages = {
            SyncStage.SCANNING: self._scan,
            SyncStage.SELECT: selection_page,
            SyncStage.REVIEW: review_page,
            SyncStage.SYNC: self.execution,
        }

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(header)
        layout.addWidget(self._storage_bar)
        self._scan_issues = HostScanIssues(self)
        self._scan_issues.hide()
        layout.addWidget(self._scan_issues)
        layout.addWidget(self._content, 1)

        self._scan.cancelRequested.connect(self.scanCancelRequested.emit)
        self._selection_exit.clicked.connect(self.exitRequested.emit)
        self._review_button.clicked.connect(self.show_review)
        self._back.clicked.connect(self.show_selection)
        self._review_cancel.clicked.connect(self.exitRequested.emit)
        self._execute.clicked.connect(self._request_execution)
        self._reconcile_playlists.toggled.connect(self._playlist_reconciliation_toggled)
        self.execution.cancelRequested.connect(self.executionCancelRequested.emit)
        self.execution.exitRequested.connect(self.exitRequested.emit)
        self._library_navigation.pageRequested.connect(self._show_library_page)
        self._library_navigation.playlist_tree.selected.connect(self._playlist_selected)
        self.selection.changed.connect(self._refresh_selection_summary)
        self.selection.changed.connect(self._refresh_storage_estimate)
        self._settings.settingChanged.connect(self._storage_settings_changed)
        self.selection.changed.connect(self._refresh_review_summary)
        self._set_stage(SyncStage.SCANNING)
        self.retranslate_ui()

    @property
    def stage(self) -> SyncStage:
        return self._stage

    @property
    def plan(self) -> SyncPlan | None:
        return self._review.plan

    @property
    def reconcile_playlists(self) -> bool:
        return self._reconcile_playlists.isChecked()

    @property
    def library_page_ids(self) -> frozenset[PageId]:
        return frozenset(
            (PageId.PLAYLISTS, *(page_id for page_id, _glyph in _LIBRARY_NAVIGATION))
        )

    def show_scan(self, detail: str) -> None:
        self._scan_issues.load(())
        self._podcast_execution = False
        self.retranslate_ui()
        self.stop_scan()
        self._reset_playlist_preview()
        self._scan.set_progress(detail)
        self._set_stage(SyncStage.SCANNING)

    def update_scan(
        self,
        detail: str,
        *,
        path: str = "",
        completed: int = 0,
        total: int = 0,
        phase: str = "scan",
    ) -> None:
        self._scan.set_progress(
            detail, path=path, completed=completed, total=total, phase=phase
        )

    def stop_scan(self) -> None:
        """Discard scan timing on exit, cancellation, failure or user review."""

        self._scan.eta.reset()

    def load_comparison(
        self,
        library: HostMediaLibrary,
        comparison: SyncPlan,
        active_ipod: ActiveIPod,
        ipod_media: IPodMediaLibrary,
    ) -> None:
        self._reset_playlist_preview()
        self._scan_issues.load(library.issues)
        self._storage_projection = SyncStorageProjection(
            library, ipod_media, active_ipod.candidate, active_ipod.profile
        )
        self._storage_bar.set_device(active_ipod)
        browser = self._ensure_browser()
        browser.load(library)
        self.selection.reset(library, comparison)
        self._show_library_page(PageId.ALBUMS.value)
        self.show_selection()

    def set_available_pages(self, pages: frozenset[PageId]) -> None:
        self._library_navigation.set_available_pages(pages)

    def show_selection(self) -> None:
        self._set_stage(SyncStage.SELECT)
        self._refresh_selection_summary()

    def show_review(self) -> None:
        self._review.load_review(self.selection)
        self._set_stage(SyncStage.REVIEW)
        self._review.review_pending_duplicates()

    def _request_execution(self) -> None:
        if not self._review.review_pending_duplicates():
            self.executeRequested.emit()

    def set_execution_available(self, available: bool) -> None:
        self._execution_available = available
        self._refresh_review_summary()

    def set_podcast_count(self, count: int) -> None:
        """Make automatic Podcast retention visible alongside the Host review."""
        self._podcast_count = count
        self._refresh_review_summary()

    def set_playlist_preview(self, changes: tuple[PlaylistSyncChange, ...]) -> None:
        """Present the exact playlist effects computed for the selected Sync Plan."""
        if changes == self._playlist_preview:
            return
        self._playlist_preview = changes
        self._refresh_playlist_preview()
        self._refresh_review_summary()

    def show_execution(self, *, podcasts: bool = False) -> None:
        self._podcast_execution = podcasts
        self.retranslate_ui()
        self.execution.begin()
        self._set_stage(SyncStage.SYNC)

    def clear(self) -> None:
        self._scan_issues.load(())
        self.stop_scan()
        self._reset_playlist_preview()
        self._storage_projection = None
        self._storage_bar.set_device(None)
        self.selection.clear()
        self._review.clear_plan()
        self._set_stage(SyncStage.SCANNING)

    def shutdown(self) -> None:
        self.stop_scan()
        if self.browser is not None:
            self.browser.shutdown()

    def retranslate_ui(self) -> None:
        self._title.setText(
            self.tr("Sync Podcasts")
            if self._podcast_execution
            else self.tr("Sync with Host")
        )
        stage_labels = {
            SyncStage.SOURCES: self.tr("Sources"),
            SyncStage.SELECT: self.tr("Select Media"),
            SyncStage.REVIEW: self.tr("Review"),
            SyncStage.SYNC: self.tr("Sync"),
        }
        for stage, number in _STAGES:
            self._stage_labels[stage].setVisible(not self._podcast_execution)
            self._stage_labels[stage].setText(
                self.tr("%1  %2")
                .replace("%1", number)
                .replace("%2", stage_labels[stage])
            )
        self._library_navigation.retranslate_ui()
        self._scan.retranslate_ui()
        self._review.retranslate_ui()
        self.execution.retranslate_ui()
        self._storage_bar.retranslate_ui()
        if self.browser is not None:
            self.browser.retranslate()
        self._review_button.setText(self.tr("Review Sync"))
        self._selection_exit.setText(self.tr("Exit Sync"))
        self._back.setText(self.tr("Edit Selection"))
        self._review_cancel.setText(
            QCoreApplication.translate("CommonActions", "Cancel")
        )
        self._reconcile_playlists.setText(self.tr("Reconcile Playlists"))
        self._reconcile_playlists.setToolTip(
            self.tr(
                "Create and update supported Host Playlists using the selected media. "
                "Review membership and order changes below. References to removed Tracks "
                "are removed from iPod Playlists even when this option is off."
            )
        )
        self._playlist_changes.setAccessibleName(self.tr("Playlist changes"))
        self._playlist_changes.setAccessibleDescription(
            self.tr(
                "Read-only preview of Playlist creation, membership, and order changes."
            )
        )
        self._refresh_selection_summary()
        self._refresh_playlist_preview()
        self._refresh_review_summary()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

    def _set_stage(self, stage: SyncStage) -> None:
        if stage is not SyncStage.SCANNING:
            self.stop_scan()
        self._stage = stage
        self._refresh_review_summary()
        self._storage_bar.setVisible(stage in {SyncStage.SELECT, SyncStage.REVIEW})
        self._scan_issues.setVisible(
            self._scan_issues.has_issues
            and stage in {SyncStage.SELECT, SyncStage.REVIEW}
        )
        self._content.setCurrentWidget(self._stage_pages[stage])
        order = (SyncStage.SOURCES, SyncStage.SELECT, SyncStage.REVIEW, SyncStage.SYNC)
        current = 0 if stage is SyncStage.SCANNING else order.index(stage)
        for position, candidate in enumerate(order):
            label = self._stage_labels[candidate]
            label.setProperty("current", position == current)
            label.setProperty("complete", position < current)
            style = label.style()
            style.unpolish(label)
            style.polish(label)

    def _show_library_page(self, value: str) -> None:
        browser = self.browser
        if browser is None:
            return
        page_id = PageId(value)
        page = browser.page_widgets.get(page_id)
        if page is None:
            return
        self._library_stack.setCurrentWidget(page)
        self._library_navigation.set_current_page(page_id)
        if page_id is not PageId.PLAYLISTS:
            browser.playlist_page.select_playlist(None)

    def _playlist_selected(self, playlist_id: object) -> None:
        browser = self.browser
        if browser is None:
            return
        self._show_library_page(PageId.PLAYLISTS.value)
        browser.playlist_page.select_playlist(playlist_id)

    def _playlist_page_selected(self, playlist_id: object) -> None:
        if isinstance(playlist_id, int):
            self._library_navigation.playlist_tree.select_playlist(playlist_id)

    def _ensure_browser(self) -> HostLibraryBrowser:
        browser = self.browser
        if browser is not None:
            return browser
        browser = HostLibraryBrowser(
            self._settings,
            self._theme_manager,
            self._artwork_provider,
            self._host_workspace,
            self._library_stack,
            self.selection,
        )
        for page in browser.pages:
            self._library_stack.addWidget(page)
        browser.playlist_page.playlistSelected.connect(self._playlist_page_selected)
        self.browser = browser
        return browser

    def _refresh_selection_summary(self) -> None:
        count = self.selection.selected_host_count
        self._selection_summary.setText(
            self.tr("%n Host item selected for the iPod", None, count)
            if count == 1
            else self.tr("%n Host items selected for the iPod", None, count)
        )

    def _refresh_storage_estimate(self) -> None:
        projection = self._storage_projection
        self._storage_bar.set_estimate(
            projection.estimate(
                self.selection.selected_plan,
                settings=read_transcoder_settings(self._settings),
            )
            if projection is not None
            else None
        )

    def _storage_settings_changed(self, key: str, _value: object) -> None:
        if key.startswith("transcoding/") and self._storage_projection is not None:
            self._refresh_storage_estimate()

    def _refresh_review_summary(self) -> None:
        playlist_count = len(self._playlist_preview) if self.reconcile_playlists else 0
        pending_duplicates = bool(self.selection.pending_duplicate_groups)
        self._execute.setText(
            self.tr("Resolve selected duplicates…")
            if pending_duplicates
            else self.tr("Sync Selected")
        )
        self._execute.setToolTip(
            self.tr("Choose which selected copies to link, add separately, or skip.")
            if pending_duplicates
            else self.tr(
                "Validate and apply the selected changes using your transcoding and Sync settings. "
                "Independent items that fail preparation are skipped and reported."
            )
        )
        self._execute.setEnabled(
            self._execution_available
            and self._stage is SyncStage.REVIEW
            and (
                self.selection.selected_plan.change_count > 0
                or playlist_count > 0
                or self._podcast_count > 0
                or pending_duplicates
            )
        )
        summary = (
            self.tr("%1 of %2 selected")
            .replace("%1", f"{self.selection.selected_plan.change_count:,}")
            .replace("%2", f"{self.selection.review_plan.change_count:,}")
        )
        if self._playlist_preview:
            summary += english_count_fallback(
                " · %Ln Playlist change(s)",
                self.tr(" · %Ln Playlist change(s)", "", playlist_count),
                playlist_count,
            )
        if pending_duplicates:
            summary += " · " + self.tr("Selected duplicates need choices")
        self._review_summary.setText(summary)
        self._podcast_detail.setVisible(self._podcast_count > 0)
        self._podcast_detail.setText(
            english_count_fallback(
                "%n Podcast(s) will sync using their saved settings. "
                "Episodes may be added or removed.",
                self.tr(
                    "%n Podcast(s) will sync using their saved settings. "
                    "Episodes may be added or removed.",
                    "",
                    self._podcast_count,
                ),
                self._podcast_count,
            )
        )
        self._review_summary.setToolTip(
            self.tr(
                "Selected media changes across all groups, including items hidden by filters, "
                "and selected Playlist changes."
            )
        )

    def _reset_playlist_preview(self) -> None:
        self._playlist_preview = ()
        with QSignalBlocker(self._reconcile_playlists):
            self._reconcile_playlists.setChecked(True)
        self._refresh_playlist_preview()
        self._refresh_review_summary()

    def _playlist_reconciliation_toggled(self, _checked: bool) -> None:
        self._refresh_playlist_preview()
        self._refresh_review_summary()
        self.playlistReconciliationChanged.emit()

    def _refresh_playlist_preview(self) -> None:
        lines: list[str] = []
        for change in self._playlist_preview:
            action = (
                self.tr("Create") if change.action == "create" else self.tr("Update")
            )
            detail = (
                self.tr("%1 added, %2 removed")
                .replace("%1", f"{change.added_count:,}")
                .replace("%2", f"{change.removed_count:,}")
            )
            if change.order_changed:
                detail += self.tr(", order changed")
            lines.append(f"{action} {change.name}: {detail}")
        text = "\n".join(lines)
        if self._playlist_changes.toPlainText() != text:
            self._playlist_changes.setPlainText(text)
        self._playlist_changes.setVisible(bool(lines))
        if not self.reconcile_playlists:
            detail = self.tr(
                "Host Playlists will not be reconciled. References to removed Tracks "
                "are still removed."
            )
        elif lines:
            detail = self.tr("Membership and order changes for the selected media:")
        else:
            detail = self.tr("No Playlist changes for the selected media.")
        self._playlist_detail.setText(detail)

    @staticmethod
    def _footer(*widgets: QWidget) -> QFrame:
        footer = QFrame()
        footer.setObjectName("syncWorkspaceFooter")
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(
            LAYOUT.space_lg,
            LAYOUT.space_sm,
            LAYOUT.space_lg,
            LAYOUT.space_sm,
        )
        layout.setSpacing(LAYOUT.space_xs)
        if widgets:
            layout.addWidget(widgets[0], 1)
            for widget in widgets[1:]:
                layout.addWidget(widget)
        return footer


__all__ = ["SyncStage", "SyncWorkspace"]
