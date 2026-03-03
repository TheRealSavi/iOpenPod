"""
Settings page widget for iOpenPod.

Displayed as a full-page view in the central stack (like the sync review page).
Matches the dark translucent UI style of the rest of the app.
"""

from PyQt6.QtCore import pyqtSignal, pyqtSlot, Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QComboBox, QFrame, QScrollArea, QFileDialog,
)
from PyQt6.QtGui import QFont
from pathlib import Path
from ..styles import Colors, FONT_FAMILY, Metrics, btn_css


# ── Reusable row widgets ────────────────────────────────────────────────────

class SettingRow(QFrame):
    """A single setting row with label, description, and control on the right."""

    def __init__(self, title: str, description: str = ""):
        super().__init__()
        self.setStyleSheet(f"""
            QFrame {{
                background: {Colors.SURFACE_ALT};
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-radius: {Metrics.BORDER_RADIUS}px;
            }}
        """)

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(16, 12, 16, 12)
        self._layout.setSpacing(16)

        # Left side: title + description
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)

        self.title_label = QLabel(title)
        self.title_label.setFont(QFont(FONT_FAMILY, 11, QFont.Weight.DemiBold))
        self.title_label.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; background: transparent; border: none;")
        text_layout.addWidget(self.title_label)

        if description:
            self.desc_label = QLabel(description)
            self.desc_label.setFont(QFont(FONT_FAMILY, 9))
            self.desc_label.setStyleSheet(f"color: {Colors.TEXT_TERTIARY}; background: transparent; border: none;")
            self.desc_label.setWordWrap(True)
            text_layout.addWidget(self.desc_label)

        self._layout.addLayout(text_layout, stretch=1)

    def add_control(self, widget: QWidget):
        """Add a control widget to the right side of the row."""
        widget.setStyleSheet(widget.styleSheet() + " background: transparent; border: none;")
        self._layout.addWidget(widget)


class ToggleRow(SettingRow):
    """Setting row with a toggle switch (checkbox)."""

    changed = pyqtSignal(bool)

    def __init__(self, title: str, description: str = "", checked: bool = False):
        super().__init__(title, description)

        self.checkbox = QCheckBox()
        self.checkbox.setChecked(checked)
        self.checkbox.setStyleSheet(f"""
            QCheckBox {{
                background: transparent;
                border: none;
            }}
            QCheckBox::indicator {{
                width: 38px;
                height: 20px;
                border-radius: 10px;
                background: rgba(255,255,255,30);
                border: 1px solid rgba(255,255,255,40);
            }}
            QCheckBox::indicator:checked {{
                background: {Colors.ACCENT};
                border: 1px solid {Colors.ACCENT};
            }}
        """)
        self.checkbox.toggled.connect(self.changed.emit)
        self.add_control(self.checkbox)

    @property
    def value(self) -> bool:
        return self.checkbox.isChecked()

    @value.setter
    def value(self, v: bool):
        self.checkbox.setChecked(v)


class ComboRow(SettingRow):
    """Setting row with a dropdown."""

    changed = pyqtSignal(str)

    def __init__(self, title: str, description: str = "",
                 options: list[str] | None = None, current: str = ""):
        super().__init__(title, description)

        self.combo = QComboBox()
        self.combo.setFixedWidth(130)
        self.combo.setFont(QFont(FONT_FAMILY, 10))
        self.combo.setStyleSheet(f"""
            QComboBox {{
                background: {Colors.SURFACE_RAISED};
                border: 1px solid {Colors.BORDER};
                border-radius: {Metrics.BORDER_RADIUS_SM}px;
                color: white;
                padding: 5px 10px;
            }}
            QComboBox:hover {{
                border: 1px solid {Colors.BORDER_FOCUS};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 22px;
            }}
            QComboBox::down-arrow {{
                image: none;
                border: none;
            }}
            QComboBox QAbstractItemView {{
                background: #2a2a3a;
                color: white;
                selection-background-color: {Colors.ACCENT};
                border: 1px solid {Colors.BORDER};
                border-radius: 4px;
                padding: 2px;
                outline: none;
            }}
        """)
        if options:
            self.combo.addItems(options)
        if current:
            idx = self.combo.findText(current)
            if idx >= 0:
                self.combo.setCurrentIndex(idx)
        self.combo.currentTextChanged.connect(self.changed.emit)
        self.add_control(self.combo)

    @property
    def value(self) -> str:
        return self.combo.currentText()


