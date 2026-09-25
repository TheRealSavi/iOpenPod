"""Shared, provisional device storage preview for Sync selection and Review."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from iOpenPod.GUI.presentation.device_images import device_pixmap
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT

if TYPE_CHECKING:
    from PySide6.QtGui import QPaintEvent

    from iOpenPod.app.models.device import ActiveIPod
    from iOpenPod.app.sync_storage import SyncStorageEstimate
    from iOpenPod.GUI.presentation.theme.manager import ThemeManager


class _StorageSegments(QWidget):
    def __init__(self, theme: ThemeManager, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("syncStorageSegments")
        self.setFixedHeight(LAYOUT.sync_storage_bar_height)
        self._theme = theme
        self.estimate: SyncStorageEstimate | None = None
        theme.effectiveThemeChanged.connect(self.update)

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bounds = QRectF(self.rect())
        clip = QPainterPath()
        clip.addRoundedRect(bounds, bounds.height() / 2, bounds.height() / 2)
        painter.setClipPath(clip)
        tokens = self._theme.tokens
        painter.fillRect(bounds, QColor(tokens.surface_alt))
        estimate = self.estimate
        if estimate is not None and estimate.total_bytes > 0:
            used = min(1.0, estimate.current_used_bytes / estimate.total_bytes)
            projected = min(1.0, estimate.projected_used_bytes / estimate.total_bytes)
            base = min(used, projected) * bounds.width()
            end = max(used, projected) * bounds.width()
            painter.fillRect(QRectF(0, 0, base, bounds.height()), QColor(tokens.accent))
            delta_color = tokens.success if estimate.net_bytes >= 0 else tokens.warning
            if estimate.free_bytes < 0:
                delta_color = tokens.danger
            painter.fillRect(
                QRectF(base, 0, end - base, bounds.height()), QColor(delta_color)
            )
            if estimate.free_bytes < 0:
                # Remain visibly over capacity even when the device was already full.
                painter.setClipping(False)
                painter.setPen(QColor(tokens.danger))
                painter.drawRoundedRect(
                    bounds.adjusted(0.5, 0.5, -0.5, -0.5),
                    bounds.height() / 2,
                    bounds.height() / 2,
                )
        painter.end()


class SyncStorageBar(QFrame):
    """Show observed usage and a source-size approximation, with explicit limits."""

    def __init__(self, theme: ThemeManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("syncStorageBar")
        self._device_name = ""
        self._product_image = "iPodGeneric.png"
        self._image = QLabel(self)
        self._image.setFixedSize(
            LAYOUT.sidebar_device_image_size, LAYOUT.sidebar_device_image_size
        )
        self._name = QLabel(self)
        self._name.setObjectName("syncStorageDevice")
        self._name.setTextFormat(Qt.TextFormat.PlainText)
        self._name.setWordWrap(True)
        self._title = QLabel(self)
        self._title.setObjectName("syncStorageTitle")
        self._current = QLabel(self)
        self._current.setObjectName("syncStorageCurrent")
        self._delta = QLabel(self)
        self._delta.setObjectName("syncStorageDelta")
        self._remaining = QLabel(self)
        self._remaining.setObjectName("syncStorageRemaining")
        self._note = QLabel(self)
        self._note.setObjectName("syncStorageNote")
        self._note.setWordWrap(True)
        self._segments = _StorageSegments(theme, self)

        heading = QHBoxLayout()
        heading.addWidget(self._name, 1)
        heading.addWidget(self._title)
        values = QHBoxLayout()
        values.setSpacing(LAYOUT.space_md)
        values.addWidget(self._current)
        values.addWidget(self._delta)
        values.addStretch(1)
        values.addWidget(self._remaining)
        contents = QVBoxLayout()
        contents.setSpacing(LAYOUT.space_2xs)
        contents.addLayout(heading)
        contents.addWidget(self._segments)
        contents.addLayout(values)
        contents.addWidget(self._note)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            LAYOUT.space_lg, LAYOUT.space_sm, LAYOUT.space_lg, LAYOUT.space_sm
        )
        layout.setSpacing(LAYOUT.space_sm)
        layout.addWidget(self._image, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(contents, 1)
        self.retranslate_ui()

    @property
    def estimate(self) -> SyncStorageEstimate | None:
        return self._segments.estimate

    def set_device(self, active: ActiveIPod | None) -> None:
        self._device_name = active.display_name if active is not None else ""
        self._product_image = (
            active.profile.product_image if active is not None else "iPodGeneric.png"
        )
        self.retranslate_ui()

    def set_estimate(self, estimate: SyncStorageEstimate | None) -> None:
        self._segments.estimate = estimate
        self._segments.update()
        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        self._name.setText(self._device_name or self.tr("iPod storage"))
        self._refresh_image()
        self._title.setText(self.tr("Source-size estimate"))
        note = self.tr(
            "Based on source file sizes. Final size after conversion is not yet available."
        )
        self.setToolTip(
            self.tr(
                "Uses the last observed device capacity and scanned media sizes. "
                "Excludes changes to artwork, photo thumbnails, databases, and "
                "temporary space needed during Sync."
            )
        )
        estimate = self.estimate
        available = estimate is not None and estimate.total_bytes > 0
        self._segments.setVisible(available)
        self._current.setVisible(available)
        self._delta.setVisible(available)
        status = "normal"
        if estimate is None or not available:
            self._current.clear()
            self._delta.clear()
            self._remaining.setText(self.tr("Device capacity unavailable"))
        else:
            self._current.setText(
                self.tr("Used: %1 / %2")
                .replace("%1", _format_bytes(estimate.current_used_bytes))
                .replace("%2", _format_bytes(estimate.total_bytes))
            )
            sign = "+" if estimate.net_bytes >= 0 else "-"
            self._delta.setText(
                self.tr("Net: %1").replace(
                    "%1", sign + _format_bytes(abs(estimate.net_bytes))
                )
            )
            self._delta.setProperty(
                "direction", "add" if estimate.net_bytes >= 0 else "remove"
            )
            if estimate.free_bytes < 0:
                status = "over"
                remaining = self.tr("About %1 over capacity")
            else:
                remaining = self.tr("About %1 free after Sync")
            self._remaining.setText(
                remaining.replace("%1", _format_bytes(abs(estimate.free_bytes)))
            )
            if estimate.unknown_items:
                self._title.setText(self.tr("Partial source-size estimate"))
                note += " " + (
                    self.tr(
                        "%n unresolved item excluded.", None, estimate.unknown_items
                    )
                    if estimate.unknown_items == 1
                    else self.tr(
                        "%n unresolved items excluded.", None, estimate.unknown_items
                    )
                )
                if status == "normal":
                    status = "partial"
        self._note.setText(note)
        self._remaining.setProperty("status", status)
        self._delta.setProperty("status", status)
        for label in (self._delta, self._remaining):
            style = label.style()
            style.unpolish(label)
            style.polish(label)
        self._segments.setAccessibleName(self.tr("Source-size storage estimate"))
        self._segments.setAccessibleDescription(
            " · ".join(
                (
                    self._name.text(),
                    self._current.text(),
                    self._delta.text(),
                    self._remaining.text(),
                    note,
                )
            )
        )

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        elif event.type() == QEvent.Type.DevicePixelRatioChange:
            self._refresh_image()
        super().changeEvent(event)

    def _refresh_image(self) -> None:
        self._image.setPixmap(
            device_pixmap(
                self._product_image,
                LAYOUT.sidebar_device_image_size,
                self.devicePixelRatioF(),
            )
        )


def _format_bytes(value: int) -> str:
    amount = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if amount < 1024 or unit == "TiB":
            return f"{amount:.0f} {unit}" if unit == "B" else f"{amount:.1f} {unit}"
        amount /= 1024
    raise AssertionError("Unreachable size unit")


__all__ = ["SyncStorageBar"]
