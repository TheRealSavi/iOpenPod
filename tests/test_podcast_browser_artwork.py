from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QColor, QContextMenuEvent, QPixmap
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout, QWidget

from iopenpod.gui.widgets.podcastBrowser import (
    _COMBINED_FEED_COLUMNS,
    _EPISODE_ARTWORK_COLLAPSED_HEIGHT,
    _EPISODE_ROW_GAP,
    _PODCAST_EPISODE_COLUMNS,
    PodcastBrowser,
    _episode_description_text,
    _episode_is_listened,
    _episode_key,
    _episode_meta_text,
    _is_remote_artwork_source,
    _PodcastEpisodeCard,
    _PodcastEpisodeList,
    _read_local_artwork_bytes,
    _resolve_local_artwork_path,
    _set_episode_listened,
)
from iopenpod.podcasts.artwork import cache_feed_artwork, resolve_feed_artwork_source
from iopenpod.podcasts.models import (
    STATUS_DOWNLOADED,
    STATUS_DOWNLOADING,
    STATUS_ON_IPOD,
    PodcastEpisode,
    PodcastFeed,
)


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
        "iopenpod.podcasts.artwork.requests.get",
        lambda *_args, **_kwargs: _Response(),
    )

    feed = PodcastFeed(
        feed_url="https://example.test/feed.xml",
        artwork_path="",
        artwork_url="https://example.test/cover.png",
    )
    (tmp_path / "iPod_Control" / "iOpenPodPodcasts").mkdir(parents=True)
    (tmp_path / "iPodInfo.json").write_text("{}", encoding="utf-8")
    podcast_dir = tmp_path / "iPod_Control" / "iOpenPodPodcasts"

    cached = cache_feed_artwork(feed, podcast_dir)

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


def test_episode_dict_marks_card_ipod_actions() -> None:
    episode = PodcastEpisode(
        guid="episode-guid",
        title="Episode",
        status=STATUS_DOWNLOADED,
    )

    row = PodcastBrowser._ep_to_dict(episode, "Downloaded")

    assert row["_can_add_to_ipod"] is True
    assert row["_can_remove_from_ipod"] is False

    episode.status = STATUS_DOWNLOADING
    row = PodcastBrowser._ep_to_dict(episode, "Downloading...")

    assert row["_can_add_to_ipod"] is False
    assert row["_can_remove_from_ipod"] is False

    episode.status = STATUS_ON_IPOD
    episode.ipod_db_track_id = 42
    row = PodcastBrowser._ep_to_dict(episode, "On iPod")

    assert row["_can_add_to_ipod"] is False
    assert row["_can_remove_from_ipod"] is True


def test_episode_dict_marks_listened_state() -> None:
    episode = PodcastEpisode(
        guid="episode-guid",
        title="Episode",
        play_count=1,
    )

    row = PodcastBrowser._ep_to_dict(episode, "Listened")

    assert row["_was_listened"] is True
    assert row["play_count_1"] == 1
    assert row["ep_status"] == "Listened"


def test_episode_meta_text_includes_listened_with_download_status() -> None:
    row = {
        "ep_status": "Downloaded",
        "date_added": 0,
        "length": 0,
        "size": 0,
        "_was_listened": True,
    }

    assert _episode_meta_text(row) == "Listened"


def test_set_episode_listened_can_mark_and_unmark_on_ipod_episode() -> None:
    episode = PodcastEpisode(
        guid="episode-guid",
        title="Episode",
        status=STATUS_ON_IPOD,
        ipod_db_track_id=42,
    )

    _set_episode_listened(episode, True)

    assert _episode_is_listened(episode) is True
    assert episode.listened_override is True
    assert episode.play_count == 1

    _set_episode_listened(episode, False)

    assert _episode_is_listened(episode) is False
    assert episode.listened_override is False
    assert episode.play_count == 0


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


