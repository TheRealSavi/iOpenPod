"""
iPod device picker dialog.

Scans all drives for connected iPods and presents them in a grid
for the user to select. Includes a manual folder picker fallback.
"""

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QPixmap, QPainter, QColor
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QWidget, QGridLayout, QFileDialog, QMessageBox, QFrame,
    QScrollArea,
)

from ..device_scanner import scan_for_ipods, DiscoveredIPod
from ..ipod_images import get_ipod_image


class _ScanThread(QThread):
    """Background thread to scan for iPods without freezing the UI."""
    finished = pyqtSignal(list)  # list[DiscoveredIPod]

    def run(self):
        ipods = scan_for_ipods()
        self.finished.emit(ipods)


def _make_ipod_icon(family: str, color_hint: str, size: int = 80) -> QPixmap:
    """
    Render a simple iPod silhouette icon as a QPixmap.

    Uses different shapes for Classic vs Nano vs Shuffle vs Mini.
    """
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    family_lower = family.lower()
    # Pick accent color from device color hint
    color_map = {
        "black": QColor(60, 60, 60),
        "silver": QColor(180, 185, 190),
        "white": QColor(220, 220, 225),
        "blue": QColor(80, 130, 200),
        "green": QColor(80, 180, 100),
        "pink": QColor(220, 130, 160),
        "red": QColor(200, 60, 60),
        "purple": QColor(140, 80, 180),
        "orange": QColor(230, 140, 50),
        "yellow": QColor(220, 200, 60),
        "gold": QColor(200, 170, 80),
        "graphite": QColor(90, 90, 95),
        "space gray": QColor(80, 80, 85),
        "slate": QColor(70, 75, 80),
    }
    accent = color_map.get(color_hint.lower(), QColor(180, 185, 190))

    margin = 8
    w = size - margin * 2
    h = size - margin * 2

    if "classic" in family_lower or "video" in family_lower or "photo" in family_lower:
        # Rounded rectangle body with a circle (click wheel)
        body_h = int(h * 0.92)
        body_w = int(w * 0.72)
        x = (size - body_w) // 2
        y = (size - body_h) // 2

        # Body
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(accent)
        painter.drawRoundedRect(x, y, body_w, body_h, 8, 8)

        # Screen
        screen_w = int(body_w * 0.75)
        screen_h = int(body_h * 0.38)
        sx = x + (body_w - screen_w) // 2
        sy = y + int(body_h * 0.08)
        painter.setBrush(QColor(40, 50, 65))
        painter.drawRoundedRect(sx, sy, screen_w, screen_h, 3, 3)

        # Click wheel
        wheel_r = int(body_w * 0.32)
        cx = x + body_w // 2
        cy = y + int(body_h * 0.70)
        painter.setBrush(accent.lighter(115))
        painter.drawEllipse(cx - wheel_r, cy - wheel_r, wheel_r * 2, wheel_r * 2)

        # Center button
        btn_r = int(wheel_r * 0.42)
        painter.setBrush(accent.lighter(130))
        painter.drawEllipse(cx - btn_r, cy - btn_r, btn_r * 2, btn_r * 2)

    elif "nano" in family_lower:
        # Taller, narrower body
        body_h = int(h * 0.95)
        body_w = int(w * 0.55)
        x = (size - body_w) // 2
        y = (size - body_h) // 2

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(accent)
        painter.drawRoundedRect(x, y, body_w, body_h, 6, 6)

        # Screen
        screen_w = int(body_w * 0.80)
        screen_h = int(body_h * 0.42)
        sx = x + (body_w - screen_w) // 2
        sy = y + int(body_h * 0.06)
        painter.setBrush(QColor(40, 50, 65))
        painter.drawRoundedRect(sx, sy, screen_w, screen_h, 3, 3)

        # Small click wheel
        wheel_r = int(body_w * 0.28)
        cx = x + body_w // 2
        cy = y + int(body_h * 0.73)
        painter.setBrush(accent.lighter(110))
        painter.drawEllipse(cx - wheel_r, cy - wheel_r, wheel_r * 2, wheel_r * 2)

    elif "shuffle" in family_lower:
        # Small square-ish body with a circle
        body_s = int(min(w, h) * 0.65)
        x = (size - body_s) // 2
        y = (size - body_s) // 2

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(accent)
        painter.drawRoundedRect(x, y, body_s, body_s, 8, 8)

        # Circle control
        cr = int(body_s * 0.32)
        cx = x + body_s // 2
        cy = y + body_s // 2
        painter.setBrush(accent.lighter(120))
        painter.drawEllipse(cx - cr, cy - cr, cr * 2, cr * 2)

    elif "mini" in family_lower:
        # Slightly narrower and taller
        body_h = int(h * 0.88)
        body_w = int(w * 0.62)
        x = (size - body_w) // 2
        y = (size - body_h) // 2

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(accent)
        painter.drawRoundedRect(x, y, body_w, body_h, 7, 7)

        # Screen
        screen_w = int(body_w * 0.72)
        screen_h = int(body_h * 0.30)
        sx = x + (body_w - screen_w) // 2
        sy = y + int(body_h * 0.08)
        painter.setBrush(QColor(45, 55, 50))
        painter.drawRoundedRect(sx, sy, screen_w, screen_h, 3, 3)

        # Scroll wheel (different from classic — no center button display)
        wheel_r = int(body_w * 0.30)
        cx = x + body_w // 2
        cy = y + int(body_h * 0.66)
        painter.setBrush(accent.lighter(115))
        painter.drawEllipse(cx - wheel_r, cy - wheel_r, wheel_r * 2, wheel_r * 2)

    else:
        # Generic iPod shape (1G-4G: taller, no click wheel — scroll)
        body_h = int(h * 0.90)
        body_w = int(w * 0.68)
        x = (size - body_w) // 2
        y = (size - body_h) // 2

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(accent)
        painter.drawRoundedRect(x, y, body_w, body_h, 8, 8)

        # Screen
        screen_w = int(body_w * 0.75)
        screen_h = int(body_h * 0.35)
        sx = x + (body_w - screen_w) // 2
        sy = y + int(body_h * 0.08)
        painter.setBrush(QColor(50, 60, 55))
        painter.drawRoundedRect(sx, sy, screen_w, screen_h, 3, 3)

        # Scroll wheel
        wheel_r = int(body_w * 0.30)
        cx = x + body_w // 2
        cy = y + int(body_h * 0.68)
        painter.setBrush(accent.lighter(110))
        painter.drawEllipse(cx - wheel_r, cy - wheel_r, wheel_r * 2, wheel_r * 2)

    painter.end()
    return pixmap


