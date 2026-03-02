from PyQt6.QtCore import pyqtSignal, Qt, QRegularExpression
from PyQt6.QtWidgets import (
    QFrame, QPushButton, QVBoxLayout, QHBoxLayout,
    QLabel, QWidget, QProgressBar, QLineEdit
)
from PyQt6.QtGui import QFont, QCursor, QRegularExpressionValidator
from .formatters import format_size, format_duration_human as format_duration
from ..ipod_images import get_ipod_image
from ..styles import Colors, FONT_FAMILY, MONO_FONT_FAMILY, Metrics, btn_css, accent_btn_css


# iTunes enforces 63 characters for iPod names; MHOD strings are UTF-16-LE
# so only printable Unicode is allowed (no control characters).
_MAX_IPOD_NAME_LEN = 63
_IPOD_NAME_RE = QRegularExpression(r"^[^\x00-\x1f\x7f]*$")


class _RenameLineEdit(QLineEdit):
    """QLineEdit that emits cancelled on Escape."""

    cancelled = pyqtSignal()

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setMaxLength(_MAX_IPOD_NAME_LEN)
        self.setValidator(QRegularExpressionValidator(_IPOD_NAME_RE, self))

    def keyPressEvent(self, a0):
        if a0 and a0.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
        else:
            super().keyPressEvent(a0)


