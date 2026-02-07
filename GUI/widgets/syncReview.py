"""
Sync Review Widget - GUI for reviewing and executing sync plans.

Shows the diff between PC library and iPod with:
- Tracks to add (on PC, not on iPod)
- Tracks to remove (on iPod, not on PC)
- Tracks to update (PC file changed)
- Play counts to sync back
"""

from PyQt6.QtCore import Qt, pyqtSignal, QThread
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTreeWidget, QTreeWidgetItem, QHeaderView, QProgressBar,
    QFrame, QStackedWidget, QMessageBox, QFileDialog, QDialog,
    QDialogButtonBox, QSplitter
)
from PyQt6.QtGui import QFont, QColor, QBrush
from pathlib import Path

from SyncEngine.fingerprint_diff_engine import SyncPlan, SyncItem, SyncAction, FingerprintDiffEngine
from SyncEngine.pc_library import PCLibrary

from .formatters import format_size as _format_size, format_duration_mmss as _format_duration

import os
from typing import Optional


class SyncWorker(QThread):
    """Background worker for computing sync diff."""
    progress = pyqtSignal(str, int, int, str)  # stage, current, total, message
    finished = pyqtSignal(object)  # SyncPlan
    error = pyqtSignal(str)

    def __init__(self, pc_folder: str, ipod_tracks: list, ipod_path: str = ""):
        super().__init__()
        self.pc_folder = pc_folder
        self.ipod_tracks = ipod_tracks
        self.ipod_path = ipod_path

    def run(self):
        try:
            # Initialize PC library scanner
            pc_library = PCLibrary(self.pc_folder)

            # Create fingerprint-based diff engine
            diff_engine = FingerprintDiffEngine(pc_library, self.ipod_path)

            # Compute diff with progress callback
            plan = diff_engine.compute_diff(
                self.ipod_tracks,
                progress_callback=lambda stage, cur, tot, msg: self.progress.emit(stage, cur, tot, msg)
            )

            self.finished.emit(plan)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.error.emit(str(e))


class SyncExecuteWorker(QThread):
    """Background worker for executing sync plan."""
    progress = pyqtSignal(str, int, int, str)  # stage, current, total, message
    finished = pyqtSignal(object)  # SyncResult
    error = pyqtSignal(str)

    def __init__(self, ipod_path: str, plan):
        super().__init__()
        self.ipod_path = ipod_path
        self.plan = plan

    def run(self):
        try:
            from SyncEngine.sync_executor import SyncExecutor, SyncProgress
            from SyncEngine.mapping import MappingManager
            from ..settings import get_settings

            settings = get_settings()

            # Use custom transcode cache dir if configured
            cache_dir = Path(settings.transcode_cache_dir) if settings.transcode_cache_dir else None

            # Initialize executor
            executor = SyncExecutor(self.ipod_path, cache_dir=cache_dir)

            # Load mapping file (load() returns empty MappingFile if doesn't exist)
            mapping_manager = MappingManager(self.ipod_path)
            mapping = mapping_manager.load()

            # Progress callback
            def on_progress(prog: SyncProgress):
                self.progress.emit(prog.stage, prog.current, prog.total, prog.message)

            # Execute sync — executor saves mapping internally on success
            result = executor.execute(
                plan=self.plan,
                mapping=mapping,
                progress_callback=on_progress,
                dry_run=False,
                is_cancelled=self.isInterruptionRequested,
                write_back_to_pc=settings.write_back_to_pc,
                aac_bitrate=settings.aac_bitrate,
            )

            self.finished.emit(result)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.error.emit(str(e))


