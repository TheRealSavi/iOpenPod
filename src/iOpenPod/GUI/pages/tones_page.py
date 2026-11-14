"""Hallmark · existing iOpenPod themes · quiet list with explicit audio preview.

Pre-emit critique: P5 H5 E4 S5 R5 V4. Porcelain/Slate, narrow/wide,
100/200% scaling, German text, native keyboard activation and disabled states.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QLocale, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.tone_preview import TonePreview
from iOpenPod.GUI.delegates.extras_delegate import ToneDelegate
from iOpenPod.GUI.presentation.i18n.workflow import workflow_text
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.browser_chrome import PageHeader
from iOpenPod.GUI.widgets.extras_collection import ExtrasCollection
from iOpenPod.GUI.widgets.themed_buttons import ActionButton

if TYPE_CHECKING:
    from PySide6.QtGui import QHideEvent

    from iOpenPod.app.extras_controller import ExtrasController
    from iOpenPod.app.models.extras import AlarmToneItem


class TonesPage(QWidget):
    previewRequested = Signal()

    def __init__(
        self, controller: ExtrasController, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("tonesPage")
        self._controller = controller
        self._preview = TonePreview(self)
        self._items: tuple[AlarmToneItem, ...] = ()
        self._header = PageHeader(self)
        content = QWidget(self)
        content.setMaximumWidth(LAYOUT.extras_collection_width)
        self._status = QLabel(content)
        self._status.setWordWrap(True)
        self._status.setTextFormat(Qt.TextFormat.PlainText)
        panel = ExtrasCollection(content)
        panel.setObjectName("tonesCollection")
        self._list = panel.view
        self._list.setObjectName("tonesList")
        self._list.setColumnCount(3)
        self._list.hideColumn(1)
        self._list.hideColumn(2)
        self._list.setItemDelegate(ToneDelegate(self._list))
        self._empty = panel.empty
        self._empty.setObjectName("tonesEmpty")
        self._play = ActionButton(parent=panel, glyph="play")
        self._play.setObjectName("tonePreview")
        self._count = QLabel(panel)
        self._count.setProperty("extrasMuted", True)
        panel.action_layout.addWidget(self._play)
        panel.action_layout.addStretch(1)
        panel.action_layout.addWidget(self._count)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(LAYOUT.space_md)
        layout.addWidget(self._status)
        layout.addWidget(panel)
        layout.addStretch(1)
        centered = QHBoxLayout()
        centered.setContentsMargins(
            LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg
        )
        centered.addStretch(1)
        centered.addWidget(content)
        centered.addStretch(1)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._header)
        root.addLayout(centered, 1)
        self._play.clicked.connect(self._toggle_preview)
        self._list.itemSelectionChanged.connect(self._selection_changed)
        self._list.itemActivated.connect(self._toggle_preview)
        self._preview.changed.connect(self._update_play)
        self._preview.failed.connect(self._show_error)
        controller.changed.connect(self._reload)
        self._retranslate()
        self._reload()

    def _selected(self) -> AlarmToneItem | None:
        selected = self._list.currentItem()
        index = self._list.indexOfTopLevelItem(selected) if selected is not None else -1
        return self._items[index] if 0 <= index < len(self._items) else None

    def _reload(self) -> None:
        catalog = self._controller.catalog
        if self._items != catalog.tones:
            self._preview.stop()
            selected = self._selected()
            key = selected.key if selected is not None else None
            self._items = catalog.tones
            self._list.clear()
            for item in self._items:
                row = QTreeWidgetItem(
                    [
                        workflow_text(item.name) if item.builtin else item.name,
                        self.tr("Built-in") if item.builtin else self.tr("Custom"),
                        self.tr("%1 s").replace(
                            "%1", QLocale().toString(item.duration_ms / 1000, "f", 1)
                        )
                        if item.notes
                        else "—",
                    ]
                )
                row.setToolTip(
                    0,
                    "\n".join(
                        filter(
                            None, (row.text(0), row.text(1), row.text(2), item.issue)
                        )
                    ),
                )
                row.setData(0, Qt.ItemDataRole.AccessibleTextRole, row.toolTip(0))
                self._list.addTopLevelItem(row)
                if item.key == key:
                    self._list.setCurrentItem(row)
            first = self._list.topLevelItem(0)
            if self._list.currentItem() is None and first is not None:
                self._list.setCurrentItem(first)
        self._list.setVisible(bool(self._items))
        self._empty.setVisible(not self._items)
        self._empty.setText(
            self.tr("Loading tones…")
            if self._controller.busy
            else self.tr("No tones to show.")
        )
        self._status.setText(
            self._controller.message
            or "\n".join(issue for issue in catalog.issues if "tone" in issue.lower())
        )
        self._status.setVisible(bool(self._status.text()))
        self._count.setText(
            self.tr("%1 of 19 custom tones").replace(
                "%1", str(sum(not item.builtin for item in self._items))
            )
        )
        self._update_play()

    def _selection_changed(self) -> None:
        self._preview.stop()
        self._update_play()

    def _toggle_preview(self) -> None:
        item = self._selected()
        if self._preview.playing:
            self._preview.stop()
        elif item is not None and item.notes:
            self.previewRequested.emit()
            self._preview.play(item.notes)

    def _update_play(self) -> None:
        item = self._selected()
        self._play.setText(
            self.tr("Stop") if self._preview.playing else self.tr("Listen")
        )
        self._play.setEnabled(
            item is not None and bool(item.notes) and item.duration_ms <= 30000
        )

    def _show_error(self, message: str) -> None:
        self._status.setText(workflow_text(message))
        self._status.show()

    def _retranslate(self) -> None:
        self._header.set_title(self.tr("Tones"))
        self._list.setAccessibleName(self.tr("Tones"))
        self._list.setHeaderLabels(
            [self.tr("Tone"), self.tr("Type"), self.tr("Duration")]
        )
        self._play.setToolTip(
            self.tr("Preview the notes. The iPod's speaker will sound different.")
        )

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self._retranslate()
            self._items = ()
            self._reload()
        super().changeEvent(event)

    def hideEvent(self, event: QHideEvent) -> None:
        self._preview.stop()
        super().hideEvent(event)
