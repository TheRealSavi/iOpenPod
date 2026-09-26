"""Show every active Host preparation with independent phase progress."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QProgressBar,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.GUI.presentation.theme.tokens import LAYOUT

if TYPE_CHECKING:
    from iOpenPod.app.library_write import WriteItemProgress


class _PreparationRow(QFrame):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("syncPreparationRow")
        self._name = QLabel(self)
        self._name.setObjectName("syncPreparationName")
        self._detail = QLabel(self)
        self._detail.setObjectName("syncPreparationDetail")
        for label in (self._name, self._detail):
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
        self._bar = QProgressBar(self)
        self._bar.setObjectName("syncPreparationProgress")
        self._bar.setTextVisible(False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, LAYOUT.space_xs, 0, LAYOUT.space_xs)
        layout.setSpacing(LAYOUT.space_xs)
        layout.addWidget(self._name)
        layout.addWidget(self._detail)
        layout.addWidget(self._bar)

    def update_item(self, item: WriteItemProgress) -> None:
        self.setToolTip(item.item_id)
        self._name.setText(item.name)
        update = item.progress
        parts = [self.tr(update.message)]
        processed, duration = update.processed_seconds, update.duration_seconds
        measured = processed is not None and math.isfinite(processed) and processed >= 0
        known_duration = (
            duration is not None and math.isfinite(duration) and duration > 0
        )
        if measured and known_duration:
            assert processed is not None and duration is not None
            fraction = min(processed / duration, 1)
            self._bar.setRange(0, 1000)
            self._bar.setValue(int(fraction * 1000))
            parts.append(f"{int(fraction * 100)}%")
            parts.append(f"{_media_time(processed)} / {_media_time(duration)}")
        else:
            self._bar.setRange(0, 0)
            if measured:
                assert processed is not None
                parts.append(
                    self.tr("%1 processed").replace("%1", _media_time(processed))
                )
        if (
            update.speed is not None
            and math.isfinite(update.speed)
            and update.speed > 0
        ):
            parts.append(self.tr("%1x speed").replace("%1", f"{update.speed:.2f}"))
        self._detail.setText(" · ".join(parts))
        self._bar.setAccessibleName(item.name + ": " + self._detail.text())


def _media_time(seconds: float) -> str:
    minutes, seconds_part = divmod(int(seconds), 60)
    hours, minutes_part = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes_part:02}:{seconds_part:02}"
    return f"{minutes}:{seconds_part:02}"


class SyncPreparationProgress(QScrollArea):
    """Rows are keyed by source identity, so duplicate titles remain independent."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("syncPreparationProgressList")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMaximumHeight(320)
        self.setMinimumHeight(100)
        self._content = QWidget(self)
        self._layout = QVBoxLayout(self._content)
        self._layout.setContentsMargins(0, 0, LAYOUT.space_sm, 0)
        self._layout.setSpacing(LAYOUT.space_sm)
        self._layout.addStretch()
        self.setWidget(self._content)
        self._rows: dict[str, _PreparationRow] = {}
        self.hide()

    def set_items(self, items: tuple[WriteItemProgress, ...]) -> None:
        identities = {item.item_id for item in items}
        for identity in tuple(self._rows):
            if identity not in identities:
                removed = self._rows.pop(identity)
                self._layout.removeWidget(removed)
                removed.setParent(None)
                removed.deleteLater()
        for index, item in enumerate(items):
            row = self._rows.get(item.item_id)
            if row is None:
                row = _PreparationRow(self._content)
                self._rows[item.item_id] = row
                self._layout.insertWidget(index, row)
                row.show()
            row.update_item(item)
        self.setVisible(bool(items))
