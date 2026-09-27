"""Artwork-led Podcast Subscription and Episode browser."""

from __future__ import annotations

from typing import TYPE_CHECKING
from weakref import proxy

from PySide6.QtCore import (
    QEvent,
    QItemSelection,
    QItemSelectionModel,
    QModelIndex,
    QPoint,
    QSignalBlocker,
    Qt,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import QAction, QHideEvent, QShowEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListView,
    QMenu,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from iOpenPod.app.models.artwork_seed import stable_artwork_seed
from iOpenPod.app.models.podcast_list_models import (
    ALL_PODCASTS_SOURCE_ID,
    PodcastEpisodeFilter,
    PodcastEpisodeListModel,
    PodcastListRole,
    PodcastSubscriptionListModel,
)
from iOpenPod.app.podcasts.controller import PodcastController, PodcastOperationFailure
from iOpenPod.GUI.delegates.podcast_delegates import (
    PodcastEpisodeDelegate,
    PodcastShowDelegate,
)
from iOpenPod.GUI.dialogs.podcast_search import PodcastSearchDialog
from iOpenPod.GUI.dialogs.podcast_sync_settings import PodcastSyncSettingsDialog
from iOpenPod.GUI.presentation.theme.podcast_styles import render_podcast_page_style
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.artwork_view import ArtworkView
from iOpenPod.GUI.widgets.browser_chrome import PageHeader, SourceListPanel
from iOpenPod.GUI.widgets.elided_label import ElidedLabel
from iOpenPod.GUI.widgets.podcast_artwork import (
    PodcastArtworkView,
    PodcastCollectionArtworkView,
)
from iOpenPod.GUI.widgets.search_field import SearchField
from iOpenPod.GUI.widgets.themed_buttons import ActionButton, ActionButtonKind

_PODCAST_HERO_MAX_HEIGHT = 240
_PODCAST_DESCRIPTION_LINES = 4
_STATUS_SOURCE = "podcasts"

if TYPE_CHECKING:
    from iOpenPod.app.core.status import ApplicationStatus
    from iOpenPod.app.podcasts.models import PodcastEpisode, PodcastSubscription
    from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
    from iOpenPod.GUI.presentation.podcast_artwork_provider import (
        PodcastArtworkPixmapProvider,
    )
    from iOpenPod.GUI.presentation.theme.manager import ThemeManager
    from iOpenPod.GUI.widgets.track_actions import TrackActions
    from iPodDB.library import Track


class PodcastPage(QWidget):
    """Browse an artwork-led Podcast catalogue with explicit device state."""

    trackActivated = Signal(object)

    def __init__(
        self,
        controller: PodcastController,
        status: ApplicationStatus,
        theme_manager: ThemeManager,
        artwork_provider: PodcastArtworkPixmapProvider,
        parent: QWidget | None = None,
        *,
        device_artwork_provider: ArtworkPixmapProvider | None = None,
        track_actions: TrackActions | None = None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._status = status
        self._theme_manager = theme_manager
        self._artwork_provider = artwork_provider
        self._device_artwork_provider = device_artwork_provider
        self._track_actions = (
            proxy(track_actions) if track_actions is not None else None
        )
        self._snapshot = controller.snapshot
        self._query = ""
        self._opened_source_id: str | None = None
        self._pending_open_source_id: str | None = None
        self._open_refresh_scheduled = False
        self._status_message = ""
        self.setObjectName("podcastsPage")

        self._subscription_model = PodcastSubscriptionListModel(self)
        self._episode_model = PodcastEpisodeListModel(self)

        toolbar = PageHeader(self)
        toolbar.setObjectName("podcastsToolbar")
        self._page_header = toolbar
        self._title = toolbar.title_label
        self._title.setObjectName("podcastsTitle")
        self._add = ActionButton(parent=toolbar, kind=ActionButtonKind.PRIMARY)
        self._add.setObjectName("podcastsAdd")
        self._sync_all = ActionButton(parent=toolbar)
        self._sync_all.setObjectName("podcastsSyncAll")
        toolbar.add_action(self._sync_all)
        toolbar.add_action(self._add)

        self._content = QStackedWidget(self)
        self._content.setObjectName("podcastContent")
        self._empty_page = self._build_empty_page()
        self._browser_page = self._build_browser_page()
        self._content.addWidget(self._empty_page)
        self._content.addWidget(self._browser_page)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(toolbar)
        layout.addWidget(self._content, 1)

        self._dialog: PodcastSearchDialog | None = None
        self._settings_dialog: PodcastSyncSettingsDialog | None = None
        self._settings_subscription_id: str | None = None
        self._search.queryChanged.connect(self._filter)
        for option in self._episode_filter_options:
            option.toggled.connect(self._episode_filters_changed)
        self._add.clicked.connect(self._show_add_dialog)
        self._empty_add.clicked.connect(self._show_add_dialog)
        self._sync_all.clicked.connect(self._sync_podcasts)
        self._sync_show.clicked.connect(self._sync_selected)
        self._sync_settings.clicked.connect(self._show_sync_settings)
        self._add_episodes.clicked.connect(self._add_selected_episodes)
        self._remove_episodes.clicked.connect(self._remove_selected_episodes)
        self._add_episode_action.triggered.connect(self._add_selected_episodes)
        self._remove_episode_action.triggered.connect(self._remove_selected_episodes)
        self._refresh_show.clicked.connect(self._refresh_selected)
        self._unsubscribe.clicked.connect(self._unsubscribe_selected)
        self._shows.selectionModel().currentChanged.connect(self._subscription_changed)
        self._episodes.selectionModel().selectionChanged.connect(
            self._episode_selection_changed
        )
        self._episodes.activated.connect(self._episode_activated)
        self._episodes.customContextMenuRequested.connect(
            self._show_episode_context_menu
        )
        self._mark_listened.triggered.connect(lambda: self._set_listened(True))
        self._mark_unlistened.triggered.connect(lambda: self._set_listened(False))
        artwork_provider.artworkChanged.connect(self._artwork_changed)
        theme_manager.effectiveThemeChanged.connect(self._theme_changed)
        controller.changed.connect(self._controller_changed)
        controller.busyChanged.connect(self._availability_changed)
        controller.operationFailed.connect(self._operation_failed)
        self._apply_styles()
        self.retranslate_ui()
        self._controller_changed()

    def _build_empty_page(self) -> QWidget:
        page = QWidget(self)
        page.setObjectName("podcastEmptyPage")
        artwork = PodcastArtworkView(
            self._theme_manager,
            self._artwork_provider,
            144,
            page,
        )
        artwork.set_artwork("", stable_artwork_seed("iOpenPod Podcasts"))
        self._empty_title = QLabel(page)
        self._empty_title.setObjectName("podcastEmptyTitle")
        self._empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_detail = QLabel(page)
        self._empty_detail.setObjectName("podcastEmptyDetail")
        self._empty_detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_detail.setWordWrap(True)
        self._empty_detail.setMaximumWidth(480)
        self._empty_add = ActionButton(parent=page, kind=ActionButtonKind.PRIMARY)
        empty_layout = QVBoxLayout(page)
        empty_layout.setContentsMargins(
            LAYOUT.space_3xl,
            LAYOUT.space_3xl,
            LAYOUT.space_3xl,
            LAYOUT.space_3xl,
        )
        empty_layout.setSpacing(LAYOUT.space_sm)
        empty_layout.addStretch(1)
        empty_layout.addWidget(artwork, 0, Qt.AlignmentFlag.AlignHCenter)
        empty_layout.addSpacing(LAYOUT.space_sm)
        empty_layout.addWidget(self._empty_title)
        empty_layout.addWidget(self._empty_detail, 0, Qt.AlignmentFlag.AlignHCenter)
        empty_layout.addSpacing(LAYOUT.space_xs)
        empty_layout.addWidget(self._empty_add, 0, Qt.AlignmentFlag.AlignHCenter)
        empty_layout.addStretch(1)
        return page

    def _build_browser_page(self) -> QWidget:
        page = QWidget(self)
        page.setObjectName("podcastBrowserPage")

        shelf = SourceListPanel(LAYOUT.artwork_source_list_width, page)
        shelf.setObjectName("podcastShelf")
        shelf.title_label.setObjectName("podcastSectionLabel")
        shelf.count_label.setObjectName("podcastSectionMeta")
        self._show_shelf = shelf
        self._shows = QListView(shelf)
        self._shows.setObjectName("podcastShowShelf")
        self._shows.setModel(self._subscription_model)
        self._shows.setItemDelegate(
            PodcastShowDelegate(
                self._theme_manager,
                self._artwork_provider,
                self._shows,
                device_artwork_provider=self._device_artwork_provider,
            )
        )
        self._shows.setViewMode(QListView.ViewMode.ListMode)
        self._shows.setFlow(QListView.Flow.TopToBottom)
        self._shows.setWrapping(False)
        self._shows.setResizeMode(QListView.ResizeMode.Adjust)
        self._shows.setMovement(QListView.Movement.Static)
        self._shows.setMouseTracking(True)
        self._shows.setUniformItemSizes(True)
        shelf.set_view(self._shows, standard_items=False)

        detail = QWidget(page)
        detail.setObjectName("podcastDetail")

        hero = QFrame(detail)
        hero.setObjectName("podcastHero")
        hero.setFixedHeight(_PODCAST_HERO_MAX_HEIGHT)
        self._show_artwork_stack = QStackedWidget(hero)
        self._show_artwork_stack.setObjectName("podcastShowArtworkStack")
        self._show_artwork_stack.setFixedSize(176, 176)
        self._show_artwork = PodcastArtworkView(
            self._theme_manager,
            self._artwork_provider,
            176,
            self._show_artwork_stack,
        )
        self._show_artwork_stack.addWidget(self._show_artwork)
        self._collection_show_artwork = PodcastCollectionArtworkView(
            self._theme_manager,
            self._artwork_provider,
            176,
            self._show_artwork_stack,
            device_artwork_provider=self._device_artwork_provider,
        )
        self._show_artwork_stack.addWidget(self._collection_show_artwork)
        self._device_show_artwork = (
            ArtworkView(
                self._theme_manager,
                self._device_artwork_provider,
                self._show_artwork_stack,
            )
            if self._device_artwork_provider is not None
            else None
        )
        if self._device_show_artwork is not None:
            self._device_show_artwork.setFixedSize(176, 176)
            self._show_artwork_stack.addWidget(self._device_show_artwork)
        self._show_title = QLabel(hero)
        self._show_title.setObjectName("podcastShowTitle")
        self._show_title.setWordWrap(True)
        self._show_meta = ElidedLabel(1, hero)
        self._show_meta.setObjectName("podcastShowMeta")
        self._show_description = ElidedLabel(
            _PODCAST_DESCRIPTION_LINES,
            hero,
        )
        self._show_description.setObjectName("podcastShowDescription")
        show_copy = QVBoxLayout()
        show_copy.setSpacing(LAYOUT.space_xs)
        show_copy.addWidget(self._show_title)
        show_copy.addWidget(self._show_meta)
        show_copy.addWidget(self._show_description)
        show_copy.addStretch(1)
        self._refresh_show = ActionButton(parent=hero)
        self._refresh_show.setObjectName("podcastRefreshShow")
        self._unsubscribe = ActionButton(parent=hero, kind=ActionButtonKind.DANGER)
        self._unsubscribe.setObjectName("podcastUnsubscribe")
        hero_actions = QHBoxLayout()
        hero_actions.setSpacing(LAYOUT.space_xs)
        hero_actions.addStretch(1)
        hero_actions.addWidget(self._refresh_show)
        hero_actions.addWidget(self._unsubscribe)
        hero_layout = QGridLayout(hero)
        hero_layout.setContentsMargins(
            LAYOUT.space_lg,
            LAYOUT.space_lg,
            LAYOUT.space_lg,
            LAYOUT.space_lg,
        )
        hero_layout.setSpacing(LAYOUT.space_lg)
        hero_layout.addWidget(
            self._show_artwork_stack,
            0,
            0,
            2,
            1,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
        )
        hero_layout.addLayout(show_copy, 0, 1)
        hero_layout.addLayout(hero_actions, 1, 1)
        hero_layout.setColumnStretch(1, 1)
        hero_layout.setRowStretch(0, 1)

        episodes_section = QWidget(detail)
        episodes_section.setObjectName("podcastEpisodesSection")
        self._episodes_label = QLabel(episodes_section)
        self._episodes_label.setObjectName("podcastEpisodesTitle")
        self._episode_count = QLabel(episodes_section)
        self._episode_count.setObjectName("podcastSectionMeta")
        self._filter_button = ActionButton(
            parent=episodes_section,
            kind=ActionButtonKind.SECONDARY,
        )
        self._filter_button.setObjectName("podcastEpisodeFilter")
        self._filter_menu = QMenu(self._filter_button)
        self._filter_menu.setObjectName("podcastEpisodeFilterMenu")
        self._filter_menu.setMinimumWidth(184)
        self._filter_button.setMenu(self._filter_menu)
        self._filter_listened = _add_filter_option(
            self._filter_menu,
            "podcastFilterListened",
        )
        self._filter_unlistened = _add_filter_option(
            self._filter_menu,
            "podcastFilterUnlistened",
        )
        self._filter_menu.addSeparator()
        self._filter_on_ipod = _add_filter_option(
            self._filter_menu,
            "podcastFilterOnIPod",
        )
        self._filter_not_on_ipod = _add_filter_option(
            self._filter_menu,
            "podcastFilterNotOnIPod",
        )
        self._episode_filter_options = (
            self._filter_listened,
            self._filter_unlistened,
            self._filter_on_ipod,
            self._filter_not_on_ipod,
        )
        self._search = SearchField(episodes_section)
        self._search.setObjectName("podcastsSearch")
        self._search.setMinimumWidth(260)

        episode_heading = QHBoxLayout()
        episode_heading.addWidget(self._episodes_label)
        episode_heading.addWidget(self._episode_count)
        episode_heading.addStretch(1)
        episode_heading.addWidget(self._filter_button)
        episode_heading.addWidget(self._search)
        self._episodes = QListView(episodes_section)
        self._episodes.setObjectName("podcastEpisodeList")
        self._episodes.setModel(self._episode_model)
        self._episode_delegate = PodcastEpisodeDelegate(
            self._theme_manager, self._episodes
        )
        self._episodes.setItemDelegate(self._episode_delegate)
        self._episode_delegate.actionRequested.connect(self._episode_action_requested)
        self._episodes.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self._episodes.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._episodes.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._episodes.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self._episodes.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._episodes.setMouseTracking(True)
        self._episodes.setUniformItemSizes(True)

        self._episode_menu = QMenu(self._episodes)
        self._episode_menu.setObjectName("podcastEpisodeContextMenu")
        self._add_episode_action = QAction(self._episode_menu)
        self._add_episode_action.setObjectName("podcastAddEpisodesAction")
        self._episode_menu.addAction(self._add_episode_action)
        self._remove_episode_action = QAction(self._episode_menu)
        self._remove_episode_action.setObjectName("podcastRemoveEpisodesAction")
        self._episode_menu.addAction(self._remove_episode_action)
        self._episode_menu.addSeparator()
        self._mark_listened = QAction(self._episode_menu)
        self._mark_listened.setObjectName("podcastMarkListened")
        self._episode_menu.addAction(self._mark_listened)
        self._mark_unlistened = QAction(self._episode_menu)
        self._mark_unlistened.setObjectName("podcastMarkUnlistened")
        self._episode_menu.addAction(self._mark_unlistened)

        episodes_layout = QVBoxLayout(episodes_section)
        episodes_layout.setContentsMargins(
            LAYOUT.space_lg,
            LAYOUT.space_lg,
            LAYOUT.space_lg,
            0,
        )
        self._add_episodes = ActionButton(parent=episodes_section)
        self._add_episodes.setObjectName("podcastAddEpisodes")
        self._remove_episodes = ActionButton(
            parent=episodes_section, kind=ActionButtonKind.DANGER
        )
        self._remove_episodes.setObjectName("podcastRemoveEpisodes")
        self._sync_show = ActionButton(parent=episodes_section)
        self._sync_show.setObjectName("podcastSyncShow")
        self._sync_settings = ActionButton(parent=episodes_section)
        self._sync_settings.setObjectName("podcastSyncSettings")
        episode_actions = QHBoxLayout()
        episode_actions.setSpacing(LAYOUT.space_xs)
        episode_actions.addWidget(self._add_episodes)
        episode_actions.addWidget(self._remove_episodes)
        episode_actions.addStretch(1)
        sync_actions = QHBoxLayout()
        sync_actions.setSpacing(LAYOUT.space_xs)
        sync_actions.addWidget(self._sync_show)
        sync_actions.addWidget(self._sync_settings)
        sync_actions.addStretch(1)
        episodes_layout.setSpacing(LAYOUT.space_sm)
        episodes_layout.addLayout(sync_actions)
        episodes_layout.addLayout(episode_heading)
        episodes_layout.addWidget(self._episodes, 1)
        episodes_layout.addLayout(episode_actions)
        episodes_layout.addSpacing(LAYOUT.space_sm)

        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(0)
        detail_layout.addWidget(hero)
        detail_layout.addWidget(episodes_section, 1)

        splitter = QSplitter(Qt.Orientation.Horizontal, page)
        splitter.setObjectName("podcastBrowserSplitter")
        splitter.setProperty("sourceListBrowser", True)
        splitter.setHandleWidth(LAYOUT.source_list_splitter_handle_width)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(shelf)
        splitter.addWidget(detail)
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes((LAYOUT.artwork_source_list_width, 900))
        self._browser_splitter = splitter

        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(splitter)
        return page

    def retranslate_ui(self) -> None:
        self._page_header.set_title(self.tr("Podcasts"))
        self._search.setPlaceholderText(self.tr("Search episodes"))
        self._search.setAccessibleName(self.tr("Search Podcast episodes"))
        self._add.setText(self.tr("Add Podcast"))
        self._sync_all.setText(self.tr("Sync Podcasts"))
        self._sync_all.setToolTip(self.tr("Sync every Podcast using its settings."))
        self._sync_show.setText(self.tr("Sync Podcast"))
        self._sync_settings.setText(self.tr("Sync Settings…"))
        self._add_episodes.setText(self.tr("Add to iPod"))
        self._remove_episodes.setText(self.tr("Remove from iPod"))
        self._add_episode_action.setText(self.tr("Add to iPod"))
        self._remove_episode_action.setText(self.tr("Remove from iPod"))
        self._empty_title.setText(self.tr("Your Podcast library starts here"))
        self._empty_detail.setText(
            self.tr(
                "Subscribe with the directory or an RSS feed. Podcasts already on "
                "your iPod will appear automatically."
            )
        )
        self._empty_add.setText(self.tr("Find a Podcast"))
        self._show_shelf.set_title(self.tr("YOUR SHOWS"))
        self._refresh_show.setText(self.tr("Refresh Show"))
        self._unsubscribe.setText(self.tr("Unsubscribe"))
        self._episodes_label.setText(self.tr("Episodes"))
        self._filter_button.setText(self.tr("Filter"))
        self._filter_button.setAccessibleName(self.tr("Filter Podcast episodes"))
        self._filter_button.setToolTip(
            self.tr("Show or hide episodes by listening and iPod status.")
        )
        self._filter_menu.setAccessibleName(self.tr("Episode filters"))
        self._filter_listened.setText(self.tr("Listened"))
        self._filter_unlistened.setText(self.tr("Unlistened"))
        self._filter_on_ipod.setText(self.tr("On iPod"))
        self._filter_not_on_ipod.setText(self.tr("Not on iPod"))
        self._episode_menu.setAccessibleName(self.tr("Episode actions"))
        self._mark_listened.setText(self.tr("Mark Listened"))
        self._mark_unlistened.setText(self.tr("Mark Unlistened"))
        self._render_status()
        self._render_selected_subscription()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._publish_status_message()
        self._schedule_open_refresh()

    def hideEvent(self, event: QHideEvent) -> None:
        self._status.clear(_STATUS_SOURCE)
        super().hideEvent(event)

    @Slot()
    def _controller_changed(self) -> None:
        selected_id = self._selected_source_id()
        self._snapshot = self._controller.snapshot
        selection = self._shows.selectionModel()
        with QSignalBlocker(selection):
            self._subscription_model.replace(
                self._snapshot.subscriptions,
                include_all=True,
            )
            self._content.setCurrentWidget(
                self._browser_page if self._snapshot.subscriptions else self._empty_page
            )
            if self._snapshot.subscriptions:
                row = self._subscription_model.row_for_id(selected_id)
                self._shows.setCurrentIndex(
                    self._subscription_model.index(max(0, row), 0)
                )
        self._show_shelf.set_count(len(self._snapshot.subscriptions))
        self._render_status()
        self._open_selected_subscription()

    @Slot(str)
    def _filter(self, query: str) -> None:
        self._query = query.strip()
        self._render_selected_subscription()

    @Slot(bool)
    def _episode_filters_changed(self, _checked: bool) -> None:
        self._render_selected_subscription()

    @Slot()
    def _show_add_dialog(self) -> None:
        if self._dialog is None:
            self._dialog = PodcastSearchDialog(
                self._controller,
                self._theme_manager,
                self,
            )
        self._dialog.show()
        self._dialog.raise_()
        self._dialog.activateWindow()

    @Slot()
    def _refresh_selected(self) -> None:
        if self._is_all_podcasts_selected():
            self._controller.refresh()
            return
        if subscription_id := self._selected_subscription_id():
            self._controller.refresh(subscription_id)

    @Slot()
    def _sync_podcasts(self) -> None:
        self._controller.sync()

    @Slot()
    def _sync_selected(self) -> None:
        if subscription_id := self._selected_subscription_id():
            self._controller.sync(subscription_id)

    @Slot()
    def _show_sync_settings(self) -> None:
        subscription = self._selected_subscription()
        if subscription is None or not self._controller.can_edit:
            return
        if self._settings_dialog is not None:
            self._settings_dialog.close()
            self._settings_dialog.deleteLater()
        self._settings_subscription_id = subscription.subscription_id
        self._settings_dialog = PodcastSyncSettingsDialog(
            subscription.title, subscription.sync_settings, self
        )
        self._settings_dialog.accepted.connect(self._save_sync_settings)
        self._settings_dialog.open()

    @Slot()
    def _save_sync_settings(self) -> None:
        if (
            self._settings_dialog is not None
            and self._settings_subscription_id is not None
            and self._controller.can_edit
        ):
            self._controller.set_sync_settings(
                self._settings_subscription_id,
                self._settings_dialog.selected_settings,
            )

    @Slot()
    def _add_selected_episodes(self) -> None:
        if identities := self._selected_sync_identities(on_device=False):
            self._controller.add_episodes(identities)

    @Slot()
    def _remove_selected_episodes(self) -> None:
        if identities := self._selected_sync_identities(on_device=True):
            self._controller.remove_episodes(identities)

    @Slot()
    def _unsubscribe_selected(self) -> None:
        if subscription_id := self._selected_subscription_id():
            self._controller.unsubscribe(subscription_id)

    @Slot(QModelIndex, QModelIndex)
    def _subscription_changed(
        self,
        _current: QModelIndex,
        _previous: QModelIndex,
    ) -> None:
        self._open_selected_subscription()

    def _open_selected_subscription(self) -> None:
        self._render_selected_subscription()
        self._availability_changed()
        source_id = self._selected_source_id()
        if source_id != self._opened_source_id:
            self._opened_source_id = source_id
            self._pending_open_source_id = source_id
        self._schedule_open_refresh()

    def _schedule_open_refresh(self) -> None:
        source_id = self._pending_open_source_id
        subscription = (
            self._snapshot.subscription(source_id)
            if source_id is not None and source_id != ALL_PODCASTS_SOURCE_ID
            else None
        )
        refreshable = (
            any(item.feed_url for item in self._snapshot.subscriptions)
            if source_id == ALL_PODCASTS_SOURCE_ID
            else subscription is not None and bool(subscription.feed_url)
        )
        if not refreshable:
            self._pending_open_source_id = None
            return
        if (
            not self.isVisible()
            or not self._controller.can_edit
            or self._open_refresh_scheduled
        ):
            return
        self._open_refresh_scheduled = True
        QTimer.singleShot(0, self._refresh_open_source)

    @Slot()
    def _refresh_open_source(self) -> None:
        self._open_refresh_scheduled = False
        source_id = self._pending_open_source_id
        if source_id != self._selected_source_id():
            return
        subscription = (
            self._snapshot.subscription(source_id)
            if source_id is not None and source_id != ALL_PODCASTS_SOURCE_ID
            else None
        )
        refreshable = (
            any(item.feed_url for item in self._snapshot.subscriptions)
            if source_id == ALL_PODCASTS_SOURCE_ID
            else subscription is not None and bool(subscription.feed_url)
        )
        if not refreshable:
            self._pending_open_source_id = None
            return
        if not self._controller.can_edit:
            return
        self._pending_open_source_id = None
        if source_id == ALL_PODCASTS_SOURCE_ID:
            self._controller.refresh()
        else:
            self._controller.refresh(source_id)

    @Slot(QItemSelection, QItemSelection)
    def _episode_selection_changed(
        self,
        _selected: QItemSelection,
        _deselected: QItemSelection,
    ) -> None:
        self._availability_changed()

    @Slot()
    @Slot(bool)
    def _availability_changed(self, _busy: bool | None = None) -> None:
        editable = self._controller.can_edit
        syncable = self._controller.can_sync
        self._episode_delegate.set_add_enabled(syncable)
        self._episodes.viewport().update()
        subscription = self._selected_subscription()
        selected_episodes = bool(self._selected_episode_identities())
        self._add.setEnabled(editable)
        self._empty_add.setEnabled(editable)
        self._sync_all.setEnabled(syncable and bool(self._snapshot.subscriptions))
        self._sync_show.setVisible(subscription is not None)
        self._sync_show.setEnabled(syncable and subscription is not None)
        self._sync_settings.setVisible(subscription is not None)
        self._sync_settings.setEnabled(editable and subscription is not None)
        addable = syncable and bool(self._selected_sync_identities(on_device=False))
        removable = syncable and bool(self._selected_sync_identities(on_device=True))
        self._add_episodes.setEnabled(addable)
        self._remove_episodes.setEnabled(removable)
        self._add_episode_action.setEnabled(addable)
        self._remove_episode_action.setEnabled(removable)
        if (
            self._settings_dialog is not None
            and self._settings_subscription_id is not None
            and (
                not editable
                or self._snapshot.subscription(self._settings_subscription_id) is None
            )
        ):
            self._settings_dialog.reject()
        device_backed = subscription is not None and subscription.on_device_count > 0
        self._unsubscribe.setEnabled(
            editable and subscription is not None and not device_backed
        )
        self._unsubscribe.setToolTip(
            self.tr(
                "Remove this Podcast's episodes from the iPod before unsubscribing."
            )
            if device_backed
            else ""
        )
        self._refresh_show.setEnabled(
            editable
            and (
                bool(subscription.feed_url)
                if subscription is not None
                else self._is_all_podcasts_selected()
                and any(item.feed_url for item in self._snapshot.subscriptions)
            )
        )
        self._mark_listened.setEnabled(editable and selected_episodes)
        self._mark_unlistened.setEnabled(editable and selected_episodes)

    @Slot(object)
    def _operation_failed(self, value: object) -> None:
        if isinstance(value, PodcastOperationFailure):
            self._set_status_message(value.message)

    @Slot(QModelIndex)
    def _episode_activated(self, index: QModelIndex) -> None:
        episode = self._episode_model.episode_at(index.row())
        if episode is None:
            return
        track = self._controller.track_for_episode(episode.track_id)
        if track is not None:
            self.trackActivated.emit(track)

    @Slot(QModelIndex)
    def _episode_action_requested(self, index: QModelIndex) -> None:
        episode = self._episode_model.episode_at(index.row())
        if episode is None:
            return
        if episode.on_device:
            self._episode_activated(index)
        elif self._controller.can_sync and episode.enclosure_url:
            identity = self._episode_model.identity_at(index.row())
            if identity is not None:
                self._controller.add_episodes((identity,))

    @Slot(QPoint)
    def _show_episode_context_menu(self, position: QPoint) -> None:
        index = self._episodes.indexAt(position)
        if not index.isValid():
            return

        selection = self._episodes.selectionModel()
        if not selection.isSelected(index):
            selection.setCurrentIndex(
                index,
                QItemSelectionModel.SelectionFlag.ClearAndSelect
                | QItemSelectionModel.SelectionFlag.Rows,
            )
        self._availability_changed()
        menu = self._episode_menu
        if self._track_actions is not None:
            track_menu = self._track_actions.build_menu_for_tracks(
                self._selected_device_tracks()
            )
            if track_menu is not None:
                track_menu.addSeparator()
                track_menu.addAction(self._add_episode_action)
                track_menu.addAction(self._remove_episode_action)
                track_menu.addSeparator()
                track_menu.addAction(self._mark_listened)
                track_menu.addAction(self._mark_unlistened)
                track_menu.aboutToHide.connect(track_menu.deleteLater)
                menu = track_menu
        menu.popup(self._episodes.viewport().mapToGlobal(position))

    def _set_listened(self, listened: bool) -> None:
        identities = self._selected_episode_identities()
        if identities:
            self._controller.mark_listened_selection(identities, listened)

    def _render_status(self) -> None:
        if self._controller.busy:
            message = self.tr("Updating Podcasts…")
        elif self._snapshot.issues:
            message = "  ".join(issue.message for issue in self._snapshot.issues)
        elif self._snapshot.subscriptions and not self._snapshot.writable:
            message = self.tr("Podcast state is read-only for this Active iPod.")
        else:
            message = ""
        self._set_status_message(message)

    def _set_status_message(self, message: str) -> None:
        if message == self._status_message:
            return
        self._status_message = message
        if self.isVisible():
            self._publish_status_message()

    def _publish_status_message(self) -> None:
        if self._status_message:
            self._status.show(_STATUS_SOURCE, self._status_message)
        else:
            self._status.clear(_STATUS_SOURCE)

    def _render_selected_subscription(self) -> None:
        if self._is_all_podcasts_selected():
            self._render_all_podcasts()
            return
        subscription = self._selected_subscription()
        if subscription is None:
            self._episode_model.replace("", ())
            self._show_artwork.set_artwork("", 0)
            self._show_artwork_stack.setCurrentWidget(self._show_artwork)
            self._show_title.setText(self.tr("Select a Podcast"))
            self._show_meta.clear()
            self._show_description.clear()
            self._episode_count.clear()
            return
        self._refresh_show.setText(self.tr("Refresh Show"))
        self._episodes_label.setText(self.tr("Episodes"))
        artwork_seed = stable_artwork_seed(subscription.subscription_id)
        if subscription.artwork_url:
            self._show_artwork.set_artwork(subscription.artwork_url, artwork_seed)
            self._show_artwork_stack.setCurrentWidget(self._show_artwork)
        elif self._device_show_artwork is not None and subscription.artwork_id > 0:
            self._device_show_artwork.set_seed(artwork_seed)
            self._device_show_artwork.set_artwork_id(subscription.artwork_id)
            self._show_artwork_stack.setCurrentWidget(self._device_show_artwork)
        else:
            self._show_artwork.set_artwork("", artwork_seed)
            self._show_artwork_stack.setCurrentWidget(self._show_artwork)
        self._show_title.setText(subscription.title)
        meta = " · ".join(
            part
            for part in (
                subscription.author,
                subscription.category,
                self.tr("%n episode(s)", None, len(subscription.episodes)),
                self.tr("%n on iPod", None, subscription.on_device_count)
                if subscription.on_device_count
                else "",
            )
            if part
        )
        self._show_meta.setText(meta)
        self._show_description.setText(
            subscription.description
            or self.tr("No show description is available from this feed.")
        )
        self._episode_model.replace(
            subscription.subscription_id,
            subscription.episodes,
            self._query,
            self._episode_filter(),
        )
        visible = self._episode_model.rowCount()
        filters_active = self._episode_filter().active
        self._episode_count.setText(
            self.tr("%n result(s)", None, visible)
            if self._query or filters_active
            else str(visible)
        )

    def _render_all_podcasts(self) -> None:
        subscriptions = self._snapshot.subscriptions
        episode_count = sum(len(item.episodes) for item in subscriptions)
        on_device_count = sum(item.on_device_count for item in subscriptions)
        self._collection_show_artwork.set_subscriptions(subscriptions)
        self._show_artwork_stack.setCurrentWidget(self._collection_show_artwork)
        self._refresh_show.setText(self.tr("Refresh All"))
        self._show_title.setText(self.tr("All Podcasts"))
        self._show_meta.setText(
            " · ".join(
                part
                for part in (
                    self.tr("%n show(s)", None, len(subscriptions)),
                    self.tr("%n episode(s)", None, episode_count),
                    self.tr("%n on iPod", None, on_device_count)
                    if on_device_count
                    else "",
                )
                if part
            )
        )
        self._show_description.setText(
            self.tr("The latest episodes from every Podcast you subscribe to.")
        )
        self._episodes_label.setText(self.tr("Latest Episodes"))
        self._episode_model.replace_all(
            subscriptions,
            self._query,
            self._episode_filter(),
        )
        visible = self._episode_model.rowCount()
        filters_active = self._episode_filter().active
        self._episode_count.setText(
            self.tr("%n result(s)", None, visible)
            if self._query or filters_active
            else str(visible)
        )

    def _episode_filter(self) -> PodcastEpisodeFilter:
        return PodcastEpisodeFilter(
            include_listened=self._filter_listened.isChecked(),
            include_unlistened=self._filter_unlistened.isChecked(),
            include_on_ipod=self._filter_on_ipod.isChecked(),
            include_not_on_ipod=self._filter_not_on_ipod.isChecked(),
        )

    def _selected_subscription_id(self) -> str | None:
        subscription = self._subscription_model.subscription_at(
            self._shows.currentIndex().row()
        )
        return subscription.subscription_id if subscription is not None else None

    def _selected_source_id(self) -> str | None:
        value = self._shows.currentIndex().data(PodcastListRole.IDENTITY)
        return value if isinstance(value, str) else None

    def _is_all_podcasts_selected(self) -> bool:
        return self._subscription_model.is_all_at(self._shows.currentIndex().row())

    def _selected_subscription(self) -> PodcastSubscription | None:
        subscription_id = self._selected_subscription_id()
        return (
            self._snapshot.subscription(subscription_id)
            if subscription_id is not None
            else None
        )

    def _selected_episode_identities(self) -> tuple[tuple[str, str], ...]:
        selection = self._episodes.selectionModel()
        identities = {
            identity
            for index in selection.selectedRows()
            if (identity := self._episode_model.identity_at(index.row())) is not None
        }
        return tuple(sorted(identities))

    def _selected_episodes(self) -> tuple[PodcastEpisode, ...]:
        selection = self._episodes.selectionModel()
        return tuple(
            episode
            for index in sorted(selection.selectedRows(), key=lambda value: value.row())
            if (episode := self._episode_model.episode_at(index.row())) is not None
        )

    def _selected_sync_identities(
        self, *, on_device: bool
    ) -> tuple[tuple[str, str], ...]:
        return tuple(
            sorted(
                identity
                for index in self._episodes.selectionModel().selectedRows()
                if (episode := self._episode_model.episode_at(index.row())) is not None
                and episode.on_device == on_device
                and (on_device or bool(episode.enclosure_url))
                and (identity := self._episode_model.identity_at(index.row()))
                is not None
            )
        )

    def _selected_device_tracks(self) -> tuple[Track, ...]:
        tracks: dict[int, Track] = {}
        for episode in self._selected_episodes():
            track = self._controller.track_for_episode(episode.track_id)
            if track is not None:
                tracks.setdefault(track.track_id, track)
        return tuple(tracks.values())

    @Slot(str)
    def _artwork_changed(self, _source_url: str) -> None:
        self._shows.viewport().update()

    @Slot(str)
    def _theme_changed(self, _theme: str) -> None:
        self._apply_styles()
        self._shows.viewport().update()
        self._episodes.viewport().update()
        self._show_artwork.update()
        self._collection_show_artwork.update()

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            render_podcast_page_style(
                self._theme_manager.tokens,
                self._theme_manager.typography,
            )
        )


def _add_filter_option(menu: QMenu, object_name: str) -> QCheckBox:
    checkbox = QCheckBox(menu)
    checkbox.setObjectName(object_name)
    checkbox.setChecked(True)
    action = QWidgetAction(menu)
    action.setDefaultWidget(checkbox)
    menu.addAction(action)
    return checkbox


__all__ = ["PodcastPage"]