class FolderRow(SettingRow):
    """Setting row with folder path display and browse button."""

    changed = pyqtSignal(str)

    def __init__(self, title: str, description: str = "", path: str = ""):
        super().__init__(title, description)

        right_layout = QHBoxLayout()
        right_layout.setSpacing(8)

        self.path_label = QLabel(self._truncate(path) if path else "Not set")
        self.path_label.setFont(QFont(FONT_FAMILY, 9))
        self.path_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; background: transparent; border: none;")
        self.path_label.setMinimumWidth(120)
        self.path_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        right_layout.addWidget(self.path_label)

        self.browse_btn = QPushButton("Browse…")
        self.browse_btn.setFont(QFont(FONT_FAMILY, 9))
        self.browse_btn.setFixedWidth(80)
        self.browse_btn.setStyleSheet(btn_css(
            bg=Colors.SURFACE_RAISED,
            bg_hover=Colors.SURFACE_ACTIVE,
            bg_press=Colors.SURFACE_ALT,
            border=f"1px solid {Colors.BORDER}",
            padding="4px 8px",
        ))
        self.browse_btn.clicked.connect(self._browse)
        right_layout.addWidget(self.browse_btn)

        container = QWidget()
        container.setLayout(right_layout)
        self.add_control(container)

        self._full_path = path

    def _truncate(self, path: str) -> str:
        if len(path) > 40:
            return "…" + path[-38:]
        return path

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Select Folder", self._full_path,
            QFileDialog.Option.ShowDirsOnly,
        )
        if folder:
            self._full_path = folder
            self.path_label.setText(self._truncate(folder))
            self.changed.emit(folder)

    @property
    def value(self) -> str:
        return self._full_path

    @value.setter
    def value(self, v: str):
        self._full_path = v
        self.path_label.setText(self._truncate(v) if v else "Not set")


class ActionRow(SettingRow):
    """Setting row with an action button."""

    clicked = pyqtSignal()

    def __init__(self, title: str, description: str = "", button_text: str = "Run"):
        super().__init__(title, description)

        self.action_btn = QPushButton(button_text)
        self.action_btn.setFont(QFont(FONT_FAMILY, 9))
        self.action_btn.setFixedWidth(100)
        self.action_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.action_btn.setStyleSheet(btn_css(
            bg=Colors.SURFACE_RAISED,
            bg_hover=Colors.SURFACE_ACTIVE,
            bg_press=Colors.SURFACE_ALT,
            border=f"1px solid {Colors.BORDER}",
            padding="5px 12px",
        ))
        self.action_btn.clicked.connect(self.clicked.emit)
        self.add_control(self.action_btn)

    def set_enabled(self, enabled: bool):
        """Enable or disable the action button."""
        self.action_btn.setEnabled(enabled)