class SyncItemWidget(QTreeWidgetItem):
    """Tree item representing a single sync action."""

    def __init__(self, item: SyncItem, parent=None):
        super().__init__(parent)
        self.sync_item = item
        self.setCheckState(0, Qt.CheckState.Checked)

        # Set columns based on action type
        if item.action == SyncAction.ADD_TO_IPOD:
            self._setup_add_item()
        elif item.action == SyncAction.REMOVE_FROM_IPOD:
            self._setup_remove_item()
        elif item.action == SyncAction.SYNC_PLAYCOUNT:
            self._setup_playcount_item()
        elif item.action == SyncAction.UPDATE_METADATA:
            self._setup_metadata_item()
        elif item.action == SyncAction.UPDATE_FILE:
            self._setup_file_update_item()
        elif item.action == SyncAction.UPDATE_ARTWORK:
            self._setup_artwork_item()

    def _set_tooltip(self, track=None, ipod_track=None, extra_info=""):
        """Set comprehensive tooltip for the item."""
        lines = []

        if track:
            lines.append(f"Title: {track.title or track.filename}")
            lines.append(f"Artist: {track.artist or 'Unknown'}")
            lines.append(f"Album: {track.album or 'Unknown'}")
            if track.album_artist and track.album_artist != track.artist:
                lines.append(f"Album Artist: {track.album_artist}")
            if track.year:
                lines.append(f"Year: {track.year}")
            if track.genre:
                lines.append(f"Genre: {track.genre}")
            if track.track_number:
                lines.append(f"Track: {track.track_number}")
            lines.append(f"Duration: {self._format_duration(track.duration_ms)}")
            lines.append(f"Size: {self._format_size(track.size)}")
            lines.append(f"Format: {track.extension.upper()}")
            lines.append("")
            lines.append(f"Path: {track.path}")
        elif ipod_track:
            lines.append(f"Title: {ipod_track.get('Title', 'Unknown')}")
            lines.append(f"Artist: {ipod_track.get('Artist', 'Unknown')}")
            lines.append(f"Album: {ipod_track.get('Album', 'Unknown')}")
            lines.append(f"Duration: {self._format_duration(ipod_track.get('length', 0))}")
            lines.append(f"Size: {self._format_size(ipod_track.get('size', 0))}")

        if extra_info:
            lines.append("")
            lines.append(extra_info)

        tooltip = "\n".join(lines)
        for i in range(self.columnCount()):
            self.setToolTip(i, tooltip)

    def _setup_add_item(self):
        """Setup for ADD_TO_IPOD action."""
        track = self.sync_item.pc_track
        if track:
            self.setText(1, track.title or track.filename)
            self.setText(2, track.artist or "Unknown")
            self.setText(3, track.album or "Unknown")
            self.setText(4, self._format_size(track.size))
            self.setText(5, self._format_duration(track.duration_ms))
            self._set_tooltip(track=track, extra_info="Action: Add to iPod")
            # Green tint for adds
            for i in range(6):
                self.setForeground(i, QBrush(QColor(100, 200, 100)))

    def _setup_remove_item(self):
        """Setup for REMOVE_FROM_IPOD action."""
        ipod_track = self.sync_item.ipod_track

        if ipod_track:
            self.setText(1, ipod_track.get("Title", "Unknown"))
            self.setText(2, ipod_track.get("Artist", "Unknown"))
            self.setText(3, ipod_track.get("Album", "Unknown"))
            self.setText(4, self._format_size(ipod_track.get("size", 0)))
            self.setText(5, self._format_duration(ipod_track.get("length", 0)))
            self._set_tooltip(ipod_track=ipod_track, extra_info="Action: Remove from iPod\n(File not found on PC)")
        else:
            # Orphaned mapping entry — track no longer in iTunesDB
            desc = self.sync_item.description or "Unknown track"
            self.setText(1, desc)
            self.setText(2, "—")
            self.setText(3, "—")
            self.setText(4, "—")
            dbid = self.sync_item.dbid
            tooltip = f"Orphaned mapping entry (dbid={dbid})\nTrack not found in iTunesDB or on PC."
            for i in range(6):
                self.setToolTip(i, tooltip)

        # Red tint for removes
        for i in range(6):
            self.setForeground(i, QBrush(QColor(220, 100, 100)))

    def _setup_playcount_item(self):
        """Setup for SYNC_PLAYCOUNT action."""
        track = self.sync_item.pc_track
        if track:
            self.setText(1, track.title or track.filename)
            self.setText(2, track.artist or "Unknown")
            self.setText(3, track.album or "Unknown")

            plays = self.sync_item.play_count_delta
            skips = self.sync_item.skip_count_delta
            stats_parts = []
            if plays > 0:
                stats_parts.append(f"+{plays} plays")
            if skips > 0:
                stats_parts.append(f"+{skips} skips")
            self.setText(4, " ".join(stats_parts) if stats_parts else "—")
            self.setText(5, self._format_duration(track.duration_ms))

            extra = f"Action: Sync play statistics back to PC\n\nPlays since last sync: {plays}\nSkips since last sync: {skips}"
            self._set_tooltip(track=track, extra_info=extra)

            # Blue tint for playcount sync
            for i in range(6):
                self.setForeground(i, QBrush(QColor(100, 150, 220)))

    def _setup_metadata_item(self):
        """Setup for UPDATE_METADATA action."""
        track = self.sync_item.pc_track
        if track:
            self.setText(1, track.title or track.filename)
            self.setText(2, track.artist or "Unknown")
            self.setText(3, track.album or "Unknown")

            changes = self.sync_item.metadata_changes
            changed_fields = ", ".join(changes.keys()) if changes else "metadata"
            self.setText(4, changed_fields)
            self.setText(5, self._format_duration(track.duration_ms))

            # Build tooltip with before/after for each field
            extra_lines = ["Action: Update metadata on iPod", ""]
            for field_name, (pc_val, ipod_val) in changes.items():
                extra_lines.append(f"{field_name}: \"{ipod_val}\" → \"{pc_val}\"")
            self._set_tooltip(track=track, extra_info="\n".join(extra_lines))

            # Purple tint for metadata updates
            for i in range(6):
                self.setForeground(i, QBrush(QColor(170, 130, 220)))

    def _setup_file_update_item(self):
        """Setup for UPDATE_FILE action."""
        track = self.sync_item.pc_track
        if track:
            self.setText(1, track.title or track.filename)
            self.setText(2, track.artist or "Unknown")
            self.setText(3, track.album or "Unknown")
            self.setText(4, self._format_size(track.size))
            self.setText(5, self._format_duration(track.duration_ms))
            self._set_tooltip(track=track, extra_info="Action: Source file changed, re-sync to iPod")

            # Cyan tint for file updates
            for i in range(6):
                self.setForeground(i, QBrush(QColor(100, 200, 200)))

    def _setup_artwork_item(self):
        """Setup for UPDATE_ARTWORK action."""
        track = self.sync_item.pc_track
        if track:
            self.setText(1, track.title or track.filename)
            self.setText(2, track.artist or "Unknown")
            self.setText(3, track.album or "Unknown")

            # Distinguish add / change / remove
            new_hash = self.sync_item.new_art_hash
            old_hash = self.sync_item.old_art_hash
            if not new_hash and old_hash:
                label = "Art removed"
                color = QColor(220, 120, 120)  # Red-ish for removal
                tooltip_extra = "Action: Embedded album art was removed from the PC file"
            elif new_hash and not old_hash:
                label = "Art added"
                color = QColor(130, 200, 170)  # Green-ish for addition
                tooltip_extra = "Action: New album art detected, will sync to iPod"
            else:
                label = "Art changed"
                color = QColor(200, 130, 200)  # Magenta for change
                tooltip_extra = "Action: Album art changed, re-extract to iPod"

            self.setText(4, label)
            self.setText(5, self._format_duration(track.duration_ms))
            self._set_tooltip(track=track, extra_info=tooltip_extra)

            for i in range(6):
                self.setForeground(i, QBrush(color))

    _format_size = staticmethod(_format_size)
    _format_duration = staticmethod(_format_duration)


class SyncRatingWidget(QTreeWidgetItem):
    """Tree item representing a rating sync action."""

    def __init__(self, item: SyncItem, parent=None):
        super().__init__(parent)
        self.sync_item = item
        self.setCheckState(0, Qt.CheckState.Checked)

        track = item.pc_track
        if track:
            self.setText(1, track.title or track.filename)
            self.setText(2, track.artist or "Unknown")
            self.setText(3, track.album or "Unknown")

            # Show rating change: PC/iPod → new rating
            pc_stars = self._rating_to_stars(item.pc_rating)
            ipod_stars = self._rating_to_stars(item.ipod_rating)
            new_stars = self._rating_to_stars(item.new_rating)
            rating_text = f"{pc_stars}/{ipod_stars} → {new_stars}"
            self.setText(4, rating_text)
            self.setText(5, self._format_duration(track.duration_ms))

            # Tooltip with details
            lines = [
                f"Title: {track.title or track.filename}",
                f"Artist: {track.artist or 'Unknown'}",
                f"Album: {track.album or 'Unknown'}",
                "",
                f"PC Rating: {pc_stars} ({item.pc_rating}/100)",
                f"iPod Rating: {ipod_stars} ({item.ipod_rating}/100)",
                f"New Rating: {new_stars} ({item.new_rating}/100)",
                "",
                "Action: Sync rating to both PC and iPod",
            ]
            tooltip = "\n".join(lines)
            for i in range(6):
                self.setToolTip(i, tooltip)

            # Gold/orange tint for rating sync
            for i in range(6):
                self.setForeground(i, QBrush(QColor(230, 180, 80)))

    @staticmethod
    def _rating_to_stars(rating: int) -> str:
        """Convert rating (0-100) to star display."""
        if rating <= 0:
            return "☆☆☆☆☆"
        stars = (rating + 10) // 20  # 0-20=1, 21-40=2, etc.
        stars = max(0, min(5, stars))  # Clamp to 0-5
        return "★" * stars + "☆" * (5 - stars)

    _format_duration = staticmethod(_format_duration)


class SyncCategoryHeader(QTreeWidgetItem):
    """Category header in the sync tree (Add, Remove, Update, etc.)."""

    def __init__(self, icon: str, title: str, count: int, size_bytes: int = 0):
        super().__init__()
        self.setFlags(self.flags() | Qt.ItemFlag.ItemIsAutoTristate)
        self.setCheckState(0, Qt.CheckState.Checked)

        # Format the header text
        size_str = ""
        if size_bytes > 0:
            size_str = f"+{self._format_size(size_bytes)}"
        elif size_bytes < 0:
            size_str = f"-{self._format_size(abs(size_bytes))}"

        header_text = f"{icon} {title} ({count})"
        if size_str:
            header_text += f" — {size_str}"

        self.setText(1, header_text)

        # Bold font
        font = QFont()
        font.setBold(True)
        font.setPointSize(11)
        self.setFont(1, font)

        # Expand by default
        self.setExpanded(True)

    _format_size = staticmethod(_format_size)


