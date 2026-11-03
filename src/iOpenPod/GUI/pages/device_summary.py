"""An Apple-inspired device portrait and read-only Active iPod summary.

Hallmark: left product portrait and aligned specification list; existing theme;
side-rail navigation; capacity-strip footer; no decorative motion.
Pre-emit critique: philosophy 4, hierarchy 4, execution 4, specificity 5,
restraint 5, variety 4. Desktop pane reflow checked from 320 to 1200 pixels.
"""

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QBoxLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.models.device import ActiveIPod
from iOpenPod.app.services.device_summary import device_storage_breakdown
from iOpenPod.GUI.presentation.device_images import device_pixmap
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.browser_chrome import PageHeader
from iOpenPod.GUI.widgets.storage_breakdown import StorageBreakdown, format_capacity
from iOpenPod.GUI.widgets.themed_buttons import ActionButton


class DeviceSummaryPage(QWidget):
    """Compose path-free device state without initiating any device operation."""

    def __init__(self, parent: QWidget | None = None, *, theme: ThemeManager) -> None:
        super().__init__(parent)
        self.setObjectName("deviceSummaryPage")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._theme = theme
        self._active: ActiveIPod | None = None
        self._draft_name = ""
        self._header = PageHeader(self)
        self._scroll = QScrollArea(self)
        self._scroll.setObjectName("deviceSummaryScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        canvas = QWidget()
        canvas.setObjectName("deviceSummaryCanvas")
        canvas_layout = QHBoxLayout(canvas)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        self._body = QWidget(canvas)
        canvas_layout.addWidget(self._body, 1)
        body = QVBoxLayout(self._body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self._empty_title = self._label("deviceSummaryEmptyTitle")
        self._empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_detail = self._label("deviceSummaryModel")
        self._empty_detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.addWidget(self._empty_title)
        body.addWidget(self._empty_detail)
        self._surface = QFrame(self._body)
        self._surface.setObjectName("deviceSummarySurface")
        self._surface_layout = QHBoxLayout(self._surface)
        self._identity_content = QWidget(self._surface)
        self._identity_content.setMaximumWidth(LAYOUT.device_summary_identity_width)
        self._identity = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self._identity.setSpacing(LAYOUT.space_2xl)
        self._identity.setContentsMargins(0, 0, 0, 0)
        self._identity_content.setLayout(self._identity)
        self._surface_layout.addStretch(0)
        self._surface_layout.addWidget(self._identity_content, 1)
        self._surface_layout.addStretch(0)
        self._portrait = QLabel(self._body)
        self._portrait.setObjectName("deviceSummaryPortrait")
        self._portrait.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._portrait.setFixedSize(
            LAYOUT.device_summary_image_size, LAYOUT.device_summary_image_size
        )
        self._identity.addWidget(self._portrait, 0, Qt.AlignmentFlag.AlignCenter)
        self._details = QWidget(self._body)
        self._grid = QGridLayout(self._details)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(LAYOUT.space_xs)
        self._grid.setVerticalSpacing(LAYOUT.space_xs)
        self._grid.setColumnStretch(1, 1)
        self._fields: list[tuple[QLabel, QLabel]] = []
        for index, key in enumerate(
            (
                "name",
                "capacity",
                "firmware",
                "serial",
                "model",
                "model_name",
                "finish",
            )
        ):
            label = self._label("deviceSummaryFieldLabel", self._details)
            label.setWordWrap(False)
            label.setSizePolicy(
                QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred
            )
            label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
            value = self._label(
                "deviceSummaryName" if key == "name" else f"deviceSummary_{key}",
                self._details,
            )
            value.setProperty("deviceSummaryValue", True)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self._grid.addWidget(label, index, 0)
            self._grid.addWidget(value, index, 1)
            self._fields.append((label, value))
        self._name = self._fields[0][1]
        self._identity.addWidget(self._details, 1, Qt.AlignmentFlag.AlignVCenter)
        surface_row = QHBoxLayout()
        surface_row.setContentsMargins(
            LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg, 0
        )
        surface_row.addWidget(self._surface)
        body.addLayout(surface_row)
        self._restore_row = QFrame(self._body)
        self._restore_row.setObjectName("deviceRestoreRow")
        restore_layout = QHBoxLayout(self._restore_row)
        restore_layout.setContentsMargins(
            LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg
        )
        restore_layout.setSpacing(LAYOUT.space_sm)
        self._restore = ActionButton(parent=self._restore_row)
        self._restore.setObjectName("restoreDevice")
        self._restore.setEnabled(False)
        self._coming_soon = self._label("deviceRestoreComingSoon", self._restore_row)
        restore_layout.addWidget(self._restore)
        restore_layout.addWidget(self._coming_soon, 1)
        restore_surface_row = QHBoxLayout()
        restore_surface_row.setContentsMargins(
            LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg
        )
        restore_surface_row.addWidget(self._restore_row)
        body.addLayout(restore_surface_row)
        body.addStretch(1)
        self._scroll.setWidget(canvas)
        self._storage = StorageBreakdown(theme, self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._header)
        layout.addWidget(self._scroll, 1)
        layout.addWidget(self._storage)
        theme.deviceArtworkChanged.connect(self._refresh_portrait)
        self.retranslate_ui()

    def _label(self, name: str, parent: QWidget | None = None) -> QLabel:
        label = QLabel(parent or self._body)
        label.setObjectName(name)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        label.setMinimumWidth(0)
        label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        return label

    def set_active_ipod(self, active: ActiveIPod | None) -> None:
        self._active = active
        self._draft_name = ""
        self._refresh()

    def set_device_name(self, name: str) -> None:
        """Reflect a name edit; capacity stays tied to the saved device state."""
        self._draft_name = name.strip()
        self._refresh_name()

    def retranslate_ui(self) -> None:
        self._header.set_title(self.tr("Summary"))
        self._restore.setText(self.tr("Restore iPod"))
        self._restore.setToolTip(self.tr("Coming soon"))
        self._coming_soon.setText(self.tr("Coming soon"))
        self._empty_title.setText(self.tr("No Active iPod"))
        self._empty_detail.setText(
            self.tr("Choose an iPod from the sidebar to see its details.")
        )
        labels = (
            self.tr("Name"),
            self.tr("Capacity"),
            self.tr("Software version"),
            self.tr("Serial number"),
            self.tr("Model number"),
            self.tr("Model"),
            self.tr("Color"),
        )
        for (label, _), text in zip(self._fields, labels, strict=True):
            label.setText(f"{text}:")
        self._refresh()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        elif event.type() in {
            QEvent.Type.DevicePixelRatioChange,
            QEvent.Type.ScreenChangeInternal,
        }:
            self._refresh_portrait()
        super().changeEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        for label, _ in self._fields:
            label.setWordWrap(self.width() < 480)
        padding = LAYOUT.space_xs if self.width() < 480 else LAYOUT.space_lg
        self._surface_layout.setContentsMargins(
            padding, LAYOUT.space_md, padding, LAYOUT.space_md
        )
        image_size = min(
            LAYOUT.device_summary_image_size,
            max(
                128,
                self.width()
                - 2 * LAYOUT.space_lg
                - 2 * padding
                - LAYOUT.scrollbar_extent
                - 2 * LAYOUT.device_summary_border_width,
            ),
        )
        if self._portrait.width() != image_size:
            self._portrait.setFixedSize(image_size, image_size)
            self._refresh_portrait()
        self._identity.setDirection(
            QBoxLayout.Direction.LeftToRight
            if self.width() >= 760
            else QBoxLayout.Direction.TopToBottom
        )

    def _refresh_name(self) -> None:
        active = self._active
        self._name.setText(
            (self._draft_name or active.display_name)
            if active
            else self.tr("No Active iPod")
        )

    def _refresh(self) -> None:
        active = self._active
        self._empty_title.setVisible(active is None)
        self._empty_detail.setVisible(active is None)
        self._details.setVisible(active is not None)
        self._restore_row.setVisible(active is not None)
        self._refresh_portrait()
        values = ("—",) * len(self._fields)
        if active is not None:
            values = (
                active.display_name,
                format_capacity(active.candidate.total_bytes)
                if active.candidate.total_bytes > 0
                else self.tr("Unavailable"),
                active.firmware_version or self.tr("Unavailable"),
                active.serial_number or self.tr("Unavailable"),
                active.profile.model_number,
                active.profile.display_name,
                active.profile.finish,
            )
        for (label, value), text in zip(self._fields, values, strict=True):
            value.setText(text)
            value.setAccessibleName(label.text().removesuffix(":"))
        self._refresh_name()
        self._storage.set_breakdown(
            device_storage_breakdown(
                active.candidate,
                active.library,
                game_storage_bytes=active.game_storage_bytes,
                album_artwork_storage_bytes=active.album_artwork_storage_bytes,
            )
            if active
            else None
        )

    def _refresh_portrait(self) -> None:
        active = self._active
        self._portrait.setPixmap(
            device_pixmap(
                active.profile.product_image if active else "iPodGeneric.png",
                self._portrait.width(),
                self.devicePixelRatioF(),
                itunes_107=self._theme.itunes_107_artwork,
            )
        )
        self._portrait.setAccessibleName(
            active.profile.display_name if active else self.tr("iPod")
        )
