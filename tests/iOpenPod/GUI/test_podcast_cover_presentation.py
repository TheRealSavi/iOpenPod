"""Paint real Qt delegates to verify discovery and Episode artwork provenance."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QLineEdit,
    QListView,
    QPushButton,
    QStyleOptionViewItem,
    QWidget,
)
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION
from tests.iOpenPod.GUI.test_podcast_page import PodcastControllerStub

from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.core.settings.stores import DeviceSettingsStore, GlobalSettingsStore
from iOpenPod.app.models.podcast_list_models import (
    PodcastEpisodeListModel,
    PodcastSearchResultListModel,
)
from iOpenPod.app.podcasts.controller import PodcastOperation, PodcastOperationFailure
from iOpenPod.app.podcasts.models import (
    PodcastEpisode,
    PodcastSearchResult,
    PodcastSnapshot,
    PodcastSubscription,
    SubscriptionSource,
)
from iOpenPod.GUI.delegates.podcast_delegates import (
    PodcastEpisodeDelegate,
    PodcastSearchResultDelegate,
)
from iOpenPod.GUI.dialogs.podcast_search import PodcastSearchDialog
from iOpenPod.GUI.presentation.theme.manager import ThemeManager

if TYPE_CHECKING:
    from iOpenPod.app.podcasts.controller import PodcastController
    from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
    from iOpenPod.GUI.presentation.podcast_artwork_provider import (
        PodcastArtworkPixmapProvider,
    )


class _Pixels:
    def __init__(self, colors: dict[str | int, str]) -> None:
        self.colors = colors
        self.requests: list[str | int] = []

    def pixmap(self, source: str | int, size: int, _ratio: float) -> QPixmap | None:
        self.requests.append(source)
        if source not in self.colors:
            return None
        image = QPixmap(size, size)
        image.fill(QColor(self.colors[source]))
        return image

    def feed_pixmap(self, source: str, size: int, ratio: float) -> QPixmap | None:
        return self.pixmap(source, size, ratio)


@pytest.mark.parametrize("source", ("episode", "device", "show"))
@pytest.mark.parametrize("aggregate", (False, True))
def test_episode_cover_prefers_episode_then_device_then_its_own_show(
    source: str, aggregate: bool
) -> None:
    theme = ThemeManager(
        APPLICATION, SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    )
    remote = _Pixels({source: "#2d9b74", "other-show": "#c73442"})
    device = _Pixels({7: "#2d9b74"} if source == "device" else {})
    model = PodcastEpisodeListModel()
    episode = PodcastEpisode(
        "one",
        title="A long title with enough room to breathe",
        description="Full Episode description remains accessible without a hover popup.",
        artwork_url="episode",
        track_id=1,
        on_device=True,
    )
    if aggregate:
        model.replace_all(
            (
                PodcastSubscription(
                    "other",
                    "",
                    "Other",
                    SubscriptionSource.USER,
                    artwork_url="other-show",
                ),
                PodcastSubscription(
                    "show",
                    "",
                    "Show",
                    SubscriptionSource.USER,
                    artwork_url="show",
                    episodes=(episode,),
                ),
            )
        )
    else:
        model.replace("show", (episode,), artwork_url="show")
    index = model.index(0, 0)
    assert episode.description not in str(index.data(Qt.ItemDataRole.ToolTipRole))
    assert episode.description in str(index.data(Qt.ItemDataRole.AccessibleTextRole))
    widget = QWidget()
    option = QStyleOptionViewItem()
    option.widget = widget
    option.font = APPLICATION.font()
    delegate = PodcastEpisodeDelegate(
        theme,
        artwork_provider=cast("PodcastArtworkPixmapProvider", remote),
        device_artwork_provider=cast("ArtworkPixmapProvider", device),
        artwork_id_for_episode=lambda _: 7,
    )
    option.rect = QRect(0, 0, 800, 156)
    image = QImage(option.rect.size(), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(theme.tokens.window))
    painter = QPainter(image)
    try:
        delegate.paint(painter, option, model.index(0, 0))
    finally:
        painter.end()
        theme.close()
    assert image.pixelColor(70, 70) == QColor("#2d9b74")
    assert "other-show" not in remote.requests
    if source == "episode":
        assert not device.requests and "show" not in remote.requests


def test_search_cover_uses_feed_identity_and_preserves_subscription_actions() -> None:
    theme = ThemeManager(
        APPLICATION, SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    )
    provider = _Pixels({"https://publisher.test/rss": "#2d9b74"})
    model = PodcastSearchResultListModel()
    result = PodcastSearchResult("Show", "Publisher", "https://publisher.test/rss")
    model.replace((result,))
    widget = QWidget()
    option = QStyleOptionViewItem()
    option.widget = widget
    delegate = PodcastSearchResultDelegate(
        theme, artwork_provider=cast("PodcastArtworkPixmapProvider", provider)
    )
    option.rect = QRect(QPoint(), delegate.sizeHint(option, model.index(0, 0)))
    image = QImage(option.rect.size(), QImage.Format.Format_ARGB32_Premultiplied)
    painter = QPainter(image)
    try:
        delegate.paint(painter, option, model.index(0, 0))
    finally:
        painter.end()
    assert image.pixelColor(50, 50) == QColor("#2d9b74")
    assert provider.requests == [result.feed_url]
    controller = PodcastControllerStub(PodcastSnapshot(writable=True))
    dialog = PodcastSearchDialog(cast("PodcastController", controller), theme)
    try:
        dialog.show()
        controller.searchFinished.emit((result,))
        APPLICATION.processEvents()
        panel = dialog.findChild(QFrame, "podcastRssPanel")
        toggle = dialog.findChild(QPushButton, "podcastToggleRss")
        assert panel is not None and not panel.isVisible()
        assert toggle is not None
        toggle.click()
        assert panel.isVisible()
        dialog.resize(640, 560)
        APPLICATION.processEvents()
        assert dialog.height() >= dialog.minimumSizeHint().height()
        assert panel.height() >= panel.minimumSizeHint().height()
        toggle.click()
        assert not panel.isVisible()
        controller.busy = True
        controller.busyChanged.emit(True)
        results = dialog.findChild(QListView, "podcastDirectoryResults")
        subscribe = dialog.findChild(QPushButton, "podcastSubscribeSelected")
        assert results is not None and subscribe is not None
        results.activated.emit(results.currentIndex())
        assert not controller.subscribe_calls and dialog.isVisible()
        controller.busy = False
        controller.busyChanged.emit(False)
        subscribe.click()
        assert controller.subscribe_calls == [result.feed_url]
    finally:
        dialog.close()
        theme.close()


def test_search_states_keep_one_message_when_retranslated() -> None:
    theme = ThemeManager(
        APPLICATION, SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    )
    controller = PodcastControllerStub(PodcastSnapshot(writable=True))
    dialog = PodcastSearchDialog(cast("PodcastController", controller), theme)
    try:
        empty = dialog.findChild(QLabel, "podcastSearchEmpty")
        status = dialog.findChild(QLabel, "podcastSearchStatus")
        query = dialog.findChild(QLineEdit, "podcastDirectoryQuery")
        assert empty is not None and status is not None and query is not None
        query.setText("Some show")
        search = dialog.findChild(QPushButton, "podcastDirectorySearch")
        assert search is not None
        search.click()
        assert "Searching" in empty.text() and not status.text()
        controller.searchFinished.emit(())
        dialog.retranslate_ui()
        assert "No matching" in empty.text() and not status.text()
        controller.operationFailed.emit(
            PodcastOperationFailure(PodcastOperation.SEARCH, "Search unavailable")
        )
        dialog.retranslate_ui()
        assert empty.text() == "Search unavailable" and not status.text()
    finally:
        dialog.close()
        theme.close()