def test_episode_card_shows_and_emits_ipod_action_buttons(qtbot) -> None:
    card = _PodcastEpisodeCard()
    qtbot.addWidget(card)
    card.resize(900, _EPISODE_ARTWORK_COLLAPSED_HEIGHT - _EPISODE_ROW_GAP)
    card.show()

    add_seen: list[int] = []
    remove_seen: list[int] = []
    card.add_requested.connect(add_seen.append)
    card.remove_requested.connect(remove_seen.append)

    row = {
        "Title": "Episode",
        "podcast_feed_title": "Example Show",
        "Description Text": "Description",
        "ep_status": "Downloaded",
        "_can_add_to_ipod": True,
        "_can_remove_from_ipod": False,
    }
    card.bind(
        row_index=7,
        row=row,
        row_key="row-7",
        selected=False,
        expanded=False,
        description_text="Description",
        show_more=True,
        show_artwork=True,
        artwork_source="cover",
        artwork_pixmap=QPixmap(4, 4),
    )

    add_button = card.findChild(QPushButton, "podcastEpisodeAddButton")
    remove_button = card.findChild(QPushButton, "podcastEpisodeRemoveButton")
    assert add_button is not None
    assert remove_button is not None
    assert add_button.isVisibleTo(card)
    assert not remove_button.isVisibleTo(card)

    qtbot.mouseClick(add_button, Qt.MouseButton.LeftButton)

    assert add_seen == [7]
    assert remove_seen == []

    row["_can_add_to_ipod"] = False
    row["_can_remove_from_ipod"] = True
    card.bind(
        row_index=8,
        row=row,
        row_key="row-8",
        selected=False,
        expanded=False,
        description_text="Description",
        show_more=True,
        show_artwork=True,
        artwork_source="cover",
        artwork_pixmap=QPixmap(4, 4),
    )

    assert not add_button.isVisibleTo(card)
    assert remove_button.isVisibleTo(card)

    qtbot.mouseClick(remove_button, Qt.MouseButton.LeftButton)

    assert add_seen == [7]
    assert remove_seen == [8]


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


def test_episode_list_uses_app_scrollbar_style_path(qtbot) -> None:
    class _Owner(QWidget):
        def _on_episode_context_menu(self, _pos: QPoint) -> None:
            pass

    owner = _Owner()
    qtbot.addWidget(owner)
    episode_list = _PodcastEpisodeList(cast(PodcastBrowser, owner))
    qtbot.addWidget(episode_list)

    table = episode_list.table

    assert table.styleSheet() == ""
    assert table.frameShape() == table.Shape.NoFrame
    assert table.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded
    assert table.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    viewport = table.viewport()
    assert viewport is not None
    assert viewport.autoFillBackground() is False


def test_episode_list_resets_scroll_when_rows_change(qtbot) -> None:
    class _Owner(QWidget):
        def _on_episode_context_menu(self, _pos: QPoint) -> None:
            pass

        def _artwork_placeholder_pixmap(self, _size: int) -> None:
            return None

    def _rows(prefix: str) -> list[dict]:
        return [
            {
                "Title": f"{prefix} Episode {i}",
                "Description Text": "Description",
                "ep_status": "",
                "length": 0,
                "date_added": i,
                "size": 0,
                "_ep_guid": f"{prefix}-{i}",
                "_ep_key": f"{prefix}-{i}",
            }
            for i in range(40)
        ]

    owner = _Owner()
    qtbot.addWidget(owner)
    layout = QVBoxLayout(owner)
    layout.setContentsMargins(0, 0, 0, 0)
    episode_list = _PodcastEpisodeList(cast(PodcastBrowser, owner))
    layout.addWidget(episode_list)
    owner.resize(500, 240)
    owner.show()

    episode_list.set_rows(_rows("first"), _PODCAST_EPISODE_COLUMNS)
    bar = episode_list.table.verticalScrollBar()
    assert bar is not None
    qtbot.waitUntil(lambda: bar.maximum() > 0, timeout=2000)
    bar.setValue(bar.maximum())
    assert bar.value() > 0

    episode_list.set_rows(_rows("second"), _PODCAST_EPISODE_COLUMNS)

    assert bar.value() == 0
