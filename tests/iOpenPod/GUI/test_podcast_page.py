"""Visual-structure tests for the artwork-led Podcast browser."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from PySide6.QtCore import (
    QItemSelectionModel,
    QObject,
    QPoint,
    QRect,
    QRectF,
    Qt,
    Signal,
)
from PySide6.QtGui import QAction, QColor, QImage, QPainter, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QLabel,
    QListView,
    QMenu,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QStyleOptionViewItem,
    QTableWidget,
    QWidget,
)
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION

from iOpenPod.app.artwork_controller import ArtworkController
from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.core.settings.stores import DeviceSettingsStore, GlobalSettingsStore
from iOpenPod.app.core.status import ApplicationStatus
from iOpenPod.app.models.artwork import ArtworkImage, ArtworkRequest
from iOpenPod.app.models.podcast_list_models import PodcastEpisodeListModel
from iOpenPod.app.podcasts.artwork_controller import PodcastArtworkController
from iOpenPod.app.podcasts.models import (
    PodcastArtworkImage,
    PodcastArtworkRequest,
    PodcastClearAge,
    PodcastClearMethod,
    PodcastEpisode,
    PodcastFillMode,
    PodcastSearchResult,
    PodcastSnapshot,
    PodcastSubscription,
    PodcastSyncSettings,
    SubscriptionSource,
)
from iOpenPod.GUI.delegates.podcast_delegates import (
    PodcastEpisodeDelegate,
    episode_status_text,
)
from iOpenPod.GUI.dialogs.podcast_search import PodcastSearchDialog
from iOpenPod.GUI.dialogs.podcast_sync_settings import PodcastSyncSettingsDialog
from iOpenPod.GUI.pages.podcast_page import PodcastPage
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.presentation.podcast_artwork_provider import (
    PodcastArtworkPixmapProvider,
)
from iOpenPod.GUI.presentation.podcast_collection_artwork import (
    paint_podcast_collection_artwork,
)
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT, LIGHT_TOKENS
from iOpenPod.GUI.widgets.artwork_view import ArtworkView
from iOpenPod.GUI.widgets.browser_chrome import PageHeader, SourceListPanel
from iOpenPod.GUI.widgets.elided_label import ElidedLabel
from iOpenPod.GUI.widgets.podcast_artwork import PodcastCollectionArtworkView
from iOpenPod.GUI.widgets.search_field import SearchField
from iPodDB.library import Track

if TYPE_CHECKING:
    from iOpenPod.app.podcasts.controller import PodcastController
    from iOpenPod.GUI.widgets.track_actions import TrackActions


class _Controller(QObject):
    changed = Signal()
    busyChanged = Signal(bool)
    operationFailed = Signal(object)
    searchFinished = Signal(object)

    def __init__(
        self,
        snapshot: PodcastSnapshot,
        tracks: tuple[Track, ...] = (),
    ) -> None:
        super().__init__()
        self.snapshot = snapshot
        self.tracks = {track.track_id: track for track in tracks}
        self.busy = False
        self.can_edit = True
        self.can_sync = True
        self.listened_calls: list[tuple[tuple[tuple[str, str], ...], bool]] = []
        self.refresh_calls: list[str | None] = []
        self.subscribe_calls: list[str] = []
        self.sync_calls: list[str | None] = []
        self.add_episode_calls: list[tuple[tuple[str, str], ...]] = []
        self.remove_episode_calls: list[tuple[tuple[str, str], ...]] = []
        self.settings_calls: list[tuple[str, PodcastSyncSettings]] = []

    def refresh(self, subscription_id: str | None = None) -> None:
        self.refresh_calls.append(subscription_id)

    def unsubscribe(self, _subscription_id: str) -> None:
        pass

    def sync(self, subscription_id: str | None = None) -> None:
        self.sync_calls.append(subscription_id)

    def add_episodes(self, identities: tuple[tuple[str, str], ...]) -> None:
        self.add_episode_calls.append(identities)

    def remove_episodes(self, identities: tuple[tuple[str, str], ...]) -> None:
        self.remove_episode_calls.append(identities)

    def set_sync_settings(
        self, subscription_id: str, settings: PodcastSyncSettings
    ) -> None:
        self.settings_calls.append((subscription_id, settings))

    def search(self, _query: str) -> None:
        pass

    def subscribe(self, feed_url: str) -> None:
        self.subscribe_calls.append(feed_url)

    def mark_listened(
        self,
        subscription_id: str,
        episode_ids: tuple[str, ...],
        listened: bool,
    ) -> None:
        self.listened_calls.append(
            (
                tuple((subscription_id, episode_id) for episode_id in episode_ids),
                listened,
            )
        )

    def mark_listened_selection(
        self,
        episode_identities: tuple[tuple[str, str], ...],
        listened: bool,
    ) -> None:
        self.listened_calls.append((episode_identities, listened))

    def track_for_episode(self, track_id: int | None) -> Track | None:
        return self.tracks.get(track_id) if track_id is not None else None


class _TrackActions:
    def __init__(self) -> None:
        self.parent: QWidget | None = None
        self.calls: list[tuple[Track, ...]] = []

    def build_menu_for_tracks(self, tracks: tuple[Track, ...]) -> QMenu | None:
        self.calls.append(tracks)
        if not tracks:
            return None
        assert self.parent is not None
        menu = QMenu(self.parent)
        menu.setObjectName("trackContextMenu")
        menu.addAction("Edit Metadata…")
        return menu


class _NoArtwork:
    def load_artwork(
        self,
        request: PodcastArtworkRequest,
    ) -> PodcastArtworkImage | None:
        del request
        return None


class _DeviceArtwork:
    def load_artwork(self, request: ArtworkRequest) -> ArtworkImage:
        size = request.target_px
        return ArtworkImage(
            cache_key=f"device/{request.artwork_id}/{size}",
            artwork_id=request.artwork_id,
            format_id=1,
            width=size,
            height=size,
            rgb888=bytes((30, 90, 150)) * size * size,
        )


def test_podcast_directory_is_textual_and_subscribes_using_the_feed_url() -> None:
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    theme = ThemeManager(APPLICATION, settings)
    controller = _Controller(PodcastSnapshot(writable=True))
    dialog = PodcastSearchDialog(cast("PodcastController", controller), theme)
    result = PodcastSearchResult(
        "Example Show",
        "Example Publisher",
        "https://publisher.example.test/rss",
        category="Technology",
        episode_count=42,
    )
    try:
        dialog.show()
        controller.searchFinished.emit((result,))
        APPLICATION.processEvents()
        results = dialog.findChild(QListView, "podcastDirectoryResults")
        intro = dialog.findChild(QLabel, "podcastDialogIntro")
        subscribe = dialog.findChild(QPushButton, "podcastSubscribeSelected")
        assert results is not None and results.model().rowCount() == 1
        assert intro is not None and "publisher" in intro.text()
        assert "artwork" not in intro.text()
        assert not dialog.grab().isNull()
        assert subscribe is not None and subscribe.isEnabled()
        subscribe.click()
        assert controller.subscribe_calls == [result.feed_url]
    finally:
        dialog.close()
        theme.close()


class _SolidPodcastArtworkProvider:
    def __init__(self, colors: dict[str, QColor]) -> None:
        self._colors = colors

    def pixmap(
        self,
        source_url: str,
        logical_size: int,
        _device_pixel_ratio: float,
    ) -> QPixmap | None:
        color = self._colors.get(source_url)
        if color is None:
            return None
        pixmap = QPixmap(logical_size, logical_size)
        pixmap.fill(color)
        return pixmap


def test_all_podcasts_artwork_paints_four_cover_collection() -> None:
    colors = {
        "https://example.test/one.png": QColor("#CC3344"),
        "https://example.test/two.png": QColor("#338855"),
        "https://example.test/three.png": QColor("#3366CC"),
        "https://example.test/four.png": QColor("#CC9933"),
    }
    subscriptions = tuple(
        PodcastSubscription(
            f"show-{position}",
            f"https://example.test/{position}.xml",
            f"Show {position}",
            SubscriptionSource.USER,
            artwork_url=source_url,
        )
        for position, source_url in enumerate(colors, start=1)
    )
    image = QImage(100, 100, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    paint_podcast_collection_artwork(
        painter,
        QRectF(0, 0, 100, 100),
        subscriptions,
        cast("PodcastArtworkPixmapProvider", _SolidPodcastArtworkProvider(colors)),
        LIGHT_TOKENS,
        1.0,
    )
    painter.end()

    assert image.pixelColor(24, 24) == colors["https://example.test/one.png"]
    assert image.pixelColor(76, 24) == colors["https://example.test/two.png"]
    assert image.pixelColor(24, 76) == colors["https://example.test/three.png"]
    assert image.pixelColor(76, 76) == colors["https://example.test/four.png"]


def test_podcast_page_uses_artwork_catalogue_and_episode_stream() -> None:
    show_description_text = (
        "Conversations about the small decisions that shape great products, "
        "from hierarchy and rhythm to accessibility and restraint. Each episode "
        "follows one interface from the original idea through difficult tradeoffs, "
        "testing, revision, and the details that ultimately make it feel considered. "
        "Guests share the mistakes, constraints, and discoveries behind their work."
    )
    subscription = PodcastSubscription(
        "design-show",
        "https://example.test/feed.xml",
        "Design Details",
        SubscriptionSource.USER,
        author="Example Studio",
        description=show_description_text,
        artwork_id=77,
        category="Design",
        episodes=(
            PodcastEpisode(
                "episode-one",
                title="The weight of a good interface",
                description="A thoughtful look at rhythm, hierarchy, and restraint.",
                enclosure_url="https://example.test/interface.mp3",
                published_at=1_700_000_000,
                duration_seconds=2_940,
            ),
            PodcastEpisode(
                "episode-two",
                title="Designing for the device in your hand",
                description="What hardware teaches us about software.",
                on_device=True,
                track_id=42,
                listened=True,
            ),
        ),
    )
    device_track = Track(42, "Designing for the device in your hand", "", "", 1)
    controller = _Controller(
        PodcastSnapshot(subscriptions=(subscription,), writable=True),
        (device_track,),
    )
    status = ApplicationStatus(APPLICATION)
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    theme = ThemeManager(APPLICATION, settings)
    artwork_controller = PodcastArtworkController(_NoArtwork())
    provider = PodcastArtworkPixmapProvider(artwork_controller)
    device_artwork_controller = ArtworkController(_DeviceArtwork())
    device_provider = ArtworkPixmapProvider(device_artwork_controller)
    track_actions = _TrackActions()
    page = PodcastPage(
        cast("PodcastController", controller),
        status,
        theme,
        provider,
        device_artwork_provider=device_provider,
        track_actions=cast("TrackActions", track_actions),
    )
    track_actions.parent = page

    try:
        assert controller.refresh_calls == []
        page.resize(1180, 900)
        page.show()
        APPLICATION.processEvents()
        assert controller.refresh_calls == [None]

        show_shelf = page.findChild(QListView, "podcastShowShelf")
        assert show_shelf is not None
        assert show_shelf.model().rowCount() == 2
        assert show_shelf.currentIndex().row() == 0
        assert show_shelf.currentIndex().data() == "All Podcasts"
        show_title = page.findChild(QLabel, "podcastShowTitle")
        assert show_title is not None
        assert show_title.text() == "All Podcasts"
        artwork_stack = page.findChild(QStackedWidget, "podcastShowArtworkStack")
        collection_artwork = page.findChild(
            PodcastCollectionArtworkView,
            "podcastCollectionArtworkView",
        )
        assert artwork_stack is not None
        assert collection_artwork is not None
        assert artwork_stack.currentWidget() is collection_artwork
        show_shelf.setCurrentIndex(show_shelf.model().index(1, 0))
        APPLICATION.processEvents()
        assert controller.refresh_calls == [None, subscription.subscription_id]

        controller.busy = True
        controller.can_edit = False
        controller.changed.emit()
        APPLICATION.processEvents()
        assert status.current_message == "Updating Podcasts…"
        controller.busy = False
        controller.can_edit = True
        controller.changed.emit()
        APPLICATION.processEvents()
        assert status.current_message == ""
        add_button = page.findChild(QPushButton, "podcastsAdd")
        assert add_button is not None
        add_button.click()
        APPLICATION.processEvents()

        episode_list = page.findChild(QListView, "podcastEpisodeList")
        directory_results = page.findChild(QListView, "podcastDirectoryResults")
        show_description = page.findChild(ElidedLabel, "podcastShowDescription")
        hero = page.findChild(QFrame, "podcastHero")
        refresh_show = page.findChild(QPushButton, "podcastRefreshShow")
        unsubscribe = page.findChild(QPushButton, "podcastUnsubscribe")
        toolbar = page.findChild(QFrame, "podcastsToolbar")
        episodes_section = page.findChild(QWidget, "podcastEpisodesSection")
        episode_search = page.findChild(SearchField, "podcastsSearch")
        filter_button = page.findChild(QPushButton, "podcastEpisodeFilter")
        filter_menu = page.findChild(QMenu, "podcastEpisodeFilterMenu")
        filter_listened = page.findChild(QCheckBox, "podcastFilterListened")
        filter_unlistened = page.findChild(QCheckBox, "podcastFilterUnlistened")
        filter_on_ipod = page.findChild(QCheckBox, "podcastFilterOnIPod")
        filter_not_on_ipod = page.findChild(QCheckBox, "podcastFilterNotOnIPod")
        episode_menu = page.findChild(QMenu, "podcastEpisodeContextMenu")
        mark_listened = page.findChild(QAction, "podcastMarkListened")
        mark_unlistened = page.findChild(QAction, "podcastMarkUnlistened")

        assert episode_list is not None
        assert directory_results is not None
        assert artwork_stack.currentWidget() is page.findChild(ArtworkView)
        assert show_description is not None
        assert hero is not None
        assert refresh_show is not None
        assert unsubscribe is not None
        assert isinstance(toolbar, PageHeader)
        assert toolbar.height() == LAYOUT.page_header_height
        assert page.findChild(QPushButton, "podcastsRefreshAll") is None
        source_list = page.findChild(SourceListPanel, "podcastShelf")
        assert source_list is not None
        assert source_list.title_label.text() == "YOUR SHOWS"
        assert source_list.count_label.text() == "1"
        splitter = page.findChild(QSplitter, "podcastBrowserSplitter")
        assert splitter is not None
        assert splitter.count() == 2
        assert splitter.handleWidth() == LAYOUT.source_list_splitter_handle_width
        assert not splitter.childrenCollapsible()
        assert all(
            not splitter.isCollapsible(index) for index in range(splitter.count())
        )
        original_shelf_width = splitter.sizes()[0]
        splitter.moveSplitter(original_shelf_width + 40, 1)
        APPLICATION.processEvents()
        assert splitter.sizes()[0] > original_shelf_width
        assert episodes_section is not None
        assert episode_search is not None
        assert filter_button is not None
        assert filter_menu is not None
        assert filter_listened is not None
        assert filter_unlistened is not None
        assert filter_on_ipod is not None
        assert filter_not_on_ipod is not None
        assert episode_menu is not None
        assert mark_listened is not None
        assert mark_unlistened is not None
        assert page.findChild(QLabel, "podcastsStatus") is None
        assert page.findChild(QLabel, "podcastsEyebrow") is None
        assert page.findChild(QLabel, "podcastShowKicker") is None
        assert page.findChild(QPushButton, "podcastMarkListened") is None
        assert page.findChild(QPushButton, "podcastMarkUnlistened") is None
        assert episodes_section.isAncestorOf(episode_search)
        assert not toolbar.isAncestorOf(episode_search)
        assert filter_button.menu() is filter_menu
        assert all(
            option.isChecked()
            for option in (
                filter_listened,
                filter_unlistened,
                filter_on_ipod,
                filter_not_on_ipod,
            )
        )
        filter_origin = filter_button.mapTo(episodes_section, QPoint())
        search_origin = episode_search.mapTo(episodes_section, QPoint())
        assert filter_origin.x() < search_origin.x()
        assert (
            episode_list.contextMenuPolicy() is Qt.ContextMenuPolicy.CustomContextMenu
        )
        assert [
            None if action.isSeparator() else action.text()
            for action in episode_menu.actions()
        ] == [
            "Add to iPod",
            "Remove from iPod",
            None,
            "Mark Listened",
            "Mark Unlistened",
        ]
        assert show_shelf.viewMode() is QListView.ViewMode.ListMode
        assert show_shelf.flow() is QListView.Flow.TopToBottom
        assert (
            show_shelf.horizontalScrollBarPolicy()
            is Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        assert (
            show_shelf.verticalScrollBarPolicy() is Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        show_origin = show_shelf.mapTo(page, QPoint())
        hero_origin = hero.mapTo(page, QPoint())
        assert show_origin.x() < hero_origin.x()
        assert show_shelf.height() > show_shelf.width()
        assert hero.minimumHeight() == 240
        assert hero.maximumHeight() == 240
        assert hero.height() == 240
        artwork_origin = artwork_stack.mapTo(hero, QPoint())
        assert artwork_origin.x() == 24
        assert artwork_origin.y() - hero.contentsRect().top() == 24
        refresh_origin = refresh_show.mapTo(hero, QPoint())
        unsubscribe_origin = unsubscribe.mapTo(hero, QPoint())
        assert refresh_origin.y() == unsubscribe_origin.y()
        assert refresh_origin.x() < unsubscribe_origin.x()
        assert (
            hero.contentsRect().bottom()
            - (unsubscribe_origin.y() + unsubscribe.height() - 1)
            == 24
        )
        assert show_description.maximum_lines == 4
        assert show_description.is_elided
        assert show_description.toolTip() == show_description_text
        assert show_shelf.model().rowCount() == 2
        assert episode_list.model().rowCount() == 2
        assert episode_status_text(subscription.episodes[0]) == "Add to iPod"
        assert episode_status_text(subscription.episodes[1]) == "ON IPOD · LISTENED"

        filter_listened.setChecked(False)
        APPLICATION.processEvents()
        assert episode_list.model().rowCount() == 1
        assert episode_list.model().index(0, 0).data() == subscription.episodes[0].title
        filter_listened.setChecked(True)
        filter_not_on_ipod.setChecked(False)
        APPLICATION.processEvents()
        assert episode_list.model().rowCount() == 1
        assert episode_list.model().index(0, 0).data() == subscription.episodes[1].title
        filter_on_ipod.setChecked(False)
        APPLICATION.processEvents()
        assert episode_list.model().rowCount() == 0
        filter_on_ipod.setChecked(True)
        filter_not_on_ipod.setChecked(True)
        APPLICATION.processEvents()
        assert episode_list.model().rowCount() == 2

        episode_selection = episode_list.selectionModel()
        episode_model = episode_list.model()
        selection_flags = (
            QItemSelectionModel.SelectionFlag.Select
            | QItemSelectionModel.SelectionFlag.Rows
        )
        episode_selection.select(episode_model.index(0, 0), selection_flags)
        episode_selection.select(episode_model.index(1, 0), selection_flags)
        second_episode_position = episode_list.visualRect(
            episode_model.index(1, 0)
        ).center()
        episode_list.customContextMenuRequested.emit(second_episode_position)
        APPLICATION.processEvents()
        track_menu = page.findChild(QMenu, "trackContextMenu")
        assert track_menu is not None and track_menu.isVisible()
        assert [
            None if action.isSeparator() else action.text()
            for action in track_menu.actions()
        ] == [
            "Edit Metadata…",
            None,
            "Add to iPod",
            "Remove from iPod",
            None,
            "Mark Listened",
            "Mark Unlistened",
        ]
        assert track_actions.calls == [(device_track,)]
        assert [index.row() for index in episode_selection.selectedRows()] == [0, 1]
        mark_listened.trigger()
        track_menu.hide()
        assert controller.listened_calls == [
            (
                (
                    ("design-show", "episode-one"),
                    ("design-show", "episode-two"),
                ),
                True,
            )
        ]

        episode_selection.clearSelection()
        episode_selection.select(episode_model.index(0, 0), selection_flags)
        episode_list.customContextMenuRequested.emit(second_episode_position)
        APPLICATION.processEvents()
        assert [index.row() for index in episode_selection.selectedRows()] == [1]
        mark_unlistened.trigger()
        episode_menu.hide()
        assert controller.listened_calls[-1] == (
            (("design-show", "episode-two"),),
            False,
        )

        episode_selection.clearSelection()
        episode_selection.select(episode_model.index(0, 0), selection_flags)
        first_episode_position = episode_list.visualRect(
            episode_model.index(0, 0)
        ).center()
        episode_list.customContextMenuRequested.emit(first_episode_position)
        APPLICATION.processEvents()
        assert episode_menu.isVisible()
        assert track_actions.calls[-1] == ()
        episode_menu.hide()

        assert isinstance(artwork_stack.currentWidget(), ArtworkView)
        assert not page.findChildren(QTableWidget)
        assert "macrostructure: Catalogue" in page.styleSheet()

        second = PodcastSubscription(
            "engineering-show",
            "https://example.test/engineering.xml",
            "Engineering Details",
            SubscriptionSource.USER,
            author="Second Network",
            episodes=(
                PodcastEpisode(
                    "episode-three",
                    title="A newer episode from another show",
                    published_at=1_800_000_000,
                ),
            ),
        )
        controller.snapshot = PodcastSnapshot(
            subscriptions=(subscription, second),
            writable=True,
        )
        controller.changed.emit()
        APPLICATION.processEvents()
        assert controller.refresh_calls == [None, subscription.subscription_id]

        assert show_shelf.model().rowCount() == 3
        show_shelf.setCurrentIndex(show_shelf.model().index(2, 0))
        APPLICATION.processEvents()
        assert controller.refresh_calls == [
            None,
            subscription.subscription_id,
            second.subscription_id,
        ]
        assert refresh_show.text() == "Refresh Show"

        show_shelf.setCurrentIndex(show_shelf.model().index(0, 0))
        APPLICATION.processEvents()
        assert refresh_show.text() == "Refresh All"
        assert refresh_show.isEnabled()
        assert controller.refresh_calls == [
            None,
            subscription.subscription_id,
            second.subscription_id,
            None,
        ]
        assert episode_list.model().rowCount() == 3
        assert (
            episode_list.model().index(0, 0).data()
            == "A newer episode from another show"
        )
        assert (
            episode_list.model().index(1, 0).data() == "The weight of a good interface"
        )

        episode_search.setText("Second Network")
        episode_search.queryChanged.emit("Second Network")
        APPLICATION.processEvents()
        assert episode_list.model().rowCount() == 1
        assert (
            episode_list.model().index(0, 0).data()
            == "A newer episode from another show"
        )
        episode_search.clear()
        episode_search.queryChanged.emit("")
        APPLICATION.processEvents()

        episode_selection.select(episode_model.index(0, 0), selection_flags)
        episode_selection.select(episode_model.index(1, 0), selection_flags)
        mark_listened.trigger()
        selected_identities, listened = controller.listened_calls[-1]
        assert set(selected_identities) == {
            ("design-show", "episode-one"),
            ("engineering-show", "episode-three"),
        }
        assert listened is True

        controller.changed.emit()
        APPLICATION.processEvents()
        assert controller.refresh_calls == [
            None,
            subscription.subscription_id,
            second.subscription_id,
            None,
        ]
    finally:
        page.close()
        page.deleteLater()
        APPLICATION.processEvents()
        provider.shutdown()
        artwork_controller.shutdown()
        device_provider.shutdown()
        device_artwork_controller.shutdown()
        theme.close()


def test_episode_delegate_paints_resting_rows_on_surface() -> None:
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    theme = ThemeManager(APPLICATION, settings)
    model = PodcastEpisodeListModel()
    model.replace(
        "design-show",
        (PodcastEpisode("episode-one", title="The weight of a good interface"),),
    )
    index = model.index(0, 0)
    delegate = PodcastEpisodeDelegate(theme)
    option = QStyleOptionViewItem()
    size = delegate.sizeHint(option, index)
    option.rect = QRect(QPoint(), size)
    image = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(theme.tokens.window))
    painter = QPainter(image)

    try:
        delegate.paint(painter, option, index)
    finally:
        painter.end()

    try:
        assert image.pixelColor(12, size.height() // 2) == QColor(theme.tokens.surface)
    finally:
        theme.close()


def test_podcast_sync_actions_preserve_show_identity_and_filter_membership() -> None:
    subscriptions = tuple(
        PodcastSubscription(
            show_id,
            f"https://example.test/{show_id}.xml",
            show_id,
            SubscriptionSource.USER,
            episodes=(
                PodcastEpisode(
                    "new",
                    title=f"New {show_id}",
                    enclosure_url=f"https://example.test/{show_id}.mp3",
                    published_at=200,
                ),
                PodcastEpisode(
                    "saved",
                    title=f"Saved {show_id}",
                    on_device=True,
                    track_id=track_id,
                    published_at=100,
                ),
                PodcastEpisode("no-media", title="No media URL"),
            ),
        )
        for show_id, track_id in (("First", 1), ("Second", 2))
    )
    controller = _Controller(
        PodcastSnapshot(subscriptions=subscriptions, writable=True)
    )
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    theme = ThemeManager(APPLICATION, settings)
    artwork_controller = PodcastArtworkController(_NoArtwork())
    provider = PodcastArtworkPixmapProvider(artwork_controller)
    page = PodcastPage(
        cast("PodcastController", controller),
        ApplicationStatus(APPLICATION),
        theme,
        provider,
    )
    try:
        page.resize(1180, 900)
        page.show()
        APPLICATION.processEvents()
        episodes = page.findChild(QListView, "podcastEpisodeList")
        shows = page.findChild(QListView, "podcastShowShelf")
        add = page.findChild(QPushButton, "podcastAddEpisodes")
        remove = page.findChild(QPushButton, "podcastRemoveEpisodes")
        sync_all = page.findChild(QPushButton, "podcastsSyncAll")
        sync_show = page.findChild(QPushButton, "podcastSyncShow")
        sync_settings = page.findChild(QPushButton, "podcastSyncSettings")
        assert episodes is not None and shows is not None
        assert add is not None and remove is not None
        assert sync_all is not None and sync_show is not None
        assert sync_settings is not None
        assert not add.isEnabled() and not remove.isEnabled()
        assert not sync_show.isVisible() and not sync_settings.isVisible()
        sync_all.click()
        assert controller.sync_calls == [None]

        episodes.selectAll()
        assert add.isEnabled() and remove.isEnabled()
        add.click()
        remove.click()
        assert controller.add_episode_calls == [(("First", "new"), ("Second", "new"))]
        assert controller.remove_episode_calls == [
            (("First", "saved"), ("Second", "saved"))
        ]
        controller.can_sync = False
        controller.busyChanged.emit(True)
        assert not add.isEnabled() and not remove.isEnabled()
        assert not sync_all.isEnabled()
        controller.can_sync = True
        controller.busyChanged.emit(False)

        shows.setCurrentIndex(shows.model().index(1, 0))
        APPLICATION.processEvents()
        assert sync_show.isVisible() and sync_show.isEnabled()
        assert sync_settings.isVisible() and sync_settings.isEnabled()
        sync_show.click()
        assert controller.sync_calls == [None, "First"]
        model = cast("PodcastEpisodeListModel", episodes.model())
        no_media_row = next(
            row
            for row in range(model.rowCount())
            if model.identity_at(row) == ("First", "no-media")
        )
        episodes.setCurrentIndex(model.index(no_media_row, 0))
        assert not add.isEnabled() and not remove.isEnabled()

        sync_settings.click()
        APPLICATION.processEvents()
        dialog = page.findChild(PodcastSyncSettingsDialog)
        assert dialog is not None and dialog.isVisible()
        slots = dialog.findChild(QSpinBox, "podcastSyncEpisodeSlots")
        assert slots is not None
        slots.setValue(7)
        dialog.reject()
        assert controller.settings_calls == []
        sync_settings.click()
        APPLICATION.processEvents()
        dialogs = page.findChildren(PodcastSyncSettingsDialog)
        dialog = next(item for item in dialogs if item.isVisible())
        slots = dialog.findChild(QSpinBox, "podcastSyncEpisodeSlots")
        assert slots is not None
        assert slots.value() == 3
        slots.setValue(8)
        dialog.accept()
        assert controller.settings_calls == [
            ("First", PodcastSyncSettings(episode_slots=8))
        ]

        sync_settings.click()
        APPLICATION.processEvents()
        dialog = next(
            item
            for item in page.findChildren(PodcastSyncSettingsDialog)
            if item.isVisible()
        )
        controller.snapshot = PodcastSnapshot()
        controller.changed.emit()
        assert not dialog.isVisible()
        assert len(controller.settings_calls) == 1
    finally:
        page.close()
        page.deleteLater()
        APPLICATION.processEvents()
        provider.shutdown()
        artwork_controller.shutdown()
        theme.close()


def test_podcast_sync_settings_retain_policy_and_explain_age_selection() -> None:
    policy = PodcastSyncSettings(
        episode_slots=12,
        fill_mode=PodcastFillMode.NEXT,
        clear_when_listened=False,
        clear_older_than=PodcastClearAge.TWO_WEEKS,
        clear_method=PodcastClearMethod.REPLACE,
    )
    dialog = PodcastSyncSettingsDialog("Example Podcast", policy)
    try:
        dialog.show()
        APPLICATION.processEvents()
        assert dialog.selected_settings == policy
        slots = dialog.findChild(QSpinBox, "podcastSyncEpisodeSlots")
        fill = dialog.findChild(QComboBox, "podcastSyncFillMode")
        age = dialog.findChild(QComboBox, "podcastSyncClearAge")
        method = dialog.findChild(QComboBox, "podcastSyncClearMethod")
        listened = dialog.findChild(QCheckBox, "podcastSyncClearListened")
        assert slots is not None and (slots.minimum(), slots.maximum()) == (1, 50)
        assert slots.accessibleName() == "Episodes to keep"
        assert slots.text() == "12 episodes"
        assert "extra episodes yourself" in slots.toolTip()
        assert fill is not None and age is not None and method is not None
        assert listened is not None and not listened.isChecked()
        assert age.isEnabled() and age.count() == 9
        descriptions = dialog.findChildren(QLabel, "pageDescription")
        explanation = " ".join(label.text() for label in descriptions)
        assert fill.currentText() == "Next in order"
        assert age.currentText() == "2 weeks on iPod"
        assert method.currentText() == "Only when replaced"
        assert "Unlistened episodes removed after this time are skipped" in explanation
        assert "Automatic target" not in explanation
        assert "Starts with the oldest" in fill.toolTip()
        assert "replacements are ready" in method.toolTip()
        fill.setCurrentIndex(fill.findData("newest"))
        assert age.isEnabled()
        assert dialog.selected_settings.clear_older_than is PodcastClearAge.TWO_WEEKS
        explanation = " ".join(label.text() for label in descriptions)
        assert fill.currentText() == "Newest episodes"
        assert "when there's room" in fill.toolTip()
        assert "skipped" not in explanation
        fill.setCurrentIndex(fill.findData("next"))
        age.setCurrentIndex(age.findData("never"))
        explanation = " ".join(label.text() for label in descriptions)
        assert "skipped" not in explanation
        slots.setValue(1)
        assert slots.text() == "1 episode"
        slots.setValue(12)
        age.setCurrentIndex(age.findData("immediate"))
        method.setCurrentIndex(method.findData("remove"))
        listened.setChecked(True)
        explanation = " ".join(label.text() for label in descriptions)
        assert "Unlistened episodes removed after this time are skipped" in explanation
        assert age.currentText() == "Every sync"
        assert method.currentText() == "At next sync"
        assert "even if there isn't another" in method.toolTip()
        assert dialog.selected_settings == PodcastSyncSettings(
            episode_slots=12,
            fill_mode=PodcastFillMode.NEXT,
            clear_older_than=PodcastClearAge.IMMEDIATE,
        )
        assert not dialog.grab().isNull()
    finally:
        dialog.close()


def test_episode_badge_click_adds_only_that_episode_and_play_circle_plays() -> None:
    incoming = PodcastEpisode(
        "incoming", title="Incoming", enclosure_url="https://example.test/episode.mp3"
    )
    unavailable = PodcastEpisode("unavailable", title="No media")
    saved = PodcastEpisode("saved", title="Saved", on_device=True, track_id=42)
    subscriptions = (
        PodcastSubscription(
            "first",
            "https://example.test/first.xml",
            "First",
            SubscriptionSource.USER,
            episodes=(incoming, unavailable),
        ),
        PodcastSubscription(
            "second",
            "https://example.test/second.xml",
            "Second",
            SubscriptionSource.USER,
            episodes=(saved,),
        ),
    )
    track = Track(42, "Saved", "", "", 1)
    controller = _Controller(
        PodcastSnapshot(subscriptions=subscriptions, writable=True), (track,)
    )
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    theme = ThemeManager(APPLICATION, settings)
    artwork_controller = PodcastArtworkController(_NoArtwork())
    provider = PodcastArtworkPixmapProvider(artwork_controller)
    page = PodcastPage(
        cast("PodcastController", controller),
        ApplicationStatus(APPLICATION),
        theme,
        provider,
    )
    activated: list[object] = []
    page.trackActivated.connect(activated.append)
    try:
        page.resize(1180, 900)
        page.show()
        APPLICATION.processEvents()
        episodes = page.findChild(QListView, "podcastEpisodeList")
        assert episodes is not None
        model = cast("PodcastEpisodeListModel", episodes.model())
        delegate = episodes.itemDelegate()
        assert isinstance(delegate, PodcastEpisodeDelegate)
        episodes.selectAll()
        incoming_row = next(
            row
            for row in range(model.rowCount())
            if model.identity_at(row) == ("first", "incoming")
        )
        saved_row = next(
            row
            for row in range(model.rowCount())
            if model.identity_at(row) == ("second", "saved")
        )
        option = QStyleOptionViewItem()
        option.initFrom(episodes)
        option.rect = episodes.visualRect(model.index(incoming_row, 0))
        badge = delegate.action_rect(option, model.index(incoming_row, 0))
        assert not badge.isEmpty()
        QTest.mouseClick(
            episodes.viewport(), Qt.MouseButton.LeftButton, pos=badge.center().toPoint()
        )
        assert controller.add_episode_calls == [(("first", "incoming"),)]

        # The body keeps ordinary selection, even if a drag ends over the badge.
        body = option.rect.topLeft() + QPoint(40, 45)
        QTest.mousePress(episodes.viewport(), Qt.MouseButton.LeftButton, pos=body)
        QTest.mouseRelease(
            episodes.viewport(), Qt.MouseButton.LeftButton, pos=badge.center().toPoint()
        )
        assert len(controller.add_episode_calls) == 1
        assert episodes.currentIndex().row() == incoming_row

        controller.can_sync = False
        controller.busyChanged.emit(True)
        QTest.mouseClick(
            episodes.viewport(), Qt.MouseButton.LeftButton, pos=badge.center().toPoint()
        )
        assert len(controller.add_episode_calls) == 1
        option.rect = episodes.visualRect(model.index(saved_row, 0))
        circle = delegate.action_rect(option, model.index(saved_row, 0))
        QTest.mouseClick(
            episodes.viewport(),
            Qt.MouseButton.LeftButton,
            pos=circle.center().toPoint(),
        )
        assert activated == [track]
        assert episode_status_text(unavailable) == "Unavailable"
        missing_row = next(
            row
            for row in range(model.rowCount())
            if model.identity_at(row) == ("first", "unavailable")
        )
        option.rect = episodes.visualRect(model.index(missing_row, 0))
        assert delegate.action_rect(option, model.index(missing_row, 0)).isEmpty()
    finally:
        page.close()
        page.deleteLater()
        APPLICATION.processEvents()
        provider.shutdown()
        artwork_controller.shutdown()
        theme.close()