class StatWidget(QWidget):
    """Widget showing a value and description label."""

    def __init__(self, value: str, label: str):
        super().__init__()
        self.setStyleSheet("background: transparent; border: none;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)

        self.value_label = QLabel(value)
        self.value_label.setFont(QFont(FONT_FAMILY, 13, QFont.Weight.Bold))
        self.value_label.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; background: transparent; border: none;")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.value_label)

        self.desc_label = QLabel(label)
        self.desc_label.setFont(QFont(FONT_FAMILY, 8))
        self.desc_label.setStyleSheet(f"color: {Colors.TEXT_TERTIARY}; background: transparent; border: none;")
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
        layout.setContentsMargins(0, 1, 0, 1)
        layout.setSpacing(4)

        self.label_widget = QLabel(label)
        self.label_widget.setFont(QFont(FONT_FAMILY, 8))
        self.label_widget.setStyleSheet(f"color: {Colors.TEXT_TERTIARY}; background: transparent; border: none;")
        layout.addWidget(self.label_widget)

        layout.addStretch()

        self.value_widget = QLabel(value)
        self.value_widget.setFont(QFont(MONO_FONT_FAMILY, 8))
        self.value_widget.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; background: transparent; border: none;")
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
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(64,156,255,60), stop:1 rgba(40,100,180,60));
                border: 1px solid rgba(64,156,255,70);
                border-radius: {Metrics.BORDER_RADIUS_LG}px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # iPod icon and name row
        header_layout = QHBoxLayout()
        header_layout.setSpacing(8)

        self.icon_label = QLabel("🎵")
        self.icon_label.setFont(QFont(FONT_FAMILY, 24))
        self.icon_label.setFixedSize(52, 52)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setStyleSheet("background: transparent; border: none;")
        header_layout.addWidget(self.icon_label)

        name_layout = QVBoxLayout()
        name_layout.setSpacing(0)
        self._name_layout = name_layout

        self.name_label = QLabel("No Device")
        self.name_label.setFont(QFont(FONT_FAMILY, 13, QFont.Weight.Bold))
        self.name_label.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; background: transparent; border: none;")
        self.name_label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.name_label.setToolTip("Click to rename your iPod")
        self.name_label.mousePressEvent = lambda ev: self._start_rename()
        name_layout.addWidget(self.name_label)

        self.model_label = QLabel("")
        self.model_label.setFont(QFont(FONT_FAMILY, 9))
        self.model_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; background: transparent; border: none;")
        self.model_label.setWordWrap(True)
        name_layout.addWidget(self.model_label)

        header_layout.addLayout(name_layout)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        # Separator
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background-color: rgba(255,255,255,30); border: none;")
        layout.addWidget(sep)

        # Stats grid
        stats_widget = QWidget()
        stats_widget.setStyleSheet("background: transparent; border: none;")
        stats_layout = QVBoxLayout(stats_widget)
        stats_layout.setContentsMargins(0, 4, 0, 0)
        stats_layout.setSpacing(6)

        # Row 1: Tracks and Albums
        row1 = QHBoxLayout()
        self.tracks_stat = StatWidget("0", "tracks")
        self.albums_stat = StatWidget("0", "albums")
        row1.addWidget(self.tracks_stat)
        row1.addWidget(self.albums_stat)
        stats_layout.addLayout(row1)

        # Row 2: Size and Duration
        row2 = QHBoxLayout()
        self.size_stat = StatWidget("0 GB", "music")
        self.duration_stat = StatWidget("0h", "playtime")
        row2.addWidget(self.size_stat)
        row2.addWidget(self.duration_stat)
        stats_layout.addLayout(row2)

        layout.addWidget(stats_widget)

        # Technical details section (collapsible)
        self.tech_toggle = QPushButton("▶ Technical Details")
        self.tech_toggle.setFont(QFont(FONT_FAMILY, 8))
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
        tech_layout.setContentsMargins(0, 4, 0, 0)
        tech_layout.setSpacing(2)

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
        self.storage_bar.setFixedHeight(5)
        self.storage_bar.setTextVisible(False)
        self.storage_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: rgba(0,0,0,40);
                border: none;
                border-radius: 2px;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {Colors.ACCENT}, stop:1 {Colors.ACCENT_LIGHT});
                border-radius: 2px;
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
        self._rename_edit.setFont(QFont(FONT_FAMILY, 13, QFont.Weight.Bold))
        self._rename_edit.setStyleSheet(f"""
            QLineEdit {{
                color: {Colors.TEXT_PRIMARY};
                background: rgba(0,0,0,60);
                border: 1px solid {Colors.ACCENT};
                border-radius: 4px;
                padding: 1px 4px;
            }}
        """)
        self._rename_edit.selectAll()
        self._rename_edit.returnPressed.connect(self._finish_rename)
        self._rename_edit.editingFinished.connect(self._finish_rename)
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

        new_name = self._rename_edit.text().strip()
        old_name = self.name_label.text()

        # Remove the edit widget
        self._rename_edit.hide()
        self._rename_edit.deleteLater()
        self._rename_edit = None
        self.name_label.show()

        if new_name and new_name != old_name:
            self.name_label.setText(new_name)
            self.device_renamed.emit(new_name)

    def _toggle_tech_details(self):
        """Toggle technical details visibility."""
        self._tech_expanded = not self._tech_expanded
        self.tech_container.setVisible(self._tech_expanded)
        self.tech_toggle.setText("▼ Technical Details" if self._tech_expanded else "▶ Technical Details")

    def update_device_info(self, name: str, model: str = ""):
        """Update device name and model."""
        self.name_label.setText(name or "No Device")
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

        photo = get_ipod_image(family, generation, 48, color) if family else None
        if photo and not photo.isNull():
            self.icon_label.setPixmap(photo)
            self.icon_label.setFont(QFont())  # Clear emoji font
        else:
            # Fallback to emoji
            model_lower = model.lower() if model else ""
            if "classic" in model_lower:
                self.icon_label.setText("📱")
            elif "nano" in model_lower:
                self.icon_label.setText("🎵")
            elif "shuffle" in model_lower:
                self.icon_label.setText("🔀")
            elif "mini" in model_lower:
                self.icon_label.setText("🎶")
            elif "video" in model_lower or "photo" in model_lower:
                self.icon_label.setText("📱")
            else:
                self.icon_label.setText("🎵")
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

            # Checksum / hashing
            checksum_names = {0: 'None', 1: 'HASH58', 2: 'HASH72', 98: 'HASHAB', 99: 'Unknown'}
            self.checksum_row.setValue(checksum_names.get(dev.checksum_type, 'Unknown'))
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

    def update_stats(self, tracks: int, albums: int, size_bytes: int, duration_ms: int):
        """Update library statistics."""
        self.tracks_stat.setValue(f"{tracks:,}")
        self.albums_stat.setValue(f"{albums:,}")
        self.size_stat.setValue(format_size(size_bytes))
        self.duration_stat.setValue(format_duration(duration_ms))

    def clear(self):
        """Clear all info (when no device selected)."""
        self.name_label.setText("No Device")
        self.model_label.setText("Select a device to begin")
        self.tracks_stat.setValue("—")
        self.albums_stat.setValue("—")
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

    def __init__(self):
        from ..app import category_glyphs
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
        self.sidebarLayout.setContentsMargins(10, 12, 10, 12)
        self.sidebarLayout.setSpacing(8)
        self.setFixedWidth(Metrics.SIDEBAR_WIDTH)

        # Device info card at top
        self.device_card = DeviceInfoCard()
        self.device_card.device_renamed.connect(self.device_renamed)
        self.sidebarLayout.addWidget(self.device_card)

        # Device select buttons - row 1
        self.deviceSelectLayout = QHBoxLayout()
        self.deviceSelectLayout.setContentsMargins(0, 0, 0, 0)
        self.deviceSelectLayout.setSpacing(6)

        self.deviceButton = QPushButton("📂 Select")
        self.rescanButton = QPushButton("🔃 Rescan")

        button_style = btn_css(
            bg=Colors.SURFACE_RAISED,
            bg_hover=Colors.SURFACE_ACTIVE,
            bg_press=Colors.SURFACE_ALT,
            padding="7px 0",
        )
        self.deviceButton.setStyleSheet(button_style)
        self.rescanButton.setStyleSheet(button_style)
        self.deviceButton.setFont(QFont(FONT_FAMILY, 10, QFont.Weight.DemiBold))
        self.rescanButton.setFont(QFont(FONT_FAMILY, 10, QFont.Weight.DemiBold))

        self.deviceSelectLayout.addWidget(self.deviceButton)
        self.deviceSelectLayout.addWidget(self.rescanButton)

        self.sidebarLayout.addLayout(self.deviceSelectLayout)

        # Sync button - row 2 (full width)
        self.syncButton = QPushButton("🔄 Sync with PC")
        self.syncButton.setStyleSheet(accent_btn_css())
        self.syncButton.setFont(QFont(FONT_FAMILY, 10, QFont.Weight.DemiBold))
        self.sidebarLayout.addWidget(self.syncButton)

        # Backup button
        self.backupButton = QPushButton("💾 Backups")
        self.backupButton.setFont(QFont(FONT_FAMILY, 10, QFont.Weight.DemiBold))
        self.backupButton.setStyleSheet(btn_css(
            bg=Colors.SURFACE_ALT,
            bg_hover=Colors.SURFACE_ACTIVE,
            bg_press=Colors.SURFACE,
            padding="8px 12px",
            extra="text-align: left;",
        ))
        self.sidebarLayout.addWidget(self.backupButton)

        # Separator
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background-color: {Colors.BORDER_SUBTLE};")
        self.sidebarLayout.addWidget(sep)

        # Category label
        lib_label = QLabel("LIBRARY")
        lib_label.setFont(QFont(FONT_FAMILY, 9, QFont.Weight.Bold))
        lib_label.setStyleSheet(f"color: {Colors.TEXT_TERTIARY}; background: transparent; padding-left: 4px;")
        self.sidebarLayout.addWidget(lib_label)

        self.buttons = {}

        for category, glyph in category_glyphs.items():
            btn = QPushButton(f"{glyph} {category}")
            btn.setFont(QFont(FONT_FAMILY, 11, QFont.Weight.DemiBold))

            btn.setStyleSheet(btn_css(
                bg=Colors.SURFACE_ALT,
                bg_hover=Colors.SURFACE_ACTIVE,
                bg_press=Colors.SURFACE,
                radius=Metrics.BORDER_RADIUS_SM,
                padding="9px 12px",
                extra="text-align: left;",
            ))

            btn.clicked.connect(
                lambda clicked, category=category: self.selectCategory(category))

            self.sidebarLayout.addWidget(btn)
            self.buttons[category] = btn

        self.sidebarLayout.addStretch()

        # Settings button at bottom
        self.settingsButton = QPushButton("⚙ Settings")
        self.settingsButton.setFont(QFont(FONT_FAMILY, 10, QFont.Weight.DemiBold))
        self.settingsButton.setStyleSheet(btn_css(
            bg="transparent",
            bg_hover=Colors.SURFACE_RAISED,
            bg_press=Colors.SURFACE,
            fg=Colors.TEXT_SECONDARY,
            padding="8px 12px",
            extra="text-align: left;",
        ))
        self.sidebarLayout.addWidget(self.settingsButton)

        self.selectedCategory = list(category_glyphs.keys())[0]
        self.selectCategory(self.selectedCategory)

    def updateDeviceInfo(self, name: str, model: str, tracks: int, albums: int,
                         size_bytes: int, duration_ms: int,
                         db_version_hex: str = "", db_version_name: str = "",
                         db_id: int = 0):
        """Update the device info card with current device data."""
        self.device_card.update_device_info(name, model)
        self.device_card.update_stats(tracks, albums, size_bytes, duration_ms)
        if db_version_hex:
            self.device_card.update_database_info(db_version_hex, db_version_name, db_id)

    def clearDeviceInfo(self):
        """Clear device info when no device is selected."""
        self.device_card.clear()

    def updateDeviceButton(self, device_name: str):
        """Update the device button text to show selected device."""
        self.deviceButton.setText("📂 Device")

    def selectCategory(self, category):
        # Reset the previous selected button's style
        self.buttons[self.selectedCategory].setStyleSheet(btn_css(
            bg=Colors.SURFACE_ALT,
            bg_hover=Colors.SURFACE_ACTIVE,
            bg_press=Colors.SURFACE,
            radius=Metrics.BORDER_RADIUS_SM,
            padding="9px 12px",
            extra="text-align: left;",
        ))

        self.selectedCategory = category
        # set the selected button's style
        self.buttons[self.selectedCategory].setStyleSheet(btn_css(
            bg=Colors.ACCENT,
            bg_hover="rgba(64,156,255,200)",
            bg_press="rgba(64,156,255,160)",
            radius=Metrics.BORDER_RADIUS_SM,
            padding="9px 12px",
            extra="text-align: left;",
        ))
        self.category_changed.emit(category)
