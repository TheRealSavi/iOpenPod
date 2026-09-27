"""Full-page Album and collection context around the shared Track table."""

from PySide6.QtCore import QCoreApplication, QEvent, QLocale, Qt, Signal
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QBoxLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.models.album_list_model import AlbumSummary
from iOpenPod.app.models.collection_list_model import CollectionSummary
from iOpenPod.app.models.library_filter_models import TrackFilterProxyModel
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.presentation.i18n.text import (
    track_count_text,
    visible_track_count_text,
)
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.artwork_view import ArtworkView
from iOpenPod.GUI.widgets.search_field import SearchField
from iOpenPod.GUI.widgets.themed_buttons import ActionButton, ActionButtonKind
from iOpenPod.GUI.widgets.track_table import TrackTable


class CollectionDetailPage(QWidget):
    """Keep collection context and bulk membership independent of Track search."""

    backRequested = Signal()
    tracksCheckRequested = Signal(object, bool)

    def __init__(
        self,
        table: TrackTable,
        proxy: TrackFilterProxyModel,
        theme_manager: ThemeManager,
        artwork_provider: ArtworkPixmapProvider,
        parent: QWidget | None = None,
        *,
        selection_mode: bool = True,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("collectionDetailPage")
        self._proxy = proxy
        self._selection_mode = selection_mode
        self._summary: AlbumSummary | CollectionSummary | None = None
        self._track_ids: tuple[int, ...] = ()
        self._duration_ms = 0
        self._size_bytes = 0

        self._back = ActionButton(
            parent=self, glyph="chevron-left", kind=ActionButtonKind.QUIET
        )
        self._back.setObjectName("collectionDetailBack")
        self._back.clicked.connect(self.backRequested.emit)
        navigation = QHBoxLayout()
        navigation.addWidget(self._back)
        navigation.addStretch(1)

        self._artwork = ArtworkView(theme_manager, artwork_provider, self)
        self._artwork.setFixedSize(
            LAYOUT.collection_detail_artwork_size, LAYOUT.collection_detail_artwork_size
        )
        self._title = QLabel(self)
        self._title.setObjectName("pageTitle")
        self._artist = QLabel(self)
        self._artist.setProperty("browserTitle", True)
        self._metadata = QLabel(self)
        self._metadata.setObjectName("pageMeta")
        self._totals = QLabel(self)
        self._totals.setObjectName("pageMeta")
        for label in (self._title, self._artist, self._metadata, self._totals):
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            label.setMinimumWidth(0)

        self._select_all = ActionButton(parent=self)
        self._select_all.setObjectName("collectionDetailSelectAll")
        self._deselect_all = ActionButton(parent=self)
        self._deselect_all.setObjectName("collectionDetailDeselectAll")
        self._select_all.clicked.connect(lambda: self._set_checked(True))
        self._deselect_all.clicked.connect(lambda: self._set_checked(False))
        self._actions = QWidget(self)
        self._actions.setVisible(selection_mode)
        self._action_layout = QBoxLayout(
            QBoxLayout.Direction.LeftToRight, self._actions
        )
        self._action_layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self._action_layout.setContentsMargins(0, 0, 0, 0)
        self._action_layout.setSpacing(LAYOUT.space_xs)
        self._action_layout.addWidget(self._select_all)
        self._action_layout.addWidget(self._deselect_all)
        self._action_layout.addStretch(1)

        context = QVBoxLayout()
        context.setSpacing(LAYOUT.space_2xs)
        context.addStretch(1)
        context.addWidget(self._title)
        context.addWidget(self._artist)
        context.addWidget(self._metadata)
        context.addWidget(self._totals)
        context.addStretch(1)
        self._cover = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self._cover.setSpacing(LAYOUT.space_lg)
        self._cover.addWidget(
            self._artwork, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeading
        )
        self._cover.addLayout(context, 1)
        header = QVBoxLayout()
        header.setSpacing(LAYOUT.space_sm)
        header.addLayout(navigation)

        self._search = SearchField(self)
        self._search.setObjectName("collectionDetailSearch")
        self._search.queryChanged.connect(proxy.set_query)
        self._search_width = self._search.maximumWidth()
        self._toolbar = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self._toolbar.setSpacing(LAYOUT.space_md)
        if selection_mode:
            header.addLayout(self._cover)
            self._toolbar.addWidget(self._actions, 1)
            self._toolbar.addWidget(self._search, 1)
        else:
            self._toolbar.addLayout(self._cover, 1)
            self._toolbar.addWidget(self._search, 1, Qt.AlignmentFlag.AlignBottom)
            header.addLayout(self._toolbar)

        self._count = QLabel(self)
        self._count.setObjectName("collectionDetailCount")
        self._count.setContentsMargins(0, LAYOUT.space_xs, 0, 0)
        layout = QVBoxLayout(self)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        layout.setContentsMargins(
            LAYOUT.space_lg, LAYOUT.space_md, LAYOUT.space_lg, LAYOUT.space_xs
        )
        layout.setSpacing(LAYOUT.space_md)
        layout.addLayout(header)
        tracks = QVBoxLayout()
        tracks.setSpacing(LAYOUT.space_sm)
        if selection_mode:
            tracks.addLayout(self._toolbar)
        self._table_group = QVBoxLayout()
        self._table_group.setSpacing(0)
        self._table_group.addWidget(self._count)
        self.set_table(table)
        tracks.addLayout(self._table_group, 1)
        layout.addLayout(tracks, 1)
        QWidget.setTabOrder(self._back, self._select_all)
        QWidget.setTabOrder(self._select_all, self._deselect_all)
        QWidget.setTabOrder(self._deselect_all, self._search)
        QWidget.setTabOrder(self._search, table)
        proxy.rowsInserted.connect(self._refresh_count)
        proxy.rowsRemoved.connect(self._refresh_count)
        proxy.modelReset.connect(self._refresh_count)
        self.retranslate_ui()

    def set_table(self, table: TrackTable) -> None:
        """Move the existing table here without replacing its actions or selection."""

        self._table_group.insertWidget(0, table, 1)

    def clear_query(self) -> None:
        self._search.set_query("")
        self._proxy.set_query("")

    def set_context(self, summary: AlbumSummary | CollectionSummary) -> None:
        """Capture the opened card's identity before selection grouping can move it."""

        self._summary = summary
        self.clear_query()
        tracks = tuple(
            track
            for row in range(self._proxy.rowCount())
            if (track := self._proxy.track_at(self._proxy.index(row, 0))) is not None
        )
        self._track_ids = tuple(track.track_id for track in tracks)
        self._size_bytes = sum(track.size_bytes for track in tracks)
        self._duration_ms = sum(track.length_ms for track in tracks)
        self._artwork.set_seed(summary.artwork_seed)
        if isinstance(summary, AlbumSummary):
            self._artwork.set_artwork_id(summary.artwork_id)
        else:
            self._artwork.set_artwork_ids(summary.artwork_ids)
        self._refresh_context()

    def retranslate_ui(self) -> None:
        self._back.setText(QCoreApplication.translate("CommonActions", "Back"))
        self._back.setAccessibleName(self.tr("Back to collections"))
        self._select_all.setText(
            QCoreApplication.translate("CommonActions", "Select All")
        )
        self._deselect_all.setText(
            QCoreApplication.translate("CommonActions", "Deselect All")
        )
        self._select_all.setToolTip(
            self.tr("Select every Track in this collection for Sync")
        )
        self._deselect_all.setToolTip(
            self.tr("Deselect every Track in this collection from Sync")
        )
        self._search.setPlaceholderText(
            QCoreApplication.translate("LibraryLabels", "Search Tracks")
        )
        self._search.setAccessibleName(self.tr("Search Tracks in this collection"))
        self._refresh_context()
        self._arrange_header()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.LayoutRequest:
            self._arrange_header()
        return super().event(event)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._arrange_header()

    def _arrange_header(self) -> None:
        """Keep controls together and preserve readable context in narrow panes."""

        width = max(0, self.width() - 2 * LAYOUT.space_lg)
        actions_width = (
            0
            if self._actions.isHidden()
            else (
                self._select_all.sizeHint().width()
                + LAYOUT.space_xs
                + self._deselect_all.sizeHint().width()
            )
        )
        self._action_layout.setDirection(
            QBoxLayout.Direction.TopToBottom
            if width < actions_width
            else QBoxLayout.Direction.LeftToRight
        )
        text_width = max(
            self._artwork.width(),
            *(
                label.minimumSizeHint().width()
                for label in (self._title, self._artist, self._metadata, self._totals)
            ),
        )
        cover_width = self._artwork.width() + LAYOUT.space_lg + text_width
        stacked = width < (
            actions_width + LAYOUT.space_md + self._search.minimumWidth()
            if self._selection_mode
            else cover_width + LAYOUT.space_md + self._search_width
        )
        self._toolbar.setDirection(
            QBoxLayout.Direction.TopToBottom
            if stacked
            else QBoxLayout.Direction.LeftToRight
        )
        self._search.setMaximumWidth(width if stacked else self._search_width)
        context_width = width
        if not self._selection_mode and not stacked:
            context_width -= self._search_width + LAYOUT.space_md
        self._cover.setDirection(
            QBoxLayout.Direction.TopToBottom
            if context_width < cover_width
            else QBoxLayout.Direction.LeftToRight
        )

    def _set_checked(self, checked: bool) -> None:
        if self._summary is not None:
            self.tracksCheckRequested.emit(self._track_ids, checked)

    def _refresh_context(self) -> None:
        summary = self._summary
        if summary is None:
            return
        album = isinstance(summary, AlbumSummary)
        self._title.setText(
            summary.title
            or (
                QCoreApplication.translate("LibraryLabels", "Unknown Album")
                if album
                else QCoreApplication.translate("LibraryLabels", "Unknown Collection")
            )
        )
        self._artist.setVisible(album)
        self._artist.setText(
            summary.artist
            or QCoreApplication.translate("LibraryLabels", "Unknown Artist")
            if isinstance(summary, AlbumSummary)
            else ""
        )
        count = track_count_text(len(self._track_ids))
        self._metadata.setText(
            f"{summary.year} · {count}"
            if isinstance(summary, AlbumSummary) and summary.year
            else count
        )
        duration = self.tr("%1 min").replace("%1", str(self._duration_ms // 60_000))
        self._totals.setText(f"{duration} · {_format_size(self._size_bytes)}")
        self._refresh_count()

    def _refresh_count(self, *_args: object) -> None:
        if self._summary is None:
            return
        shown = self._proxy.rowCount()
        total = len(self._track_ids)
        self._count.setText(
            track_count_text(total)
            if shown == total
            else visible_track_count_text(shown, total)
        )


def _format_size(size_bytes: int) -> str:
    return QLocale().formattedDataSize(
        size_bytes, 1, QLocale.DataSizeFormat.DataSizeSIFormat
    )
