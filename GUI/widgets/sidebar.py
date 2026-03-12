from PyQt6.QtCore import pyqtSignal, Qt, QRegularExpression, QSize
from PyQt6.QtWidgets import (
    QFrame, QPushButton, QVBoxLayout, QHBoxLayout,
    QLabel, QWidget, QProgressBar, QLineEdit, QScrollArea
)
from PyQt6.QtGui import QFont, QCursor, QFontMetrics, QRegularExpressionValidator
from .formatters import format_size, format_duration_human as format_duration
from ..ipod_images import get_ipod_image
from ..glyphs import glyph_icon, glyph_pixmap
from ..styles import (
    Colors, FONT_FAMILY, MONO_FONT_FAMILY, Metrics,
    btn_css, accent_btn_css,
    sidebar_nav_css, sidebar_nav_selected_css, toolbar_btn_css,
    LABEL_PRIMARY, LABEL_SECONDARY, LABEL_TERTIARY,
    make_separator, make_section_header,
)


# iTunes enforces 63 characters for iPod names; MHOD strings are UTF-16-LE
# so only printable Unicode is allowed (no control characters).
_MAX_IPOD_NAME_LEN = 63
_IPOD_NAME_RE = QRegularExpression(r"^[^\x00-\x1f\x7f]*$")


class _RenameLineEdit(QLineEdit):
    """QLineEdit that emits cancelled on Escape."""

    cancelled = pyqtSignal()
    focus_lost = pyqtSignal()

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setMaxLength(_MAX_IPOD_NAME_LEN)
        self.setValidator(QRegularExpressionValidator(_IPOD_NAME_RE, self))

    def keyPressEvent(self, a0):
        if a0 and a0.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
        else:
            super().keyPressEvent(a0)

    def focusOutEvent(self, a0):
        super().focusOutEvent(a0)
        self.focus_lost.emit()


class StatWidget(QWidget):
    """Widget showing a value and description label."""

    def __init__(self, value: str, label: str):
        super().__init__()
        self.setStyleSheet("background: transparent; border: none;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.value_label = QLabel(value)
        self.value_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_XXL, QFont.Weight.Bold))
        self.value_label.setStyleSheet(LABEL_PRIMARY())
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.value_label)

        self.desc_label = QLabel(label)
        self.desc_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_XS))
        self.desc_label.setStyleSheet(LABEL_TERTIARY())
        self.desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.desc_label)

    def setValue(self, value: str):
        """Update the value text."""
        self.value_label.setText(value)


class TechInfoRow(QWidget):
    """A single row of technical info: label and value."""

    def __init__(self, label: str, value: str = ""):
        super().__init__()
        self.setStyleSheet("background: transparent; border: none;")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, (3), 0, (3))
        layout.setSpacing((6))

        self.label_widget = QLabel(label)
        self.label_widget.setFont(QFont(FONT_FAMILY, Metrics.FONT_XS))
        self.label_widget.setStyleSheet(LABEL_TERTIARY())
        layout.addWidget(self.label_widget)

        layout.addStretch()

        self.value_widget = QLabel(value)
        self.value_widget.setFont(QFont(MONO_FONT_FAMILY, Metrics.FONT_XS))
        self.value_widget.setStyleSheet(LABEL_SECONDARY())
        self.value_widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.value_widget)

    def setValue(self, value: str):
        """Update the value text."""
        self.value_widget.setText(value)


