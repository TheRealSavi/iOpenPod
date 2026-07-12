"""Manage Storage page for iPod database byte breakdowns."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from iopenpod.application.database_storage import DatabaseStorageReport, StorageBreakdownNode

from ..styles import (
    FONT_FAMILY,
    MONO_FONT_FAMILY,
    Colors,
    Metrics,
    back_btn_css,
)
from .formatters import format_size


def _label_css(color: str) -> str:
    return f"color: {color}; background: transparent; border: none;"


class DatabaseStorageBrowser(QWidget):
    """Tree view of database storage usage."""

    closed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._report: DatabaseStorageReport | None = None
        self._max_database_bytes = 0
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(14)

        header = QFrame(self)
        header.setStyleSheet("background: transparent; border: none;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(10)

        self.back_button = QPushButton("\u2190")
        self.back_button.setObjectName("databaseStorageBackButton")
        self.back_button.setFont(QFont(FONT_FAMILY, Metrics.FONT_LG))
        self.back_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back_button.setAccessibleName("Back")
        self.back_button.setToolTip("Back")
        self.back_button.setStyleSheet(back_btn_css())
        self.back_button.clicked.connect(self.closed.emit)
        header_layout.addWidget(self.back_button, 0, Qt.AlignmentFlag.AlignVCenter)

        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(1)

        title = QLabel("Database Storage Usage")
        title.setFont(QFont(FONT_FAMILY, Metrics.FONT_XXL, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; background: transparent;")
        title_col.addWidget(title)

        self.summary_label = QLabel("")
        self.summary_label.setObjectName("databaseStorageSummary")
        self.summary_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.summary_label.setStyleSheet(
            f"color: {Colors.TEXT_TERTIARY}; background: transparent;"
        )
        self.summary_label.setWordWrap(True)
        self.summary_label.setTextFormat(Qt.TextFormat.PlainText)
        title_col.addWidget(self.summary_label)

        header_layout.addLayout(title_col, 1)
        root.addWidget(header)

        root.addWidget(self._build_explanation())

        self.tree = QTreeWidget(self)
        self.tree.setObjectName("databaseStorageTree")
        self.tree.setHeaderLabels(["Component", "Size", "Limit", "Details"])
        self.tree.setRootIsDecorated(True)
        self.tree.setIndentation(18)
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(False)
        self.tree.setAllColumnsShowFocus(True)
        self.tree.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.tree.setStyleSheet(f"""
            QTreeWidget {{
                background: {Colors.SHADOW_LIGHT};
                alternate-background-color: {Colors.SURFACE};
                color: {Colors.TEXT_PRIMARY};
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-radius: {Metrics.BORDER_RADIUS_SM}px;
                outline: none;
            }}
            QTreeWidget::item {{
                padding: 5px 6px;
                border-bottom: 1px solid {Colors.BORDER_SUBTLE};
            }}
            QTreeWidget::item:selected {{
                background: {Colors.SELECTION};
                color: {Colors.TEXT_PRIMARY};
            }}
            QTreeWidget::item:hover {{
                background: {Colors.SURFACE_HOVER};
            }}
            QHeaderView::section {{
                background: {Colors.SURFACE_ALT};
                color: {Colors.TEXT_SECONDARY};
                border: none;
                border-bottom: 1px solid {Colors.BORDER};
                padding: 6px 8px;
                font-weight: 600;
                font-size: {Metrics.FONT_LG}pt;
            }}
        """)
        header_view = self.tree.header()
        if header_view is not None:
            header_view.setStretchLastSection(True)
            header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
            header_view.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
            header_view.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.tree, 1)

    def _build_explanation(self) -> QFrame:
        panel = QFrame(self)
        panel.setObjectName("databaseStorageExplanation")
        panel.setStyleSheet(
            f"QFrame#databaseStorageExplanation {{"
            f"background:{Colors.SURFACE};"
            f"border:1px solid {Colors.ACCENT_BORDER};"
            f"border-radius:{Metrics.BORDER_RADIUS_MD}px;"
            f"}}"
            f"QFrame#databaseStorageExplanation:hover {{"
            f"background:{Colors.SURFACE_ALT};"
            f"}}"
        )

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(9)

        help_mark = QLabel("?", panel)
        help_mark.setObjectName("databaseStorageExplanationMark")
        help_mark.setFixedSize(28, 28)
        help_mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        help_mark.setFont(QFont(MONO_FONT_FAMILY, Metrics.FONT_MD, QFont.Weight.DemiBold))
        help_mark.setStyleSheet(
            f"color:{Colors.ACCENT_LIGHT};"
            f"background:{Colors.ACCENT_MUTED};"
            f"border:1px solid {Colors.ACCENT_BORDER};"
            f"border-radius:{Metrics.BORDER_RADIUS_SM}px;"
        )
        header.addWidget(help_mark)

        title_stack = QVBoxLayout()
        title_stack.setContentsMargins(0, 0, 0, 0)
        title_stack.setSpacing(1)

        title = QLabel("What's this for?", panel)
        title.setObjectName("databaseStorageExplanationTitle")
        title.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD, QFont.Weight.DemiBold))
        title.setStyleSheet(_label_css(Colors.TEXT_PRIMARY))
        title_stack.addWidget(title)

        profile = QLabel("iTunesDB, iTunesCDB, and SQLite files", panel)
        profile.setObjectName("databaseStorageExplanationProfile")
        profile.setFont(QFont(MONO_FONT_FAMILY, Metrics.FONT_XS))
        profile.setStyleSheet(_label_css(Colors.TEXT_TERTIARY))
        title_stack.addWidget(profile)

        header.addLayout(title_stack, 1)
        layout.addLayout(header)

        compact = QLabel(
            "The iPod must load this entire file into RAM for the iPod to function. "
            "Slimming the database by removing unnecessary data can allow for more tracks to be stored.",
            panel,
        )
        compact.setObjectName("databaseStorageExplanationSummary")
        compact.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM, QFont.Weight.DemiBold))
        compact.setStyleSheet(_label_css(Colors.TEXT_PRIMARY))
        compact.setWordWrap(True)
        compact.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(compact)

        # body = QLabel(
        #     "On most iPods all metadata is stored in the iTunesDB file. Some iPods instead use an SQLite DB. "
        #     "SQLite DB devices will have an iTunesDB or iTunesCDB file, but it is mostly unused for the iPod.",
        #     panel,
        # )
        # body.setObjectName("databaseStorageExplanationBody")
        # body.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        # body.setStyleSheet(_label_css(Colors.TEXT_SECONDARY))
        # body.setWordWrap(True)
        # body.setTextFormat(Qt.TextFormat.PlainText)
        # layout.addWidget(body)

        return panel

    def load_report(
        self,
        report: DatabaseStorageReport,
        *,
        max_database_bytes: int = 0,
    ) -> None:
        """Render a new storage report."""
        self._report = report
        self._max_database_bytes = max(0, int(max_database_bytes or 0))
        self._refresh_summary()
        self.tree.clear()
        if not report.roots:
            self.tree.addTopLevelItem(QTreeWidgetItem(["No database data", "", "", report.note]))
            return

        for node in report.roots:
            self.tree.addTopLevelItem(self._item_for_node(node))
        self.tree.expandAll()

    def clear(self) -> None:
        self._report = None
        self._max_database_bytes = 0
        self.summary_label.setText("")
        self.tree.clear()

    def _refresh_summary(self) -> None:
        report = self._report
        if report is None:
            self.summary_label.setText("")
            return

        parts = [self._summary_status(report)]
        if report.note:
            parts.append(report.note)
        self.summary_label.setText(" · ".join(parts))

    def _summary_status(self, report: DatabaseStorageReport) -> str:
        size = format_size(report.logical_bytes) or "0 B"
        if report.mode == "sqlite":
            return f"SQLite library · {size} across .itdb files"

        if self._max_database_bytes:
            limit = format_size(self._max_database_bytes) or "0 B"
            percent = (max(0, report.logical_bytes) / self._max_database_bytes) * 100
            status = f" iTunesDB · {size} of {limit} RAM budget ({percent:.1f}%)"
        else:
            status = f" iTunesDB · {size} "

        if report.physical_bytes and report.physical_bytes != report.logical_bytes:
            physical = format_size(report.physical_bytes) or "0 B"
            status += f" · {physical} compressed on disk"
        return status

    def _item_for_node(self, node: StorageBreakdownNode) -> QTreeWidgetItem:
        item = QTreeWidgetItem([
            node.label,
            format_size(node.bytes_used) or "0 B",
            self._percent_text(node.bytes_used),
            node.detail,
        ])
        item.setData(0, Qt.ItemDataRole.UserRole, node.kind)
        item.setData(1, Qt.ItemDataRole.UserRole, node.bytes_used)
        if node.kind in {"mhod", "sqlite_table"}:
            item.setFont(0, QFont(FONT_FAMILY, Metrics.FONT_MD, QFont.Weight.DemiBold))
        item.setFont(1, QFont(MONO_FONT_FAMILY, Metrics.FONT_SM))
        item.setFont(2, QFont(MONO_FONT_FAMILY, Metrics.FONT_SM))
        for child in node.children:
            item.addChild(self._item_for_node(child))
        return item

    def _percent_text(self, bytes_used: int) -> str:
        denominator = self._max_database_bytes
        if denominator <= 0:
            report = self._report
            denominator = report.logical_bytes if report else 0
        if denominator <= 0:
            return "—"
        return f"{(max(0, bytes_used) / denominator) * 100:.1f}%"
