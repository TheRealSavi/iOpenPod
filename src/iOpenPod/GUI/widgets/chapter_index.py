"""A compact, anchored chapter index for the audiobook Player action."""

from PySide6.QtCore import (
    QEvent,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QPoint,
    QRectF,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QIcon,
    QKeyEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPalette,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.playback.artwork import playback_artwork_times
from iOpenPod.app.playback.chapters import chapter_at
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.animated_popup import (
    POPUP_OVERSHOOT_INSET,
    AnimatedPopup,
    PopupDirection,
)
from iPodDB.library import TrackChapter

_ARTWORK_TIME_ROLE = Qt.ItemDataRole.UserRole


class _ChapterArtworkDelegate(QStyledItemDelegate):
    """Request exact chapter thumbnails only when the view paints visible rows."""

    def __init__(self, provider: ArtworkPixmapProvider, view: QListWidget) -> None:
        super().__init__(view)
        self._provider = provider
        self._view = view
        self._artwork_id = 0
        self._display_times: frozenset[int] = frozenset()
        provider.artworkChanged.connect(self._artwork_changed)
        provider.cleared.connect(self._refresh_times)

    def set_artwork_id(self, artwork_id: int) -> None:
        self._artwork_id = artwork_id
        self._refresh_times()

    def _refresh_times(self) -> None:
        self._display_times = frozenset(
            playback_artwork_times(self._provider.display_times(self._artwork_id))
        )
        self._view.viewport().update()

    def _artwork_changed(self, artwork_id: int) -> None:
        if artwork_id == self._artwork_id:
            self._view.viewport().update()

    def sizeHint(
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        size = super().sizeHint(option, index)
        return QSize(
            size.width() + LAYOUT.playback_row_artwork_size + LAYOUT.space_xs,
            max(
                size.height(),
                LAYOUT.playback_row_artwork_size + 2 * LAYOUT.space_2xs,
            ),
        )

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        size = LAYOUT.playback_row_artwork_size
        time = index.data(_ARTWORK_TIME_ROLE)
        pixmap = (
            self._provider.pixmap(
                self._artwork_id,
                size,
                self._view.devicePixelRatioF(),
                display_time_ms=time,
            )
            if isinstance(time, int) and time in self._display_times
            else None
        )
        if pixmap is None:
            pixmap = QPixmap(size, size)
            pixmap.fill(Qt.GlobalColor.transparent)
            placeholder = QPainter(pixmap)
            placeholder.setRenderHint(QPainter.RenderHint.Antialiasing)
            placeholder.setPen(QPen(styled.palette.color(QPalette.ColorRole.Mid), 1))
            placeholder.drawRoundedRect(QRectF(1, 1, size - 2, size - 2), 3, 3)
            placeholder.drawLine(size // 3, size // 2, 2 * size // 3, size // 2)
            placeholder.end()
        styled.icon = QIcon(pixmap)
        styled.decorationSize = QSize(size, size)
        styled.features |= QStyleOptionViewItem.ViewItemFeature.HasDecoration
        self._view.style().drawControl(
            QStyle.ControlElement.CE_ItemViewItem, styled, painter, self._view
        )


class ChapterIndexPopup(AnimatedPopup):
    """Render chapter choices and emit seek intent without owning transport."""

    chapterSelected = Signal(int)

    def __init__(
        self, trigger: QWidget, *, artwork_provider: ArtworkPixmapProvider | None = None
    ) -> None:
        surface = _ChapterSurface()
        super().__init__(trigger, surface, direction=PopupDirection.DOWN)
        self._chapter_surface = surface
        surface.setObjectName("playerChaptersSurface")
        self.animation.setObjectName("playerChaptersAnimation")
        self.setObjectName("playerChapterPopup")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoMouseReplay)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._trigger = trigger
        self._chapters: tuple[TrackChapter, ...] = ()
        self._current_chapter: TrackChapter | None = None
        self._layout = QVBoxLayout(surface)
        self._layout.setSpacing(LAYOUT.space_xs)
        self._heading = QLabel(surface)
        self._heading.setObjectName("playerChaptersHeading")
        self._layout.addWidget(self._heading)
        self._list = QListWidget(surface)
        self._list.setObjectName("playerChapterList")
        self._artwork_delegate = (
            _ChapterArtworkDelegate(artwork_provider, self._list)
            if artwork_provider is not None
            else None
        )
        if self._artwork_delegate is not None:
            self._list.setItemDelegate(self._artwork_delegate)
        self._list.setUniformItemSizes(True)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self._list.itemClicked.connect(self._activate_chapter)
        self._list.itemActivated.connect(self._activate_chapter)
        self._list.installEventFilter(self)
        self._layout.addWidget(self._list, 1)
        self._empty = QLabel(surface)
        self._empty.setObjectName("playerChaptersEmpty")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._layout.addWidget(self._empty, 1)
        self._retranslate()

    def show_index(
        self,
        chapters: tuple[TrackChapter, ...],
        position_ms: int,
        *,
        artwork_id: int = 0,
    ) -> None:
        """Open under the trigger, bounded to its screen, at the current chapter."""

        self._chapters = chapters
        self._current_chapter = None
        if self._artwork_delegate is not None:
            self._artwork_delegate.set_artwork_id(artwork_id)
        self._rebuild_list()
        self.update_position(position_ms)
        if self._list.count() and self._list.currentRow() < 0:
            self._list.setCurrentRow(0)
        screen = self._trigger.screen().availableGeometry()
        width = min(LAYOUT.chapter_popup_width, screen.width())
        row_height = max(self._list.sizeHintForRow(0), self.fontMetrics().height() * 2)
        content_height = (
            row_height * len(chapters) if chapters else self._empty.sizeHint().height()
        )
        height = min(
            LAYOUT.chapter_popup_maximum_height + POPUP_OVERSHOOT_INSET,
            screen.height(),
            content_height
            + self._heading.sizeHint().height()
            + 4 * LAYOUT.space_sm
            + POPUP_OVERSHOOT_INSET,
        )
        anchor = self._trigger.mapToGlobal(
            QPoint(self._trigger.width() // 2, self._trigger.height())
        )
        above = self._trigger.mapToGlobal(QPoint(0, 0)).y() - screen.top()
        below = screen.bottom() - anchor.y() + 1
        opens_below = below >= height or below >= above
        self.direction = PopupDirection.DOWN if opens_below else PopupDirection.UP
        self._chapter_surface.opens_below = opens_below
        height = min(height, max(1, below if opens_below else above))
        x = max(screen.left(), min(anchor.x() - width // 2, screen.right() - width + 1))
        y = anchor.y() if opens_below else anchor.y() - self._trigger.height() - height
        y = max(screen.top(), min(y, screen.bottom() - height + 1))
        self._chapter_surface.arrow_x = min(
            width - LAYOUT.radius_panel - LAYOUT.space_xs,
            max(LAYOUT.radius_panel + LAYOUT.space_xs, anchor.x() - x),
        )
        self._layout.setContentsMargins(
            LAYOUT.space_sm,
            LAYOUT.space_sm + (LAYOUT.space_xs if opens_below else 0),
            LAYOUT.space_sm,
            LAYOUT.space_sm + (0 if opens_below else LAYOUT.space_xs),
        )
        self.setGeometry(x, y, width, height)
        self.open_at(QPoint(x, y))
        if chapters:
            self._list.scrollToItem(self._list.currentItem())
            self._list.setFocus(Qt.FocusReason.PopupFocusReason)
        else:
            self.setFocus(Qt.FocusReason.PopupFocusReason)

    def update_position(self, position_ms: int) -> None:
        chapter = chapter_at(self._chapters, position_ms)
        if chapter == self._current_chapter:
            return
        self._current_chapter = chapter
        self._list.setCurrentRow(self._chapters.index(chapter) if chapter else -1)

    def _activate_chapter(self, item: QListWidgetItem) -> None:
        row = self._list.row(item)
        if not self.is_open or not 0 <= row < len(self._chapters):
            return
        start_ms = self._chapters[row].start_ms
        self.close()
        self._trigger.setFocus(Qt.FocusReason.PopupFocusReason)
        self.chapterSelected.emit(start_ms)

    def _rebuild_list(self) -> None:
        self._list.clear()
        for number, chapter in enumerate(self._chapters, 1):
            title = chapter.title.strip() or self.tr("Untitled Chapter")
            seconds, milliseconds = divmod(chapter.start_ms, 1000)
            minutes, seconds = divmod(seconds, 60)
            hours, minutes = divmod(minutes, 60)
            timestamp = (
                f"{hours}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"
                if hours
                else f"{minutes}:{seconds:02d}.{milliseconds:03d}"
            )
            text = self.tr("{number}. {title}\n{timestamp}").format(
                number=number, title=title, timestamp=timestamp
            )
            item = QListWidgetItem(text, self._list)
            item.setData(Qt.ItemDataRole.AccessibleTextRole, text)
            # Native Chapter metadata can retain a first-start sentinel of 1 ms;
            # the corresponding initial image still has an ordinary zero key.
            item.setData(
                _ARTWORK_TIME_ROLE, 0 if chapter.start_ms == 1 else chapter.start_ms
            )
        self._list.setVisible(bool(self._chapters))
        self._empty.setVisible(not self._chapters)

    def _retranslate(self) -> None:
        self._heading.setText(self.tr("Chapters"))
        self.setAccessibleName(self.tr("Chapters"))
        self._list.setAccessibleName(self.tr("Chapters"))
        self._empty.setText(self.tr("No chapters available"))

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() is QEvent.Type.LanguageChange:
            row = self._list.currentRow()
            self._retranslate()
            self._rebuild_list()
            self._list.setCurrentRow(row)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            watched is self._list
            and isinstance(event, QKeyEvent)
            and event.type() is QEvent.Type.KeyPress
        ):
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if self._list.currentRow() >= 0:
                    self._activate_chapter(self._list.currentItem())
                return True
            if event.key() == Qt.Key.Key_Escape:
                self.close()
                self._trigger.setFocus(Qt.FocusReason.PopupFocusReason)
                return True
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            self._trigger.setFocus(Qt.FocusReason.PopupFocusReason)
            event.accept()
            return
        super().keyPressEvent(event)


class _ChapterSurface(QFrame):
    """Paint the arrow and panel together as they travel through the popup clip."""

    def __init__(self) -> None:
        super().__init__()
        self.opens_below = True
        self.arrow_x = 0

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        arrow_height = LAYOUT.space_xs
        panel = QRectF(self.rect()).adjusted(
            0.5,
            arrow_height + 0.5 if self.opens_below else 0.5,
            -0.5,
            -0.5 if self.opens_below else -arrow_height - 0.5,
        )
        outline = QPainterPath()
        outline.addRoundedRect(panel, LAYOUT.radius_panel, LAYOUT.radius_panel)
        arrow = QPainterPath()
        base_y = panel.top() if self.opens_below else panel.bottom()
        tip_y = 0.5 if self.opens_below else self.height() - 0.5
        arrow.moveTo(self.arrow_x - arrow_height, base_y)
        arrow.lineTo(self.arrow_x, tip_y)
        arrow.lineTo(self.arrow_x + arrow_height, base_y)
        arrow.closeSubpath()
        palette = QApplication.palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(palette.color(QPalette.ColorRole.Mid), 1))
        painter.setBrush(palette.brush(QPalette.ColorRole.Base))
        painter.drawPath(outline.united(arrow))