class DeviceInfoCard(QFrame):
    """Card showing iPod device information and stats."""

    device_renamed = pyqtSignal(str)  # emits the new name

    def __init__(self):
        super().__init__()
        self._rename_edit: QLineEdit | None = None
        self.setStyleSheet(f"""
            QFrame {{
                background: {Colors.SURFACE_RAISED};
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-radius: {Metrics.BORDER_RADIUS_LG}px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins((14), (14), (14), (14))
        layout.setSpacing((8))

        # iPod icon and name row
        header_layout = QHBoxLayout()
        header_layout.setSpacing((8))

        self.icon_label = QLabel()
        px = glyph_pixmap("music", (32), Colors.TEXT_SECONDARY)
        if px:
            self.icon_label.setPixmap(px)
        else:
            self.icon_label.setText("♪")
            self.icon_label.setFont(QFont(FONT_FAMILY, (24)))
        self.icon_label.setFixedSize((52), (52))
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setStyleSheet("background: transparent; border: none;")
        header_layout.addWidget(self.icon_label)

        name_layout = QVBoxLayout()
        name_layout.setSpacing(0)
        self._name_layout = name_layout

        self.name_label = QLabel("No Device")
        self.name_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_XXL, QFont.Weight.Bold))
        self.name_label.setStyleSheet(LABEL_PRIMARY())
        self.name_label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.name_label.setToolTip("Click to rename your iPod")
        self.name_label.mousePressEvent = lambda ev: self._start_rename()
        name_layout.addWidget(self.name_label)

        self.model_label = QLabel("Press Select to choose your iPod")
        self.model_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.model_label.setStyleSheet(LABEL_SECONDARY())
        self.model_label.setWordWrap(True)
        name_layout.addWidget(self.model_label)

        header_layout.addLayout(name_layout)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        # Separator
        sep = make_separator()
        layout.addWidget(sep)

        # Stats grid
        stats_widget = QWidget()
        stats_widget.setStyleSheet("background: transparent; border: none;")
        stats_layout = QHBoxLayout(stats_widget)
        stats_layout.setContentsMargins(0, (6), 0, (2))
        stats_layout.setSpacing((8))

        self.items_stat = StatWidget("0", "items")
        self.size_stat = StatWidget("0 GB", "music")
        self.duration_stat = StatWidget("0h", "playtime")
        stats_layout.addWidget(self.items_stat)
        stats_layout.addWidget(self.size_stat)
        stats_layout.addWidget(self.duration_stat)

        layout.addWidget(stats_widget)

        # Technical details section (collapsible)
        self.tech_toggle = QPushButton("Technical Details")
        _chev = glyph_icon("chevron-right", (12), Colors.TEXT_TERTIARY)
        if _chev:
            self.tech_toggle.setIcon(_chev)
            self.tech_toggle.setIconSize(QSize((12), (12)))
        self.tech_toggle.setFont(QFont(FONT_FAMILY, Metrics.FONT_XS))
        self.tech_toggle.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                color: {Colors.TEXT_TERTIARY};
                text-align: left;
                padding: 2px 0;
            }}
            QPushButton:hover {{
                color: {Colors.TEXT_SECONDARY};
            }}
        """)
        self.tech_toggle.clicked.connect(self._toggle_tech_details)
        layout.addWidget(self.tech_toggle)

        # Technical details container
        self.tech_container = QWidget()
        self.tech_container.setStyleSheet("background: transparent; border: none;")
        self.tech_container.hide()  # Hidden by default
        tech_layout = QVBoxLayout(self.tech_container)
        tech_layout.setContentsMargins(0, (6), 0, 0)
        tech_layout.setSpacing(0)

        # Technical info rows — identity
        self.model_num_row = TechInfoRow("Model #:", "—")
        self.serial_row = TechInfoRow("Serial:", "—")
        self.firmware_row = TechInfoRow("Firmware:", "—")
        self.board_row = TechInfoRow("Board:", "—")
        self.fw_guid_row = TechInfoRow("FW GUID:", "—")
        self.usb_pid_row = TechInfoRow("USB PID:", "—")
        self.id_method_row = TechInfoRow("ID Method:", "—")

        # Technical info rows — database / security
        self.db_version_row = TechInfoRow("Database:", "—")
        self.db_id_row = TechInfoRow("DB ID:", "—")
        self.checksum_row = TechInfoRow("Checksum:", "—")
        self.hash_scheme_row = TechInfoRow("Hash Scheme:", "—")

        # Technical info rows — storage & artwork
        self.disk_size_row = TechInfoRow("Disk Size:", "—")
        self.free_space_row = TechInfoRow("Free Space:", "—")
        self.art_formats_row = TechInfoRow("Art Formats:", "—")

        for w in (
            self.model_num_row, self.serial_row, self.firmware_row,
            self.board_row, self.fw_guid_row, self.usb_pid_row,
            self.id_method_row,
            self.db_version_row, self.db_id_row,
            self.checksum_row, self.hash_scheme_row,
            self.disk_size_row, self.free_space_row, self.art_formats_row,
        ):
            tech_layout.addWidget(w)

        layout.addWidget(self.tech_container)

        # Storage bar (optional, for when we have capacity info)
        self.storage_bar = QProgressBar()
        self.storage_bar.setFixedHeight((4))
        self.storage_bar.setTextVisible(False)
        self.storage_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {Colors.SHADOW};
                border: none;
                border-radius: {(2)}px;
            }}
            QProgressBar::chunk {{
                background: {Colors.ACCENT};
                border-radius: {(2)}px;
            }}
        """)
        self.storage_bar.hide()  # Hidden until we have capacity data
        layout.addWidget(self.storage_bar)

        self._tech_expanded = False

    def _start_rename(self, event=None):
        """Show an inline QLineEdit to rename the iPod."""
        current = self.name_label.text()
        if current == "No Device" or self._rename_edit is not None:
            return

        self._rename_edit = _RenameLineEdit(current)
        self._rename_edit.setFont(QFont(FONT_FAMILY, Metrics.FONT_XXL, QFont.Weight.Bold))
        self._rename_edit.setStyleSheet(f"""
            QLineEdit {{
                color: {Colors.TEXT_PRIMARY};
                background: {Colors.SHADOW_DEEP};
                border: 1px solid {Colors.ACCENT};
                border-radius: {(4)}px;
                padding: 1px {(4)}px;
            }}
        """)
        self._rename_edit.selectAll()
        self._rename_edit.returnPressed.connect(self._finish_rename)
        self._rename_edit.focus_lost.connect(self._finish_rename)
        self._rename_edit.cancelled.connect(self._cancel_rename)

        # Replace name_label with the line edit in the name VBox
        idx = self._name_layout.indexOf(self.name_label)
        self.name_label.hide()
        self._name_layout.insertWidget(idx, self._rename_edit)
        self._rename_edit.setFocus()

    def _cancel_rename(self):
        """Cancel the rename and restore the original label."""
        if self._rename_edit is None:
            return
        self._rename_edit.hide()
        self._rename_edit.deleteLater()
        self._rename_edit = None
        self.name_label.show()

    def _finish_rename(self):
        """Accept the rename and emit the new name."""
        if self._rename_edit is None:
            return

        edit = self._rename_edit
        self._rename_edit = None  # prevent re-entrant call from .hide()

        new_name = edit.text().strip()
        old_name = self.name_label.text()

        edit.hide()
        edit.deleteLater()
        self.name_label.show()

        if new_name and new_name != old_name:
            self.name_label.setText(new_name)
            self._fit_name_font(new_name)
            self.device_renamed.emit(new_name)

    def _toggle_tech_details(self):
        """Toggle technical details visibility."""
        self._tech_expanded = not self._tech_expanded
        self.tech_container.setVisible(self._tech_expanded)
        chev = "chevron-down" if self._tech_expanded else "chevron-right"
        icon = glyph_icon(chev, (12), Colors.TEXT_TERTIARY)
        if icon:
            self.tech_toggle.setIcon(icon)

    def _fit_name_font(self, text: str):
        """Shrink the device name font if the text is too wide for the card."""
        max_w = (130)  # approximate width available for the name
        for size in (Metrics.FONT_XXL, Metrics.FONT_XL, Metrics.FONT_LG, Metrics.FONT_MD):
            f = QFont(FONT_FAMILY, size, QFont.Weight.Bold)
            if QFontMetrics(f).horizontalAdvance(text) <= max_w:
                self.name_label.setFont(f)
                return
        self.name_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD, QFont.Weight.Bold))

    def update_device_info(self, name: str, model: str = ""):
        """Update device name and model."""
        display = name or "No Device"
        self.name_label.setText(display)
        self._fit_name_font(display)
        self.model_label.setText(model)

        # Try to load real product photo from centralized store
        family = ""
        generation = ""
        color = ""
        try:
            from device_info import get_current_device
            dev = get_current_device()
            if dev:
                family = dev.model_family or ""
                generation = dev.generation or ""
                color = dev.color or ""
        except Exception:
            pass
        if not family and model:
            family = model

        photo = get_ipod_image(family, generation, (48), color) if family else None
        if photo and not photo.isNull():
            self.icon_label.setPixmap(photo)
            self.icon_label.setFont(QFont())  # Clear emoji font
        else:
            # Fallback to SVG music icon
            px = glyph_pixmap("music", (32), Colors.TEXT_SECONDARY)
            if px:
                self.icon_label.setPixmap(px)
            else:
                self.icon_label.setText("♪")
                self.icon_label.setFont(QFont(FONT_FAMILY, 24))

        # Update technical details from centralized store
        try:
            from device_info import get_current_device
            dev = get_current_device()
        except Exception:
            dev = None

        if dev:
            self.model_num_row.setValue(dev.model_number or '—')
            self.serial_row.setValue(dev.serial or '—')
            self.firmware_row.setValue(dev.firmware or '—')
            self.board_row.setValue(dev.board or '—')
            self.fw_guid_row.setValue(dev.firewire_guid or '—')
            self.usb_pid_row.setValue(f"0x{dev.usb_pid:04X}" if dev.usb_pid else '—')
            self.id_method_row.setValue(dev.identification_method or '—')

            # Checksum / hashing — derive display name from the canonical enum
            from ipod_models import ChecksumType
            try:
                cs_name = ChecksumType(dev.checksum_type).name
            except ValueError:
                cs_name = 'Unknown'
            self.checksum_row.setValue(cs_name)
            scheme_names = {-1: '—', 0: 'None', 1: 'Scheme 1', 2: 'Scheme 2'}
            self.hash_scheme_row.setValue(scheme_names.get(dev.hashing_scheme, str(dev.hashing_scheme)))

            # Storage
            if dev.disk_size_gb > 0:
                self.disk_size_row.setValue(f"{dev.disk_size_gb:.1f} GB")
            if dev.free_space_gb > 0:
                self.free_space_row.setValue(f"{dev.free_space_gb:.1f} GB")

            # Storage bar
            if dev.disk_size_gb > 0:
                used_pct = int(((dev.disk_size_gb - dev.free_space_gb) / dev.disk_size_gb) * 100)
                self.storage_bar.setValue(max(0, min(100, used_pct)))
                self.storage_bar.setToolTip(
                    f"{dev.free_space_gb:.1f} GB free of {dev.disk_size_gb:.1f} GB"
                )
                self.storage_bar.show()

            # Artwork formats
            if dev.artwork_formats:
                fmt_strs = [f"{fid}" for fid in sorted(dev.artwork_formats)]
                self.art_formats_row.setValue(", ".join(fmt_strs))
            else:
                self.art_formats_row.setValue('—')

    def update_database_info(self, version_hex: str, version_name: str, db_id: int):
        """Update database technical information."""
        self.db_version_row.setValue(f"{version_hex} ({version_name})")
        # Format database ID as hex
        if db_id:
            self.db_id_row.setValue(f"{db_id:016X}")
        else:
            self.db_id_row.setValue("—")

    def update_stats(self, tracks: int, albums: int, size_bytes: int, duration_ms: int,
                     videos: int = 0, podcasts: int = 0, audiobooks: int = 0):
        """Update library statistics."""
        total_items = tracks + videos + podcasts + audiobooks
        self.items_stat.setValue(f"{total_items:,}")
        self.size_stat.setValue(format_size(size_bytes))
        self.duration_stat.setValue(format_duration(duration_ms))

        # Build items description
        parts = []
        if tracks > 0:
            parts.append(f"{tracks:,} tracks")
        if albums > 0:
            parts.append(f"{albums:,} albums")
        self.items_stat.desc_label.setText("items")

    def clear(self):
        """Clear all info (when no device selected)."""
        self.name_label.setText("No Device")
        self._fit_name_font("No Device")
        self.model_label.setText("Press Select to choose your iPod")
        self.items_stat.setValue("—")
        self.size_stat.setValue("—")
        self.duration_stat.setValue("—")
        self.storage_bar.hide()
        # Clear tech details
        for row in (
            self.model_num_row, self.serial_row, self.firmware_row,
            self.board_row, self.fw_guid_row, self.usb_pid_row,
            self.id_method_row,
            self.db_version_row, self.db_id_row,
            self.checksum_row, self.hash_scheme_row,
            self.disk_size_row, self.free_space_row, self.art_formats_row,
        ):
            row.setValue("—")


class Sidebar(QFrame):
    category_changed = pyqtSignal(str)
    device_renamed = pyqtSignal(str)  # emits new iPod name

    # Categories that only make sense on video-capable iPods
    _VIDEO_CATEGORIES = frozenset({"Videos", "Movies", "TV Shows", "Music Videos"})

    # Categories that only make sense when podcast support is present
    _PODCAST_CATEGORIES = frozenset({"Podcasts"})

    category_glyphs = {
        "Albums": "music",
        "Artists": "user",
        "Tracks": "music",
        "Playlists": "annotation-dots",
        "Genres": "grid",
        "Podcasts": "broadcast",
        "Audiobooks": "book",
        "Videos": "video",
        "Movies": "film",
        "TV Shows": "monitor",
        "Music Videos": "video",
    }

    def __init__(self):
        super().__init__()
        self.setStyleSheet(f"""
            QFrame#sidebar {{
                background-color: {Colors.SURFACE};
                border: 1px solid {Colors.BORDER};
                border-radius: {Metrics.BORDER_RADIUS_LG}px;
            }}
        """)
        self.setObjectName("sidebar")

        self.sidebarLayout = QVBoxLayout(self)
        self.sidebarLayout.setContentsMargins((10), (12), (10), (12))
        self.sidebarLayout.setSpacing((10))
        self.setFixedWidth(Metrics.SIDEBAR_WIDTH)

        # Device info card at top
        self.device_card = DeviceInfoCard()
        self.device_card.device_renamed.connect(self.device_renamed)
        self.sidebarLayout.addWidget(self.device_card)

        # Device select buttons - row 1
        self.deviceSelectLayout = QHBoxLayout()
        self.deviceSelectLayout.setContentsMargins(0, 0, 0, 0)
        self.deviceSelectLayout.setSpacing((6))

        self.deviceButton = QPushButton("Select")
        self.rescanButton = QPushButton("Rescan")

        self.deviceButton.setStyleSheet(toolbar_btn_css())
        self.rescanButton.setStyleSheet(toolbar_btn_css())
        self.deviceButton.setFont(QFont(FONT_FAMILY, Metrics.FONT_LG, QFont.Weight.DemiBold))
        self.rescanButton.setFont(QFont(FONT_FAMILY, Metrics.FONT_LG, QFont.Weight.DemiBold))

        _icon_sz = QSize((20), (20))
        _bi = glyph_icon("tablet", (20), Colors.TEXT_SECONDARY)
        if _bi:
            self.deviceButton.setIcon(_bi)
            self.deviceButton.setIconSize(_icon_sz)
        _bi = glyph_icon("refresh", (20), Colors.TEXT_SECONDARY)
        if _bi:
            self.rescanButton.setIcon(_bi)
            self.rescanButton.setIconSize(_icon_sz)

        self.deviceSelectLayout.addWidget(self.deviceButton)
        self.deviceSelectLayout.addWidget(self.rescanButton)

        self.sidebarLayout.addLayout(self.deviceSelectLayout)

        # Sync button - row 2 (full width)
        self.syncButton = QPushButton("Sync with PC")
        self.syncButton.setStyleSheet(accent_btn_css())
        self.syncButton.setFont(QFont(FONT_FAMILY, Metrics.FONT_LG, QFont.Weight.DemiBold))
        _bi = glyph_icon("download", (20), Colors.TEXT_ON_ACCENT)
        if _bi:
            self.syncButton.setIcon(_bi)
            self.syncButton.setIconSize(_icon_sz)
        self.sidebarLayout.addWidget(self.syncButton)

        # Backup button
        self.backupButton = QPushButton("Backups")
        self.backupButton.setFont(QFont(FONT_FAMILY, Metrics.FONT_LG))
        self.backupButton.setStyleSheet(sidebar_nav_css())
        _bi = glyph_icon("archive", (20), Colors.TEXT_SECONDARY)
        if _bi:
            self.backupButton.setIcon(_bi)
            self.backupButton.setIconSize(_icon_sz)
        self.sidebarLayout.addWidget(self.backupButton)

        self.sidebarLayout.addWidget(make_separator())

        # ── Scrollable library section ──────────────────────────────
        lib_scroll = QScrollArea()
        lib_scroll.setWidgetResizable(True)
        lib_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        lib_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        lib_scroll.setFrameShape(QFrame.Shape.NoFrame)
        lib_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        lib_container = QWidget()
        lib_container.setStyleSheet("background: transparent;")
        lib_layout = QVBoxLayout(lib_container)
        lib_layout.setContentsMargins(0, 0, 0, 0)
        lib_layout.setSpacing((1))

        lib_label = make_section_header("Library")
        lib_label.setStyleSheet(lib_label.styleSheet() + f" padding-left: {(4)}px;")
        lib_layout.addWidget(lib_label)

        self.buttons = {}
        self._button_icons: dict[str, str] = {}
        _nav_icon_sz = QSize((20), (20))

        for category, icon_name in self.category_glyphs.items():
            btn = QPushButton(category)
            btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_LG))
            icon = glyph_icon(icon_name, (20), Colors.TEXT_SECONDARY)
            if icon:
                btn.setIcon(icon)
                btn.setIconSize(_nav_icon_sz)

            btn.setStyleSheet(sidebar_nav_css())

            btn.clicked.connect(
                lambda clicked, category=category: self.selectCategory(category))

            lib_layout.addWidget(btn)
            self.buttons[category] = btn
            self._button_icons[category] = icon_name

        lib_layout.addStretch()
        lib_scroll.setWidget(lib_container)
        self.sidebarLayout.addWidget(lib_scroll, 1)  # stretch factor 1

        self.sidebarLayout.addWidget(make_separator())

        # Settings button at bottom
        self.settingsButton = QPushButton("Settings")
        self.settingsButton.setFont(QFont(FONT_FAMILY, Metrics.FONT_LG))
        self.settingsButton.setStyleSheet(btn_css(
            bg="transparent",
            bg_hover=Colors.SURFACE_RAISED,
            bg_press=Colors.SURFACE,
            fg=Colors.TEXT_TERTIARY,
            padding=f"{(7)}px {(12)}px",
            extra="text-align: left;",
        ))
        _bi = glyph_icon("settings", (20), Colors.TEXT_TERTIARY)
        if _bi:
            self.settingsButton.setIcon(_bi)
            self.settingsButton.setIconSize(QSize((20), (20)))
        self.sidebarLayout.addWidget(self.settingsButton)

        self.selectedCategory = list(self.category_glyphs.keys())[0]
        self.selectCategory(self.selectedCategory)

    def updateDeviceInfo(self, name: str, model: str, tracks: int, albums: int,
                         size_bytes: int, duration_ms: int,
                         db_version_hex: str = "", db_version_name: str = "",
                         db_id: int = 0, videos: int = 0,
                         podcasts: int = 0, audiobooks: int = 0):
        """Update the device info card with current device data."""
        self.device_card.update_device_info(name, model)
        self.device_card.update_stats(tracks, albums, size_bytes, duration_ms,
                                      videos=videos, podcasts=podcasts, audiobooks=audiobooks)
        if db_version_hex:
            self.device_card.update_database_info(db_version_hex, db_version_name, db_id)

    def clearDeviceInfo(self):
        """Clear device info when no device is selected."""
        self.device_card.clear()
        # Show all categories again when no device is selected
        self.setVideoVisible(True)
        self.setPodcastVisible(True)

    def setVideoVisible(self, visible: bool):
        """Show or hide video-related sidebar categories.

        Called after device identification to hide video categories on iPods
        that don't support video (e.g. Mini, Nano 1G/2G, Shuffle, iPod 1G-4G).
        If the currently selected category is being hidden, switch to Albums.
        """
        for cat in self._VIDEO_CATEGORIES:
            btn = self.buttons.get(cat)
            if btn:
                btn.setVisible(visible)
        # If the selected category is being hidden, switch to a safe default
        if not visible and self.selectedCategory in self._VIDEO_CATEGORIES:
            self.selectCategory("Albums")

    def setPodcastVisible(self, visible: bool):
        """Show or hide podcast sidebar categories.

        Called after device identification to hide podcasts on iPods
        that don't support them (pre-5G, Shuffle).
        """
        for cat in self._PODCAST_CATEGORIES:
            btn = self.buttons.get(cat)
            if btn:
                btn.setVisible(visible)
        if not visible and self.selectedCategory in self._PODCAST_CATEGORIES:
            self.selectCategory("Albums")

    def selectCategory(self, category):
        self._style_nav_btn(self.selectedCategory, selected=False)
        self.selectedCategory = category
        self._style_nav_btn(category, selected=True)
        self.category_changed.emit(category)

    def _style_nav_btn(self, category: str, selected: bool):
        btn = self.buttons[category]
        btn.setStyleSheet(sidebar_nav_selected_css() if selected else sidebar_nav_css())
        icon_name = self._button_icons.get(category)
        if icon_name:
            color = Colors.ACCENT if selected else Colors.TEXT_SECONDARY
            icon = glyph_icon(icon_name, (20), color)
            if icon:
                btn.setIcon(icon)
