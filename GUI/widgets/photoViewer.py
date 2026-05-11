from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QImage, QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..styles import FONT_FAMILY, Colors, Metrics


def pil_to_pixmap(img) -> QPixmap:
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    data = img.tobytes("raw", "RGBA")
    qimg = QImage(data, img.width, img.height, img.width * 4, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimg.copy())


class PhotoViewerPane(QFrame):
    """Shared photo preview pane used by both iPod and PC photo browsers."""
    variantSelected = pyqtSignal(int)

    def __init__(
        self,
        heading: str = "Preview",
        empty_title: str = "No photo selected",
        empty_summary: str = "Select a photo to preview it here.",
        parent=None,
    ):
        super().__init__(parent)
        self._empty_title = empty_title
        self._empty_summary = empty_summary
        self._source_pixmap = QPixmap()
        self._preview_placeholder_text = "Select a photo"
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)

        self.setStyleSheet(f"""
            QFrame#photoViewer {{
                background: {Colors.SURFACE};
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-radius: 0px;
            }}
        """)
        self.setObjectName("photoViewer")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self._heading_label = QLabel(heading, self)
        self._heading_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM, QFont.Weight.DemiBold))
        self._heading_label.setStyleSheet(
            f"color: {Colors.TEXT_TERTIARY}; background: transparent; text-transform: uppercase;"
        )
        if heading:
            layout.addWidget(self._heading_label)
        else:
            self._heading_label.hide()

        self.title_label = QLabel(empty_title, self)
        self.title_label.setWordWrap(True)
        self.title_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_PAGE_TITLE, QFont.Weight.Bold))
        self.title_label.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; background: transparent;")
        layout.addWidget(self.title_label)

        self.summary_label = QLabel(empty_summary, self)
        self.summary_label.setWordWrap(True)
        self.summary_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        self.summary_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; background: transparent;")
        layout.addWidget(self.summary_label)

        self._variant_row = QWidget(self)
        variant_row_layout = QHBoxLayout(self._variant_row)
        variant_row_layout.setContentsMargins(0, 0, 0, 0)
        variant_row_layout.setSpacing(8)

        self._variant_label = QLabel("IDs", self._variant_row)
        self._variant_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM, QFont.Weight.DemiBold))
        self._variant_label.setStyleSheet(
            f"color: {Colors.TEXT_TERTIARY}; background: transparent; text-transform: uppercase;"
        )
        variant_row_layout.addWidget(self._variant_label)

        self._variant_buttons_host = QWidget(self._variant_row)
        self._variant_buttons_layout = QHBoxLayout(self._variant_buttons_host)
        self._variant_buttons_layout.setContentsMargins(0, 0, 0, 0)
        self._variant_buttons_layout.setSpacing(6)
        variant_row_layout.addWidget(self._variant_buttons_host, 1)
        layout.addWidget(self._variant_row)
        self._variant_row.hide()
        self._variant_buttons: list[QPushButton] = []

        self._content_splitter = QSplitter(Qt.Orientation.Vertical, self)
        self._content_splitter.setChildrenCollapsible(False)
        self._content_splitter.setHandleWidth(8)
        self._content_splitter.splitterMoved.connect(lambda _pos, _index: self._apply_scaled_pixmap())
        self._content_splitter.setStyleSheet(f"""
            QSplitter::handle {{
                background: {Colors.BORDER_SUBTLE};
                margin: 2px 0;
                border-radius: 3px;
            }}
            QSplitter::handle:hover {{
                background: {Colors.BORDER};
            }}
        """)
        layout.addWidget(self._content_splitter, 1)

        preview_host = QWidget(self)
        preview_layout = QVBoxLayout(preview_host)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(0)

        self.preview_label = QLabel(preview_host)
        self.preview_label.setMinimumWidth(0)
        self.preview_label.setMinimumHeight(280)
        self.preview_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setStyleSheet(f"""
            QLabel {{
                background: transparent;
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-radius: {Metrics.BORDER_RADIUS_LG + 2}px;
                color: {Colors.TEXT_TERTIARY};
                padding: 12px;
            }}
        """)
        preview_layout.addWidget(self.preview_label, 1)
        self._content_splitter.addWidget(preview_host)

        details_host = QWidget(self)
        details_layout = QVBoxLayout(details_host)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.setSpacing(6)

        self._details_label = QLabel("Device Metadata", details_host)
        self._details_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM, QFont.Weight.DemiBold))
        self._details_label.setStyleSheet(
            f"color: {Colors.TEXT_TERTIARY}; background: transparent; text-transform: uppercase;"
        )
        details_layout.addWidget(self._details_label)

        self.meta_tree = QTreeWidget(details_host)
        self.meta_tree.setHeaderLabels(["Field", "Value"])
        self.meta_tree.setRootIsDecorated(True)
        self.meta_tree.setIndentation(14)
        self.meta_tree.setAlternatingRowColors(True)
        self.meta_tree.setUniformRowHeights(False)
        self.meta_tree.setWordWrap(True)
        self.meta_tree.setAllColumnsShowFocus(True)
        self.meta_tree.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.meta_tree.setStyleSheet(f"""
            QTreeWidget {{
                background: transparent;
                color: {Colors.TEXT_PRIMARY};
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-radius: {Metrics.BORDER_RADIUS_SM}px;
                padding: 4px;
            }}
            QTreeWidget::item {{
                padding: 3px 2px;
            }}
            QTreeWidget::item:selected {{
                background: {Colors.SURFACE_ACTIVE};
                color: {Colors.TEXT_PRIMARY};
            }}
            QHeaderView::section {{
                background: {Colors.SURFACE_RAISED};
                color: {Colors.TEXT_SECONDARY};
                border: none;
                border-bottom: 1px solid {Colors.BORDER_SUBTLE};
                padding: 6px;
                font-weight: 600;
            }}
        """)
        header = self.meta_tree.header()
        if header is not None:
            header.setStretchLastSection(True)
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        details_layout.addWidget(self.meta_tree, 1)
        self._content_splitter.addWidget(details_host)

        self._content_splitter.setStretchFactor(0, 2)
        self._content_splitter.setStretchFactor(1, 2)
        self._content_splitter.setSizes([420, 320])

        self.clearPreview()

    def clearPreview(
        self,
        title: str | None = None,
        summary: str | None = None,
        meta_lines: list[str] | None = None,
        meta_sections: list[tuple[str, list[tuple[str, str]]]] | None = None,
    ) -> None:
        self._source_pixmap = QPixmap()
        self._preview_placeholder_text = "Select a photo"
        self.preview_label.clear()
        self.preview_label.setText(self._preview_placeholder_text)
        self.title_label.setText(title or self._empty_title)
        self.summary_label.setText(summary or self._empty_summary)
        self._set_meta_content(meta_lines=meta_lines, meta_sections=meta_sections)
        self.setVariantIds([])

    def setPhoto(
        self,
        title: str,
        pixmap: QPixmap | None,
        summary: str = "",
        meta_lines: list[str] | None = None,
        meta_sections: list[tuple[str, list[tuple[str, str]]]] | None = None,
    ) -> None:
        self.title_label.setText(title or self._empty_title)
        self.summary_label.setText(summary or "")
        self._set_meta_content(meta_lines=meta_lines, meta_sections=meta_sections)
        self._preview_placeholder_text = "Preview unavailable"
        self._source_pixmap = pixmap if pixmap and not pixmap.isNull() else QPixmap()
        self._apply_scaled_pixmap()

    def setPreviewPixmap(self, pixmap: QPixmap | None) -> None:
        self._preview_placeholder_text = "Preview unavailable"
        self._source_pixmap = pixmap if pixmap and not pixmap.isNull() else QPixmap()
        self._apply_scaled_pixmap()

    def setPreviewPlaceholder(self, text: str) -> None:
        self._source_pixmap = QPixmap()
        self._preview_placeholder_text = text
        self.preview_label.clear()
        self.preview_label.setText(text)

    def _set_meta_content(
        self,
        *,
        meta_lines: list[str] | None = None,
        meta_sections: list[tuple[str, list[tuple[str, str]]]] | None = None,
    ) -> None:
        if meta_sections:
            self._populate_meta_tree(meta_sections)
            return

        fallback_rows: list[tuple[str, str]] = []
        for raw_line in (meta_lines or []):
            line = raw_line.strip()
            if not line:
                continue
            if ":" in line:
                key, value = line.split(":", 1)
                fallback_rows.append((key.strip(), value.strip()))
            else:
                fallback_rows.append(("", line))

        if fallback_rows:
            self._populate_meta_tree([("Details", fallback_rows)])
        else:
            self._populate_meta_tree([])

    def _populate_meta_tree(self, sections: list[tuple[str, list[tuple[str, str]]]]) -> None:
        self.meta_tree.clear()

        has_rows = False
        for section_title, rows in sections:
            clean_rows = [(k, v) for (k, v) in rows if v]
            if not clean_rows:
                continue

            has_rows = True
            section_item = QTreeWidgetItem([section_title, ""])
            section_font = section_item.font(0)
            section_font.setBold(True)
            section_item.setFont(0, section_font)
            section_item.setFont(1, section_font)
            section_item.setFlags(section_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)

            for key, value in clean_rows:
                row_item = QTreeWidgetItem([key, value])
                row_item.setToolTip(0, key)
                row_item.setToolTip(1, value)
                section_item.addChild(row_item)

            self.meta_tree.addTopLevelItem(section_item)
            section_item.setExpanded(True)

        if not has_rows:
            placeholder = QTreeWidgetItem(["No metadata available", ""])
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.meta_tree.addTopLevelItem(placeholder)

    def setVariantIds(
        self,
        variant_ids: list[int],
        selected_id: int | None = None,
        label: str = "IDs",
    ) -> None:
        while self._variant_buttons_layout.count():
            item = self._variant_buttons_layout.takeAt(0)
            widget = item.widget() if item else None
            if widget is not None:
                widget.deleteLater()
        self._variant_buttons.clear()

        if len(variant_ids) <= 1:
            self._variant_row.hide()
            return

        self._variant_label.setText(label)

        chip_css = f"""
            QPushButton {{
                background: {Colors.SURFACE_RAISED};
                color: {Colors.TEXT_SECONDARY};
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-radius: 999px;
                padding: 4px 10px;
            }}
            QPushButton:hover {{
                background: {Colors.SURFACE_HOVER};
                color: {Colors.TEXT_PRIMARY};
                border: 1px solid {Colors.BORDER};
            }}
            QPushButton:checked {{
                background: {Colors.SURFACE_ACTIVE};
                color: {Colors.TEXT_PRIMARY};
                border: 1px solid {Colors.ACCENT};
            }}
        """

        for index, image_id in enumerate(variant_ids):
            btn = QPushButton(str(image_id), self._variant_buttons_host)
            btn.setCheckable(True)
            btn.setAutoExclusive(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
            btn.setStyleSheet(chip_css)
            btn.clicked.connect(lambda _checked=False, image_id=image_id: self.variantSelected.emit(image_id))
            if selected_id is not None and image_id == selected_id:
                btn.setChecked(True)
            elif selected_id is None and index == 0:
                btn.setChecked(True)
            self._variant_buttons.append(btn)
            self._variant_buttons_layout.addWidget(btn)

        self._variant_buttons_layout.addStretch()
        self._variant_row.show()

    def resizeEvent(self, a0):
        super().resizeEvent(a0)
        self._apply_scaled_pixmap()

    def _apply_scaled_pixmap(self) -> None:
        if self._source_pixmap.isNull():
            self.preview_label.clear()
            self.preview_label.setText(self._preview_placeholder_text)
            return
        self.preview_label.setText("")
        target_size = self.preview_label.contentsRect().size()
        if target_size.width() <= 0 or target_size.height() <= 0:
            target_size = self.preview_label.size()
        self.preview_label.setPixmap(
            self._source_pixmap.scaled(
                target_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
