"""A capacity strip with readable category totals beside its color encoding."""

from PySide6.QtCore import QLocale, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPaintEvent, QResizeEvent
from PySide6.QtWidgets import (
    QBoxLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.services.device_summary import DeviceStorageBreakdown, StorageCategory
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT, ThemeTokens


def format_capacity(size_bytes: int) -> str:
    """Match the Sidebar's locale-aware capacity units."""
    return QLocale().formattedDataSize(
        size_bytes, 1, QLocale.DataSizeFormat.DataSizeTraditionalFormat
    )


def _category_color(category: StorageCategory, tokens: ThemeTokens) -> str:
    return {
        StorageCategory.MUSIC: tokens.artwork_blue,
        StorageCategory.VIDEOS: tokens.artwork_violet,
        StorageCategory.PODCASTS: tokens.artwork_coral,
        StorageCategory.AUDIOBOOKS: tokens.artwork_gold,
        StorageCategory.PHOTOS: tokens.artwork_green,
        StorageCategory.GAMES: tokens.storage_games,
        StorageCategory.ALBUM_ARTWORK: tokens.storage_album_artwork,
        StorageCategory.OTHER: tokens.border_strong,
        StorageCategory.FREE: tokens.surface_alt,
    }[category]


class _CapacityBar(QWidget):
    def __init__(self, theme: ThemeManager, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("deviceCapacityBar")
        self.setFixedHeight(LAYOUT.device_storage_bar_height)
        self._theme = theme
        self.breakdown: DeviceStorageBreakdown | None = None
        theme.effectiveThemeChanged.connect(self.update)

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bounds = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        clip = QPainterPath()
        clip.addRoundedRect(bounds, LAYOUT.space_2xs, LAYOUT.space_2xs)
        painter.fillPath(clip, QColor(self._theme.tokens.surface_alt))
        breakdown = self.breakdown
        if breakdown is not None and breakdown.total_bytes > 0:
            painter.save()
            painter.setClipPath(clip)
            offset = 0.0
            for segment in breakdown.segments:
                width = bounds.width() * segment.size_bytes / breakdown.total_bytes
                left = bounds.left() + offset
                if self.layoutDirection() == Qt.LayoutDirection.RightToLeft:
                    left = bounds.right() - offset - width
                painter.fillRect(
                    QRectF(left, bounds.top(), width, bounds.height()),
                    QColor(_category_color(segment.category, self._theme.tokens)),
                )
                offset += width
            painter.restore()
        painter.setPen(QColor(self._theme.tokens.border_strong))
        painter.drawPath(clip)
        painter.end()


class _Swatch(QWidget):
    def __init__(
        self, category: StorageCategory, theme: ThemeManager, parent: QWidget
    ) -> None:
        super().__init__(parent)
        self._category = category
        self._theme = theme
        self.setFixedSize(LAYOUT.space_sm, LAYOUT.space_sm)
        theme.effectiveThemeChanged.connect(self.update)

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor(self._theme.tokens.border_strong))
        painter.setBrush(QColor(_category_color(self._category, self._theme.tokens)))
        painter.drawRoundedRect(
            QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 2, 2
        )
        painter.end()


class StorageBreakdown(QFrame):
    """Present observed capacity and estimated, indexed category sizes."""

    def __init__(self, theme: ThemeManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("deviceStorageBreakdown")
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._theme = theme
        self._breakdown: DeviceStorageBreakdown | None = None
        self._entries: list[QWidget] = []
        self._columns = 0
        self._title = QLabel(self)
        self._title.setObjectName("sectionTitle")
        self._capacity = QLabel(self)
        self._capacity.setObjectName("deviceStorageCapacity")
        self._heading = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self._heading.addWidget(self._title)
        self._heading.addStretch(1)
        self._heading.addWidget(self._capacity)
        self._bar = _CapacityBar(theme, self)
        self._legend = QGridLayout()
        self._legend.setHorizontalSpacing(LAYOUT.space_lg)
        self._legend.setVerticalSpacing(LAYOUT.space_xs)
        self._note = QLabel(self)
        self._note.setObjectName("deviceStorageNote")
        self._note.setWordWrap(True)
        self._note.setTextFormat(Qt.TextFormat.PlainText)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            LAYOUT.space_lg, LAYOUT.space_md, LAYOUT.space_lg, LAYOUT.space_md
        )
        layout.setSpacing(LAYOUT.space_sm)
        layout.addLayout(self._heading)
        layout.addWidget(self._bar)
        layout.addLayout(self._legend)
        layout.addWidget(self._note)
        self.set_breakdown(None)

    def set_breakdown(self, breakdown: DeviceStorageBreakdown | None) -> None:
        self._breakdown = breakdown
        self._bar.breakdown = breakdown
        self._bar.update()
        self._title.setText(self.tr("Storage"))
        self._bar.setAccessibleName(self.tr("Storage by category"))
        for entry in self._entries:
            self._legend.removeWidget(entry)
            entry.hide()
            entry.deleteLater()
        self._entries.clear()
        self._columns = 0
        if breakdown is None or breakdown.total_bytes <= 0:
            self._capacity.setText(self.tr("Capacity unavailable"))
            self._note.setText(
                self.tr("Storage details appear when an iPod is loaded.")
                if breakdown is None
                else self.tr("This iPod's storage capacity is unavailable.")
            )
            self._bar.setAccessibleDescription(self._capacity.text())
            self._bar.setToolTip("")
            return
        self._capacity.setText(
            self.tr("%1 free of %2")
            .replace("%1", format_capacity(breakdown.available_bytes))
            .replace("%2", format_capacity(breakdown.total_bytes))
        )
        names = {
            StorageCategory.MUSIC: self.tr("Music"),
            StorageCategory.VIDEOS: self.tr("Videos"),
            StorageCategory.PODCASTS: self.tr("Podcasts"),
            StorageCategory.AUDIOBOOKS: self.tr("Audiobooks"),
            StorageCategory.PHOTOS: self.tr("Photos"),
            StorageCategory.GAMES: self.tr("Games"),
            StorageCategory.ALBUM_ARTWORK: self.tr("Album artwork"),
            StorageCategory.OTHER: self.tr("Other"),
            StorageCategory.FREE: self.tr("Free"),
        }
        descriptions: list[str] = []
        for segment in breakdown.segments:
            if segment.size_bytes <= 0:
                continue
            entry = QWidget(self)
            entry.setObjectName(f"storageCategory_{segment.category.value}")
            row = QHBoxLayout(entry)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(LAYOUT.space_xs)
            row.addWidget(_Swatch(segment.category, self._theme, entry))
            text = f"{names[segment.category]}  {format_capacity(segment.size_bytes)}"
            label = QLabel(text, entry)
            label.setWordWrap(True)
            label.setObjectName("deviceStorageLegend")
            row.addWidget(label, 1)
            descriptions.append(text)
            self._entries.append(entry)
        self._arrange_legend()
        description = "\n".join(descriptions)
        self._bar.setToolTip(description)
        self._bar.setAccessibleDescription(description)
        self._note.setText(
            self.tr(
                "Category sizes are unavailable because content sizes exceed used storage."
            )
            if breakdown.metadata_exceeds_used
            else self.tr(
                "Media sizes are estimated from the saved library. Games and Album artwork use captured folder sizes. Other includes remaining databases and unclassified files."
            )
        )

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        narrow = self.width() < 480
        self._heading.setDirection(
            QBoxLayout.Direction.TopToBottom
            if narrow
            else QBoxLayout.Direction.LeftToRight
        )
        self._heading.setSpacing(LAYOUT.space_2xs if narrow else LAYOUT.space_xs)
        self._capacity.setWordWrap(narrow)
        self._arrange_legend()

    def _arrange_legend(self) -> None:
        columns = max(1, min(4, (self.width() - LAYOUT.space_lg * 2) // 180))
        if columns == self._columns:
            return
        for entry in self._entries:
            self._legend.removeWidget(entry)
        for column in range(4):
            self._legend.setColumnStretch(column, int(column < columns))
        for index, entry in enumerate(self._entries):
            self._legend.addWidget(entry, index // columns, index % columns)
        self._columns = columns