class FileRow(SettingRow):
    """Setting row with file path display and browse button (picks a file, not a folder)."""

    changed = pyqtSignal(str)

    def __init__(self, title: str, description: str = "", path: str = "",
                 filter_str: str = "All Files (*)"):
        super().__init__(title, description)
        self._filter_str = filter_str

        right_layout = QHBoxLayout()
        right_layout.setSpacing(8)

        self.path_label = QLabel(self._truncate(path) if path else "Auto-detect")
        self.path_label.setFont(QFont(FONT_FAMILY, 9))
        self.path_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; background: transparent; border: none;")
        self.path_label.setMinimumWidth(120)
        self.path_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        right_layout.addWidget(self.path_label)

        self.browse_btn = QPushButton("Browse…")
        self.browse_btn.setFont(QFont(FONT_FAMILY, 9))
        self.browse_btn.setFixedWidth(80)
        self.browse_btn.setStyleSheet(btn_css(
            bg=Colors.SURFACE_RAISED,
            bg_hover=Colors.SURFACE_ACTIVE,
            bg_press=Colors.SURFACE_ALT,
            border=f"1px solid {Colors.BORDER}",
            padding="4px 8px",
        ))
        self.browse_btn.clicked.connect(self._browse)
        right_layout.addWidget(self.browse_btn)

        self.clear_btn = QPushButton("✕")
        self.clear_btn.setFont(QFont(FONT_FAMILY, 9))
        self.clear_btn.setFixedWidth(28)
        self.clear_btn.setToolTip("Reset to auto-detect")
        self.clear_btn.setStyleSheet(btn_css(
            bg="transparent",
            bg_hover=Colors.SURFACE_ACTIVE,
            bg_press=Colors.SURFACE_ALT,
            fg=Colors.TEXT_TERTIARY,
            border="none",
            padding="2px",
        ))
        self.clear_btn.clicked.connect(self._clear)
        right_layout.addWidget(self.clear_btn)

        container = QWidget()
        container.setLayout(right_layout)
        self.add_control(container)

        self._full_path = path

    def _truncate(self, path: str) -> str:
        if len(path) > 40:
            return "…" + path[-38:]
        return path

    def _browse(self):
        start_dir = str(Path(self._full_path).parent) if self._full_path else ""
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Select File", start_dir, self._filter_str,
        )
        if filepath:
            self._full_path = filepath
            self.path_label.setText(self._truncate(filepath))
            self.changed.emit(filepath)

    def _clear(self):
        self._full_path = ""
        self.path_label.setText("Auto-detect")
        self.changed.emit("")

    @property
    def value(self) -> str:
        return self._full_path

    @value.setter
    def value(self, v: str):
        self._full_path = v
        self.path_label.setText(self._truncate(v) if v else "Auto-detect")


class ToolRow(SettingRow):
    """Setting row showing tool status with a Download button."""

    download_clicked = pyqtSignal()

    def __init__(self, title: str, description: str = ""):
        super().__init__(title, description)

        right_layout = QHBoxLayout()
        right_layout.setSpacing(8)

        self.status_label = QLabel("Checking…")
        self.status_label.setFont(QFont(FONT_FAMILY, 9))
        self.status_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; background: transparent; border: none;")
        right_layout.addWidget(self.status_label)

        self.download_btn = QPushButton("Download")
        self.download_btn.setFont(QFont(FONT_FAMILY, 9))
        self.download_btn.setFixedWidth(90)
        self.download_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.download_btn.setStyleSheet(btn_css(
            bg=Colors.ACCENT,
            bg_hover=Colors.ACCENT_LIGHT,
            bg_press=Colors.ACCENT,
            fg="#000000",
            border="none",
            padding="4px 8px",
        ))
        self.download_btn.clicked.connect(self.download_clicked.emit)
        self.download_btn.hide()
        right_layout.addWidget(self.download_btn)

        container = QWidget()
        container.setLayout(right_layout)
        self.add_control(container)

    def set_status(self, found: bool, path: str = ""):
        """Update the status display."""
        if found:
            display = path if len(path) <= 40 else "…" + path[-38:]
            self.status_label.setText(f"✓ {display}")
            self.status_label.setStyleSheet(f"color: {Colors.SUCCESS}; background: transparent; border: none;")
            self.download_btn.hide()
        else:
            self.status_label.setText("Not found")
            self.status_label.setStyleSheet(f"color: {Colors.WARNING}; background: transparent; border: none;")
            self.download_btn.show()

    def set_downloading(self):
        """Show downloading state."""
        self.download_btn.setEnabled(False)
        self.download_btn.setText("Downloading…")
        self.status_label.setText("Downloading…")
        self.status_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; background: transparent; border: none;")


# ── Main settings page ─────────────────────────────────────────────────────

