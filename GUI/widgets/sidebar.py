from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QFrame, QPushButton, QVBoxLayout, QHBoxLayout,
    QLabel, QWidget, QProgressBar
)
from PyQt6.QtGui import QFont
from .formatters import format_size, format_duration_human as format_duration
from ..ipod_images import get_ipod_image


class StatWidget(QWidget):
    """Widget showing a value and description label."""

    def __init__(self, value: str, label: str):
        super().__init__()
        self.setStyleSheet("background: transparent; border: none;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.value_label = QLabel(value)
        self.value_label.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        self.value_label.setStyleSheet("color: white; background: transparent; border: none;")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.value_label)

        self.desc_label = QLabel(label)
        self.desc_label.setFont(QFont("Segoe UI", 8))
        self.desc_label.setStyleSheet("color: rgba(255,255,255,150); background: transparent; border: none;")
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
        self.label_widget.setFont(QFont("Segoe UI", 8))
        self.label_widget.setStyleSheet("color: rgba(255,255,255,100); background: transparent; border: none;")
        layout.addWidget(self.label_widget)

        layout.addStretch()

        self.value_widget = QLabel(value)
        self.value_widget.setFont(QFont("Consolas", 8))
        self.value_widget.setStyleSheet("color: rgba(255,255,255,200); background: transparent; border: none;")
        self.value_widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.value_widget)

    def setValue(self, value: str):
        """Update the value text."""
        self.value_widget.setText(value)


class DeviceInfoCard(QFrame):
    """Card showing iPod device information and stats."""

    def __init__(self):
        super().__init__()
        self.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(64,156,255,80), stop:1 rgba(40,100,180,80));
                border: 1px solid rgba(64,156,255,100);
                border-radius: 10px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # iPod icon and name row
        header_layout = QHBoxLayout()
        header_layout.setSpacing(8)

        self.icon_label = QLabel("🎵")
        self.icon_label.setFont(QFont("Segoe UI Emoji", 24))
        self.icon_label.setFixedSize(52, 52)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setStyleSheet("background: transparent; border: none;")
        header_layout.addWidget(self.icon_label)

        name_layout = QVBoxLayout()
        name_layout.setSpacing(0)

        self.name_label = QLabel("No Device")
        self.name_label.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        self.name_label.setStyleSheet("color: white; background: transparent; border: none;")
        name_layout.addWidget(self.name_label)

        self.model_label = QLabel("")
        self.model_label.setFont(QFont("Segoe UI", 9))
        self.model_label.setStyleSheet("color: rgba(255,255,255,180); background: transparent; border: none;")
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
        self.tech_toggle.setFont(QFont("Segoe UI", 8))
        self.tech_toggle.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                color: rgba(255,255,255,120);
                text-align: left;
                padding: 2px 0;
            }
            QPushButton:hover {
                color: rgba(255,255,255,200);
            }
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

        # Technical info rows
        self.db_version_row = TechInfoRow("Database:", "—")
        self.model_num_row = TechInfoRow("Model #:", "—")
        self.serial_row = TechInfoRow("Serial:", "—")
        self.firmware_row = TechInfoRow("Firmware:", "—")
        self.db_id_row = TechInfoRow("DB ID:", "—")
        self.checksum_row = TechInfoRow("Checksum:", "—")

        tech_layout.addWidget(self.db_version_row)
        tech_layout.addWidget(self.model_num_row)
        tech_layout.addWidget(self.serial_row)
        tech_layout.addWidget(self.firmware_row)
        tech_layout.addWidget(self.db_id_row)
        tech_layout.addWidget(self.checksum_row)

        layout.addWidget(self.tech_container)

        # Storage bar (optional, for when we have capacity info)
        self.storage_bar = QProgressBar()
        self.storage_bar.setFixedHeight(6)
        self.storage_bar.setTextVisible(False)
        self.storage_bar.setStyleSheet("""
            QProgressBar {
                background-color: rgba(0,0,0,50);
                border: none;
                border-radius: 3px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #409cff, stop:1 #60b0ff);
                border-radius: 3px;
            }
        """)
        self.storage_bar.hide()  # Hidden until we have capacity data
        layout.addWidget(self.storage_bar)

        self._tech_expanded = False

    def _toggle_tech_details(self):
        """Toggle technical details visibility."""
        self._tech_expanded = not self._tech_expanded
        self.tech_container.setVisible(self._tech_expanded)
        self.tech_toggle.setText("▼ Technical Details" if self._tech_expanded else "▶ Technical Details")

    def update_device_info(self, name: str, model: str = "", device_info: dict | None = None):
        """Update device name and model."""
        self.name_label.setText(name or "No Device")
        self.model_label.setText(model)

        # Try to load real product photo
        family = ""
        generation = ""
        if device_info:
            family = device_info.get('model_name', '') or ''
            generation = device_info.get('model_generation', '') or ''
        elif model:
            # Parse from model string as fallback
            family = model

        photo = get_ipod_image(family, generation, 48) if family else None
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
            self.icon_label.setFont(QFont("Segoe UI Emoji", 24))

        # Update technical details if provided
        if device_info:
            self.model_num_row.setValue(device_info.get('model', '—') or '—')
            self.serial_row.setValue(device_info.get('serial', '—')[:12] + '...' if len(device_info.get('serial', '')) > 12 else device_info.get('serial', '—') or '—')
            self.firmware_row.setValue(device_info.get('firmware', '—') or '—')
            # Checksum type - just show short name
            checksum_type = device_info.get('checksum_type')
            if checksum_type is not None:
                checksum_names = {0: 'None', 1: 'HASH58', 2: 'HASH72', 98: 'HASHAB', 99: 'Unknown'}
                self.checksum_row.setValue(checksum_names.get(int(checksum_type), 'Unknown'))
            else:
                self.checksum_row.setValue('—')

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
        self.db_version_row.setValue("—")
        self.model_num_row.setValue("—")
        self.serial_row.setValue("—")
        self.firmware_row.setValue("—")
        self.db_id_row.setValue("—")
        self.checksum_row.setValue("—")


