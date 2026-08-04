"""Interactive generator and inspector for iTunesDB byte-walk JSON files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from iopenpod.application.runtime import ThreadPoolSingleton, Worker
from iopenpod.itunesdb_parser.byte_walk import (
    ByteWalkChunkIndexEntry,
    hex_interpretations,
    index_byte_walk_json,
    load_indexed_chunk,
)
from iopenpod.itunesdb_parser.forensics import export_forensic_json

from ..styles import FONT_FAMILY, MONO_FONT_FAMILY, Metrics, accent_btn_css, button_css, input_css, paint_css

_ENTRY_ROLE = int(Qt.ItemDataRole.UserRole)
_POPULATED_ROLE = _ENTRY_ROLE + 1
_RESULT_LIMIT = 1_000


def _format_byte_count(value: int) -> str:
    """Format a byte count without hiding the exact number."""
    if value < 1024:
        return f"{value:,} bytes"
    units = ("KiB", "MiB", "GiB")
    amount = float(value)
    for unit in units:
        amount /= 1024
        if amount < 1024 or unit == units[-1]:
            return f"{value:,} bytes ({amount:.2f} {unit})"
    return f"{value:,} bytes"


def _short_value(value: Any, *, limit: int = 180) -> str:
    """Render a JSON value compactly enough for a tree cell."""
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return text if len(text) <= limit else f"{text[:limit - 1]}…"


class ITunesDBForensicsDialog(QDialog):
    """Generate and inspect enormous byte-walk JSON files without UI stalls."""

    def __init__(self, default_itunesdb_path: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._default_itunesdb_path = default_itunesdb_path
        self._json_path: Path | None = None
        self._entries: list[ByteWalkChunkIndexEntry] = []
        self._index_worker: Worker | None = None
        self._chunk_worker: Worker | None = None
        self._export_worker: Worker | None = None
        self.setObjectName("itunesdbForensicsDialog")
        self.setWindowTitle("iTunesDB Byte-Walk Inspector")
        self.resize(1_360, 860)
        self.setMinimumSize(1_040, 650)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 20)
        root.setSpacing(12)

        title = QLabel("iTunesDB Byte-Walk Inspector", self)
        title.setFont(QFont(FONT_FAMILY, Metrics.FONT_XXL, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {paint_css('text.primary')};")
        root.addWidget(title)

        explanation = QLabel(
            "Generate a lossless byte-walk JSON, or open one without loading the whole file into memory. "
            "Select any hex span to view several text, integer, and timestamp interpretations.",
            self,
        )
        explanation.setWordWrap(True)
        explanation.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        explanation.setStyleSheet(f"color: {paint_css('text.secondary')};")
        root.addWidget(explanation)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)

        self.open_button = QPushButton("Open Byte-Walk JSON…", self)
        self.open_button.setStyleSheet(button_css("secondary", "md"))
        self.open_button.clicked.connect(self._choose_json)
        actions.addWidget(self.open_button)

        self.generate_button = QPushButton("Generate from iTunesDB…", self)
        self.generate_button.setStyleSheet(accent_btn_css("md"))
        self.generate_button.clicked.connect(self._choose_itunesdb)
        actions.addWidget(self.generate_button)
        actions.addStretch(1)
        root.addLayout(actions)

        self.status_label = QLabel("Open a byte-walk JSON or generate one from an iTunesDB.", self)
        self.status_label.setObjectName("itunesdbForensicsStatus")
        self.status_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.status_label.setStyleSheet(f"color: {paint_css('text.tertiary')};")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_search_panel())
        splitter.addWidget(self._build_inspection_panel())
        splitter.setSizes([390, 930])
        root.addWidget(splitter, 1)

    def _build_search_panel(self) -> QWidget:
        panel = QFrame(self)
        panel.setObjectName("itunesdbForensicsSearchPanel")
        panel.setStyleSheet(
            f"QFrame#itunesdbForensicsSearchPanel {{ border: 1px solid {paint_css('border.subtle')}; "
            f"border-radius: {Metrics.BORDER_RADIUS_SM}px; background: {paint_css('surface.raised')}; }}",
        )
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        heading = QLabel("Find chunks", panel)
        heading.setFont(QFont(FONT_FAMILY, Metrics.FONT_LG, QFont.Weight.DemiBold))
        heading.setStyleSheet(f"color: {paint_css('text.primary')};")
        layout.addWidget(heading)

        self.search_input = QLineEdit(panel)
        self.search_input.setPlaceholderText("Phase Music, mhyp, 0xFE13BC…")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setStyleSheet(input_css())
        self.search_input.textChanged.connect(self._refresh_results)
        layout.addWidget(self.search_input)

        self.results_summary = QLabel("No indexed document", panel)
        self.results_summary.setFont(QFont(FONT_FAMILY, Metrics.FONT_XS))
        self.results_summary.setStyleSheet(f"color: {paint_css('text.tertiary')};")
        layout.addWidget(self.results_summary)

        self.results_tree = QTreeWidget(panel)
        self.results_tree.setObjectName("itunesdbForensicsResults")
        self.results_tree.setHeaderLabels(["Chunk", "Caption", "File offset"])
        self.results_tree.setRootIsDecorated(False)
        self.results_tree.setAlternatingRowColors(True)
        self.results_tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.results_tree.setUniformRowHeights(True)
        self.results_tree.itemSelectionChanged.connect(self._load_selected_result)
        self._style_tree(self.results_tree)
        results_header = self.results_tree.header()
        if results_header is not None:
            results_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            results_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            results_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.results_tree, 1)
        return panel

    def _build_inspection_panel(self) -> QWidget:
        panel = QWidget(self)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.chunk_label = QLabel("Select a chunk to inspect its byte order.", panel)
        self.chunk_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_LG, QFont.Weight.DemiBold))
        self.chunk_label.setStyleSheet(f"color: {paint_css('text.primary')};")
        self.chunk_label.setWordWrap(True)
        layout.addWidget(self.chunk_label)

        self.chunk_tree = QTreeWidget(panel)
        self.chunk_tree.setObjectName("itunesdbForensicsChunkTree")
        self.chunk_tree.setHeaderLabels(["At", "Bytes", "Meaning", "Value / status", "Hex"])
        self.chunk_tree.setAlternatingRowColors(True)
        self.chunk_tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.chunk_tree.setUniformRowHeights(True)
        self.chunk_tree.itemExpanded.connect(self._populate_expanded_chunk)
        self.chunk_tree.itemSelectionChanged.connect(self._select_byte_entry)
        self._style_tree(self.chunk_tree)
        chunk_header = self.chunk_tree.header()
        if chunk_header is not None:
            chunk_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            chunk_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
            chunk_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
            chunk_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
            chunk_header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.chunk_tree, 1)

        decoder = QFrame(panel)
        decoder.setObjectName("itunesdbForensicsDecoder")
        decoder.setStyleSheet(
            f"QFrame#itunesdbForensicsDecoder {{ border: 1px solid {paint_css('border.subtle')}; "
            f"border-radius: {Metrics.BORDER_RADIUS_SM}px; background: {paint_css('surface.raised')}; }}",
        )
        decoder_layout = QHBoxLayout(decoder)
        decoder_layout.setContentsMargins(12, 10, 12, 10)
        decoder_layout.setSpacing(12)

        hex_column = QVBoxLayout()
        hex_heading = QLabel("Hex decoder", decoder)
        hex_heading.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD, QFont.Weight.DemiBold))
        hex_heading.setStyleSheet(f"color: {paint_css('text.primary')};")
        hex_column.addWidget(hex_heading)
        self.hex_input = QPlainTextEdit(decoder)
        self.hex_input.setObjectName("itunesdbForensicsHexInput")
        self.hex_input.setPlaceholderText("Paste hex here, or select a byte span above")
        self.hex_input.setMaximumHeight(92)
        self.hex_input.setFont(QFont(MONO_FONT_FAMILY, Metrics.FONT_SM))
        self.hex_input.setStyleSheet(input_css())
        self.hex_input.textChanged.connect(self._refresh_interpretations)
        hex_column.addWidget(self.hex_input)
        decoder_layout.addLayout(hex_column, 1)

        self.interpretation_tree = QTreeWidget(decoder)
        self.interpretation_tree.setObjectName("itunesdbForensicsInterpretations")
        self.interpretation_tree.setHeaderLabels(["Interpretation", "Value"])
        self.interpretation_tree.setRootIsDecorated(False)
        self.interpretation_tree.setAlternatingRowColors(True)
        self.interpretation_tree.setMinimumWidth(430)
        self.interpretation_tree.setMaximumHeight(190)
        self._style_tree(self.interpretation_tree)
        interpretation_header = self.interpretation_tree.header()
        if interpretation_header is not None:
            interpretation_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            interpretation_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        decoder_layout.addWidget(self.interpretation_tree, 1)
        layout.addWidget(decoder)
        return panel

    @staticmethod
    def _style_tree(tree: QTreeWidget) -> None:
        tree.setStyleSheet(
            f"QTreeWidget {{ background: {paint_css('table.row.fill')}; color: {paint_css('text.primary')}; "
            f"border: 1px solid {paint_css('border.subtle')}; border-radius: {Metrics.BORDER_RADIUS_SM}px; }}"
            f"QTreeWidget::item {{ padding: 4px; border-bottom: 1px solid {paint_css('border.subtle')}; }}"
            f"QTreeWidget::item:selected {{ background: {paint_css('table.row.selected_fill')}; }}"
            f"QHeaderView::section {{ background: {paint_css('surface.inset')}; color: {paint_css('text.secondary')}; "
            f"border: none; border-bottom: 1px solid {paint_css('border.default')}; padding: 5px; font-weight: 600; }}",
        )

    def _choose_json(self) -> None:
        initial = str(self._json_path.parent) if self._json_path else ""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open iTunesDB byte-walk JSON",
            initial,
            "Byte-walk JSON (*.json);;All files (*)",
        )
        if path:
            self.open_byte_walk_json(path)

    def _choose_itunesdb(self) -> None:
        source, _ = QFileDialog.getOpenFileName(
            self,
            "Choose iTunesDB to export",
            self._default_itunesdb_path,
            "iTunes database (iTunesDB iTunesCDB);;All files (*)",
        )
        if not source:
            return
        default_destination = str(Path(source).with_suffix(".byte-walk.json"))
        destination, _ = QFileDialog.getSaveFileName(
            self,
            "Save iTunesDB byte-walk JSON",
            default_destination,
            "Byte-walk JSON (*.json)",
        )
        if destination:
            self.generate_byte_walk(source, destination)

    def generate_byte_walk(self, source: str | Path, destination: str | Path) -> None:
        """Generate a byte-walk file off the main Qt thread."""
        self._set_busy("Generating byte-walk JSON; this can be large…")
        worker = Worker(export_forensic_json, str(source), str(destination))
        self._export_worker = worker
        worker.signals.result.connect(self._on_export_complete)
        worker.signals.error.connect(self._on_worker_error)
        worker.signals.finished.connect(lambda active=worker: self._reap_worker("_export_worker", active))
        ThreadPoolSingleton.get_instance().start(worker)

    def open_byte_walk_json(self, path: str | Path) -> None:
        """Index a document in the background, keeping nested bytes on disk."""
        self._json_path = Path(path)
        self._entries = []
        self.results_tree.clear()
        self.chunk_tree.clear()
        self.chunk_label.setText("Indexing byte-walk JSON…")
        self._set_busy(f"Indexing {self._json_path.name} without loading its byte tree into memory…")
        worker = Worker(index_byte_walk_json, self._json_path)
        self._index_worker = worker
        worker.signals.result.connect(self._on_index_complete)
        worker.signals.error.connect(self._on_worker_error)
        worker.signals.finished.connect(lambda active=worker: self._reap_worker("_index_worker", active))
        ThreadPoolSingleton.get_instance().start(worker)

    @pyqtSlot(object)
    def _on_export_complete(self, output: object) -> None:
        self._export_worker = None
        self.open_byte_walk_json(str(output))

    @pyqtSlot(object)
    def _on_index_complete(self, result: object) -> None:
        self._index_worker = None
        self._entries = (
            [entry for entry in result if isinstance(entry, ByteWalkChunkIndexEntry)]
            if isinstance(result, list)
            else []
        )
        self._set_idle(f"Indexed {len(self._entries):,} chunks. Search by caption, chunk type, or file offset.")
        self._refresh_results()

    @pyqtSlot(tuple)
    def _on_worker_error(self, payload: tuple) -> None:
        self._set_idle("The requested forensic operation failed.")
        message = str(payload[1]) if len(payload) > 1 else "Unknown error"
        QMessageBox.critical(self, "Byte-Walk Inspector", message)

    def _reap_worker(self, attribute: str, worker: Worker) -> None:
        if getattr(self, attribute, None) is worker:
            setattr(self, attribute, None)

    def _set_busy(self, text: str) -> None:
        self.status_label.setText(text)
        self.open_button.setEnabled(False)
        self.generate_button.setEnabled(False)

    def _set_idle(self, text: str) -> None:
        self.status_label.setText(text)
        self.open_button.setEnabled(True)
        self.generate_button.setEnabled(True)

    def _refresh_results(self) -> None:
        query = self.search_input.text().strip().lower()
        if query:
            matches = [entry for entry in self._entries if query in self._searchable_text(entry)]
        else:
            matches = self._entries[:_RESULT_LIMIT]
        shown = matches[:_RESULT_LIMIT]
        self.results_tree.clear()
        for entry in shown:
            item = QTreeWidgetItem(
                [
                    entry.chunk_type,
                    entry.caption,
                    f"0x{entry.file_offset:X}",
                ],
            )
            item.setData(0, _ENTRY_ROLE, entry)
            item.setToolTip(1, f"{entry.caption}\n{_format_byte_count(entry.byte_length)}")
            self.results_tree.addTopLevelItem(item)
        suffix = "" if len(matches) <= _RESULT_LIMIT else f"; showing first {_RESULT_LIMIT:,}"
        self.results_summary.setText(f"{len(matches):,} matching chunks{suffix}")

    @staticmethod
    def _searchable_text(entry: ByteWalkChunkIndexEntry) -> str:
        return " ".join(
            (
                entry.chunk_type,
                entry.caption,
                f"0x{entry.file_offset:x}",
                str(entry.file_offset),
            ),
        ).lower()

    def _load_selected_result(self) -> None:
        selected = self.results_tree.selectedItems()
        if not selected or self._json_path is None:
            return
        entry = selected[0].data(0, _ENTRY_ROLE)
        if not isinstance(entry, ByteWalkChunkIndexEntry):
            return
        if entry.file_offset == 0 and len(self._entries) > 1:
            self.chunk_label.setText("The root contains the whole database. Search for a focused chunk before loading it.")
            return
        self.chunk_tree.clear()
        self.chunk_label.setText(f"Loading {entry.caption}…")
        worker = Worker(load_indexed_chunk, self._json_path, entry)
        self._chunk_worker = worker
        worker.signals.result.connect(self._on_chunk_complete)
        worker.signals.error.connect(self._on_worker_error)
        worker.signals.finished.connect(lambda active=worker: self._reap_worker("_chunk_worker", active))
        ThreadPoolSingleton.get_instance().start(worker)

    @pyqtSlot(object)
    def _on_chunk_complete(self, result: object) -> None:
        self._chunk_worker = None
        if not isinstance(result, dict):
            return
        chunk = result
        self.chunk_label.setText(
            f"{chunk.get('chunk', 'chunk')} — {chunk.get('caption', '')} · "
            f"file {chunk.get('file_offset', '')} · {_format_byte_count(int(chunk.get('byte_length', 0)))}",
        )
        self._add_chunk_root(chunk)

    def _add_chunk_root(self, chunk: dict[str, Any]) -> None:
        self.chunk_tree.clear()
        root = QTreeWidgetItem(
            [
                "0x0000",
                str(chunk.get("byte_length", "")),
                f"{chunk.get('chunk', 'chunk')} — {chunk.get('caption', '')}",
                "chunk",
                "",
            ],
        )
        root.setData(0, _ENTRY_ROLE, {"chunk": chunk})
        root.setData(0, _POPULATED_ROLE, True)
        self.chunk_tree.addTopLevelItem(root)
        self._add_chunk_entries(root, chunk)
        root.setExpanded(True)

    def _populate_expanded_chunk(self, item: QTreeWidgetItem) -> None:
        if item.data(0, _POPULATED_ROLE):
            return
        entry = item.data(0, _ENTRY_ROLE)
        if not isinstance(entry, dict) or not isinstance(entry.get("chunk"), dict):
            return
        item.takeChildren()
        self._add_chunk_entries(item, entry["chunk"])
        item.setData(0, _POPULATED_ROLE, True)

    def _add_chunk_entries(self, parent: QTreeWidgetItem, chunk: dict[str, Any]) -> None:
        for entry in chunk.get("bytes", []):
            if not isinstance(entry, dict):
                continue
            if isinstance(entry.get("chunk"), dict):
                nested = entry["chunk"]
                item = QTreeWidgetItem(
                    [
                        str(entry.get("at", "")),
                        str(entry.get("byte_length", "")),
                        f"{nested.get('chunk', 'chunk')} — {nested.get('caption', '')}",
                        "nested chunk",
                        "",
                    ],
                )
                item.setData(0, _ENTRY_ROLE, entry)
                item.addChild(QTreeWidgetItem(["", "", "Expand to inspect", "", ""]))
            else:
                field_or_status = str(entry.get("field") or entry.get("status") or "bytes")
                detail = _short_value(entry.get("value"))
                if entry.get("note"):
                    detail = f"{detail} — {entry['note']}".strip(" —")
                item = QTreeWidgetItem(
                    [
                        str(entry.get("at", "")),
                        str(entry.get("byte_length", "")),
                        field_or_status,
                        detail,
                        _short_value(entry.get("hex", ""), limit=96),
                    ],
                )
                item.setData(0, _ENTRY_ROLE, entry)
                item.setToolTip(4, str(entry.get("hex", "")))
            parent.addChild(item)

    def _select_byte_entry(self) -> None:
        selected = self.chunk_tree.selectedItems()
        if not selected:
            return
        entry = selected[0].data(0, _ENTRY_ROLE)
        if not isinstance(entry, dict) or "hex" not in entry:
            return
        self.hex_input.blockSignals(True)
        self.hex_input.setPlainText(str(entry["hex"]))
        self.hex_input.blockSignals(False)
        self._refresh_interpretations()

    def _refresh_interpretations(self) -> None:
        self.interpretation_tree.clear()
        try:
            values = hex_interpretations(self.hex_input.toPlainText())
        except ValueError as exc:
            self.interpretation_tree.addTopLevelItem(QTreeWidgetItem(["Input error", str(exc)]))
            return
        for label, value in values.items():
            item = QTreeWidgetItem([label, value])
            item.setToolTip(1, value)
            self.interpretation_tree.addTopLevelItem(item)
