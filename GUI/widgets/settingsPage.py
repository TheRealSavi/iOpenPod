"""
Settings page widget for iOpenPod.

Displayed as a full-page view in the central stack (like the sync review page).
Matches the dark translucent UI style of the rest of the app.
"""

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QComboBox, QFrame, QScrollArea, QFileDialog,
)
from PyQt6.QtGui import QFont


# ── Reusable row widgets ────────────────────────────────────────────────────

class SettingRow(QFrame):
    """A single setting row with label, description, and control on the right."""

    def __init__(self, title: str, description: str = ""):
        super().__init__()
        self.setStyleSheet("""
            QFrame {
                background: rgba(255,255,255,15);
                border: 1px solid rgba(255,255,255,30);
                border-radius: 8px;
            }
        """)

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(16, 12, 16, 12)
        self._layout.setSpacing(16)

        # Left side: title + description
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)

        self.title_label = QLabel(title)
        self.title_label.setFont(QFont("Segoe UI", 11, QFont.Weight.DemiBold))
        self.title_label.setStyleSheet("color: white; background: transparent; border: none;")
        text_layout.addWidget(self.title_label)

        if description:
            self.desc_label = QLabel(description)
            self.desc_label.setFont(QFont("Segoe UI", 9))
            self.desc_label.setStyleSheet("color: rgba(255,255,255,120); background: transparent; border: none;")
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
        self.checkbox.setStyleSheet("""
            QCheckBox {
                background: transparent;
                border: none;
            }
            QCheckBox::indicator {
                width: 40px;
                height: 22px;
                border-radius: 11px;
                background: rgba(255,255,255,40);
                border: 1px solid rgba(255,255,255,60);
            }
            QCheckBox::indicator:checked {
                background: #409cff;
                border: 1px solid #409cff;
            }
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
        self.combo.setFixedWidth(120)
        self.combo.setFont(QFont("Segoe UI", 10))
        self.combo.setStyleSheet("""
            QComboBox {
                background: rgba(255,255,255,30);
                border: 1px solid rgba(255,255,255,50);
                border-radius: 6px;
                color: white;
                padding: 4px 8px;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox::down-arrow {
                image: none;
                border: none;
            }
            QComboBox QAbstractItemView {
                background: #2a2a2a;
                color: white;
                selection-background-color: #409cff;
                border: 1px solid rgba(255,255,255,50);
            }
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
        self.path_label.setFont(QFont("Segoe UI", 9))
        self.path_label.setStyleSheet("color: rgba(255,255,255,150); background: transparent; border: none;")
        self.path_label.setMinimumWidth(120)
        self.path_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        right_layout.addWidget(self.path_label)

        self.browse_btn = QPushButton("Browse…")
        self.browse_btn.setFont(QFont("Segoe UI", 9))
        self.browse_btn.setFixedWidth(80)
        self.browse_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,30);
                border: 1px solid rgba(255,255,255,50);
                border-radius: 6px;
                color: white;
                padding: 4px 8px;
            }
            QPushButton:hover {
                background: rgba(255,255,255,50);
            }
        """)
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
        back_btn.setFont(QFont("Segoe UI", 11))
        back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        back_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                color: #409cff;
                padding: 4px 8px;
            }
            QPushButton:hover { color: #60b0ff; }
        """)
        back_btn.clicked.connect(self._on_close)
        tb_layout.addWidget(back_btn)

        title = QLabel("Settings")
        title.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        title.setStyleSheet("color: white; background: transparent;")
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
            QScrollBar:vertical {
                background: transparent;
                width: 8px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255,255,255,40);
                border-radius: 4px;
                min-height: 30px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 8, 24, 24)
        layout.setSpacing(12)

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

        self.transcode_timeout = ComboRow(
            "Transcode Timeout",
            "Maximum time to wait for FFmpeg per file. Increase for large FLAC files on slower machines.",
            options=["2 minutes", "5 minutes", "10 minutes", "30 minutes"],
            current="5 minutes",
        )
        layout.addWidget(self.transcode_timeout)

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

        self.reset_cache_dir_btn = QPushButton("Reset to Default")
        self.reset_cache_dir_btn.setFont(QFont("Segoe UI", 9))
        self.reset_cache_dir_btn.setFixedWidth(130)
        self.reset_cache_dir_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reset_cache_dir_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,20);
                border: 1px solid rgba(255,255,255,40);
                border-radius: 6px;
                color: rgba(255,255,255,150);
                padding: 4px 8px;
            }
            QPushButton:hover {
                background: rgba(255,255,255,40);
                color: white;
            }
        """)
        self.reset_cache_dir_btn.setToolTip("Clear both custom paths and use platform defaults")
        self.reset_cache_dir_btn.clicked.connect(self._reset_storage_defaults)
        layout.addWidget(self.reset_cache_dir_btn, alignment=Qt.AlignmentFlag.AlignRight)

        layout.addStretch()
        scroll.setWidget(content)
        outer.addWidget(scroll)

    def _section_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        label.setStyleSheet("color: rgba(255,255,255,100); background: transparent; padding-left: 4px; padding-top: 8px;")
        return label

    def load_from_settings(self):
        """Populate UI controls from the current AppSettings."""
        from ..settings import get_settings
        s = get_settings()

        self.music_folder.value = s.music_folder
        self.write_back.value = s.write_back_to_pc
        self.show_art.value = s.show_art_in_tracklist
        self.transcode_cache_dir.value = s.transcode_cache_dir
        self.settings_dir.value = s.settings_dir

        # AAC bitrate → combo text
        bitrate_map = {128: "128 kbps", 192: "192 kbps", 256: "256 kbps", 320: "320 kbps"}
        br_text = bitrate_map.get(s.aac_bitrate, "256 kbps")
        idx = self.aac_bitrate.combo.findText(br_text)
        if idx >= 0:
            self.aac_bitrate.combo.setCurrentIndex(idx)

        # Transcode timeout → combo text
        timeout_map = {120: "2 minutes", 300: "5 minutes", 600: "10 minutes", 1800: "30 minutes"}
        tt_text = timeout_map.get(s.transcode_timeout, "5 minutes")
        idx = self.transcode_timeout.combo.findText(tt_text)
        if idx >= 0:
            self.transcode_timeout.combo.setCurrentIndex(idx)

        # Connect signals to auto-save
        self.music_folder.changed.connect(self._save)
        self.write_back.changed.connect(self._save)
        self.aac_bitrate.changed.connect(self._save)
        self.transcode_timeout.changed.connect(self._save)
        self.show_art.changed.connect(self._save)
        self.transcode_cache_dir.changed.connect(self._save)
        self.settings_dir.changed.connect(self._save)

    def _save(self, *_args):
        """Read all controls back into AppSettings and persist."""
        from ..settings import get_settings
        s = get_settings()

        s.music_folder = self.music_folder.value
        s.write_back_to_pc = self.write_back.value
        s.show_art_in_tracklist = self.show_art.value
        s.transcode_cache_dir = self.transcode_cache_dir.value
        s.settings_dir = self.settings_dir.value

        # Parse AAC bitrate
        br_text = self.aac_bitrate.value
        s.aac_bitrate = int(br_text.split()[0]) if br_text else 256

        # Parse timeout
        tt_text = self.transcode_timeout.value
        timeout_values = {"2 minutes": 120, "5 minutes": 300, "10 minutes": 600, "30 minutes": 1800}
        s.transcode_timeout = timeout_values.get(tt_text, 300)

        s.save()

    def _reset_storage_defaults(self):
        """Clear custom storage paths and revert to platform defaults."""
        self.transcode_cache_dir.value = ""
        self.settings_dir.value = ""
        self._save()

    def _on_close(self):
        """Go back — settings are already saved on every change."""
        self.closed.emit()
