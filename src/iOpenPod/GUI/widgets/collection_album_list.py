"""Selected Artist/Genre context and lazily materialized Album track sections."""

from dataclasses import dataclass

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QRect, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.models.album_list_model import AlbumListModel, AlbumRole, AlbumSummary
from iOpenPod.app.models.collection_list_model import CollectionKind, CollectionSummary
from iOpenPod.app.models.library_filter_models import (
    AlbumFilterProxyModel,
    TrackFilterProxyModel,
)
from iOpenPod.app.models.track_order import album_track_sort_key
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.presentation.i18n.text import album_count_text, track_count_text
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.inline_album_panel import InlineAlbumPanel
from iOpenPod.GUI.widgets.themed_buttons import IconButton, IconButtonKind
from iPodDB.library import Track


@dataclass(frozen=True)
class _Section:
    album: AlbumSummary
    tracks: tuple[Track, ...]
    top: int
    height: int


class CollectionAlbumList(QWidget):
    """One context header and one scroll surface, shared by Artists and Genres."""

    playRequested = Signal(object)
    playNextRequested = Signal(object)
    queueRequested = Signal(object)
    currentTrackChanged = Signal(object)
    panelCreated = Signal(object)

    def __init__(
        self,
        albums: AlbumListModel,
        tracks: TrackFilterProxyModel,
        theme: ThemeManager,
        artwork: ArtworkPixmapProvider,
        kind: CollectionKind,
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("collectionAlbumList")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # Membership comes from the matching Tracks, including unknown Genres
        # and guest Artists on Albums whose representative Artist differs.
        self._albums = AlbumFilterProxyModel(albums, self)
        self._tracks = tracks
        self._theme = theme
        self._artwork = artwork
        self._kind = kind
        self._summary: CollectionSummary | None = None
        self._ordered_tracks: tuple[Track, ...] = ()
        self._sections: list[_Section] = []
        self._panels: dict[str, InlineAlbumPanel] = {}
        self._title = QLabel(self)
        self._title.setObjectName("collectionAlbumTitle")
        self._title.setTextFormat(Qt.TextFormat.PlainText)
        self._title.setWordWrap(True)
        self._title.setMinimumWidth(0)
        self._counts = QLabel(self)
        self._counts.setObjectName("pageMeta")
        self._play = IconButton("play", "", self, kind=IconButtonKind.QUIET)
        self._next = IconButton("play-next", "", self, kind=IconButtonKind.QUIET)
        self._queue = IconButton("play-last", "", self, kind=IconButtonKind.QUIET)
        self._play.setObjectName("collectionPlay")
        self._next.setObjectName("collectionPlayNext")
        self._queue.setObjectName("collectionQueue")
        self._play.clicked.connect(
            lambda: self.playRequested.emit(self._ordered_tracks)
        )
        self._next.clicked.connect(
            lambda: self.playNextRequested.emit(self._ordered_tracks)
        )
        self._queue.clicked.connect(
            lambda: self.queueRequested.emit(self._ordered_tracks)
        )
        heading = QHBoxLayout()
        heading.addWidget(self._title)
        for button in (self._play, self._next, self._queue):
            heading.addWidget(button, 0, Qt.AlignmentFlag.AlignTop)
        heading.addStretch()
        header = QVBoxLayout()
        header.setContentsMargins(
            LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_md
        )
        header.addLayout(heading)
        header.addWidget(self._counts)
        self._scroll = QScrollArea(self)
        self._scroll.setObjectName("collectionAlbumScroll")
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._body = QWidget()
        self._body.setObjectName("collectionAlbumBody")
        self._body.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._scroll.setWidget(self._body)
        self._scroll.viewport().installEventFilter(self)
        self._scroll.verticalScrollBar().valueChanged.connect(self._materialize)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(header)
        layout.addWidget(self._scroll, 1)
        self._measure = self._make_panel()
        self._measure.hide()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self._refresh)
        for model in (self._albums, tracks):
            for signal in (
                model.modelReset,
                model.rowsInserted,
                model.rowsRemoved,
                model.dataChanged,
                model.layoutChanged,
            ):
                signal.connect(self._schedule_refresh)
        theme.effectiveThemeChanged.connect(self._schedule_refresh)
        self.retranslate_ui()

    def set_context(self, summary: CollectionSummary | None) -> None:
        changed = (self._summary.key if self._summary else None) != (
            summary.key if summary else None
        )
        self._summary = summary
        if changed:
            for panel in self._panels.values():
                panel.hide()
                panel.deleteLater()
            self._panels.clear()
            self._scroll.verticalScrollBar().setValue(0)
        self._refresh()

    def _schedule_refresh(self, *_args: object) -> None:
        self._refresh_timer.start(0)

    def _refresh(self) -> None:
        self._refresh_timer.stop()
        grouped: dict[str, list[Track]] = {}
        if self._summary is not None:
            for row in range(self._tracks.rowCount()):
                track = self._tracks.track_at(self._tracks.index(row, 0))
                if track is not None:
                    grouped.setdefault(track.album_key, []).append(track)
        sections: list[_Section] = []
        top = 0
        for row in range(self._albums.rowCount()):
            album = self._albums.index(row, 0).data(AlbumRole.SUMMARY)
            if not isinstance(album, AlbumSummary) or album.key not in grouped:
                continue
            tracks = tuple(sorted(grouped[album.key], key=album_track_sort_key))
            height = self._measure.section_height(len(tracks))
            sections.append(_Section(album, tracks, top, height))
            top += height
        self._sections = sections
        self._ordered_tracks = tuple(
            track for section in sections for track in section.tracks
        )
        title = ""
        if self._summary is not None:
            title = self._summary.title or (
                QCoreApplication.translate("LibraryLabels", "Unknown Artist")
                if self._kind is CollectionKind.ARTIST
                else QCoreApplication.translate("LibraryLabels", "Unknown Genre")
            )
        self._title.setText(title)
        self._counts.setText(
            f"{album_count_text(len(sections))} · {track_count_text(len(self._ordered_tracks))}"
        )
        for button in (self._play, self._next, self._queue):
            button.setEnabled(bool(self._ordered_tracks))
        self._body.resize(self._scroll.viewport().width(), max(1, top))
        self._materialize()

    def _make_panel(self) -> InlineAlbumPanel:
        return InlineAlbumPanel(
            self._tracks,
            self._theme,
            self._artwork,
            self._body,
            stacked=True,
            show_album_artist=self._kind is CollectionKind.GENRE,
        )

    def _materialize(self, *_args: object) -> None:
        if not hasattr(self, "_measure"):
            return
        viewport = self._scroll.viewport()
        visible = QRect(
            0,
            self._scroll.verticalScrollBar().value() - LAYOUT.album_artwork_size,
            viewport.width(),
            viewport.height() + 2 * LAYOUT.album_artwork_size,
        )
        retained: set[str] = set()
        for section in self._sections:
            rect = QRect(0, section.top, viewport.width(), section.height)
            panel = self._panels.get(section.album.key)
            if not rect.intersects(visible) and not (
                panel is not None
                and (panel.track_view.hasFocus() or panel.selected_tracks())
            ):
                continue
            retained.add(section.album.key)
            if panel is None:
                panel = self._make_panel()
                self._panels[section.album.key] = panel
                panel.currentTrackChanged.connect(self.currentTrackChanged.emit)
                self.panelCreated.emit(panel)
            panel.setGeometry(rect)
            panel.set_context(section.album, section.tracks)
            panel.show()
        for key in set(self._panels) - retained:
            panel = self._panels.pop(key)
            panel.hide()
            panel.deleteLater()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._scroll.viewport() and event.type() == QEvent.Type.Resize:
            self._body.resize(self._scroll.viewport().width(), self._body.height())
            self._materialize()
        return super().eventFilter(watched, event)

    def retranslate_ui(self) -> None:
        for button, label in (
            (self._play, self.tr("Play")),
            (self._next, self.tr("Add to top of queue")),
            (self._queue, self.tr("Add to bottom of queue")),
        ):
            button.setAccessibleName(label)
            button.setToolTip(label)
        if hasattr(self, "_refresh_timer"):
            self._refresh()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)