class DuplicateGroupHeader(QTreeWidgetItem):
    """Header for a group of duplicate files with the same fingerprint."""

    def __init__(self, fingerprint: str, tracks: list):
        super().__init__()
        self.fingerprint = fingerprint
        self.tracks = tracks

        # No checkbox for info-only section
        self.setFlags(self.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)

        # Parse fingerprint to show track info
        parts = fingerprint.split("|")
        if len(parts) >= 3:
            artist = parts[0].title() if parts[0] else "Unknown"
            album = parts[1].title() if parts[1] else "Unknown"
            title = parts[2].title() if parts[2] else "Unknown"
            self.setText(1, f"{title}")
            self.setText(2, f"{artist}")
            self.setText(3, f"{album}")
        else:
            self.setText(1, fingerprint)

        self.setText(4, f"{len(tracks)} copies")

        # Yellow/orange tint for duplicates
        for i in range(6):
            self.setForeground(i, QBrush(QColor(220, 180, 80)))

        # Bold font
        font = QFont()
        font.setBold(True)
        self.setFont(1, font)


class DuplicateItemWidget(QTreeWidgetItem):
    """Tree item representing a single file in a duplicate group."""

    def __init__(self, track, parent=None):
        super().__init__(parent)
        self.track = track

        # No checkbox for info-only section
        self.setFlags(self.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)

        # Show the path difference - just the directory part
        self.setText(1, track.filename)
        self.setText(2, self._get_short_path(track.path))
        self.setText(3, "")
        self.setText(4, self._format_size(track.size))
        self.setText(5, self._format_duration(track.duration_ms))

        # Set tooltip with full path
        tooltip = f"Full path: {track.path}"
        for i in range(6):
            self.setToolTip(i, tooltip)
            self.setForeground(i, QBrush(QColor(180, 160, 100)))

    def _get_short_path(self, path: str) -> str:
        """Get shortened directory path."""
        import os
        dir_path = os.path.dirname(path)
        # Show last 2-3 directory components
        parts = dir_path.replace("\\", "/").split("/")
        if len(parts) > 3:
            return ".../" + "/".join(parts[-3:])
        return dir_path

    _format_size = staticmethod(_format_size)
    _format_duration = staticmethod(_format_duration)


