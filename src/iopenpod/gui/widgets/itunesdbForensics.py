"""Interactive generator and inspector for iTunesDB byte-walk JSON files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt, QTimer, pyqtSlot
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
    QProgressBar,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from iopenpod.application.runtime import ThreadPoolSingleton, Worker
from iopenpod.itunesdb_parser.byte_walk import (
    ByteWalkChunkCache,
    ByteWalkChunkIndexEntry,
    ByteWalkChunkLoad,
    hex_interpretations,
    index_byte_walk_json,
)
from iopenpod.itunesdb_parser.forensics import export_forensic_json

from ..styles import (
    FONT_FAMILY,
    MONO_FONT_FAMILY,
    Metrics,
    accent_btn_css,
    button_css,
    input_css,
    paint_css,
    panel_css,
    progress_bar_css,
)

_ENTRY_ROLE = int(Qt.ItemDataRole.UserRole)
_POPULATED_ROLE = _ENTRY_ROLE + 1
_RESULT_RENDER_BATCH = 250
_CHUNK_RENDER_BATCH = 250


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


def _display_value(value: Any) -> str:
    """Render a JSON value without truncating the inspector's source data."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class ITunesDBForensicsDialog(QDialog):
    """Generate and inspect enormous byte-walk JSON files without UI stalls."""

    def __init__(self, default_itunesdb_path: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._default_itunesdb_path = default_itunesdb_path
        self._json_path: Path | None = None
        self._entries: list[ByteWalkChunkIndexEntry] = []
        self._chunk_cache = ByteWalkChunkCache()
        self._index_worker: Worker | None = None
        self._chunk_worker: Worker | None = None
        self._export_worker: Worker | None = None
        self._chunk_request_id = 0
        self._active_operations: dict[str, str] = {}
        self._pending_result_entries: list[ByteWalkChunkIndexEntry] = []
        self._result_render_offset = 0
        self._result_render_timer = QTimer(self)
        self._result_render_timer.setSingleShot(True)
        self._result_render_timer.timeout.connect(self._render_next_results_batch)
        self._pending_chunk_entries: list[Any] = []
        self._chunk_render_parent: QTreeWidgetItem | None = None
        self._chunk_render_offset = 0
        self._chunk_render_operation = "chunk"
        self._chunk_render_complete_text = ""
        self._chunk_render_timer = QTimer(self)
        self._chunk_render_timer.setSingleShot(True)
        self._chunk_render_timer.timeout.connect(self._render_next_chunk_entries_batch)
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

        self.loading_indicator = QProgressBar(self)
        self.loading_indicator.setObjectName("itunesdbForensicsLoading")
        self.loading_indicator.setRange(0, 0)
        self.loading_indicator.setTextVisible(False)
        self.loading_indicator.setFixedHeight(5)
        self.loading_indicator.setStyleSheet(
            progress_bar_css(height=5, radius=2, chunk=paint_css("data.accent.fill")),
        )
        self.loading_indicator.hide()
        root.addWidget(self.loading_indicator)

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
        self.results_tree.setWordWrap(False)
        self.results_tree.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.results_tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.results_tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.results_tree.setUniformRowHeights(True)
        self.results_tree.itemSelectionChanged.connect(self._load_selected_result)
        self._style_tree(self.results_tree)
        results_header = self.results_tree.header()
        if results_header is not None:
            results_header.setStretchLastSection(False)
            results_header.setMinimumSectionSize(80)
            results_header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
            self.results_tree.setColumnWidth(0, 84)
            self.results_tree.setColumnWidth(1, 220)
            self.results_tree.setColumnWidth(2, 110)
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

        hierarchy = QFrame(panel)
        hierarchy.setObjectName("itunesdbForensicsHierarchy")
        hierarchy.setStyleSheet(
            panel_css(
                "itunesdbForensicsHierarchy",
                bg=paint_css("surface.inset"),
                border=f"1px solid {paint_css('border.subtle')}",
                radius=Metrics.BORDER_RADIUS_SM,
            ),
        )
        hierarchy_layout = QHBoxLayout(hierarchy)
        hierarchy_layout.setContentsMargins(10, 7, 10, 7)
        hierarchy_layout.setSpacing(8)
        hierarchy_heading = QLabel("Hierarchy", hierarchy)
        hierarchy_heading.setFont(QFont(FONT_FAMILY, Metrics.FONT_XS, QFont.Weight.DemiBold))
        hierarchy_heading.setStyleSheet(f"color: {paint_css('text.tertiary')};")
        hierarchy_layout.addWidget(hierarchy_heading)
        self.hierarchy_path_label = QLabel("Select a chunk to see its hierarchy.", hierarchy)
        self.hierarchy_path_label.setObjectName("itunesdbForensicsHierarchyPath")
        self.hierarchy_path_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.hierarchy_path_label.setStyleSheet(f"color: {paint_css('text.secondary')};")
        self.hierarchy_path_label.setWordWrap(True)
        hierarchy_layout.addWidget(self.hierarchy_path_label, 1)
        layout.addWidget(hierarchy)

        self.chunk_tree = QTreeWidget(panel)
        self.chunk_tree.setObjectName("itunesdbForensicsChunkTree")
        self.chunk_tree.setHeaderLabels(["At", "Bytes", "Meaning", "Value / status", "Hex"])
        self.chunk_tree.setAlternatingRowColors(True)
        self.chunk_tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.chunk_tree.setUniformRowHeights(True)
        self.chunk_tree.setWordWrap(False)
        self.chunk_tree.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.chunk_tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.chunk_tree.itemExpanded.connect(self._populate_expanded_chunk)
        self.chunk_tree.itemSelectionChanged.connect(self._select_byte_entry)
        chunk_scrollbar = self.chunk_tree.verticalScrollBar()
        if chunk_scrollbar is not None:
            chunk_scrollbar.valueChanged.connect(self._update_hierarchy_from_viewport)
        self._style_tree(self.chunk_tree)
        chunk_header = self.chunk_tree.header()
        if chunk_header is not None:
            chunk_header.setStretchLastSection(False)
            chunk_header.setMinimumSectionSize(80)
            chunk_header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
            for column, width in enumerate((92, 76, 210, 300, 220)):
                self.chunk_tree.setColumnWidth(column, width)
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
        self.hex_input.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.hex_input.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
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
        self.interpretation_tree.setWordWrap(False)
        self.interpretation_tree.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.interpretation_tree.setMinimumWidth(430)
        self.interpretation_tree.setMaximumHeight(190)
        self.interpretation_tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.interpretation_tree.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._style_tree(self.interpretation_tree)
        interpretation_header = self.interpretation_tree.header()
        if interpretation_header is not None:
            interpretation_header.setStretchLastSection(False)
            interpretation_header.setMinimumSectionSize(110)
            interpretation_header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
            self.interpretation_tree.setColumnWidth(0, 190)
            self.interpretation_tree.setColumnWidth(1, 330)
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
        self._set_results_interaction_enabled(False)
        self._set_busy("Generating byte-walk JSON; this can be large…", "export")
        worker = Worker(export_forensic_json, str(source), str(destination))
        self._export_worker = worker
        worker.signals.result.connect(self._on_export_complete)
        worker.signals.error.connect(lambda payload: self._on_worker_error(payload, "export"))
        worker.signals.finished.connect(lambda active=worker: self._reap_worker("_export_worker", active))
        ThreadPoolSingleton.get_instance().start(worker)

    def open_byte_walk_json(self, path: str | Path) -> None:
        """Index a document in the background, keeping nested bytes on disk."""
        if self._chunk_worker is not None:
            self._chunk_worker.cancel()
        self._active_operations.pop("chunk", None)
        self._active_operations.pop("chunk_tree", None)
        self._chunk_request_id += 1
        self._chunk_cache.clear()
        self._result_render_timer.stop()
        self._chunk_render_timer.stop()
        self._pending_result_entries = []
        self._result_render_offset = 0
        self._pending_chunk_entries = []
        self._chunk_render_parent = None
        self._json_path = Path(path)
        self._entries = []
        self.results_tree.clear()
        self.chunk_tree.clear()
        self._clear_hierarchy_context()
        self.chunk_label.setText("Indexing byte-walk JSON…")
        self._set_results_interaction_enabled(False)
        self._set_busy(f"Indexing {self._json_path.name} without loading its byte tree into memory…", "index")
        worker = Worker(index_byte_walk_json, self._json_path)
        self._index_worker = worker
        worker.signals.result.connect(self._on_index_complete)
        worker.signals.error.connect(lambda payload: self._on_worker_error(payload, "index"))
        worker.signals.finished.connect(lambda active=worker: self._reap_worker("_index_worker", active))
        ThreadPoolSingleton.get_instance().start(worker)

    @pyqtSlot(object)
    def _on_export_complete(self, output: object) -> None:
        self._export_worker = None
        self._set_idle("Generated byte-walk JSON.", "export")
        self.open_byte_walk_json(str(output))

    @pyqtSlot(object)
    def _on_index_complete(self, result: object) -> None:
        self._index_worker = None
        self._entries = (
            [entry for entry in result if isinstance(entry, ByteWalkChunkIndexEntry)]
            if isinstance(result, list)
            else []
        )
        self._set_idle(
            f"Indexed {len(self._entries):,} chunks. Search by caption, chunk type, or file offset.",
            "index",
        )
        self._set_results_interaction_enabled(True)
        self._refresh_results()

    def _on_worker_error(self, payload: tuple, operation: str) -> None:
        self._set_idle("The requested forensic operation failed.", operation)
        if operation in {"export", "index"}:
            self._set_results_interaction_enabled(True)
        message = str(payload[1]) if len(payload) > 1 else "Unknown error"
        QMessageBox.critical(self, "Byte-Walk Inspector", message)

    def _reap_worker(self, attribute: str, worker: Worker) -> None:
        if getattr(self, attribute, None) is worker:
            setattr(self, attribute, None)

    def _set_busy(self, text: str, operation: str = "manual") -> None:
        self._active_operations[operation] = text
        self._refresh_loading_state(text)

    def _set_idle(self, text: str, operation: str = "manual") -> None:
        self._active_operations.pop(operation, None)
        self._refresh_loading_state(text)

    def _refresh_loading_state(self, completed_text: str) -> None:
        active_operation = next(reversed(self._active_operations), None)
        active_text = (
            self._active_operations[active_operation]
            if active_operation is not None
            else None
        )
        self.status_label.setText(active_text or completed_text)
        is_busy = active_text is not None
        self.loading_indicator.setVisible(is_busy)
        self.open_button.setEnabled(not is_busy)
        self.generate_button.setEnabled(not is_busy)

    def _set_results_interaction_enabled(self, enabled: bool) -> None:
        self.search_input.setEnabled(enabled)
        self.results_tree.setEnabled(enabled)

    def _refresh_results(self) -> None:
        self._result_render_timer.stop()
        query = self.search_input.text().strip().lower()
        if query:
            matches = [entry for entry in self._entries if query in self._searchable_text(entry)]
        else:
            matches = self._entries
        self.results_tree.clear()
        self._pending_result_entries = matches
        self._result_render_offset = 0
        self._render_next_results_batch()

    def _render_next_results_batch(self) -> None:
        """Add all search results in event-loop batches to keep scrolling responsive."""
        start = self._result_render_offset
        stop = min(start + _RESULT_RENDER_BATCH, len(self._pending_result_entries))
        if start < stop:
            items: list[QTreeWidgetItem] = []
            for entry in self._pending_result_entries[start:stop]:
                item = QTreeWidgetItem(
                    [
                        entry.chunk_type,
                        entry.caption,
                        f"0x{entry.file_offset:X}",
                    ],
                )
                item.setData(0, _ENTRY_ROLE, entry)
                item.setToolTip(1, f"{entry.caption}\n{_format_byte_count(entry.byte_length)}")
                items.append(item)
            self.results_tree.setUpdatesEnabled(False)
            self.results_tree.addTopLevelItems(items)
            self.results_tree.setUpdatesEnabled(True)
            self._result_render_offset = stop

        total = len(self._pending_result_entries)
        if self._result_render_offset < total:
            self.results_summary.setText(
                f"{total:,} matching chunks — showing {self._result_render_offset:,}; loading the remainder…",
            )
            self._result_render_timer.start(0)
            return
        self.results_summary.setText(f"{total:,} matching chunks")

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
        if self._chunk_worker is not None:
            self._chunk_worker.cancel()
        self._chunk_request_id += 1
        request_id = self._chunk_request_id
        self._chunk_render_timer.stop()
        self._pending_chunk_entries = []
        self._chunk_render_parent = None
        self.chunk_tree.clear()
        self._clear_hierarchy_context()
        self.chunk_label.setText(f"Loading {entry.caption}…")
        self._set_busy(f"Loading {entry.caption} for inspection…", "chunk")
        worker = Worker(self._chunk_cache.load, self._json_path, entry)
        self._chunk_worker = worker
        worker.signals.result.connect(
            lambda result, active_request_id=request_id: self._on_chunk_complete(result, active_request_id),
        )
        worker.signals.error.connect(
            lambda payload, active_request_id=request_id: self._on_chunk_error(payload, active_request_id),
        )
        worker.signals.finished.connect(lambda active=worker: self._reap_worker("_chunk_worker", active))
        ThreadPoolSingleton.get_instance().start(worker)

    def _on_chunk_complete(self, result: object, request_id: int | None = None) -> None:
        if request_id is not None and request_id != self._chunk_request_id:
            return
        self._chunk_worker = None
        was_cached = False
        if isinstance(result, ByteWalkChunkLoad):
            chunk = result.chunk
            was_cached = result.was_cached
        else:
            chunk = result
        if not isinstance(chunk, dict):
            self._set_idle("The selected chunk could not be loaded.", "chunk")
            return
        self.chunk_label.setText(
            f"{chunk.get('chunk', 'chunk')} — {chunk.get('caption', '')} · "
            f"file {chunk.get('file_offset', '')} · {_format_byte_count(int(chunk.get('byte_length', 0)))}",
        )
        cache_note = " from cache" if was_cached else ""
        self._add_chunk_root(chunk, f"Loaded {chunk.get('caption', 'chunk')}{cache_note}.")

    def _on_chunk_error(self, payload: tuple, request_id: int) -> None:
        if request_id != self._chunk_request_id:
            return
        self._chunk_worker = None
        self._on_worker_error(payload, "chunk")

    def _add_chunk_root(self, chunk: dict[str, Any], completion_text: str = "Loaded chunk.") -> None:
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
        root.setExpanded(True)
        self._set_hierarchy_context(root)
        self._start_chunk_entry_render(root, chunk, "chunk", completion_text)

    def _populate_expanded_chunk(self, item: QTreeWidgetItem) -> None:
        if item.data(0, _POPULATED_ROLE):
            return
        self._set_hierarchy_context(item)
        entry = item.data(0, _ENTRY_ROLE)
        if not isinstance(entry, dict) or not isinstance(entry.get("chunk"), dict):
            return
        item.takeChildren()
        item.setData(0, _POPULATED_ROLE, True)
        nested = entry["chunk"]
        caption = str(nested.get("caption", nested.get("chunk", "chunk")))
        self._set_busy(f"Loading {caption} byte spans…", "chunk_tree")
        self._start_chunk_entry_render(item, nested, "chunk_tree", f"Expanded {caption}.")

    def _start_chunk_entry_render(
        self,
        parent: QTreeWidgetItem,
        chunk: dict[str, Any],
        operation: str,
        completion_text: str,
    ) -> None:
        """Render a chunk's spans in small event-loop batches."""
        self._chunk_render_timer.stop()
        raw_entries = chunk.get("bytes", [])
        self._pending_chunk_entries = raw_entries if isinstance(raw_entries, list) else []
        self._chunk_render_parent = parent
        self._chunk_render_offset = 0
        self._chunk_render_operation = operation
        self._chunk_render_complete_text = completion_text
        self.chunk_tree.setEnabled(False)
        self._render_next_chunk_entries_batch()

    def _render_next_chunk_entries_batch(self) -> None:
        """Populate enough byte spans to remain responsive for large chunks."""
        parent = self._chunk_render_parent
        if parent is None or parent.treeWidget() is not self.chunk_tree:
            return
        start = self._chunk_render_offset
        stop = min(start + _CHUNK_RENDER_BATCH, len(self._pending_chunk_entries))
        if start < stop:
            self.chunk_tree.setUpdatesEnabled(False)
            for entry in self._pending_chunk_entries[start:stop]:
                if isinstance(entry, dict):
                    self._add_chunk_entry(parent, entry)
            self.chunk_tree.setUpdatesEnabled(True)
            self._chunk_render_offset = stop

        total = len(self._pending_chunk_entries)
        if self._chunk_render_offset < total:
            self._set_busy(
                f"Preparing byte spans ({self._chunk_render_offset:,} of {total:,})…",
                self._chunk_render_operation,
            )
            self._chunk_render_timer.start(0)
            return
        self.chunk_tree.setEnabled(True)
        self._set_idle(self._chunk_render_complete_text, self._chunk_render_operation)

    def _add_chunk_entry(self, parent: QTreeWidgetItem, entry: dict[str, Any]) -> None:
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
            detail = _display_value(entry.get("value"))
            if entry.get("note"):
                detail = f"{detail} — {entry['note']}".strip(" —")
            item = QTreeWidgetItem(
                [
                    str(entry.get("at", "")),
                    str(entry.get("byte_length", "")),
                    field_or_status,
                    detail,
                    str(entry.get("hex", "")),
                ],
            )
            item.setData(0, _ENTRY_ROLE, entry)
            item.setToolTip(3, detail)
            item.setToolTip(4, str(entry.get("hex", "")))
        parent.addChild(item)

    def _select_byte_entry(self) -> None:
        selected = self.chunk_tree.selectedItems()
        if not selected:
            return
        item = selected[0]
        self._set_hierarchy_context(item)
        entry = item.data(0, _ENTRY_ROLE)
        if not isinstance(entry, dict) or "hex" not in entry:
            return
        self.hex_input.blockSignals(True)
        self.hex_input.setPlainText(str(entry["hex"]))
        self.hex_input.blockSignals(False)
        self._refresh_interpretations()

    def _update_hierarchy_from_viewport(self) -> None:
        """Keep the path visible while users scroll below a tree ancestor."""
        item = self.chunk_tree.itemAt(8, 8)
        if item is not None:
            self._set_hierarchy_context(item)

    def _set_hierarchy_context(self, item: QTreeWidgetItem) -> None:
        """Show the item's tree ancestry in the sticky hierarchy bar."""
        labels: list[str] = []
        current: QTreeWidgetItem | None = item
        while current is not None:
            label = current.text(2).strip()
            if label and label != "Expand to inspect":
                labels.append(label)
            current = current.parent()
        path = "  ›  ".join(reversed(labels))
        self.hierarchy_path_label.setText(path or "Select a chunk to see its hierarchy.")
        self.hierarchy_path_label.setToolTip(path)

    def _clear_hierarchy_context(self) -> None:
        self.hierarchy_path_label.setText("Select a chunk to see its hierarchy.")
        self.hierarchy_path_label.setToolTip("")

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
