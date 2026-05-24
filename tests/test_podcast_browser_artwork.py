from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QColor, QContextMenuEvent, QPixmap
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton, QWidget

from GUI.widgets.podcastBrowser import (
    _COMBINED_FEED_COLUMNS,
    _EPISODE_ARTWORK_COLLAPSED_HEIGHT,
    _EPISODE_ROW_GAP,
    _PODCAST_EPISODE_COLUMNS,
    PodcastBrowser,
    _episode_description_text,
    _episode_key,
    _is_remote_artwork_source,
    _PodcastEpisodeCard,
    _PodcastEpisodeList,
    _read_local_artwork_bytes,
    _resolve_local_artwork_path,
)
from PodcastManager.artwork import cache_feed_artwork, resolve_feed_artwork_source
from PodcastManager.models import PodcastEpisode, PodcastFeed


def test_http_artwork_source_is_remote() -> None:
    assert _is_remote_artwork_source("https://example.com/cover.jpg") is True
    assert _is_remote_artwork_source("http://example.com/cover.jpg") is True
    assert _is_remote_artwork_source(r"G:\iPod_Control\cover.jpg") is False


def test_read_local_artwork_bytes_reads_existing_file(tmp_path: Path) -> None:
    image_path = tmp_path / "cover.jpg"
    image_path.write_bytes(b"image-bytes")

    assert _read_local_artwork_bytes(str(image_path)) == b"image-bytes"


def test_read_local_artwork_bytes_treats_missing_windows_path_as_local() -> None:
    missing = r"G:\iPod_Control\iOpenPodPodcasts\artwork-cache\cover.jpg"

    assert _resolve_local_artwork_path(missing) == Path(missing)
    assert _read_local_artwork_bytes(missing) == b""


def test_read_local_artwork_bytes_supports_file_uri(tmp_path: Path) -> None:
    image_path = tmp_path / "artwork cache" / "cover.jpg"
    image_path.parent.mkdir()
    image_path.write_bytes(b"uri-bytes")

    uri = image_path.as_uri()

    assert _read_local_artwork_bytes(uri) == b"uri-bytes"


def test_feed_artwork_source_falls_back_when_cached_path_is_missing(tmp_path: Path) -> None:
    feed = SimpleNamespace(
        artwork_path=str(tmp_path / "missing-cover.jpg"),
        artwork_url="https://example.test/cover.jpg",
    )

    assert resolve_feed_artwork_source(feed, tmp_path) == "https://example.test/cover.jpg"


def test_feed_artwork_source_resolves_relative_cache_path(tmp_path: Path) -> None:
    image_path = tmp_path / "artwork-cache" / "cover.jpg"
    image_path.parent.mkdir()
    image_path.write_bytes(b"image-bytes")
    feed = SimpleNamespace(
        artwork_path="artwork-cache/cover.jpg",
        artwork_url="https://example.test/cover.jpg",
    )

    assert resolve_feed_artwork_source(feed, tmp_path) == str(image_path)


def test_cache_feed_artwork_stores_relative_jpeg_path(tmp_path: Path, monkeypatch) -> None:
    from io import BytesIO

    from PIL import Image

    image_bytes = BytesIO()
    Image.new("RGBA", (2, 2), (10, 20, 30, 255)).save(image_bytes, format="PNG")

    class _Response:
        content = image_bytes.getvalue()

        def raise_for_status(self) -> None:
            pass

    monkeypatch.setattr(
        "PodcastManager.artwork.requests.get",
        lambda *_args, **_kwargs: _Response(),
    )

    feed = PodcastFeed(
        feed_url="https://example.test/feed.xml",
        artwork_path="",
        artwork_url="https://example.test/cover.png",
    )

    cached = cache_feed_artwork(feed, tmp_path)

    assert Path(cached).exists()
    assert feed.artwork_path.startswith("artwork-cache/")
    assert Path(feed.artwork_path).is_absolute() is False
    assert Path(cached).suffix == ".jpg"