class SyncReviewWidget(QWidget):
    """
    Main widget for reviewing sync differences.

    Shows a tree view of all pending sync actions grouped by type,
    with checkboxes to include/exclude individual items.
    """

    sync_requested = pyqtSignal(object)  # Emits list[SyncItem]
    cancelled = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._plan: Optional[SyncPlan] = None
        self._cancelled = False
        self._ipod_tracks_cache: list = []
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QFrame()
        header.setStyleSheet("""
            QFrame {
                background: rgba(40, 40, 45, 200);
                border-bottom: 1px solid rgba(255,255,255,30);
            }
        """)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 12, 16, 12)

        title = QLabel("🔄 Sync Review")
        title.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        title.setStyleSheet("color: white; background: transparent;")
        header_layout.addWidget(title)

        header_layout.addStretch()

        self.summary_label = QLabel("")
        self.summary_label.setStyleSheet("color: rgba(255,255,255,150); background: transparent;")
        header_layout.addWidget(self.summary_label)

        layout.addWidget(header)

        # Stacked widget for loading/content states
        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)

        # Loading state
        loading_widget = QWidget()
        loading_layout = QVBoxLayout(loading_widget)
        loading_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.loading_label = QLabel("Scanning library...")
        self.loading_label.setStyleSheet("color: white; font-size: 14px;")
        self.loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        loading_layout.addWidget(self.loading_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedWidth(300)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background: rgba(255,255,255,20);
                border: none;
                border-radius: 4px;
                height: 8px;
            }
            QProgressBar::chunk {
                background: #409cff;
                border-radius: 4px;
            }
        """)
        loading_layout.addWidget(self.progress_bar, alignment=Qt.AlignmentFlag.AlignCenter)

        self.progress_detail = QLabel("")
        self.progress_detail.setStyleSheet("color: rgba(255,255,255,100); font-size: 11px;")
        self.progress_detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        loading_layout.addWidget(self.progress_detail)

        self.stack.addWidget(loading_widget)  # Index 0

        # Content state - tree view with details panel
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # Splitter for tree and details
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.setStyleSheet("""
            QSplitter::handle {
                background: rgba(255,255,255,20);
                height: 3px;
            }
            QSplitter::handle:hover {
                background: rgba(64, 156, 255, 100);
            }
        """)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["", "Title", "Artist", "Album", "Size", "Duration"])
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setMouseTracking(True)  # Enable hover tooltips
        self.tree.setStyleSheet("""
            QTreeWidget {
                background: rgba(30, 30, 35, 200);
                border: none;
                color: white;
                font-size: 12px;
            }
            QTreeWidget::item {
                padding: 6px 0;
                border-bottom: 1px solid rgba(255,255,255,10);
            }
            QTreeWidget::item:selected {
                background: rgba(64, 156, 255, 100);
            }
            QTreeWidget::indicator {
                width: 16px;
                height: 16px;
                margin-left: 6px;
            }
            QTreeWidget::indicator:unchecked {
                border: 2px solid rgba(255,255,255,80);
                border-radius: 3px;
                background: transparent;
            }
            QTreeWidget::indicator:checked {
                border: 2px solid #409cff;
                border-radius: 3px;
                background: #409cff;
                image: none;
            }
            QTreeWidget::indicator:indeterminate {
                border: 2px solid #409cff;
                border-radius: 3px;
                background: rgba(64, 156, 255, 80);
            }
            QTreeWidget::item:hover {
                background: rgba(255,255,255,20);
            }
            QHeaderView::section {
                background: rgba(50, 50, 55, 200);
                color: rgba(255,255,255,150);
                padding: 8px;
                border: none;
                border-bottom: 1px solid rgba(255,255,255,30);
                font-weight: bold;
            }
            QToolTip {
                background: rgba(40, 40, 45, 250);
                color: white;
                border: 1px solid rgba(255,255,255,30);
                padding: 8px;
                font-size: 11px;
            }
        """)

        # Reduce tree indentation so child checkboxes don't get clipped
        self.tree.setIndentation(12)

        # Configure columns - wider for better readability
        tree_header = self.tree.header()
        if tree_header:
            tree_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
            tree_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            tree_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
            tree_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
            tree_header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
            tree_header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
            tree_header.setMinimumSectionSize(60)
        self.tree.setColumnWidth(0, 50)   # Checkbox (needs room for indentation + indicator)
        self.tree.setColumnWidth(2, 200)  # Artist (wider)
        self.tree.setColumnWidth(3, 200)  # Album (wider)
        self.tree.setColumnWidth(5, 70)   # Duration

        # Connect selection change to update details
        self.tree.itemSelectionChanged.connect(self._update_details_panel)

        self.splitter.addWidget(self.tree)

        # Details panel (collapsible)
        self.details_panel = QFrame()
        self.details_panel.setStyleSheet("""
            QFrame {
                background: rgba(25, 25, 30, 200);
                border-top: 1px solid rgba(255,255,255,20);
            }
        """)
        self.details_panel.setMinimumHeight(80)
        self.details_panel.setMaximumHeight(150)

        details_layout = QVBoxLayout(self.details_panel)
        details_layout.setContentsMargins(16, 12, 16, 12)
        details_layout.setSpacing(4)

        details_header = QLabel("Details")
        details_header.setStyleSheet("color: rgba(255,255,255,100); font-size: 10px; font-weight: bold; text-transform: uppercase;")
        details_layout.addWidget(details_header)

        self.details_text = QLabel("Select an item to see details")
        self.details_text.setStyleSheet("color: rgba(255,255,255,200); font-size: 11px;")
        self.details_text.setWordWrap(True)
        self.details_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        details_layout.addWidget(self.details_text)
        details_layout.addStretch()

        self.splitter.addWidget(self.details_panel)
        self.splitter.setSizes([400, 100])  # Initial sizes

        content_layout.addWidget(self.splitter)
        self.stack.addWidget(content_widget)  # Index 1

        # Empty state
        empty_widget = QWidget()
        empty_layout = QVBoxLayout(empty_widget)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        empty_icon = QLabel("✅")
        empty_icon.setFont(QFont("Segoe UI Emoji", 48))
        empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_icon)

        empty_text = QLabel("Everything is in sync!")
        empty_text.setFont(QFont("Segoe UI", 16))
        empty_text.setStyleSheet("color: white;")
        empty_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_text)

        self.empty_stats = QLabel("")
        self.empty_stats.setStyleSheet("color: rgba(255,255,255,100); font-size: 12px;")
        self.empty_stats.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.empty_stats)

        self.stack.addWidget(empty_widget)  # Index 2

        # Results state (sync completion)
        results_widget = QWidget()
        results_layout = QVBoxLayout(results_widget)
        results_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        results_layout.setSpacing(12)

        self.result_icon = QLabel("")
        self.result_icon.setFont(QFont("Segoe UI Emoji", 48))
        self.result_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        results_layout.addWidget(self.result_icon)

        self.result_title = QLabel("")
        self.result_title.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        self.result_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        results_layout.addWidget(self.result_title)

        self.result_details = QLabel("")
        self.result_details.setStyleSheet("color: rgba(255,255,255,200); font-size: 13px;")
        self.result_details.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.result_details.setWordWrap(True)
        self.result_details.setMaximumWidth(500)
        results_layout.addWidget(self.result_details, alignment=Qt.AlignmentFlag.AlignCenter)

        self.stack.addWidget(results_widget)  # Index 3

        # Footer with action buttons
        footer = QFrame()
        footer.setStyleSheet("""
            QFrame {
                background: rgba(40, 40, 45, 200);
                border-top: 1px solid rgba(255,255,255,30);
            }
        """)
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(16, 12, 16, 12)

        # Select all / none buttons
        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.clicked.connect(self._select_all)
        self.select_none_btn = QPushButton("Select None")
        self.select_none_btn.clicked.connect(self._select_none)

        for btn in [self.select_all_btn, self.select_none_btn]:
            btn.setStyleSheet("""
                QPushButton {
                    background: rgba(255,255,255,20);
                    border: 1px solid rgba(255,255,255,30);
                    border-radius: 4px;
                    color: white;
                    padding: 6px 12px;
                }
                QPushButton:hover {
                    background: rgba(255,255,255,40);
                }
            """)

        footer_layout.addWidget(self.select_all_btn)
        footer_layout.addWidget(self.select_none_btn)
        footer_layout.addStretch()

        # Selection summary
        self.selection_label = QLabel("")
        self.selection_label.setStyleSheet("color: rgba(255,255,255,150);")
        footer_layout.addWidget(self.selection_label)

        footer_layout.addSpacing(20)

        # Cancel and Apply buttons
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self._on_cancel_clicked)
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,20);
                border: 1px solid rgba(255,255,255,30);
                border-radius: 4px;
                color: white;
                padding: 8px 20px;
            }
            QPushButton:hover {
                background: rgba(255,255,255,40);
            }
        """)

        self.apply_btn = QPushButton("Apply Sync")
        self.apply_btn.clicked.connect(self._apply_sync)
        self.apply_btn.setStyleSheet("""
            QPushButton {
                background: #409cff;
                border: none;
                border-radius: 4px;
                color: white;
                padding: 8px 24px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #5aacff;
            }
            QPushButton:disabled {
                background: rgba(64, 156, 255, 50);
                color: rgba(255,255,255,100);
            }
        """)

        footer_layout.addWidget(self.cancel_btn)
        footer_layout.addWidget(self.apply_btn)

        layout.addWidget(footer)

        # Connect tree item changes to update selection count
        self.tree.itemChanged.connect(self._update_selection_count)
        # Allow clicking anywhere on a row to toggle its checkbox
        self.tree.itemClicked.connect(self._on_item_clicked)

    # Map internal stage names → user-friendly labels
    _STAGE_LABELS = {
        "scan": "Scanning libraries",
        "scan_pc": "Scanning PC library",
        "scan_ipod": "Scanning iPod library",
        "load_mapping": "Loading iPod mapping",
        "integrity": "Checking iPod integrity",
        "fingerprint": "Computing fingerprints",
        "duplicates": "Checking for duplicates",
        "diff": "Comparing libraries",
        "add": "Copying tracks to iPod",
        "remove": "Removing tracks from iPod",
        "update_file": "Re-syncing changed files",
        "update_metadata": "Updating metadata",
        "quality_change": "Re-syncing quality changes",
        "sync_playcount": "Syncing play counts",
        "sync_rating": "Syncing ratings",
        "write_database": "Writing iPod database",
    }

    def _friendly_stage(self, stage: str) -> str:
        return self._STAGE_LABELS.get(stage, stage.replace("_", " ").title())

    def _set_footer_for_state(self, state: str):
        """Update footer button visibility for the current state.

        States: 'loading', 'plan', 'empty', 'executing', 'results'
        """
        show_plan_btns = (state == "plan")
        self.select_all_btn.setVisible(show_plan_btns)
        self.select_none_btn.setVisible(show_plan_btns)
        self.selection_label.setVisible(show_plan_btns)
        self.apply_btn.setVisible(show_plan_btns)

        if state == "loading":
            self.cancel_btn.setText("Cancel")
            self.cancel_btn.setEnabled(True)
        elif state == "plan":
            self.cancel_btn.setText("Cancel")
            self.cancel_btn.setEnabled(True)
        elif state == "empty":
            self.cancel_btn.setText("Done")
            self.cancel_btn.setEnabled(True)
        elif state == "executing":
            self.cancel_btn.setText("Cancel")
            self.cancel_btn.setEnabled(True)
        elif state == "results":
            self.cancel_btn.setText("Done")
            self.cancel_btn.setEnabled(True)

    def show_loading(self):
        """Show loading state."""
        self.stack.setCurrentIndex(0)
        self.loading_label.setText("Scanning library...")
        self.progress_bar.setRange(0, 0)  # Indeterminate
        self._set_footer_for_state("loading")

    def update_progress(self, stage: str, current: int, total: int, message: str):
        """Update progress indicator."""
        self.loading_label.setText(self._friendly_stage(stage))
        self.progress_detail.setText(message)

        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(current)
        else:
            self.progress_bar.setRange(0, 0)  # Indeterminate

    def show_plan(self, plan: SyncPlan):
        """Display the sync plan in the tree view."""
        self._plan = plan
        self.tree.clear()

        if not plan.has_changes:
            self.stack.setCurrentIndex(2)  # Empty state
            # Show match stats
            stats = f"{plan.matched_tracks} tracks matched"
            if plan.total_pc_tracks:
                stats = f"{plan.total_pc_tracks} PC tracks · {plan.total_ipod_tracks} iPod tracks · {stats}"
            if plan.fingerprint_errors:
                stats += f" · <span style='color: #c8a040;'>{len(plan.fingerprint_errors)} files skipped (fingerprint errors)</span>"
            ir = plan.integrity_report
            if ir and not ir.is_clean:
                fixes = len(ir.missing_files) + len(ir.stale_mappings) + len(ir.orphan_files)
                stats += f" · <span style='color: #64b4e6;'>🔧 {fixes} integrity fixes applied</span>"
            self.summary_label.setText(stats)
            self.summary_label.setTextFormat(Qt.TextFormat.RichText)
            self.empty_stats.setText(stats)
            self.empty_stats.setTextFormat(Qt.TextFormat.RichText)
            self._set_footer_for_state("empty")
            return

        # Show content
        self.stack.setCurrentIndex(1)
        self._set_footer_for_state("plan")

        # Update summary with git-diff style size stats
        total_changes = sum([
            len(plan.to_add), len(plan.to_remove),
            len(plan.to_update_metadata), len(plan.to_update_file),
            len(plan.to_update_artwork),
            len(plan.to_sync_playcount), len(plan.to_sync_rating),
            1 if plan.artwork_needs_sync else 0,
        ])

        # Build size diff string
        size_parts = []
        if plan.storage.bytes_to_add > 0:
            size_parts.append(f"<span style='color: #70c070;'>+{self._format_size(plan.storage.bytes_to_add)}</span>")
        if plan.storage.bytes_to_remove > 0:
            size_parts.append(f"<span style='color: #e07070;'>-{self._format_size(plan.storage.bytes_to_remove)}</span>")

        net_change = plan.storage.bytes_to_add - plan.storage.bytes_to_remove
        if size_parts and net_change != 0:
            net_sign = "+" if net_change > 0 else "-"
            size_parts.append(f"(net {net_sign}{self._format_size(abs(net_change))})")

        size_str = " ".join(size_parts) if size_parts else ""

        summary_text = f"{plan.total_pc_tracks} PC tracks · {plan.total_ipod_tracks} iPod tracks · {total_changes} changes"
        if size_str:
            summary_text += f" · {size_str}"
        if plan.fingerprint_errors:
            summary_text += f" · <span style='color: #c8a040;'>{len(plan.fingerprint_errors)} skipped</span>"

        self.summary_label.setText(summary_text)
        self.summary_label.setTextFormat(Qt.TextFormat.RichText)

        # Show integrity fixes at top if any were found
        ir = plan.integrity_report
        if ir and not ir.is_clean:
            fix_count = len(ir.missing_files) + len(ir.stale_mappings) + len(ir.orphan_files)
            header = SyncCategoryHeader("🔧", "Integrity Fixes (auto-repaired)", fix_count)
            header.setFlags(header.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            header.setCheckState(0, Qt.CheckState.Unchecked)
            for i in range(6):
                header.setForeground(i, QBrush(QColor(100, 180, 230)))
            self.tree.addTopLevelItem(header)

            if ir.missing_files:
                for track in ir.missing_files:
                    child = QTreeWidgetItem(header)
                    child.setFlags(child.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                    child.setText(1, track.get("Title", "Unknown"))
                    child.setText(2, track.get("Artist", "Unknown"))
                    child.setText(3, track.get("Album", "Unknown"))
                    child.setText(4, "File missing from iPod")
                    for ci in range(6):
                        child.setForeground(ci, QBrush(QColor(100, 180, 230)))

            if ir.stale_mappings:
                for fp, dbid in ir.stale_mappings:
                    child = QTreeWidgetItem(header)
                    child.setFlags(child.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                    child.setText(1, f"Stale mapping (dbid={dbid})")
                    child.setText(4, "Removed from mapping")
                    for ci in range(6):
                        child.setForeground(ci, QBrush(QColor(100, 180, 230)))

            if ir.orphan_files:
                orphan_bytes = 0
                for orphan in ir.orphan_files[:20]:
                    try:
                        orphan_bytes += orphan.stat().st_size
                    except OSError:
                        pass
                    child = QTreeWidgetItem(header)
                    child.setFlags(child.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                    child.setText(1, orphan.name)
                    child.setText(4, "Orphan file deleted")
                    child.setToolTip(1, str(orphan))
                    for ci in range(6):
                        child.setForeground(ci, QBrush(QColor(100, 180, 230)))
                if len(ir.orphan_files) > 20:
                    overflow = QTreeWidgetItem(header)
                    overflow.setFlags(overflow.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                    overflow.setText(1, f"...and {len(ir.orphan_files) - 20} more")
                    for ci in range(6):
                        overflow.setForeground(ci, QBrush(QColor(100, 180, 230)))

            header.setExpanded(False)

        # Add categories to tree
        if plan.to_add:
            header = SyncCategoryHeader("📥", "Add to iPod", len(plan.to_add), plan.storage.bytes_to_add)
            self.tree.addTopLevelItem(header)
            for item in plan.to_add:
                header.addChild(SyncItemWidget(item))
            header.setExpanded(True)

        if plan.to_remove:
            header = SyncCategoryHeader("🗑️", "Remove from iPod", len(plan.to_remove), plan.storage.bytes_to_remove)
            self.tree.addTopLevelItem(header)
            for item in plan.to_remove:
                header.addChild(SyncItemWidget(item))
            header.setExpanded(True)

        if plan.to_update_file:
            header = SyncCategoryHeader("🔄", "Re-sync Changed Files", len(plan.to_update_file), plan.storage.bytes_to_update)
            self.tree.addTopLevelItem(header)
            for item in plan.to_update_file:
                header.addChild(SyncItemWidget(item))
            header.setExpanded(True)

        if plan.to_update_metadata:
            header = SyncCategoryHeader("📝", "Update Metadata", len(plan.to_update_metadata))
            self.tree.addTopLevelItem(header)
            for item in plan.to_update_metadata:
                header.addChild(SyncItemWidget(item))
            header.setExpanded(False)

        if plan.to_update_artwork:
            header = SyncCategoryHeader("🎨", "Update Artwork", len(plan.to_update_artwork))
            self.tree.addTopLevelItem(header)
            for item in plan.to_update_artwork:
                header.addChild(SyncItemWidget(item))
            header.setExpanded(False)

        if plan.to_sync_playcount:
            header = SyncCategoryHeader("🎵", "Sync Play Counts", len(plan.to_sync_playcount))
            self.tree.addTopLevelItem(header)
            for item in plan.to_sync_playcount:
                header.addChild(SyncItemWidget(item))
            header.setExpanded(False)

        # Show rating changes
        if plan.to_sync_rating:
            header = SyncCategoryHeader("⭐", "Sync Ratings", len(plan.to_sync_rating))
            self.tree.addTopLevelItem(header)
            for item in plan.to_sync_rating:
                header.addChild(SyncRatingWidget(item))
            header.setExpanded(False)

        # Show artwork sync info with individual track details
        if plan.artwork_needs_sync:
            count = plan.artwork_missing_count
            header = SyncCategoryHeader("\U0001f3a8", "Sync Album Art", count)
            header.setFlags(header.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            self.tree.addTopLevelItem(header)

            # List individual tracks missing artwork
            ipod_tracks_cache = getattr(self, '_ipod_tracks_cache', None)
            if plan.matched_pc_paths and ipod_tracks_cache:
                for dbid in plan.matched_pc_paths:
                    ipod_track = next(
                        (t for t in ipod_tracks_cache if t.get('dbid') == dbid), None
                    )
                    if ipod_track:
                        ac = ipod_track.get('artworkCount', 0)
                        ml = ipod_track.get('mhiiLink', 0)
                        if ac == 0 or ml == 0:
                            child = QTreeWidgetItem(header)
                            child.setFlags(child.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                            child.setText(1, ipod_track.get('Title', 'Unknown'))
                            child.setText(2, ipod_track.get('Artist', 'Unknown'))
                            child.setText(3, ipod_track.get('Album', 'Unknown'))
                            child.setText(4, "Missing art")
                            for ci in range(6):
                                child.setForeground(ci, QBrush(QColor(180, 140, 220)))
            elif count > 0:
                # Fallback: just show a note
                child = QTreeWidgetItem(header)
                child.setFlags(child.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                child.setText(1, f"{count} tracks missing album art")
                child.setText(4, "Will be synced")
                for ci in range(6):
                    child.setForeground(ci, QBrush(QColor(180, 140, 220)))

            header.setExpanded(False)

        # Show fingerprint errors (info only, non-blocking)
        if plan.fingerprint_errors:
            err_header = SyncCategoryHeader("⚠️", "Fingerprint Errors", len(plan.fingerprint_errors))
            err_header.setFlags(err_header.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            err_header.setCheckState(0, Qt.CheckState.Unchecked)
            for i in range(6):
                err_header.setForeground(i, QBrush(QColor(200, 160, 80)))
            self.tree.addTopLevelItem(err_header)

            for filepath, error_msg in plan.fingerprint_errors[:50]:  # Cap at 50
                child = QTreeWidgetItem(err_header)
                child.setFlags(child.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                child.setText(1, os.path.basename(filepath))
                child.setText(2, error_msg)
                child.setToolTip(1, filepath)
                child.setToolTip(2, error_msg)
                for ci in range(6):
                    child.setForeground(ci, QBrush(QColor(180, 150, 80)))

            if len(plan.fingerprint_errors) > 50:
                overflow = QTreeWidgetItem(err_header)
                overflow.setFlags(overflow.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                overflow.setText(1, f"...and {len(plan.fingerprint_errors) - 50} more")
                for ci in range(6):
                    overflow.setForeground(ci, QBrush(QColor(180, 150, 80)))

            err_header.setExpanded(False)

        # Show duplicate files (informational - first file from each group is synced)
        if plan.duplicates:
            dup_count = plan.duplicate_count
            header = SyncCategoryHeader("⚠️", f"Duplicates ({len(plan.duplicates)} groups, {dup_count} extra files skipped)", 0)
            # Remove checkbox from duplicates header - it's info only
            header.setFlags(header.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            header.setCheckState(0, Qt.CheckState.Unchecked)  # Clear any checkbox state
            # Yellow/orange color for informational warning
            for i in range(6):
                header.setForeground(i, QBrush(QColor(230, 180, 80)))
            self.tree.addTopLevelItem(header)

            for fingerprint, tracks in plan.duplicates.items():
                group_header = DuplicateGroupHeader(fingerprint, tracks)
                header.addChild(group_header)
                for track in tracks:
                    group_header.addChild(DuplicateItemWidget(track))
                group_header.setExpanded(False)  # Collapsed by default

            header.setExpanded(False)  # Collapsed by default since non-blocking

        self._update_selection_count()
        self.apply_btn.setEnabled(True)
        self.apply_btn.setToolTip("")

    def show_executing(self):
        """Show executing state - similar to loading but for sync execution."""
        self._cancelled = False
        self._completed_stages = []  # Track completed stage names
        self._current_exec_stage = ""
        self.stack.setCurrentIndex(0)  # Loading view
        self.loading_label.setText("Starting sync...")
        self.progress_detail.setText("Preparing...")
        self.progress_bar.setRange(0, 0)  # Indeterminate initially
        self._set_footer_for_state("executing")

    def update_execute_progress(self, stage: str, current: int, total: int, message: str):
        """Update progress during sync execution."""
        friendly = self._friendly_stage(stage)

        # Track stage transitions for the log
        if stage != self._current_exec_stage:
            if self._current_exec_stage:
                self._completed_stages.append(self._friendly_stage(self._current_exec_stage))
            self._current_exec_stage = stage

        self.loading_label.setText(friendly)

        # Build detail text: completed stages + current progress
        detail_parts = []
        for s in self._completed_stages[-4:]:  # Show last 4 completed stages
            detail_parts.append(f"<span style='color: rgba(255,255,255,80);'>✓ {s}</span>")
        if message:
            detail_parts.append(f"<span style='color: rgba(255,255,255,180);'>{message}</span>")
        self.progress_detail.setText("<br>".join(detail_parts))
        self.progress_detail.setTextFormat(Qt.TextFormat.RichText)

        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(current)
        else:
            self.progress_bar.setRange(0, 0)  # Indeterminate

    def show_result(self, result):
        """Show sync completion results in a styled view."""
        self.stack.setCurrentIndex(3)  # Results view
        self._set_footer_for_state("results")

        success = getattr(result, 'success', True)
        errors = getattr(result, 'errors', [])

        # Title
        if success and not errors:
            self.result_icon.setText("✅")
            self.result_title.setText("Sync Complete")
            self.result_title.setStyleSheet("color: #70c070; font-size: 18px; font-weight: bold;")
        elif errors:
            self.result_icon.setText("⚠️")
            self.result_title.setText("Sync Completed with Errors")
            self.result_title.setStyleSheet("color: #e0b050; font-size: 18px; font-weight: bold;")
        else:
            self.result_icon.setText("❌")
            self.result_title.setText("Sync Failed")
            self.result_title.setStyleSheet("color: #e07070; font-size: 18px; font-weight: bold;")

        # Build results text
        lines = []
        added = getattr(result, 'tracks_added', 0)
        removed = getattr(result, 'tracks_removed', 0)
        updated_meta = getattr(result, 'tracks_updated_metadata', 0)
        updated_file = getattr(result, 'tracks_updated_file', 0)
        playcounts = getattr(result, 'playcounts_synced', 0)
        ratings = getattr(result, 'ratings_synced', 0)

        if added:
            lines.append(f"<span style='color: #70c070;'>Added {added} track{'s' if added != 1 else ''}</span>")
        if removed:
            lines.append(f"<span style='color: #e07070;'>Removed {removed} track{'s' if removed != 1 else ''}</span>")
        if updated_file:
            lines.append(f"<span style='color: #70a0e0;'>Re-synced {updated_file} track{'s' if updated_file != 1 else ''}</span>")
        if updated_meta:
            lines.append(f"<span style='color: #70a0e0;'>Updated metadata for {updated_meta} track{'s' if updated_meta != 1 else ''}</span>")
        if playcounts:
            lines.append(f"<span style='color: #70a0e0;'>Synced play counts for {playcounts} track{'s' if playcounts != 1 else ''}</span>")
        if ratings:
            lines.append(f"<span style='color: #e0b050;'>Synced ratings for {ratings} track{'s' if ratings != 1 else ''}</span>")

        if not lines:
            lines.append("No changes were made.")

        if errors:
            lines.append("")
            lines.append(f"<span style='color: #e07070;'><b>{len(errors)} error{'s' if len(errors) != 1 else ''}:</b></span>")
            for desc, msg in errors[:10]:  # Show max 10
                lines.append(f"<span style='color: #e07070;'>  {desc}: {msg}</span>")
            if len(errors) > 10:
                lines.append(f"<span style='color: #e07070;'>  ...and {len(errors) - 10} more</span>")

        # Safe-eject reminder
        if success and (added or removed or updated_file or updated_meta):
            lines.append("")
            lines.append("<span style='color: rgba(255,255,255,100);'>Safely eject your iPod before disconnecting.</span>")

        self.result_details.setText("<br>".join(lines))
        self.result_details.setTextFormat(Qt.TextFormat.RichText)

        # Update summary
        total_actions = added + removed + updated_file + updated_meta + playcounts + ratings
        self.summary_label.setText(f"{total_actions} action{'s' if total_actions != 1 else ''} completed")

    def show_error(self, message: str):
        """Show error message."""
        QMessageBox.critical(self, "Sync Error", message)
        self.stack.setCurrentIndex(2)
        self.summary_label.setText("Error during scan")
        self._set_footer_for_state("empty")

    def _on_cancel_clicked(self):
        """Handle cancel/done button clicks based on current state."""
        current_idx = self.stack.currentIndex()
        if current_idx == 0 and not self._cancelled:
            # During loading/executing — ask for confirmation
            self._cancelled = True
            self.cancel_btn.setEnabled(False)
            self.cancel_btn.setText("Cancelling...")
            self.cancelled.emit()
        else:
            # Plan view, empty view, or results view — just go back
            self.cancelled.emit()

    def _select_all(self):
        """Select all items."""
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item:
                item.setCheckState(0, Qt.CheckState.Checked)

    def _select_none(self):
        """Deselect all items."""
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item:
                item.setCheckState(0, Qt.CheckState.Unchecked)

    def _on_item_clicked(self, item: QTreeWidgetItem, column: int):
        """Toggle checkbox when clicking anywhere on the row (not just the checkbox column).

        Column 0 is the checkbox column — Qt already handles toggling there,
        so we only act on clicks on columns 1-5 to avoid double-toggling.
        """
        if column > 0 and (item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
            current = item.checkState(0)
            new_state = (
                Qt.CheckState.Unchecked
                if current == Qt.CheckState.Checked
                else Qt.CheckState.Checked
            )
            item.setCheckState(0, new_state)

    def _update_selection_count(self):
        """Update the selection summary label."""
        selected = 0
        total = 0
        bytes_to_add = 0
        bytes_to_remove = 0

        for i in range(self.tree.topLevelItemCount()):
            header = self.tree.topLevelItem(i)
            if not header:
                continue
            # Skip duplicate headers (they're info-only)
            if isinstance(header, SyncCategoryHeader):
                header_text = header.text(1)
                if "DUPLICATE" in header_text:
                    continue
            for j in range(header.childCount()):
                child = header.child(j)
                if not child:
                    continue
                # Skip duplicate items
                if isinstance(child, (DuplicateGroupHeader, DuplicateItemWidget)):
                    continue
                total += 1
                if child.checkState(0) == Qt.CheckState.Checked:
                    selected += 1
                    if isinstance(child, SyncItemWidget):
                        item = child.sync_item
                        # Track adds and removes separately
                        if item.action == SyncAction.ADD_TO_IPOD:
                            if item.pc_track:
                                bytes_to_add += item.pc_track.size
                        elif item.action == SyncAction.REMOVE_FROM_IPOD:
                            if item.ipod_track:
                                bytes_to_remove += item.ipod_track.get("size", 0)
                        elif item.action == SyncAction.UPDATE_FILE:
                            if item.pc_track:
                                bytes_to_add += item.pc_track.size

        # Build git-diff style size string
        size_parts = []
        if bytes_to_add > 0:
            size_parts.append(f"+{self._format_size(bytes_to_add)}")
        if bytes_to_remove > 0:
            size_parts.append(f"-{self._format_size(bytes_to_remove)}")

        net_change = bytes_to_add - bytes_to_remove
        if bytes_to_add > 0 or bytes_to_remove > 0:
            net_sign = "+" if net_change >= 0 else "-"
            size_parts.append(f"(net {net_sign}{self._format_size(abs(net_change))})")

        size_str = " ".join(size_parts) if size_parts else ""

        label_text = f"{selected} of {total} selected"
        if size_str:
            label_text += f" · {size_str}"

        self.selection_label.setText(label_text)

    def _update_details_panel(self):
        """Update the details panel with selected item info."""
        selected = self.tree.selectedItems()
        if not selected:
            self.details_text.setText("Select an item to see details")
            return

        item = selected[0]

        # Skip if it's a category header
        if isinstance(item, SyncCategoryHeader):
            count = item.childCount()
            self.details_text.setText(f"Category with {count} item{'s' if count != 1 else ''}")
            return

        # Handle duplicate group headers
        if isinstance(item, DuplicateGroupHeader):
            lines = []
            lines.append("<span style='color: #ff6666;'><b>⚠️ DUPLICATES BLOCKING SYNC</b></span>")
            lines.append(f"<b>Duplicate Group:</b> {len(item.tracks)} files with identical metadata")
            lines.append("")
            lines.append("<span style='color: #e0b050;'>These files share the same artist, album, title, and duration.</span>")
            lines.append("<span style='color: #e0b050;'>iOpenPod can't decide which copy to use.</span>")
            lines.append("")
            lines.append("<b>To resolve:</b> Delete or move the extra copies so each song")
            lines.append("exists in only one location within your music folder.")
            lines.append("")
            lines.append("<b>Files:</b>")
            for track in item.tracks:
                lines.append(f"  • {track.path} ({self._format_size(track.size)})")
            self.details_text.setText("<br>".join(lines))
            return

        # Handle individual duplicate items
        if isinstance(item, DuplicateItemWidget):
            track = item.track
            lines = []
            lines.append("<span style='color: #ff6666;'><b>⚠️ DUPLICATE FILE</b></span>")
            lines.append(f"<b>Path:</b> {track.path}")
            lines.append(f"<b>Size:</b> {self._format_size(track.size)} · <b>Duration:</b> {self._format_duration(track.duration_ms)}")
            if track.artist:
                lines.append(f"<b>Artist:</b> {track.artist}")
            if track.album:
                lines.append(f"<b>Album:</b> {track.album}")
            if track.title:
                lines.append(f"<b>Title:</b> {track.title}")
            lines.append("")
            lines.append("Delete or move this file to resolve the duplicate,")
            lines.append("then re-scan to continue syncing.")
            self.details_text.setText("<br>".join(lines))
            return

        # Handle rating sync items
        if isinstance(item, SyncRatingWidget):
            si = item.sync_item
            lines = []
            lines.append("<b>Action:</b> Sync rating between PC and iPod")
            if si.pc_track:
                lines.append(f"<b>Track:</b> {si.pc_track.title or si.pc_track.filename}")
                lines.append(f"<b>Artist:</b> {si.pc_track.artist or 'Unknown'}")
                lines.append(f"<b>Album:</b> {si.pc_track.album or 'Unknown'}")
                lines.append("")
                lines.append(f"<b>File:</b> {si.pc_track.path}")
            lines.append("")
            pc_stars = item._rating_to_stars(si.pc_rating)
            ipod_stars = item._rating_to_stars(si.ipod_rating)
            new_stars = item._rating_to_stars(si.new_rating)
            lines.append(f"<b>PC Rating:</b> {pc_stars} ({si.pc_rating}/100)")
            lines.append(f"<b>iPod Rating:</b> {ipod_stars} ({si.ipod_rating}/100)")
            lines.append(f"<b>New Rating:</b> <span style='color: #e0b050;'>{new_stars} ({si.new_rating}/100)</span>")
            lines.append("")
            if si.pc_rating > 0 and si.ipod_rating > 0:
                lines.append("Both have ratings \u2014 iPod rating wins (last-write-wins).")
            elif si.ipod_rating > 0:
                lines.append("PC has no rating \u2014 using iPod rating.")
            else:
                lines.append("iPod has no rating \u2014 using PC rating.")
            self.details_text.setText("<br>".join(lines))
            return

        if not isinstance(item, SyncItemWidget):
            return

        sync_item = item.sync_item
        lines = []

        # Action-specific details
        if sync_item.action == SyncAction.ADD_TO_IPOD:
            track = sync_item.pc_track
            if track:
                lines.append("<b>Action:</b> Add to iPod")
                lines.append(f"<b>File:</b> {track.path}")
                lines.append(f"<b>Size:</b> {self._format_size(track.size)} · <b>Duration:</b> {self._format_duration(track.duration_ms)} · <b>Format:</b> {track.extension.upper()}")
                if track.genre:
                    lines.append(f"<b>Genre:</b> {track.genre}")

        elif sync_item.action == SyncAction.REMOVE_FROM_IPOD:
            ipod_track = sync_item.ipod_track
            lines.append("<b>Action:</b> Remove from iPod")
            lines.append("<span style='color: #e07070;'>Track not found on PC</span>")
            if ipod_track:
                lines.append(f"<b>iPod location:</b> {ipod_track.get('Location', 'Unknown')}")

        elif sync_item.action == SyncAction.SYNC_PLAYCOUNT:
            track = sync_item.pc_track
            ipod_track = sync_item.ipod_track
            plays = sync_item.play_count_delta
            skips = sync_item.skip_count_delta
            lines.append("<b>Action:</b> Sync play statistics back to PC library")
            if track:
                lines.append(f"<b>File:</b> {track.path}")
            stats_parts = []
            if plays > 0:
                stats_parts.append(f"<span style='color: #70a0e0;'><b>+{plays}</b> plays</span>")
            if skips > 0:
                stats_parts.append(f"<span style='color: #e0a070;'><b>+{skips}</b> skips</span>")
            if stats_parts:
                lines.append(f"<b>Changes:</b> {' · '.join(stats_parts)}")

        elif sync_item.action == SyncAction.UPDATE_METADATA:
            track = sync_item.pc_track
            lines.append("<b>Action:</b> Update metadata on iPod")
            if track:
                lines.append(f"<b>File:</b> {track.path}")
            lines.append("")
            for field_name, (pc_val, ipod_val) in sync_item.metadata_changes.items():
                lines.append(f"<b>{field_name}:</b> <span style='color: #e07070;'>{ipod_val}</span> → <span style='color: #70c070;'>{pc_val}</span>")

        elif sync_item.action == SyncAction.UPDATE_FILE:
            track = sync_item.pc_track
            lines.append("<b>Action:</b> Re-sync changed file to iPod")
            if track:
                lines.append(f"<b>File:</b> {track.path}")
                lines.append(f"<b>Size:</b> {self._format_size(track.size)} · <b>Format:</b> {track.extension.upper()}")
            lines.append("")
            lines.append("<span style='color: #70c0c0;'>The source file has been modified since last sync.</span>")

        elif sync_item.action == SyncAction.UPDATE_ARTWORK:
            track = sync_item.pc_track
            new_hash = sync_item.new_art_hash
            old_hash = sync_item.old_art_hash
            if not new_hash and old_hash:
                lines.append("<b>Action:</b> Remove album art from iPod")
                if track:
                    lines.append(f"<b>File:</b> {track.path}")
                lines.append("")
                lines.append("<span style='color: #e07070;'>The embedded album art was removed from the PC file.</span>")
                lines.append("<span style='color: #e07070;'>Art will be cleared on iPod at next database write.</span>")
            elif new_hash and not old_hash:
                lines.append("<b>Action:</b> Add album art to iPod")
                if track:
                    lines.append(f"<b>File:</b> {track.path}")
                lines.append("")
                lines.append("<span style='color: #80c8a8;'>New album art detected in the PC file.</span>")
            else:
                lines.append("<b>Action:</b> Update album art on iPod")
                if track:
                    lines.append(f"<b>File:</b> {track.path}")
                lines.append("")
                lines.append("<span style='color: #c080c0;'>The embedded album art has changed.</span>")

        self.details_text.setText("<br>".join(lines))

    def _get_selected_items(self) -> list[SyncItem]:
        """Get all checked sync items."""
        selected_items = []
        for i in range(self.tree.topLevelItemCount()):
            header = self.tree.topLevelItem(i)
            if not header:
                continue
            for j in range(header.childCount()):
                child = header.child(j)
                if not child:
                    continue
                if child.checkState(0) == Qt.CheckState.Checked:
                    if isinstance(child, SyncItemWidget):
                        selected_items.append(child.sync_item)
                    elif isinstance(child, SyncRatingWidget):
                        selected_items.append(child.sync_item)
        return selected_items

    def _apply_sync(self):
        """Emit signal to apply the selected sync actions."""
        selected_items = self._get_selected_items()
        if not selected_items:
            QMessageBox.information(self, "No Selection", "Please select items to sync.")
            return

        # Confirm
        add_count = sum(1 for s in selected_items if s.action == SyncAction.ADD_TO_IPOD)
        remove_count = sum(1 for s in selected_items if s.action == SyncAction.REMOVE_FROM_IPOD)
        meta_count = sum(1 for s in selected_items if s.action == SyncAction.UPDATE_METADATA)
        file_count = sum(1 for s in selected_items if s.action == SyncAction.UPDATE_FILE)
        art_count = sum(1 for s in selected_items if s.action == SyncAction.UPDATE_ARTWORK)
        playcount_count = sum(1 for s in selected_items if s.action == SyncAction.SYNC_PLAYCOUNT)
        rating_count = sum(1 for s in selected_items if s.action == SyncAction.SYNC_RATING)

        msg_parts = []
        if add_count:
            msg_parts.append(f"Add {add_count} tracks")
        if remove_count:
            msg_parts.append(f"Remove {remove_count} tracks")
        if file_count:
            msg_parts.append(f"Re-sync {file_count} changed files")
        if meta_count:
            msg_parts.append(f"Update metadata for {meta_count} tracks")
        if art_count:
            msg_parts.append(f"Update artwork for {art_count} tracks")
        if playcount_count:
            msg_parts.append(f"Sync {playcount_count} play counts")
        if rating_count:
            msg_parts.append(f"Sync {rating_count} ratings")

        msg = "This will:\n• " + "\n• ".join(msg_parts) + "\n\nContinue?"

        reply = QMessageBox.question(
            self, "Confirm Sync", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.sync_requested.emit(selected_items)

    _format_size = staticmethod(_format_size)
    _format_duration = staticmethod(_format_duration)


class PCFolderDialog(QDialog):
    """Dialog to select PC music folder for syncing."""

    def __init__(self, parent=None, last_folder: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Select Music Folder")
        self.setMinimumWidth(400)
        self.selected_folder = ""
        self.last_folder = last_folder

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Instructions
        label = QLabel(
            "Select the folder containing your music library.\n"
            "This folder will be compared with your iPod to find:\n"
            "• New tracks to add\n"
            "• Removed tracks to delete\n"
            "• Updated tracks to re-sync"
        )
        label.setWordWrap(True)
        layout.addWidget(label)

        # Folder selection
        folder_layout = QHBoxLayout()

        self.folder_edit = QLabel(self.last_folder or "No folder selected")
        self.folder_edit.setStyleSheet("""
            QLabel {
                background: palette(base);
                border: 1px solid palette(mid);
                border-radius: 4px;
                padding: 8px;
            }
        """)
        self.folder_edit.setWordWrap(True)
        folder_layout.addWidget(self.folder_edit, 1)

        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse)
        folder_layout.addWidget(browse_btn)

        layout.addLayout(folder_layout)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Music Folder",
            self.last_folder,
            QFileDialog.Option.ShowDirsOnly
        )
        if folder:
            self.selected_folder = folder
            self.folder_edit.setText(folder)

    def _accept(self):
        if not self.selected_folder and self.last_folder:
            self.selected_folder = self.last_folder

        if not self.selected_folder:
            QMessageBox.warning(self, "No Folder", "Please select a music folder.")
            return

        if not os.path.isdir(self.selected_folder):
            QMessageBox.warning(self, "Invalid Folder", "The selected folder does not exist.")
            return

        self.accept()
