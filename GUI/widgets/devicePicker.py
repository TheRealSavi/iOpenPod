"""
iPod device picker dialog.

Scans all drives for connected iPods and presents them in a grid
for the user to select. Includes a manual folder picker fallback.
"""

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QWidget, QGridLayout, QFileDialog, QMessageBox, QFrame,
)

from device_info import DeviceInfo
from ..device_scanner import scan_for_ipods
from ..ipod_images import get_ipod_image
from ..styles import Colors, FONT_FAMILY, Metrics, btn_css, scaled, make_scroll_area


class _ScanThread(QThread):
    """Background thread to scan for iPods without freezing the UI."""
    finished = pyqtSignal(list)  # list[DeviceInfo]

    def run(self):
        ipods = scan_for_ipods()
        self.finished.emit(ipods)


class DeviceCard(QFrame):
    """A clickable card representing a discovered iPod."""

    clicked = pyqtSignal(DeviceInfo)

    def __init__(self, ipod: DeviceInfo, parent=None):
        super().__init__(parent)
        self.ipod = ipod
        self._selected = False

        self.setFixedSize(scaled(200), scaled(200))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_style(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(scaled(12), scaled(16), scaled(12), scaled(12))
        layout.setSpacing(scaled(6))
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Icon — try real product photo first, fall back to generic icon
        icon_label = QLabel()
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet("background: transparent; border: none;")
        photo = get_ipod_image(ipod.model_family, ipod.generation, scaled(80), ipod.color)

        icon_label.setPixmap(photo)

        layout.addWidget(icon_label)

        # iPod name (user-assigned name from master playlist)
        if ipod.ipod_name:
            ipod_name_label = QLabel(ipod.ipod_name)
            ipod_name_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_LG, QFont.Weight.Bold))
            ipod_name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ipod_name_label.setWordWrap(True)
            ipod_name_label.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; background: transparent; border: none;")
            layout.addWidget(ipod_name_label)

        # Model name
        name_label = QLabel(ipod.display_name)
        name_font_size = Metrics.FONT_SM if ipod.ipod_name else Metrics.FONT_LG
        name_font_weight = QFont.Weight.Normal if ipod.ipod_name else QFont.Weight.Bold
        name_label.setFont(QFont(FONT_FAMILY, name_font_size, name_font_weight))
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_label.setWordWrap(True)
        name_color = Colors.TEXT_SECONDARY if ipod.ipod_name else Colors.TEXT_PRIMARY
        name_label.setStyleSheet(f"color: {name_color}; background: transparent; border: none;")
        layout.addWidget(name_label)

    def _apply_style(self, hovered: bool):
        if self._selected:
            self.setStyleSheet(f"""
                DeviceCard {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 {Colors.ACCENT_BORDER}, stop:1 {Colors.ACCENT_DARK});
                    border: 2px solid {Colors.ACCENT};
                    border-radius: {Metrics.BORDER_RADIUS_XL}px;
                }}
            """)
        elif hovered:
            self.setStyleSheet(f"""
                DeviceCard {{
                    background: {Colors.SURFACE_HOVER};
                    border: 1px solid {Colors.BORDER};
                    border-radius: {Metrics.BORDER_RADIUS_XL}px;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                DeviceCard {{
                    background: {Colors.SURFACE_ALT};
                    border: 1px solid {Colors.BORDER_SUBTLE};
                    border-radius: {Metrics.BORDER_RADIUS_XL}px;
                }}
            """)

    def setSelected(self, selected: bool):
        self._selected = selected
        self._apply_style(False)

    def enterEvent(self, event):
        if not self._selected:
            self._apply_style(True)
        super().enterEvent(event)

    def leaveEvent(self, a0):
        self._apply_style(False)
        super().leaveEvent(a0)

    def mousePressEvent(self, a0):
        if a0 and a0.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.ipod)
        super().mousePressEvent(a0)

    def mouseDoubleClickEvent(self, a0):
        if a0 and a0.button() == Qt.MouseButton.LeftButton:
            # Double-click = select + accept
            self.clicked.emit(self.ipod)
            dialog = self.window()
            if isinstance(dialog, DevicePickerDialog):
                dialog.accept()
        super().mouseDoubleClickEvent(a0)