class DeviceCard(QFrame):
    """A clickable card representing a discovered iPod."""

    clicked = pyqtSignal(DiscoveredIPod)

    def __init__(self, ipod: DiscoveredIPod, parent=None):
        super().__init__(parent)
        self.ipod = ipod
        self._selected = False

        self.setFixedSize(200, 200)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_style(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 16, 12, 12)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Icon — try real product photo first, fall back to silhouette
        icon_label = QLabel()
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet("background: transparent; border: none;")
        photo = get_ipod_image(ipod.model_family, ipod.generation, 80)
        if photo and not photo.isNull():
            icon_label.setPixmap(photo)
        else:
            icon_label.setPixmap(
                _make_ipod_icon(ipod.model_family, ipod.color or "silver", 80)
            )
        layout.addWidget(icon_label)

        # Model name
        name_label = QLabel(ipod.display_name)
        name_label.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_label.setWordWrap(True)
        name_label.setStyleSheet("color: white; background: transparent; border: none;")
        layout.addWidget(name_label)

        # Subtitle (drive letter + space)
        sub_label = QLabel(ipod.subtitle)
        sub_label.setFont(QFont("Segoe UI", 9))
        sub_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub_label.setWordWrap(True)
        sub_label.setStyleSheet("color: rgba(255,255,255,150); background: transparent; border: none;")
        layout.addWidget(sub_label)

    def _apply_style(self, hovered: bool):
        if self._selected:
            self.setStyleSheet("""
                DeviceCard {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 rgba(64,156,255,120), stop:1 rgba(40,100,200,120));
                    border: 2px solid rgba(64,156,255,200);
                    border-radius: 12px;
                }
            """)
        elif hovered:
            self.setStyleSheet("""
                DeviceCard {
                    background: rgba(255,255,255,40);
                    border: 1px solid rgba(255,255,255,60);
                    border-radius: 12px;
                }
            """)
        else:
            self.setStyleSheet("""
                DeviceCard {
                    background: rgba(255,255,255,20);
                    border: 1px solid rgba(255,255,255,30);
                    border-radius: 12px;
                }
            """)

    def setSelected(self, selected: bool):
        self._selected = selected
        self._apply_style(False)

    def enterEvent(self, event):  # type: ignore[override]
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
        self._cards: list[DeviceCard] = []
        self._scan_thread: _ScanThread | None = None

        self._setup_ui()
        self._start_scan()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(16)

        # Title
        title = QLabel("Select your iPod")
        title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        title.setStyleSheet("color: white;")
        layout.addWidget(title)

        subtitle = QLabel("Scanning for connected iPods...")
        subtitle.setFont(QFont("Segoe UI", 10))
        subtitle.setStyleSheet("color: rgba(255,255,255,150);")
        self._subtitle = subtitle
        layout.addWidget(subtitle)

        # Scroll area for device grid
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical {
                border: none;
                background: rgba(255,255,255,10);
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255,255,255,60);
                border-radius: 4px;
                min-height: 20px;
            }
        """)

        self._grid_container = QWidget()
        self._grid_container.setStyleSheet("background: transparent;")
        self._grid_layout = QGridLayout(self._grid_container)
        self._grid_layout.setContentsMargins(0, 0, 0, 0)
        self._grid_layout.setSpacing(16)
        scroll.setWidget(self._grid_container)
        layout.addWidget(scroll, 1)

        # No-devices message (hidden initially)
        self._no_devices_label = QLabel(
            "No iPods found.\n\n"
            "Make sure your iPod is connected and shows as a drive letter.\n"
            "You can also use the button below to select a folder manually."
        )
        self._no_devices_label.setFont(QFont("Segoe UI", 10))
        self._no_devices_label.setStyleSheet("color: rgba(255,255,255,120);")
        self._no_devices_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._no_devices_label.setWordWrap(True)
        self._no_devices_label.hide()
        layout.addWidget(self._no_devices_label)

        # Separator
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: rgba(255,255,255,25);")
        layout.addWidget(sep)

        # Bottom buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self._manual_btn = QPushButton("📁  Browse Manually...")
        self._manual_btn.setFont(QFont("Segoe UI", 10))
        self._manual_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._manual_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,30);
                border: 1px solid rgba(255,255,255,40);
                border-radius: 6px;
                color: rgba(255,255,255,180);
                padding: 8px 16px;
            }
            QPushButton:hover {
                background: rgba(255,255,255,50);
                color: white;
            }
        """)
        self._manual_btn.clicked.connect(self._browse_manually)
        btn_layout.addWidget(self._manual_btn)

        self._rescan_btn = QPushButton("🔃  Rescan")
        self._rescan_btn.setFont(QFont("Segoe UI", 10))
        self._rescan_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._rescan_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,30);
                border: 1px solid rgba(255,255,255,40);
                border-radius: 6px;
                color: rgba(255,255,255,180);
                padding: 8px 16px;
            }
            QPushButton:hover {
                background: rgba(255,255,255,50);
                color: white;
            }
        """)
        self._rescan_btn.clicked.connect(self._start_scan)
        btn_layout.addWidget(self._rescan_btn)

        btn_layout.addStretch()

        self._select_btn = QPushButton("Select")
        self._select_btn.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        self._select_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._select_btn.setEnabled(False)
        self._select_btn.setStyleSheet("""
            QPushButton {
                background: rgba(64,156,255,80);
                border: 1px solid rgba(64,156,255,100);
                border-radius: 6px;
                color: white;
                padding: 8px 24px;
            }
            QPushButton:hover {
                background: rgba(64,156,255,140);
            }
            QPushButton:disabled {
                background: rgba(255,255,255,15);
                border: 1px solid rgba(255,255,255,20);
                color: rgba(255,255,255,60);
            }
        """)
        self._select_btn.clicked.connect(self.accept)
        btn_layout.addWidget(self._select_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFont(QFont("Segoe UI", 10))
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,20);
                border: 1px solid rgba(255,255,255,30);
                border-radius: 6px;
                color: rgba(255,255,255,150);
                padding: 8px 20px;
            }
            QPushButton:hover {
                background: rgba(255,255,255,40);
                color: white;
            }
        """)
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

    def _on_scan_complete(self, ipods: list[DiscoveredIPod]):
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

    def _on_card_clicked(self, ipod: DiscoveredIPod):
        """Handle a device card being clicked."""
        self.selected_path = ipod.path

        # Update card selection states
        for card in self._cards:
            card.setSelected(card.ipod is ipod)

        self._select_btn.setEnabled(True)
        self._select_btn.setText(f"Select ({ipod.drive_letter}:)")

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