class SettingsPage(QWidget):
    """Full-page settings view, matching the app's dark translucent style."""

    closed = pyqtSignal()  # Emitted when user closes settings

    def __init__(self):
        super().__init__()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # ── Title bar ───────────────────────────────────────────────────────
        title_bar = QWidget()
        title_bar.setStyleSheet("background: transparent;")
        tb_layout = QHBoxLayout(title_bar)
        tb_layout.setContentsMargins(24, 16, 24, 8)

        back_btn = QPushButton("← Back")
        back_btn.setFont(QFont(FONT_FAMILY, 11))
        back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        back_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                color: {Colors.ACCENT};
                padding: 4px 8px;
            }}
            QPushButton:hover {{ color: {Colors.ACCENT_LIGHT}; }}
        """)
        back_btn.clicked.connect(self._on_close)
        tb_layout.addWidget(back_btn)

        title = QLabel("Settings")
        title.setFont(QFont(FONT_FAMILY, 18, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; background: transparent;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tb_layout.addWidget(title, stretch=1)

        # Spacer to balance the back button
        spacer = QWidget()
        spacer.setFixedWidth(60)
        tb_layout.addWidget(spacer)

        outer.addWidget(title_bar)

        # ── Scrollable content ──────────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollArea > QWidget > QWidget { background: transparent; }
        """)

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 8, 24, 24)
        layout.setSpacing(12)

        # ── EXTERNAL TOOLS section ──────────────────────────────────────────
        layout.addWidget(self._section_label("EXTERNAL TOOLS"))

        self.ffmpeg_tool = ToolRow(
            "FFmpeg",
            "Required for transcoding FLAC, OGG, and other formats to iPod-compatible audio.",
        )
        self.ffmpeg_tool.download_clicked.connect(self._download_ffmpeg)
        layout.addWidget(self.ffmpeg_tool)

        self.fpcalc_tool = ToolRow(
            "fpcalc (Chromaprint)",
            "Required for acoustic fingerprinting, which identifies tracks even after re-encoding.",
        )
        self.fpcalc_tool.download_clicked.connect(self._download_fpcalc)
        layout.addWidget(self.fpcalc_tool)

        self.ffmpeg_path = FileRow(
            "FFmpeg Path Override",
            "Point to a custom ffmpeg binary. Leave empty to auto-detect.",
            filter_str="FFmpeg (ffmpeg ffmpeg.exe);;All Files (*)",
        )
        layout.addWidget(self.ffmpeg_path)

        self.fpcalc_path = FileRow(
            "fpcalc Path Override",
            "Point to a custom fpcalc binary. Leave empty to auto-detect.",
            filter_str="fpcalc (fpcalc fpcalc.exe);;All Files (*)",
        )
        layout.addWidget(self.fpcalc_path)

        # ── SYNC section ────────────────────────────────────────────────────
        layout.addWidget(self._section_label("SYNC"))

        self.music_folder = FolderRow(
            "Music Folder",
            "Default PC music library folder for sync. This is remembered between sessions.",
        )
        layout.addWidget(self.music_folder)

        self.write_back = ToggleRow(
            "Write Back to PC",
            "After syncing, write play counts and ratings from iPod back into your PC music files. "
            "When off, play counts and ratings only update on the iPod.",
        )
        layout.addWidget(self.write_back)

        self.compute_sound_check = ToggleRow(
            "Compute Sound Check",
            "Analyze loudness of files missing ReplayGain/iTunNORM tags using ffmpeg, "
            "then write the result back into your PC files and sync to iPod. "
            "Sound Check values are always synced to iPod regardless of this setting.",
        )
        layout.addWidget(self.compute_sound_check)

        self.rating_strategy = ComboRow(
            "Rating Conflict Strategy",
            "How to resolve rating conflicts when iPod and PC ratings differ. "
            "iPod/PC Wins uses that source (falling back to the other if zero). "
            "Highest/Lowest picks the max/min non-zero value. Average rounds to the nearest star.",
            options=["iPod Wins", "PC Wins", "Highest", "Lowest", "Average"],
            current="iPod Wins",
        )
        layout.addWidget(self.rating_strategy)

        # ── TRANSCODING section ─────────────────────────────────────────────
        layout.addWidget(self._section_label("TRANSCODING"))

        self.aac_bitrate = ComboRow(
            "AAC Bitrate",
            "Bitrate for lossy transcodes (OGG, Opus, WMA → AAC). "
            "Higher values mean better quality but use more iPod storage.",
            options=["128 kbps", "192 kbps", "256 kbps", "320 kbps"],
            current="256 kbps",
        )
        layout.addWidget(self.aac_bitrate)

        self.video_crf = ComboRow(
            "Video Quality (CRF)",
            "Quality level for H.264 video transcodes. Lower CRF = better quality but larger files. "
            "Resolution and codec are always forced to iPod-compatible values.",
            options=["18 (High)", "20 (Good)", "23 (Balanced)", "26 (Low)", "28 (Very Low)"],
            current="23 (Balanced)",
        )
        layout.addWidget(self.video_crf)

        self.video_preset = ComboRow(
            "Video Encode Speed",
            "Slower presets produce slightly better quality at the same CRF, but take much longer.",
            options=["ultrafast", "veryfast", "fast", "medium", "slow"],
            current="fast",
        )
        layout.addWidget(self.video_preset)

        self.sync_workers = ComboRow(
            "Parallel Workers",
            "Number of files to transcode/copy simultaneously. "
            "Auto uses your CPU core count (capped at 8). More workers = faster syncs with many transcodes.",
            options=["Auto", "1", "2", "4", "6", "8"],
            current="Auto",
        )
        layout.addWidget(self.sync_workers)

        # ── APPEARANCE section ──────────────────────────────────────────────
        layout.addWidget(self._section_label("APPEARANCE"))

        self.show_art = ToggleRow(
            "Track List Artwork",
            "Show album art thumbnails next to tracks in the list view.",
            checked=True,
        )
        layout.addWidget(self.show_art)

        # ── STORAGE section ─────────────────────────────────────────────────
        layout.addWidget(self._section_label("STORAGE"))

        self.transcode_cache_dir = FolderRow(
            "Transcode Cache",
            "Where transcoded files are cached to avoid re-encoding on future syncs. "
            "Leave empty for the default (~/.iopenpod/transcode_cache).",
        )
        layout.addWidget(self.transcode_cache_dir)

        self.settings_dir = FolderRow(
            "Settings Location",
            "Custom directory to store iOpenPod settings. Useful for portable setups or backups. "
            "Leave empty for the platform default.",
        )
        layout.addWidget(self.settings_dir)

        self.log_dir = FolderRow(
            "Log Location",
            "Where iOpenPod writes log files and crash reports. "
            "Leave empty for the platform default. Takes effect on next launch.",
        )
        layout.addWidget(self.log_dir)

        self.reset_cache_dir_btn = QPushButton("Reset to Default")
        self.reset_cache_dir_btn.setFont(QFont(FONT_FAMILY, 9))
        self.reset_cache_dir_btn.setFixedWidth(130)
        self.reset_cache_dir_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reset_cache_dir_btn.setStyleSheet(btn_css(
            bg=Colors.SURFACE,
            bg_hover=Colors.SURFACE_RAISED,
            bg_press=Colors.SURFACE_ALT,
            fg=Colors.TEXT_SECONDARY,
            border=f"1px solid {Colors.BORDER}",
            padding="4px 8px",
        ))
        self.reset_cache_dir_btn.setToolTip("Clear all custom paths and use platform defaults")
        self.reset_cache_dir_btn.clicked.connect(self._reset_storage_defaults)
        layout.addWidget(self.reset_cache_dir_btn, alignment=Qt.AlignmentFlag.AlignRight)

        # ── BACKUPS section ────────────────────────────────────────────────────────────
        layout.addWidget(self._section_label("BACKUPS"))

        self.backup_dir = FolderRow(
            "Backup Location",
            "Where full device backups are stored on your PC. "
            "Leave empty for the default (~/iOpenPod_Backups/).",
        )
        layout.addWidget(self.backup_dir)

        self.backup_before_sync = ToggleRow(
            "Backup Before Sync",
            "Automatically create a full device backup before each sync. "
            "Recommended — allows you to restore your iPod if a sync goes wrong.",
            checked=True,
        )
        layout.addWidget(self.backup_before_sync)

        self.max_backups = ComboRow(
            "Max Backups",
            "Maximum number of backup snapshots to keep per device. "
            "Oldest backups are automatically removed when the limit is exceeded.",
            options=["5", "10", "20", "Unlimited"],
            current="10",
        )
        layout.addWidget(self.max_backups)

        layout.addStretch()
        scroll.setWidget(content)
        outer.addWidget(scroll)

    def _section_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setFont(QFont(FONT_FAMILY, 9, QFont.Weight.Bold))
        label.setStyleSheet(f"color: {Colors.TEXT_TERTIARY}; background: transparent; padding-left: 4px; padding-top: 8px;")
        return label

    def load_from_settings(self):
        """Populate UI controls from the current AppSettings."""
        from ..settings import get_settings
        s = get_settings()

        self.music_folder.value = s.music_folder
        self.write_back.value = s.write_back_to_pc
        self.compute_sound_check.value = s.compute_sound_check

        # Rating conflict strategy
        strategy_display = {
            "ipod_wins": "iPod Wins", "pc_wins": "PC Wins",
            "highest": "Highest", "lowest": "Lowest", "average": "Average",
        }
        rs_text = strategy_display.get(s.rating_conflict_strategy, "iPod Wins")
        idx = self.rating_strategy.combo.findText(rs_text)
        if idx >= 0:
            self.rating_strategy.combo.setCurrentIndex(idx)

        self.show_art.value = s.show_art_in_tracklist
        self.transcode_cache_dir.value = s.transcode_cache_dir
        self.settings_dir.value = s.settings_dir
        self.log_dir.value = s.log_dir
        self.ffmpeg_path.value = s.ffmpeg_path
        self.fpcalc_path.value = s.fpcalc_path

        self.backup_dir.value = s.backup_dir
        self.backup_before_sync.value = s.backup_before_sync

        # Refresh tool status indicators
        self._refresh_tool_status()

        # Max backups → combo text
        max_map = {0: "Unlimited", 5: "5", 10: "10", 20: "20"}
        mb_text = max_map.get(s.max_backups, "10")
        idx = self.max_backups.combo.findText(mb_text)
        if idx >= 0:
            self.max_backups.combo.setCurrentIndex(idx)

        # AAC bitrate → combo text
        bitrate_map = {128: "128 kbps", 192: "192 kbps", 256: "256 kbps", 320: "320 kbps"}
        br_text = bitrate_map.get(s.aac_bitrate, "256 kbps")
        idx = self.aac_bitrate.combo.findText(br_text)
        if idx >= 0:
            self.aac_bitrate.combo.setCurrentIndex(idx)

        # Video CRF → combo text
        crf_map = {18: "18 (High)", 20: "20 (Good)", 23: "23 (Balanced)", 26: "26 (Low)", 28: "28 (Very Low)"}
        crf_text = crf_map.get(s.video_crf, "23 (Balanced)")
        idx = self.video_crf.combo.findText(crf_text)
        if idx >= 0:
            self.video_crf.combo.setCurrentIndex(idx)

        # Video preset → combo text
        idx = self.video_preset.combo.findText(s.video_preset)
        if idx >= 0:
            self.video_preset.combo.setCurrentIndex(idx)

        # Sync workers → combo text
        workers_map = {0: "Auto", 1: "1", 2: "2", 4: "4", 6: "6", 8: "8"}
        sw_text = workers_map.get(s.sync_workers, "Auto")
        idx = self.sync_workers.combo.findText(sw_text)
        if idx >= 0:
            self.sync_workers.combo.setCurrentIndex(idx)

        # Connect signals to auto-save (only once)
        if not hasattr(self, '_signals_connected'):
            self._signals_connected = True
            self.music_folder.changed.connect(self._save)
            self.write_back.changed.connect(self._save)
            self.compute_sound_check.changed.connect(self._save)
            self.rating_strategy.changed.connect(self._save)
            self.aac_bitrate.changed.connect(self._save)
            self.video_crf.changed.connect(self._save)
            self.video_preset.changed.connect(self._save)
            self.sync_workers.changed.connect(self._save)
            self.show_art.changed.connect(self._save)
            self.transcode_cache_dir.changed.connect(self._save)
            self.settings_dir.changed.connect(self._save)
            self.log_dir.changed.connect(self._save)
            self.ffmpeg_path.changed.connect(self._save_and_refresh_tools)
            self.fpcalc_path.changed.connect(self._save_and_refresh_tools)
            self.backup_dir.changed.connect(self._save)
            self.backup_before_sync.changed.connect(self._save)
            self.max_backups.changed.connect(self._save)

    def _save(self, *_args):
        """Read all controls back into AppSettings and persist."""
        from ..settings import get_settings
        s = get_settings()

        s.music_folder = self.music_folder.value
        s.write_back_to_pc = self.write_back.value
        s.compute_sound_check = self.compute_sound_check.value

        # Rating conflict strategy
        strategy_keys = {
            "iPod Wins": "ipod_wins", "PC Wins": "pc_wins",
            "Highest": "highest", "Lowest": "lowest", "Average": "average",
        }
        s.rating_conflict_strategy = strategy_keys.get(self.rating_strategy.value, "ipod_wins")

        s.show_art_in_tracklist = self.show_art.value
        s.transcode_cache_dir = self.transcode_cache_dir.value
        s.settings_dir = self.settings_dir.value
        s.log_dir = self.log_dir.value
        s.ffmpeg_path = self.ffmpeg_path.value
        s.fpcalc_path = self.fpcalc_path.value
        s.backup_dir = self.backup_dir.value
        s.backup_before_sync = self.backup_before_sync.value

        # Parse max backups
        mb_text = self.max_backups.value
        s.max_backups = int(mb_text) if mb_text and mb_text != "Unlimited" else 0

        # Parse AAC bitrate
        br_text = self.aac_bitrate.value
        s.aac_bitrate = int(br_text.split()[0]) if br_text else 256

        # Parse video CRF (extract leading integer)
        crf_text = self.video_crf.value
        try:
            s.video_crf = int(crf_text.split()[0])
        except (ValueError, IndexError):
            s.video_crf = 23

        # Video preset (stored as-is)
        s.video_preset = self.video_preset.value or "fast"

        # Parse sync workers
        sw_text = self.sync_workers.value
        s.sync_workers = int(sw_text) if sw_text and sw_text != "Auto" else 0

        s.save()

    def _reset_storage_defaults(self):
        """Clear custom storage paths and revert to platform defaults."""
        self.transcode_cache_dir.value = ""
        self.settings_dir.value = ""
        self.log_dir.value = ""
        self.backup_dir.value = ""
        self._save()

    def _on_close(self):
        """Go back — settings are already saved on every change."""
        self.closed.emit()

    def _save_and_refresh_tools(self, *_args):
        """Save settings then refresh tool status indicators."""
        self._save()
        self._refresh_tool_status()

    def _refresh_tool_status(self):
        """Check whether ffmpeg and fpcalc are reachable and update the UI."""
        from SyncEngine.transcoder import find_ffmpeg
        from SyncEngine.audio_fingerprint import find_fpcalc

        ffmpeg = find_ffmpeg()
        self.ffmpeg_tool.set_status(bool(ffmpeg), ffmpeg or "")

        fpcalc = find_fpcalc()
        self.fpcalc_tool.set_status(bool(fpcalc), fpcalc or "")

    def _download_ffmpeg(self):
        """Download FFmpeg in a background thread."""
        self.ffmpeg_tool.set_downloading()
        import threading

        def _do():
            from SyncEngine.dependency_manager import download_ffmpeg
            download_ffmpeg()
            # Update UI from main thread
            from PyQt6.QtCore import QMetaObject, Qt as QtCore_Qt
            QMetaObject.invokeMethod(
                self, "_on_ffmpeg_downloaded",
                QtCore_Qt.ConnectionType.QueuedConnection,
            )

        threading.Thread(target=_do, daemon=True).start()

    def _download_fpcalc(self):
        """Download fpcalc in a background thread."""
        self.fpcalc_tool.set_downloading()
        import threading

        def _do():
            from SyncEngine.dependency_manager import download_fpcalc
            download_fpcalc()
            from PyQt6.QtCore import QMetaObject, Qt as QtCore_Qt
            QMetaObject.invokeMethod(
                self, "_on_fpcalc_downloaded",
                QtCore_Qt.ConnectionType.QueuedConnection,
            )

        threading.Thread(target=_do, daemon=True).start()

    @pyqtSlot()
    def _on_ffmpeg_downloaded(self):
        """Called on main thread after FFmpeg download completes."""
        self._refresh_tool_status()
        self.ffmpeg_tool.download_btn.setEnabled(True)
        self.ffmpeg_tool.download_btn.setText("Download")

    @pyqtSlot()
    def _on_fpcalc_downloaded(self):
        """Called on main thread after fpcalc download completes."""
        self._refresh_tool_status()
        self.fpcalc_tool.download_btn.setEnabled(True)
        self.fpcalc_tool.download_btn.setText("Download")