class Sidebar(QFrame):
    category_changed = pyqtSignal(str)

    def __init__(self):
        from ..app import category_glyphs
        super().__init__()
        self.setStyleSheet(
            "background-color: rgba(255,255,255,26);"
            "border: 1px solid rgba(255,255,255,51);"
            "border-radius: 10px;"
        )

        self.sidebarLayout = QVBoxLayout(self)
        self.sidebarLayout.setContentsMargins(10, 10, 10, 10)
        self.sidebarLayout.setSpacing(10)
        self.setFixedWidth(210)

        # Device info card at top
        self.device_card = DeviceInfoCard()
        self.sidebarLayout.addWidget(self.device_card)

        # Device select buttons - row 1
        self.deviceSelectLayout = QHBoxLayout()
        self.deviceSelectLayout.setContentsMargins(0, 0, 0, 0)
        self.deviceSelectLayout.setSpacing(6)

        self.deviceButton = QPushButton("📂 Select")
        self.rescanButton = QPushButton("🔃 Rescan")

        button_style = """
            QPushButton {
                background-color: rgba(255,255,255,51);
                border: none;
                border-radius: 6px;
                color: white;
                padding: 8px 0;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: rgba(255,255,255,80);
            }
            QPushButton:pressed {
                background-color: rgba(255,255,255,40);
            }
        """
        self.deviceButton.setStyleSheet(button_style)
        self.rescanButton.setStyleSheet(button_style)
        self.deviceButton.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        self.rescanButton.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))

        self.deviceSelectLayout.addWidget(self.deviceButton)
        self.deviceSelectLayout.addWidget(self.rescanButton)

        self.sidebarLayout.addLayout(self.deviceSelectLayout)

        # Sync button - row 2 (full width)
        self.syncButton = QPushButton("🔄 Sync with PC")
        self.syncButton.setStyleSheet("""
            QPushButton {
                background-color: rgba(64,156,255,80);
                border: 1px solid rgba(64,156,255,100);
                border-radius: 6px;
                color: white;
                padding: 8px 0;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: rgba(64,156,255,120);
            }
            QPushButton:pressed {
                background-color: rgba(64,156,255,60);
            }
        """)
        self.syncButton.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        self.sidebarLayout.addWidget(self.syncButton)

        # Separator
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background-color: rgba(255,255,255,20);")
        self.sidebarLayout.addWidget(sep)

        # Category label
        lib_label = QLabel("LIBRARY")
        lib_label.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        lib_label.setStyleSheet("color: rgba(255,255,255,100); background: transparent; padding-left: 4px;")
        self.sidebarLayout.addWidget(lib_label)

        self.buttons = {}

        for category, glyph in category_glyphs.items():
            btn = QPushButton(f"{glyph} {category}")
            btn.setFont(QFont("Segoe UI", 11, QFont.Weight.DemiBold))

            btn.setStyleSheet(
                "QPushButton {"
                "background-color: rgba(255,255,255,40);"
                "border: none;"
                "border-radius: 6px;"
                "color: white;"
                "padding: 10px 12px;"
                "text-align: left;"
                "}"
                "QPushButton:hover {"
                "background-color: rgba(255,255,255,70);"
                "}"
            )

            btn.clicked.connect(
                lambda clicked, category=category: self.selectCategory(category))

            self.sidebarLayout.addWidget(btn)
            self.buttons[category] = btn

        self.sidebarLayout.addStretch()

        # Settings button at bottom
        self.settingsButton = QPushButton("⚙ Settings")
        self.settingsButton.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        self.settingsButton.setStyleSheet(
            "QPushButton {"
            "background-color: rgba(255,255,255,30);"
            "border: none;"
            "border-radius: 6px;"
            "color: rgba(255,255,255,150);"
            "padding: 8px 12px;"
            "text-align: left;"
            "}"
            "QPushButton:hover {"
            "background-color: rgba(255,255,255,50);"
            "color: white;"
            "}"
        )
        self.sidebarLayout.addWidget(self.settingsButton)

        self.selectedCategory = list(category_glyphs.keys())[0]
        self.selectCategory(self.selectedCategory)

    def updateDeviceInfo(self, name: str, model: str, tracks: int, albums: int,
                         size_bytes: int, duration_ms: int,
                         device_info: dict | None = None,
                         db_version_hex: str = "", db_version_name: str = "",
                         db_id: int = 0):
        """Update the device info card with current device data."""
        self.device_card.update_device_info(name, model, device_info)
        self.device_card.update_stats(tracks, albums, size_bytes, duration_ms)
        if db_version_hex:
            self.device_card.update_database_info(db_version_hex, db_version_name, db_id)

    def clearDeviceInfo(self):
        """Clear device info when no device is selected."""
        self.device_card.clear()

    def updateDeviceButton(self, device_name: str):
        """Update the device button text to show selected device."""
        # Truncate long names
        if len(device_name) > 12:
            device_name = device_name[:10] + "…"
        self.deviceButton.setText(f"📂 {device_name}")

    def selectCategory(self, category):
        # Reset the previous selected button's style
        self.buttons[self.selectedCategory].setStyleSheet(
            "QPushButton {"
            "background-color: rgba(255,255,255,40);"
            "border: none;"
            "border-radius: 6px;"
            "color: white;"
            "padding: 10px 12px;"
            "text-align: left;"
            "}"
            "QPushButton:hover {"
            "background-color: rgba(255,255,255,70);"
            "}"
        )

        self.selectedCategory = category
        # set the selected button's style
        self.buttons[self.selectedCategory].setStyleSheet(
            "QPushButton {"
            "background-color: #409cff;"
            "border: none;"
            "border-radius: 6px;"
            "color: white;"
            "padding: 10px 12px;"
            "text-align: left;"
            "}"
            "QPushButton:hover {"
            "background-color: rgba(64,156,255,200);"
            "}"
        )
        self.category_changed.emit(category)