def test_podcast_episode_columns_include_description_after_title() -> None:
    assert _PODCAST_EPISODE_COLUMNS[:2] == ["Title", "Description Text"]


def test_episode_description_text_is_plain_compact_text() -> None:
    assert (
        _episode_description_text("<p>Hello&nbsp;<b>world</b></p>\n<p>Next</p>")
        == "Hello world Next"
    )


def test_episode_dict_includes_description_text() -> None:
    episode = SimpleNamespace(
        title="Episode",
        guid="episode-guid",
        description="<p>Shown in table</p>",
        duration_seconds=0,
        pub_date=0,
        size_bytes=0,
    )

    row = PodcastBrowser._ep_to_dict(episode, "Downloaded")

    assert row["Description Text"] == "Shown in table"


def test_combined_feed_columns_include_podcast_name() -> None:
    assert _COMBINED_FEED_COLUMNS[:3] == [
        "Title",
        "podcast_feed_title",
        "Description Text",
    ]


def test_episode_dict_includes_feed_identity_for_combined_feed() -> None:
    feed = PodcastFeed(
        feed_url="https://example.test/feed.xml",
        title="Example Show",
    )
    episode = PodcastEpisode(
        guid="episode-guid",
        title="Episode",
        description="Shown in table",
    )

    row = PodcastBrowser._ep_to_dict(episode, "Downloaded", feed)

    assert row["podcast_feed_title"] == "Example Show"
    assert row["_ep_key"] == _episode_key(feed, episode)


def test_episode_card_artwork_only_shows_for_combined_feed(qtbot) -> None:
    card = _PodcastEpisodeCard()
    qtbot.addWidget(card)

    artwork = QPixmap(4, 4)
    artwork.fill(QColor("red"))
    row = {
        "Title": "Episode",
        "podcast_feed_title": "Example Show",
        "Description Text": "Description",
        "ep_status": "",
    }
    art_label = card.findChild(QLabel, "podcastEpisodeArtwork")
    assert art_label is not None

    card.bind(
        row_index=0,
        row=row,
        row_key="row-1",
        selected=False,
        expanded=False,
        description_text="Description",
        show_more=False,
        show_artwork="podcast_feed_title" in _COMBINED_FEED_COLUMNS,
        artwork_source="cover",
        artwork_pixmap=artwork,
    )

    assert art_label.isVisibleTo(card)
    assert art_label.alignment() == Qt.AlignmentFlag.AlignCenter

    card.bind(
        row_index=0,
        row=row,
        row_key="row-1",
        selected=False,
        expanded=False,
        description_text="Description",
        show_more=False,
        show_artwork="podcast_feed_title" in _PODCAST_EPISODE_COLUMNS,
        artwork_source="cover",
        artwork_pixmap=artwork,
    )

    assert not art_label.isVisibleTo(card)


