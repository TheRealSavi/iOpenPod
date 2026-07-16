"""
iPod device picker dialog.

Scans all drives for connected iPods and presents them in a grid
for the user to select. Includes a manual folder picker fallback.

Automatically rescans when a new drive is mounted (cross-platform).
"""

import logging
import sys
from typing import Any

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from iopenpod.application.jobs import DeviceScanWorker
from iopenpod.device import has_exact_model_number

from ..device_warnings import show_unidentified_ipod_warning
from ..ipod_images import get_ipod_image
from ..styles import (
    FONT_FAMILY,
    Colors,
    Metrics,
    accent_btn_css,
    button_css,
    combo_css,
    input_css,
    make_scroll_area,
)

logger = logging.getLogger(__name__)


class VirtualIPodDialog(QDialog):
    """Create a virtual iPod folder from a known iPod model profile."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create Virtual iPod")
        self.setMinimumWidth(520)

        self.selected_path: str = ""
        self.selected_ipod: Any | None = None
        self._models: list[dict[str, str]] = []

        self._setup_ui()
        self._load_models()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(14)

        title = QLabel("Create Virtual iPod")
        title.setFont(QFont(FONT_FAMILY, Metrics.FONT_XL, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {Colors.TEXT_PRIMARY};")
        layout.addWidget(title)

        self._model_combo = QComboBox()
        self._model_combo.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        self._model_combo.setStyleSheet(combo_css(padding="7px 10px"))
        model_label = QLabel("iPod Model")
        model_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        model_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        layout.addWidget(model_label)
        layout.addWidget(self._model_combo)

        directory_row = QHBoxLayout()
        directory_row.setSpacing(8)

        self._directory_edit = QLineEdit()
        self._directory_edit.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        self._directory_edit.setPlaceholderText("Choose a folder")
        self._directory_edit.setStyleSheet(input_css(padding="7px 10px"))
        directory_row.addWidget(self._directory_edit, 1)

        browse_btn = QPushButton("Browse")
        browse_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        browse_btn.setStyleSheet(button_css("secondary", "md"))
        browse_btn.clicked.connect(self._browse_directory)
        directory_row.addWidget(browse_btn)

        directory_label = QLabel("Directory")
        directory_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        directory_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        layout.addWidget(directory_label)
        layout.addLayout(directory_row)

        self._button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Ok
        )
        create_btn = self._button_box.button(QDialogButtonBox.StandardButton.Ok)
        if create_btn is None:
            raise RuntimeError("Dialog OK button was not created")
        create_btn.setText("Create")
        create_btn.setStyleSheet(accent_btn_css())
        cancel_btn = self._button_box.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_btn is None:
            raise RuntimeError("Dialog cancel button was not created")
        cancel_btn.setStyleSheet(button_css("secondary", "md"))
        self._button_box.accepted.connect(self._create)
        self._button_box.rejected.connect(self.reject)
        layout.addWidget(self._button_box)

    def _load_models(self) -> None:
        from iopenpod.device import available_virtual_ipod_models

        self._models = available_virtual_ipod_models()
        for row in self._models:
            self._model_combo.addItem(row["display_name"], row["model_number"])

    def _browse_directory(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Virtual iPod Folder",
            "",
            QFileDialog.Option.ShowDirsOnly,
        )
        if folder:
            self._directory_edit.setText(folder)

    def _create(self) -> None:
        import os

        folder = self._directory_edit.text().strip()
        model_number = str(self._model_combo.currentData() or "")
        if not folder:
            QMessageBox.warning(self, "Missing Folder", "Choose a folder first.")
            return
        if not os.path.isdir(folder):
            QMessageBox.warning(self, "Invalid Folder", "The selected folder does not exist.")
            return

        try:
            from iopenpod.device import VIRTUAL_IPOD_INFO_FILENAME

            has_existing_data = (
                os.path.exists(os.path.join(folder, VIRTUAL_IPOD_INFO_FILENAME))
                or os.path.isdir(os.path.join(folder, "iPod_Control"))
            )
            if has_existing_data:
                answer = QMessageBox.question(
                    self,
                    "Use Existing Folder",
                    "This folder already contains iPod data. Create virtual iPod metadata there?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return

            from iopenpod.device import create_virtual_ipod

            ipod = create_virtual_ipod(folder, model_number)
        except Exception as exc:
            logger.exception("Failed to create virtual iPod")
            QMessageBox.critical(self, "Virtual iPod Failed", str(exc))
            return

        self.selected_path = str(getattr(ipod, "path", "") or folder)
        self.selected_ipod = ipod
        self.accept()


class _DriveWatcher(QThread):
    """Polls the OS for mounted volumes and emits *drives_changed* when the set changes.

    Works on Windows, macOS, and Linux without any platform-specific
    dependencies beyond the standard library.
    """

    drives_changed = pyqtSignal()

    def __init__(self, interval_ms: int = 2000, parent=None):
        super().__init__(parent)
        self._interval_ms = interval_ms
        self._running = True

    # ── platform helpers ──────────────────────────────────────────────

    @staticmethod
    def _current_volumes() -> set[str]:
        """Return a set of currently mounted volume paths."""
        if sys.platform == "win32":
            return _DriveWatcher._volumes_windows()
        elif sys.platform == "darwin":
            return _DriveWatcher._volumes_macos()
        else:
            return _DriveWatcher._volumes_linux()

    @staticmethod
    def _volumes_windows() -> set[str]:
        import ctypes
        windll = getattr(ctypes, "windll", None)
        kernel32 = getattr(windll, "kernel32", None)
        if kernel32 is None:
            return set()
        bitmask = kernel32.GetLogicalDrives()
        drives: set[str] = set()
        for letter_idx in range(26):
            if bitmask & (1 << letter_idx):
                drives.add(f"{chr(65 + letter_idx)}:\\")
        return drives

    @staticmethod
    def _volumes_macos() -> set[str]:
        from pathlib import Path
        volumes_dir = Path("/Volumes")
        if volumes_dir.is_dir():
            return {str(p) for p in volumes_dir.iterdir() if p.is_dir()}
        return set()

    @staticmethod
    def _volumes_linux() -> set[str]:
        import os
        from pathlib import Path
        volumes: set[str] = set()
        user = os.getenv("USER", "")
        for base in [f"/media/{user}", f"/run/media/{user}", "/mnt"]:
            p = Path(base)
            if p.is_dir():
                volumes.update(str(d) for d in p.iterdir() if d.is_dir())
        return volumes

    # ── thread loop ───────────────────────────────────────────────────

    def run(self):
        known = self._current_volumes()
        while self._running:
            self.msleep(self._interval_ms)
            if not self._running:
                break
            current = self._current_volumes()
            if current != known:
                logger.debug("Drive change detected: added=%s removed=%s",
                             current - known, known - current)
                known = current
                self.drives_changed.emit()

    def stop(self):
        self._running = False


class DeviceCard(QFrame):
    """A clickable card representing a discovered iPod."""

    clicked = pyqtSignal(object)

    def __init__(self, ipod: Any, parent=None):
        super().__init__(parent)
        self.ipod = ipod
        self._selected = False

        self.setFixedSize((200), (200))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_style(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins((12), (16), (12), (12))
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Icon — try real product photo first, fall back to generic icon
        icon_label = QLabel()
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet("background: transparent; border: none;")
        photo = get_ipod_image(ipod.model_family, ipod.generation, (80), ipod.color)

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

        if not has_exact_model_number(ipod):
            warning_label = QLabel("Identification failed")
            warning_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM, QFont.Weight.DemiBold))
            warning_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            warning_label.setStyleSheet(
                f"color: {Colors.WARNING}; background: transparent; border: none;"
            )
            layout.addWidget(warning_label)

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
        # A click receiver can open a modal warning dialog.  Its nested event
        # loop may process a rescan that removes this card, so finish Qt's
        # base handling before emitting the application-level signal.
        super().mousePressEvent(a0)
        if a0 and a0.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.ipod)

    def mouseDoubleClickEvent(self, a0):
        # QFrame's default double-click handling can re-enter
        # mousePressEvent().  Handle the event here instead, because a click
        # receiver can synchronously delete this card during a rescan.
        dialog = self.window()
        if a0 and a0.button() == Qt.MouseButton.LeftButton:
            ipod = self.ipod
            clicked = self.clicked
            a0.accept()
            clicked.emit(ipod)
            # Double-click = select + accept
            if isinstance(dialog, DevicePickerDialog):
                dialog.accept()
            return
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
        self.selected_ipod: Any | None = None
        self._cards: list[DeviceCard] = []
        self._scan_thread: DeviceScanWorker | None = None
        self._scan_orphan_threads: list[DeviceScanWorker] = []

        # Debounce timer — drives may settle over a second or two after mount
        self._rescan_debounce = QTimer(self)
        self._rescan_debounce.setSingleShot(True)
        self._rescan_debounce.setInterval(1500)
        self._rescan_debounce.timeout.connect(self._start_scan)

        # Watch for drive additions/removals and auto-rescan
        self._drive_watcher = _DriveWatcher(parent=self)
        self._drive_watcher.drives_changed.connect(self._on_drives_changed)

        self._setup_ui()
        self._start_scan()
        self._drive_watcher.start()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins((20), (20), (20), (16))
        layout.setSpacing(16)

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
        self._grid_layout.setSpacing(16)
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
        btn_layout.setSpacing(10)

        self._manual_btn = QPushButton("Browse Manually")
        self._manual_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        self._manual_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._manual_btn.setStyleSheet(button_css("secondary", "md"))
        self._manual_btn.clicked.connect(self._browse_manually)
        btn_layout.addWidget(self._manual_btn)

        self._rescan_btn = QPushButton("Rescan")
        self._rescan_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        self._rescan_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._rescan_btn.setStyleSheet(button_css("secondary", "md"))
        self._rescan_btn.clicked.connect(self._start_scan)
        btn_layout.addWidget(self._rescan_btn)

        btn_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.setStyleSheet(button_css("secondary", "md"))
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        self._select_btn = QPushButton("Select")
        self._select_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD, QFont.Weight.DemiBold))
        self._select_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._select_btn.setEnabled(False)
        self._select_btn.setStyleSheet(accent_btn_css())
        self._select_btn.clicked.connect(self.accept)
        btn_layout.addWidget(self._select_btn)

        layout.addLayout(btn_layout)

    def _start_scan(self):
        """Kick off a background scan for iPods."""
        if self._scan_thread is not None and self._scan_thread.isRunning():
            return
        self._cleanup_scan_thread()
        self._subtitle.setText("Scanning for connected iPods...")
        self._no_devices_label.hide()
        self._rescan_btn.setEnabled(False)

        self._scan_thread = DeviceScanWorker()
        worker = self._scan_thread
        worker.finished.connect(
            lambda ipods, w=worker: self._on_scan_complete(ipods, w)
        )
        worker.error.connect(
            lambda error, w=worker: self._on_scan_error(error, w)
        )
        worker.start()

    def _on_scan_complete(self, ipods: list[Any], worker=None):
        """Handle scan results."""
        if worker is not None and self._scan_thread is not worker:
            return
        worker = self._scan_thread
        self._scan_thread = None
        if worker is not None:
            worker.deleteLater()
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
            if len(ipods) == 1 and has_exact_model_number(ipods[0]):
                self._on_card_clicked(ipods[0])
        else:
            self._subtitle.setText("No iPods found")
            self._no_devices_label.show()

    def _on_scan_error(self, error_msg: str, worker=None) -> None:
        """Surface scan failures without leaving the dialog stuck as busy."""
        if worker is not None and self._scan_thread is not worker:
            return
        worker = self._scan_thread
        self._scan_thread = None
        if worker is not None:
            worker.deleteLater()
        logger.warning("iPod scan failed: %s", error_msg)
        self._subtitle.setText("Scan failed")
        self._rescan_btn.setEnabled(True)
        self._no_devices_label.show()

    def _cleanup_scan_thread(self) -> None:
        worker = self._scan_thread
        if worker is None:
            return
        try:
            worker.finished.disconnect()
            worker.error.disconnect()
        except (TypeError, RuntimeError):
            pass
        self._scan_thread = None
        if worker.isRunning():
            worker.requestInterruption()
            self._retain_scan_thread(worker)
        else:
            self._reap_scan_thread(worker)

    def _retain_scan_thread(self, worker: DeviceScanWorker) -> None:
        if worker in self._scan_orphan_threads:
            return
        self._scan_orphan_threads.append(worker)
        try:
            QThread.finished.__get__(worker, type(worker)).connect(
                lambda w=worker: self._reap_scan_thread(w)
            )
        except Exception:
            pass

    def _reap_scan_thread(self, worker: DeviceScanWorker) -> None:
        if self._scan_thread is worker:
            self._scan_thread = None
        try:
            self._scan_orphan_threads.remove(worker)
        except ValueError:
            pass
        try:
            worker.deleteLater()
        except RuntimeError:
            pass

    def _on_card_clicked(self, ipod: Any):
        """Handle a device card being clicked."""
        if not has_exact_model_number(ipod):
            self.selected_path = ""
            self.selected_ipod = None
            for card in self._cards:
                card.setSelected(False)
            self._select_btn.setEnabled(False)
            self._select_btn.setText("Select")
            show_unidentified_ipod_warning(self, ipod)
            return

        self.selected_path = ipod.path
        self.selected_ipod = ipod

        # Update card selection states
        for card in self._cards:
            card.setSelected(card.ipod is ipod)

        self._select_btn.setEnabled(True)
        self._select_btn.setText(f"Select ({ipod.mount_name})")

    def accept(self) -> None:
        """Accept only a scanned device with a model number or a manual path."""
        if self.selected_ipod is not None and not has_exact_model_number(
            self.selected_ipod
        ):
            show_unidentified_ipod_warning(self, self.selected_ipod)
            return
        if self.selected_ipod is None and not self.selected_path:
            return
        super().accept()

    def _on_drives_changed(self):
        """A drive was added or removed — debounce and rescan."""
        # Don't interrupt an in-progress scan
        if self._scan_thread and self._scan_thread.isRunning():
            return
        self._rescan_debounce.start()

    def _browse_manually(self):
        """Open a standard folder picker dialog."""
        if QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier:
            self._create_virtual_ipod()
            return

        folder = QFileDialog.getExistingDirectory(
            self,
            "Select iPod Root Folder",
            "",
            QFileDialog.Option.ShowDirsOnly,
        )
        if folder:
            # Validate the selection
            import os

            from iopenpod.device import has_virtual_ipod_info

            ipod_control = os.path.join(folder, "iPod_Control")
            if os.path.isdir(ipod_control) or has_virtual_ipod_info(folder):
                self.selected_path = folder
                # Clear any prior card selection so the caller re-identifies
                # the manual path instead of reusing a stale device object.
                self.selected_ipod = None
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

    def _create_virtual_ipod(self) -> None:
        """Open the virtual iPod creation dialog."""
        dialog = VirtualIPodDialog(self)
        if dialog.exec() and dialog.selected_path:
            self.selected_path = dialog.selected_path
            self.selected_ipod = dialog.selected_ipod
            self.accept()

    def done(self, a0):
        """Stop the drive watcher before closing the dialog."""
        self._cleanup_scan_thread()
        self._drive_watcher.stop()
        self._drive_watcher.wait()
        super().done(a0)