class DevicePickerDialog(QDialog):
    """
    Dialog to discover and select an iPod device.

    Scans all drives for iPod_Control, shows found devices in a grid
    with icons and model info. Has a manual folder picker button.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select iPod Device")
        self.setMinimumSize(500, 400)
        self.resize(560, 440)

        self.selected_path: str = ""
        self.selected_ipod: DeviceInfo | None = None
        self._cards: list[DeviceCard] = []
        self._scan_thread: _ScanThread | None = None

        self._setup_ui()
        self._start_scan()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(scaled(20), scaled(20), scaled(20), scaled(16))
        layout.setSpacing(scaled(16))

        # Title
        title = QLabel("Select your iPod")
        title.setFont(QFont(FONT_FAMILY, Metrics.FONT_PAGE_TITLE, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {Colors.TEXT_PRIMARY};")
        layout.addWidget(title)

        subtitle = QLabel("Scanning for connected iPods...")
        subtitle.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        subtitle.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        self._subtitle = subtitle
        layout.addWidget(subtitle)

        # Scroll area for device grid
        scroll = make_scroll_area()

        self._grid_container = QWidget()
        self._grid_container.setStyleSheet("background: transparent;")
        self._grid_layout = QGridLayout(self._grid_container)
        self._grid_layout.setContentsMargins(0, 0, 0, 0)
        self._grid_layout.setSpacing(scaled(16))
        scroll.setWidget(self._grid_container)
        layout.addWidget(scroll, 1)

        # No-devices message (hidden initially)
        self._no_devices_label = QLabel(
            "No iPods found.\n\n"
            "Make sure your iPod is connected and shows as a drive letter.\n"
            "You can also use the button below to select a folder manually."
        )
        self._no_devices_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        self._no_devices_label.setStyleSheet(f"color: {Colors.TEXT_TERTIARY};")
        self._no_devices_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._no_devices_label.setWordWrap(True)
        self._no_devices_label.hide()
        layout.addWidget(self._no_devices_label)

        # Separator
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {Colors.BORDER_SUBTLE};")
        layout.addWidget(sep)

        # Bottom buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(scaled(10))

        self._manual_btn = QPushButton("Browse Manually")
        self._manual_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        self._manual_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._manual_btn.setStyleSheet(btn_css(
            bg=Colors.SURFACE_RAISED,
            bg_hover=Colors.SURFACE_ACTIVE,
            bg_press=Colors.SURFACE_ALT,
            fg=Colors.TEXT_SECONDARY,
            border=f"1px solid {Colors.BORDER}",
            padding="7px 16px",
        ))
        self._manual_btn.clicked.connect(self._browse_manually)
        btn_layout.addWidget(self._manual_btn)

        self._rescan_btn = QPushButton("Rescan")
        self._rescan_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        self._rescan_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._rescan_btn.setStyleSheet(btn_css(
            bg=Colors.SURFACE_RAISED,
            bg_hover=Colors.SURFACE_ACTIVE,
            bg_press=Colors.SURFACE_ALT,
            fg=Colors.TEXT_SECONDARY,
            border=f"1px solid {Colors.BORDER}",
            padding="7px 16px",
        ))
        self._rescan_btn.clicked.connect(self._start_scan)
        btn_layout.addWidget(self._rescan_btn)

        btn_layout.addStretch()

        self._select_btn = QPushButton("Select")
        self._select_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD, QFont.Weight.DemiBold))
        self._select_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._select_btn.setEnabled(False)
        self._select_btn.setStyleSheet(f"""
            QPushButton {{
                background: {Colors.ACCENT_DIM};
                border: 1px solid {Colors.ACCENT_BORDER};
                border-radius: {Metrics.BORDER_RADIUS_SM}px;
                color: {Colors.TEXT_ON_ACCENT};
                padding: {scaled(7)}px {scaled(24)}px;
            }}
            QPushButton:hover {{
                background: {Colors.ACCENT_HOVER};
            }}
            QPushButton:disabled {{
                background: {Colors.SURFACE};
                border: 1px solid {Colors.BORDER_SUBTLE};
                color: {Colors.TEXT_DISABLED};
            }}
        """)
        self._select_btn.clicked.connect(self.accept)
        btn_layout.addWidget(self._select_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.setStyleSheet(btn_css(
            bg=Colors.SURFACE_RAISED,
            bg_hover=Colors.SURFACE_ACTIVE,
            bg_press=Colors.SURFACE_ALT,
            fg=Colors.TEXT_SECONDARY,
            border=f"1px solid {Colors.BORDER}",
            padding="7px 20px",
        ))
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)

    def _start_scan(self):
        """Kick off a background scan for iPods."""
        self._subtitle.setText("Scanning for connected iPods...")
        self._rescan_btn.setEnabled(False)

        self._scan_thread = _ScanThread()
        self._scan_thread.finished.connect(self._on_scan_complete)
        self._scan_thread.start()

    def _on_scan_complete(self, ipods: list[DeviceInfo]):
        """Handle scan results."""
        self._rescan_btn.setEnabled(True)

        # Clear existing cards
        for card in self._cards:
            card.setParent(None)
            card.deleteLater()
        self._cards.clear()

        if ipods:
            self._subtitle.setText(f"Found {len(ipods)} iPod{'s' if len(ipods) > 1 else ''}:")
            self._no_devices_label.hide()

            # Arrange in a grid (up to 3 columns)
            cols = min(len(ipods), 3)
            for i, ipod in enumerate(ipods):
                card = DeviceCard(ipod)
                card.clicked.connect(self._on_card_clicked)
                self._grid_layout.addWidget(
                    card, i // cols, i % cols,
                    Qt.AlignmentFlag.AlignCenter
                )
                self._cards.append(card)

            # If only one iPod found, auto-select it
            if len(ipods) == 1:
                self._on_card_clicked(ipods[0])
        else:
            self._subtitle.setText("No iPods found")
            self._no_devices_label.show()

    def _on_card_clicked(self, ipod: DeviceInfo):
        """Handle a device card being clicked."""
        self.selected_path = ipod.path
        self.selected_ipod = ipod

        # Update card selection states
        for card in self._cards:
            card.setSelected(card.ipod is ipod)

        self._select_btn.setEnabled(True)
        self._select_btn.setText(f"Select ({ipod.mount_name})")

    def _browse_manually(self):
        """Open a standard folder picker dialog."""
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select iPod Root Folder",
            "",
            QFileDialog.Option.ShowDirsOnly,
        )
        if folder:
            # Validate the selection
            import os
            ipod_control = os.path.join(folder, "iPod_Control")
            if os.path.isdir(ipod_control):
                self.selected_path = folder
                self.accept()
            else:
                QMessageBox.warning(
                    self,
                    "Invalid iPod Folder",
                    "The selected folder does not appear to be a valid iPod root.\n\n"
                    "Expected structure:\n"
                    "  <selected folder>/iPod_Control/iTunes/\n\n"
                    "Please select the root folder of your iPod.",
                )