def test_episode_card_description_toggle_keeps_spacing_stable(qtbot) -> None:
    card = _PodcastEpisodeCard()
    qtbot.addWidget(card)
    row = {
        "Title": (
            "A Nigella Lawson Sheet-Pan Dinner + Strawberry Rhubarb Bars! "
            "| Our Best Home Cooking Bites of the Week"
        ),
        "podcast_feed_title": "Example Show",
        "Description Text": "Description",
        "ep_status": "",
    }

    card.bind(
        row_index=0,
        row=row,
        row_key="row-1",
        selected=False,
        expanded=False,
        description_text="Line one\nLine two",
        show_more=True,
        show_artwork=True,
        artwork_source="cover",
        artwork_pixmap=QPixmap(4, 4),
    )

    card.resize(900, _EPISODE_ARTWORK_COLLAPSED_HEIGHT - _EPISODE_ROW_GAP)
    card.show()
    qtbot.wait(10)

    art = card.findChild(QLabel, "podcastEpisodeArtwork")
    podcast = card.findChild(QLabel, "podcastEpisodePodcast")
    title = card.findChild(QLabel, "podcastEpisodeTitle")
    action_row = card.findChild(QWidget, "podcastEpisodeActionRow")
    description = card.findChild(QLabel, "podcastEpisodeDescription")
    meta = card.findChild(QLabel, "podcastEpisodeMeta")
    more_button = card.findChild(QPushButton, "podcastEpisodeMoreButton")
    assert art is not None
    assert podcast is not None
    assert title is not None
    assert action_row is not None
    assert description is not None
    assert meta is not None
    assert more_button is not None
    before_art_geometry = art.geometry()
    before_podcast_geometry = podcast.geometry()
    before_title_geometry = title.geometry()
    before_action_height = (action_row.minimumHeight(), action_row.maximumHeight())
    before_button_size = (more_button.minimumSize(), more_button.maximumSize())
    before_meta_geometry = meta.geometry()
    before_description_geometry = description.geometry()
    before_description_height = (
        description.minimumHeight(),
        description.maximumHeight(),
    )

    card.bind(
        row_index=0,
        row=row,
        row_key="row-1",
        selected=False,
        expanded=True,
        description_text="\n".join(f"Line {i}" for i in range(1, 8)),
        show_more=True,
        show_artwork=True,
        artwork_source="cover",
        artwork_pixmap=QPixmap(4, 4),
    )
    card.resize(900, 360)
    qtbot.wait(10)

    assert art.geometry() == before_art_geometry
    assert podcast.geometry() == before_podcast_geometry
    assert title.geometry() == before_title_geometry
    assert (action_row.minimumHeight(), action_row.maximumHeight()) == before_action_height
    assert (more_button.minimumSize(), more_button.maximumSize()) == before_button_size
    assert meta.geometry().top() == before_meta_geometry.top()
    assert meta.geometry().height() == before_meta_geometry.height()
    assert description.geometry().top() == before_description_geometry.top()
    assert description.geometry().height() > before_description_geometry.height()
    assert description.minimumHeight() > before_description_height[0]


def test_episode_card_child_context_menu_events_reach_card(qtbot) -> None:
    card = _PodcastEpisodeCard()
    qtbot.addWidget(card)
    card.bind(
        row_index=4,
        row={
            "Title": "Episode",
            "podcast_feed_title": "Example Show",
            "Description Text": "Description",
            "ep_status": "",
        },
        row_key="row-4",
        selected=False,
        expanded=False,
        description_text="Description",
        show_more=True,
        show_artwork=True,
        artwork_source="cover",
        artwork_pixmap=QPixmap(4, 4),
    )
    card.resize(900, _EPISODE_ARTWORK_COLLAPSED_HEIGHT - _EPISODE_ROW_GAP)
    card.show()
    qtbot.wait(10)

    title = card.findChild(QLabel, "podcastEpisodeTitle")
    assert title is not None
    seen: list[tuple[int, QPoint]] = []
    card.context_requested.connect(lambda row, pos: seen.append((row, pos)))

    child_pos = QPoint(3, 3)
    event = QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse,
        child_pos,
        title.mapToGlobal(child_pos),
    )
    QApplication.sendEvent(title, event)

    assert seen == [(4, title.mapTo(card, child_pos))]


def test_episode_list_context_menu_signal_is_connected(qtbot) -> None:
    class _Owner(QWidget):
        def __init__(self) -> None:
            super().__init__()
            self.positions: list[QPoint] = []

        def _on_episode_context_menu(self, pos: QPoint) -> None:
            self.positions.append(pos)

    owner = _Owner()
    qtbot.addWidget(owner)
    episode_list = _PodcastEpisodeList(cast(PodcastBrowser, owner))
    qtbot.addWidget(episode_list)

    pos = QPoint(11, 13)
    episode_list.table.customContextMenuRequested.emit(pos)

    assert owner.positions == [pos]
