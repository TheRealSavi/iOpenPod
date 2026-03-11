"""
Backup Browser Widget — full-page view for managing iPod device backups.

Displays a list of backup snapshots with summary stats, allowing the user
to create new backups, restore a specific snapshot, or delete old ones.
Accessed via the sidebar "Backups" button (centralStack index 3).
Supports multi-device: when no device is connected (or the user clicks
"All Devices"), shows a device picker listing every device that has
backups on this PC.  Restore is only enabled when the connected iPod
matches the backup's device."""

from PyQt6.QtCore import Qt, pyqtSignal, QThread, QTimer
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QProgressBar, QMessageBox, QStackedWidget,
)
from PyQt6.QtGui import QDesktopServices, QFont
from PyQt6.QtCore import QUrl

from ..styles import Colors, FONT_FAMILY, MONO_FONT_FAMILY, Metrics, btn_css, accent_btn_css, danger_btn_css, scaled, font_scaled, make_scroll_area
from ..glyphs import glyph_pixmap
from .formatters import format_size
from SyncEngine.eta import ETATracker

import logging
import time

logger = logging.getLogger(__name__)


# ── Background workers ──────────────────────────────────────────────────────

class BackupWorker(QThread):
    """Background worker for creating a backup."""
    progress = pyqtSignal(str, int, int, str)  # stage, current, total, message
    finished = pyqtSignal(object)  # SnapshotInfo or None
    error = pyqtSignal(str)

    def __init__(self, ipod_path: str, device_id: str, device_name: str,
                 backup_dir: str, max_backups: int):
        super().__init__()
        self.ipod_path = ipod_path
        self.device_id = device_id
        self.device_name = device_name
        self.backup_dir = backup_dir
        self.max_backups = max_backups

    def run(self):
        try:
            from SyncEngine.backup_manager import BackupManager

            manager = BackupManager(
                device_id=self.device_id,
                backup_dir=self.backup_dir,
                device_name=self.device_name,
            )

            def on_progress(prog):
                self.progress.emit(prog.stage, prog.current, prog.total, prog.message)

            result = manager.create_backup(
                ipod_path=self.ipod_path,
                progress_callback=on_progress,
                is_cancelled=self.isInterruptionRequested,
                max_backups=self.max_backups,
            )

            # Clean up orphaned blobs if the backup was cancelled
            if result is None:
                try:
                    manager.garbage_collect()
                except Exception:
                    pass

            self.finished.emit(result)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.error.emit(str(e))


class RestoreWorker(QThread):
    """Background worker for restoring a backup."""
    progress = pyqtSignal(str, int, int, str)
    finished = pyqtSignal(bool)
    error = pyqtSignal(str)

    def __init__(self, snapshot_id: str, ipod_path: str, device_id: str,
                 backup_dir: str):
        super().__init__()
        self.snapshot_id = snapshot_id
        self.ipod_path = ipod_path
        self.device_id = device_id
        self.backup_dir = backup_dir

    def run(self):
        try:
            from SyncEngine.backup_manager import BackupManager

            manager = BackupManager(
                device_id=self.device_id,
                backup_dir=self.backup_dir,
            )

            def on_progress(prog):
                self.progress.emit(prog.stage, prog.current, prog.total, prog.message)

            success = manager.restore_backup(
                snapshot_id=self.snapshot_id,
                ipod_path=self.ipod_path,
                progress_callback=on_progress,
                is_cancelled=self.isInterruptionRequested,
            )

            self.finished.emit(success)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.error.emit(str(e))


# ── Device card widget (for multi-device picker) ───────────────────────────

class DeviceCard(QFrame):
    """A clickable card representing a device that has backups."""

    clicked = pyqtSignal(str)  # device_id

    def __init__(self, device_info: dict):
        super().__init__()
        self._device_id = device_info["device_id"]

        self.setStyleSheet(f"""
            QFrame {{
                background: {Colors.SURFACE_ALT};
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-radius: {Metrics.BORDER_RADIUS_LG}px;
            }}
            QFrame:hover {{
                border: 1px solid {Colors.ACCENT};
                background: {Colors.SURFACE_ACTIVE};
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(scaled(16), scaled(16), scaled(16), scaled(16))
        layout.setSpacing(scaled(12))
        # Icon TODO: replace with device photo if available (like in device picker), encode icon name into the backup folder name so we can show it here without needing to scan the device first
        icon = QLabel("\U0001F4F1")
        icon.setFont(QFont(FONT_FAMILY, Metrics.FONT_ICON_MD))
        icon.setStyleSheet("background: transparent; border: none;")
        icon.setFixedWidth(scaled(36))
        layout.addWidget(icon)

        # Info column
        info = QVBoxLayout()
        info.setSpacing(scaled(2))

        name = QLabel(device_info["device_name"])
        name.setFont(QFont(FONT_FAMILY, Metrics.FONT_XL, QFont.Weight.DemiBold))
        name.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; background: transparent; border: none;")
        info.addWidget(name)

        count = device_info["snapshot_count"]
        sub = QLabel(f"{count} backup{'s' if count != 1 else ''}")
        sub.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        sub.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; background: transparent; border: none;")
        info.addWidget(sub)

        layout.addLayout(info, stretch=1)

        # Arrow
        arrow = QLabel("\u203A")
        arrow.setFont(QFont(FONT_FAMILY, Metrics.FONT_HERO))
        arrow.setStyleSheet(f"color: {Colors.TEXT_TERTIARY}; background: transparent; border: none;")
        layout.addWidget(arrow)

    def mousePressEvent(self, a0):
        if a0 and a0.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._device_id)
        super().mousePressEvent(a0)


# ── Snapshot card widget ────────────────────────────────────────────────────

class SnapshotCard(QFrame):
    """A card representing a single backup snapshot."""

    restore_requested = pyqtSignal(str)  # snapshot_id
    delete_requested = pyqtSignal(str)  # snapshot_id

    def __init__(self, snapshot_info, *, is_initial: bool = False, is_latest: bool = False,
                 can_restore: bool = True):
        super().__init__()
        self.snapshot_id = snapshot_info.id

        border_color = Colors.ACCENT_BORDER if is_latest else Colors.BORDER_SUBTLE
        border_hover = Colors.ACCENT if is_latest else Colors.BORDER

        self.setStyleSheet(f"""
            QFrame {{
                background: {Colors.SURFACE_ALT};
                border: 1px solid {border_color};
                border-radius: {Metrics.BORDER_RADIUS_LG}px;
            }}
            QFrame:hover {{
                border: 1px solid {border_hover};
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(scaled(16), scaled(14), scaled(16), scaled(14))
        layout.setSpacing(scaled(12))

        # Left side: info
        info_layout = QVBoxLayout()
        info_layout.setSpacing(scaled(4))

        # Date/time row (with optional LATEST badge)
        date_row = QHBoxLayout()
        date_row.setSpacing(scaled(8))

        date_label = QLabel(snapshot_info.display_date)
        date_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_LG, QFont.Weight.DemiBold))
        date_label.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; background: transparent; border: none;")
        date_row.addWidget(date_label)

        if is_latest:
            latest_badge = QLabel("LATEST")
            latest_badge.setFont(QFont(FONT_FAMILY, font_scaled(7), QFont.Weight.Bold))
            latest_badge.setStyleSheet(
                f"color: {Colors.ACCENT}; background: {Colors.ACCENT_DIM}; "
                f"border: none; border-radius: {scaled(3)}px; padding: {scaled(2)}px {scaled(6)}px;"
            )
            latest_badge.setFixedHeight(scaled(18))
            date_row.addWidget(latest_badge)

        date_row.addStretch()
        info_layout.addLayout(date_row)

        # Stats line
        stats_text = f"{snapshot_info.file_count:,} files · {format_size(snapshot_info.total_size)}"
        stats_label = QLabel(stats_text)
        stats_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        stats_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; background: transparent; border: none;")
        info_layout.addWidget(stats_label)

        # Delta line
        delta_parts = []
        if snapshot_info.files_added:
            delta_parts.append(f"+{snapshot_info.files_added}")
        if snapshot_info.files_removed:
            delta_parts.append(f"−{snapshot_info.files_removed}")
        if snapshot_info.files_changed:
            delta_parts.append(f"~{snapshot_info.files_changed}")

        if delta_parts:
            delta_text = " · ".join(delta_parts) + " vs previous"
            delta_color = Colors.TEXT_TERTIARY
        elif is_initial:
            delta_text = "Initial backup"
            delta_color = Colors.ACCENT
        else:
            delta_text = "No changes vs previous"
            delta_color = Colors.TEXT_TERTIARY

        delta_label = QLabel(delta_text)
        delta_label.setFont(QFont(MONO_FONT_FAMILY, Metrics.FONT_SM))
        delta_label.setStyleSheet(f"color: {delta_color}; background: transparent; border: none;")
        info_layout.addWidget(delta_label)

        layout.addLayout(info_layout, stretch=1)

        # Right side: buttons
        btn_layout = QVBoxLayout()
        btn_layout.setSpacing(scaled(6))

        _btn_w = scaled(90)

        # TODO: Allow pressing the restore even for incorrect iPods, but show a warning dialog that the backup may not belong to the connected device and may cause problems.
        restore_btn = QPushButton("Restore")
        restore_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD, QFont.Weight.DemiBold))
        restore_btn.setFixedWidth(_btn_w)
        restore_btn.setStyleSheet(accent_btn_css())
        restore_btn.clicked.connect(lambda: self.restore_requested.emit(self.snapshot_id))
        if not can_restore:
            restore_btn.setEnabled(False)
            restore_btn.setToolTip("Connect this device to restore")
        btn_layout.addWidget(restore_btn)

        delete_btn = QPushButton("Delete")
        delete_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        delete_btn.setFixedWidth(_btn_w)
        delete_btn.setStyleSheet(danger_btn_css())
        delete_btn.clicked.connect(lambda: self.delete_requested.emit(self.snapshot_id))
        btn_layout.addWidget(delete_btn)

        layout.addLayout(btn_layout)


# ── Main backup browser widget ─────────────────────────────────────────────

class BackupBrowserWidget(QWidget):
    """Full-page backup browser, shown as centralStack index 3."""

    closed = pyqtSignal()  # Back button

    def __init__(self):
        super().__init__()

        self._backup_worker = None
        self._restore_worker = None
        self._eta_tracker = ETATracker()
        self._eta_start_time: float = 0.0
        self._current_device_id: str = ""       # sanitized id of the device we're viewing
        self._connected_device_id: str = ""     # sanitized id of the plugged-in iPod
        self._device_connected: bool = False
        self._backup_no_changes: bool = False
        self._viewing_device_name: str = ""     # display name of the viewed device

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # ── Title bar ───────────────────────────────────────────────────
        title_bar = QWidget()
        title_bar.setStyleSheet("background: transparent;")
        tb_layout = QHBoxLayout(title_bar)
        tb_layout.setContentsMargins(scaled(24), scaled(16), scaled(24), scaled(8))

        back_btn = QPushButton("← Back")
        back_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_LG))
        back_btn.setStyleSheet(btn_css(
            bg="transparent",
            bg_hover=Colors.SURFACE_ACTIVE,
            bg_press=Colors.SURFACE_ALT,
            fg=Colors.ACCENT,
        ))
        back_btn.clicked.connect(self._on_close)
        self._back_btn = back_btn
        tb_layout.addWidget(back_btn)

        title = QLabel("Device Backups")
        title.setFont(QFont(FONT_FAMILY, Metrics.FONT_HERO, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; background: transparent;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_label = title
        tb_layout.addWidget(title, stretch=1)

        # "All Devices" button — visible when viewing a single device's backups
        self._all_devices_btn = QPushButton("All Devices ›")
        self._all_devices_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        self._all_devices_btn.setStyleSheet(btn_css(
            bg="transparent",
            bg_hover=Colors.SURFACE_ACTIVE,
            bg_press=Colors.SURFACE_ALT,
            fg=Colors.ACCENT,
        ))
        self._all_devices_btn.clicked.connect(self._show_device_picker)
        self._all_devices_btn.setVisible(False)
        tb_layout.addWidget(self._all_devices_btn)

        self._open_folder_btn = QPushButton("Open")
        self._open_folder_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        self._open_folder_btn.setToolTip("Open backup folder")
        self._open_folder_btn.setStyleSheet(btn_css(
            bg="transparent",
            bg_hover=Colors.SURFACE_ALT,
            bg_press=Colors.SURFACE,
            border=f"1px solid {Colors.BORDER_SUBTLE}",
        ))
        self._open_folder_btn.clicked.connect(self._on_open_folder)
        tb_layout.addWidget(self._open_folder_btn)

        self.backup_now_btn = QPushButton("Backup Now")
        self.backup_now_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD, QFont.Weight.DemiBold))
        self.backup_now_btn.setStyleSheet(accent_btn_css())
        self.backup_now_btn.clicked.connect(self._on_backup_now)
        tb_layout.addWidget(self.backup_now_btn)

        outer.addWidget(title_bar)

        # ── Stacked content (list / progress) ───────────────────────────
        self._stack = QStackedWidget()
        outer.addWidget(self._stack)

        # Page 0: Snapshot list
        self._list_page = QWidget()
        self._list_page.setStyleSheet("background: transparent;")
        list_layout = QVBoxLayout(self._list_page)
        list_layout.setContentsMargins(scaled(24), scaled(8), scaled(24), scaled(24))
        list_layout.setSpacing(0)

        # Backup size info
        self._size_label = QLabel("")
        self._size_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self._size_label.setStyleSheet(f"color: {Colors.TEXT_TERTIARY}; background: transparent;")
        list_layout.addWidget(self._size_label)

        list_layout.addSpacing(scaled(8))

        scroll = make_scroll_area()

        self._scroll_content = QWidget()
        self._scroll_content.setStyleSheet("background: transparent;")
        self._scroll_layout = QVBoxLayout(self._scroll_content)
        self._scroll_layout.setContentsMargins(0, 0, 0, 0)
        self._scroll_layout.setSpacing(scaled(8))
        self._scroll_layout.addStretch()

        scroll.setWidget(self._scroll_content)
        list_layout.addWidget(scroll)

        self._stack.addWidget(self._list_page)  # Index 0

        # Page 1: Progress overlay
        self._progress_page = QWidget()
        self._progress_page.setStyleSheet("background: transparent;")
        prog_layout = QVBoxLayout(self._progress_page)
        prog_layout.setContentsMargins(scaled(48), scaled(48), scaled(48), scaled(48))
        prog_layout.setSpacing(scaled(16))
        prog_layout.addStretch()

        self._progress_title = QLabel("Creating backup…")
        self._progress_title.setFont(QFont(FONT_FAMILY, 16, QFont.Weight.Bold))
        self._progress_title.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; background: transparent;")
        self._progress_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        prog_layout.addWidget(self._progress_title)

        self._progress_bar = QProgressBar()
        self._progress_bar.setFixedHeight(scaled(8))
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {Colors.SURFACE_ALT};
                border: none;
                border-radius: {scaled(4)}px;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {Colors.ACCENT}, stop:1 {Colors.ACCENT_LIGHT});
                border-radius: {scaled(4)}px;
            }}
        """)
        prog_layout.addWidget(self._progress_bar)

        self._progress_file = QLabel("")
        self._progress_file.setFont(QFont(MONO_FONT_FAMILY, Metrics.FONT_SM))
        self._progress_file.setStyleSheet(f"color: {Colors.TEXT_TERTIARY}; background: transparent;")
        self._progress_file.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._progress_file.setWordWrap(True)
        prog_layout.addWidget(self._progress_file)

        self._progress_stats = QLabel("")
        self._progress_stats.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        self._progress_stats.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; background: transparent;")
        self._progress_stats.setAlignment(Qt.AlignmentFlag.AlignCenter)
        prog_layout.addWidget(self._progress_stats)

        self._progress_eta = QLabel("")
        self._progress_eta.setFont(QFont(MONO_FONT_FAMILY, Metrics.FONT_SM))
        self._progress_eta.setStyleSheet(f"color: {Colors.TEXT_TERTIARY}; background: transparent;")
        self._progress_eta.setAlignment(Qt.AlignmentFlag.AlignCenter)
        prog_layout.addWidget(self._progress_eta)

        prog_layout.addSpacing(scaled(8))

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        cancel_btn.setFixedWidth(scaled(120))
        cancel_btn.setStyleSheet(btn_css(
            bg=Colors.SURFACE_RAISED,
            bg_hover=Colors.SURFACE_ACTIVE,
            bg_press=Colors.SURFACE_ALT,
            border=f"1px solid {Colors.BORDER}",
        ))
        cancel_btn.clicked.connect(self._on_cancel)
        prog_layout.addWidget(cancel_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        prog_layout.addStretch()

        self._stack.addWidget(self._progress_page)  # Index 1

        # Page 2: Empty state
        self._empty_page = QWidget()
        self._empty_page.setStyleSheet("background: transparent;")
        empty_layout = QVBoxLayout(self._empty_page)
        empty_layout.setContentsMargins(scaled(48), scaled(48), scaled(48), scaled(48))
        empty_layout.addStretch()

        empty_icon = QLabel()
        px = glyph_pixmap("archive", Metrics.FONT_ICON_XL, Colors.TEXT_TERTIARY)
        if px:
            empty_icon.setPixmap(px)
        else:
            empty_icon.setText("●")
            empty_icon.setFont(QFont(FONT_FAMILY, Metrics.FONT_ICON_XL))
        empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_icon.setStyleSheet(f"color: {Colors.TEXT_TERTIARY}; background: transparent;")
        empty_layout.addWidget(empty_icon)

        empty_layout.addSpacing(scaled(12))

        self._empty_text = QLabel(
            "No backups yet.\n\n"
            "Click 'Backup Now' to create your first full device backup.\n"
            "Backups are stored on your PC and use content-addressable storage —\n"
            "only new or changed files are stored, saving disk space."
        )
        self._empty_text.setFont(QFont(FONT_FAMILY, Metrics.FONT_LG))
        self._empty_text.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; background: transparent;")
        self._empty_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_text.setWordWrap(True)
        empty_layout.addWidget(self._empty_text)

        empty_layout.addStretch()

        self._stack.addWidget(self._empty_page)  # Index 2

        # Page 3: Device picker (multi-device)
        self._devices_page = QWidget()
        self._devices_page.setStyleSheet("background: transparent;")
        dev_layout = QVBoxLayout(self._devices_page)
        dev_layout.setContentsMargins(scaled(24), scaled(8), scaled(24), scaled(24))
        dev_layout.setSpacing(0)

        self._devices_subtitle = QLabel("")
        self._devices_subtitle.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        self._devices_subtitle.setStyleSheet(
            f"color: {Colors.TEXT_SECONDARY}; background: transparent;"
        )
        dev_layout.addWidget(self._devices_subtitle)

        dev_layout.addSpacing(scaled(12))

        dev_scroll = make_scroll_area()

        self._devices_scroll_content = QWidget()
        self._devices_scroll_content.setStyleSheet("background: transparent;")
        self._devices_scroll_layout = QVBoxLayout(self._devices_scroll_content)
        self._devices_scroll_layout.setContentsMargins(0, 0, 0, 0)
        self._devices_scroll_layout.setSpacing(scaled(8))
        self._devices_scroll_layout.addStretch()

        dev_scroll.setWidget(self._devices_scroll_content)
        dev_layout.addWidget(dev_scroll)

        self._stack.addWidget(self._devices_page)  # Index 3

    # ── Public API ──────────────────────────────────────────────────────

    def refresh(self):
        """Reload the backup browser.

        - Device connected → show that device's snapshots immediately.
        - No device → show device picker if multiple devices have backups,
          or the single device's snapshots, or the empty state.
        """
        from ..app import DeviceManager
        from ..settings import get_settings
        from SyncEngine.backup_manager import BackupManager, get_device_identifier

        settings = get_settings()
        device = DeviceManager.get_instance()

        # Determine connected device ID (sanitized for folder-name matching)
        if device.device_path:
            self._device_connected = True
            raw_id = get_device_identifier(device.device_path, device.discovered_ipod)
            self._connected_device_id = BackupManager._sanitize_id(raw_id)
        else:
            self._device_connected = False
            self._connected_device_id = ""

        # "Backup Now" only when a device is plugged in
        self.backup_now_btn.setVisible(self._device_connected)

        if self._device_connected:
            # Online → jump straight to connected device's backups
            self._show_device_backups(self._connected_device_id)
            return

        # Offline → check all devices
        devices = BackupManager.list_all_devices(settings.backup_dir)

        if not devices:
            self._all_devices_btn.setVisible(False)
            self._show_empty(
                "No backups found.\n\n"
                "Connect an iPod and click 'Backup Now' to create\n"
                "your first full device backup."
            )
            return

        if len(devices) == 1:
            # Only one device — skip the picker, show its backups directly
            self._show_device_backups(devices[0]["device_id"])
            return

        # Multiple devices — show the picker
        self._show_device_picker()

    def _show_device_backups(self, device_id: str):
        """Show snapshots for a specific device.

        Resolves whether restore is allowed (connected device must match).
        """
        from ..settings import get_settings
        from SyncEngine.backup_manager import BackupManager

        settings = get_settings()
        self._current_device_id = device_id

        # Determine if the "All Devices" button should be visible.
        # Show it whenever there is more than one device with backups.
        all_devices = BackupManager.list_all_devices(settings.backup_dir)
        has_multiple = len(all_devices) > 1
        self._all_devices_btn.setVisible(has_multiple)

        # Find device name for the title
        self._viewing_device_name = device_id
        for d in all_devices:
            if d["device_id"] == device_id:
                self._viewing_device_name = d["device_name"]
                break

        # Can restore only if connected device matches this device's backups
        can_restore = self._device_connected and self._connected_device_id == device_id
        manager = BackupManager(
            device_id=device_id,
            backup_dir=settings.backup_dir,
        )

        snapshots = manager.list_snapshots()

        if not snapshots:
            if self._device_connected and self._connected_device_id == device_id:
                self._show_empty(
                    "No backups yet.\n\n"
                    "Click 'Backup Now' to create your first full device backup.\n"
                    "Backups are stored on your PC and use content-addressable storage —\n"
                    "only new or changed files are stored, saving disk space."
                )
            else:
                self._show_empty(
                    f"No backups for {self._viewing_device_name}.\n\n"
                    "Connect this device and click 'Backup Now' to get started."
                )
            return

        # Update title
        self._title_label.setText(f"{self._viewing_device_name}")

        # Show list page
        self._stack.setCurrentIndex(0)

        # Update size label
        total_backup_size = manager.get_backup_size()
        mode_note = ""
        if not can_restore:
            if self._device_connected:
                mode_note = "  (different device connected — restore disabled)"
            else:
                mode_note = "  (connect this device to restore)"
        self._size_label.setText(
            f"{len(snapshots)} backup{'s' if len(snapshots) != 1 else ''} · "
            f"{format_size(total_backup_size)} total on disk{mode_note}"
        )

        # Clear old cards
        while self._scroll_layout.count() > 1:  # Keep the stretch
            item = self._scroll_layout.takeAt(0)
            w = item.widget() if item else None
            if w:
                w.deleteLater()

        # Add snapshot cards
        num_snaps = len(snapshots)
        for idx, snap in enumerate(snapshots):
            card = SnapshotCard(
                snap,
                is_latest=(idx == 0),
                is_initial=(idx == num_snaps - 1),
                can_restore=can_restore,
            )
            card.restore_requested.connect(self._on_restore)
            card.delete_requested.connect(self._on_delete)
            self._scroll_layout.insertWidget(self._scroll_layout.count() - 1, card)

    def _show_device_picker(self):
        """Show the multi-device picker page."""
        from ..settings import get_settings
        from SyncEngine.backup_manager import BackupManager

        settings = get_settings()
        devices = BackupManager.list_all_devices(settings.backup_dir)

        if not devices:
            self._show_empty(
                "No backups found.\n\n"
                "Connect an iPod and click 'Backup Now' to create\n"
                "your first full device backup."
            )
            return

        self._title_label.setText("Device Backups")
        self._all_devices_btn.setVisible(False)  # Already on the picker page

        # Subtitle
        self._devices_subtitle.setText(
            f"{len(devices)} device{'s' if len(devices) != 1 else ''} with backups on this PC"
        )

        # Clear old device cards
        while self._devices_scroll_layout.count() > 1:
            item = self._devices_scroll_layout.takeAt(0)
            w = item.widget() if item else None
            if w:
                w.deleteLater()

        # Populate device cards
        for dev in devices:
            card = DeviceCard(dev)
            card.clicked.connect(self._show_device_backups)
            self._devices_scroll_layout.insertWidget(
                self._devices_scroll_layout.count() - 1, card
            )

        self._stack.setCurrentIndex(3)

    def _show_empty(self, text: str = ""):
        """Show the empty state page with optional custom text."""
        self._title_label.setText("Device Backups")
        if text:
            self._empty_text.setText(text)
        self._stack.setCurrentIndex(2)

    # ── Open backup folder ──────────────────────────────────────────────

    def _on_open_folder(self):
        """Open the backup directory in the OS file manager."""
        from ..settings import get_settings
        from SyncEngine.backup_manager import _DEFAULT_BACKUP_DIR

        settings = get_settings()
        backup_dir = settings.backup_dir or _DEFAULT_BACKUP_DIR

        # Open device-specific subfolder if we know which device
        from pathlib import Path
        folder = Path(backup_dir)
        if self._current_device_id:
            device_folder = folder / self._current_device_id
            if device_folder.exists():
                folder = device_folder

        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    # ── Stage display labels ────────────────────────────────────────────

    _STAGE_LABELS = {
        "scanning": "Scanning Device",
        "hashing": "Processing Files",
        "verifying": "Verifying Integrity",
        "cleaning": "Removing Changed Files",
        "restoring": "Copying Files to iPod",
        "no_changes": "Already Up to Date",
        "complete": "Complete",
    }

    # ── Backup Now ──────────────────────────────────────────────────────

    def _is_busy(self) -> bool:
        """True if a backup or restore operation is currently running."""
        if self._backup_worker is not None and self._backup_worker.isRunning():
            return True
        if self._restore_worker is not None and self._restore_worker.isRunning():
            return True
        return False

    def _on_backup_now(self):
        """Create a new backup."""
        if self._is_busy():
            QMessageBox.information(
                self, "Operation In Progress",
                "Please wait for the current backup or restore to finish.",
            )
            return

        from ..app import DeviceManager
        from ..settings import get_settings
        from SyncEngine.backup_manager import get_device_identifier, get_device_display_name

        device = DeviceManager.get_instance()
        if not device.device_path:
            QMessageBox.warning(self, "No Device", "Please connect and select an iPod first.")
            return

        settings = get_settings()
        device_id = get_device_identifier(device.device_path, device.discovered_ipod)
        device_name = get_device_display_name(device.discovered_ipod)

        # Show progress page
        self._progress_title.setText("Scanning Device")
        self._progress_bar.setRange(0, 0)  # Indeterminate until we know total
        self._progress_file.setText("Discovering files on iPod…")
        self._progress_stats.setText("")
        self._progress_eta.setText("")
        self._stack.setCurrentIndex(1)
        self.backup_now_btn.setEnabled(False)
        self._back_btn.setEnabled(False)
        self._eta_tracker.start()
        self._eta_start_time = time.monotonic()
        self._backup_no_changes = False

        self._backup_worker = BackupWorker(
            ipod_path=device.device_path,
            device_id=device_id,
            device_name=device_name,
            backup_dir=settings.backup_dir,
            max_backups=settings.max_backups,
        )
        self._backup_worker.progress.connect(self._on_backup_progress)
        self._backup_worker.finished.connect(self._on_backup_finished)
        self._backup_worker.error.connect(self._on_backup_error)
        self._backup_worker.start()

    def _on_backup_progress(self, stage: str, current: int, total: int, message: str):
        # Track no-changes detection from the backup engine
        if stage == "no_changes":
            self._backup_no_changes = True

        # Update title with friendly stage name
        friendly = self._STAGE_LABELS.get(stage)
        if friendly:
            self._progress_title.setText(friendly)

        if total > 0:
            self._progress_bar.setRange(0, total)
            self._progress_bar.setValue(current)
            pct = int(current / total * 100) if total else 0
            self._progress_stats.setText(f"{current:,} / {total:,} files ({pct}%)")
            # ETA tracking
            self._eta_tracker.update(stage, current, total)
            eta_text = self._eta_tracker.format_stage_progress(stage, current, total)
            elapsed = self._format_elapsed(time.monotonic() - self._eta_start_time)
            parts = [p for p in (elapsed, eta_text) if p]
            self._progress_eta.setText(" · ".join(parts))
        else:
            self._progress_stats.setText("")

        self._progress_file.setText(message)

    def _on_backup_finished(self, result):
        self.backup_now_btn.setEnabled(True)
        self._back_btn.setEnabled(True)

        # Check if result is None because the user cancelled.
        worker = self._backup_worker
        was_cancelled = worker is not None and worker.isInterruptionRequested()
        no_changes = self._backup_no_changes
        self._backup_worker = None

        if result:
            # Show brief success screen before returning to list
            elapsed = self._format_elapsed(time.monotonic() - self._eta_start_time)
            self._progress_title.setText("Backup Complete")
            self._progress_bar.setRange(0, 1)
            self._progress_bar.setValue(1)
            self._progress_stats.setText(
                f"{result.file_count:,} files · {format_size(result.total_size)}"
            )
            self._progress_file.setText("")
            self._progress_eta.setText(elapsed)
            QTimer.singleShot(1800, self.refresh)
        elif no_changes:
            # No changes since last backup — show brief info then return
            elapsed = self._format_elapsed(time.monotonic() - self._eta_start_time)
            self._progress_title.setText("Already Up to Date")
            self._progress_bar.setRange(0, 1)
            self._progress_bar.setValue(1)
            self._progress_stats.setText("No files changed since last backup")
            self._progress_file.setText("")
            self._progress_eta.setText(elapsed)
            QTimer.singleShot(1800, self.refresh)
        elif was_cancelled:
            self._stack.setCurrentIndex(0)
            QMessageBox.warning(self, "Backup Cancelled", "The backup was cancelled.")
            self.refresh()
        else:
            self._stack.setCurrentIndex(0)
            QMessageBox.warning(
                self, "Backup Failed",
                "The backup could not be completed.\n"
                "The device may be empty or the backup directory is not writable.\n\n"
                "Check the log for details.",
            )
            self.refresh()

    def _on_backup_error(self, error_msg: str):
        self.backup_now_btn.setEnabled(True)
        self._back_btn.setEnabled(True)
        self._backup_worker = None
        self._stack.setCurrentIndex(0)
        QMessageBox.critical(
            self, "Backup Failed",
            f"An error occurred while creating the backup:\n\n{error_msg}"
        )
        self.refresh()

    # ── Restore ─────────────────────────────────────────────────────────

    def _on_restore(self, snapshot_id: str):
        """Restore a specific snapshot after confirmation.

        Only proceeds if the connected device matches the backup's device.
        """
        if self._is_busy():
            QMessageBox.information(
                self, "Operation In Progress",
                "Please wait for the current backup or restore to finish.",
            )
            return

        from ..app import DeviceManager
        from ..settings import get_settings
        from SyncEngine.backup_manager import BackupManager, get_device_identifier

        device = DeviceManager.get_instance()
        if not device.device_path:
            QMessageBox.warning(
                self, "No Device",
                "Connect the iPod this backup belongs to before restoring."
            )
            return

        settings = get_settings()
        raw_id = get_device_identifier(device.device_path, device.discovered_ipod)
        connected_id = BackupManager._sanitize_id(raw_id)

        # Safety: only restore to the matching device
        if connected_id != self._current_device_id:
            QMessageBox.warning(
                self, "Wrong Device",
                "The connected iPod does not match this backup.\n\n"
                "Please connect the correct device before restoring.\n"
                f"Backup device: {self._viewing_device_name}\n"
                f"Connected device: {connected_id}",
            )
            return

        reply = QMessageBox.warning(
            self,
            "Confirm Restore",
            "Restore the iPod to this backup snapshot?\n\n"
            "Only the differences will be transferred — files that already\n"
            "match the backup will be left in place. Files not in the backup\n"
            "will be removed.\n\n"
            "Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # Show progress
        self._progress_title.setText("Verifying Integrity")
        self._progress_bar.setRange(0, 0)
        self._progress_file.setText("Verifying backup integrity…")
        self._progress_stats.setText("")
        self._progress_eta.setText("")
        self._stack.setCurrentIndex(1)
        self.backup_now_btn.setEnabled(False)
        self._back_btn.setEnabled(False)
        self._eta_tracker.start()
        self._eta_start_time = time.monotonic()

        self._restore_worker = RestoreWorker(
            snapshot_id=snapshot_id,
            ipod_path=device.device_path,
            device_id=connected_id,
            backup_dir=settings.backup_dir,
        )
        self._restore_worker.progress.connect(self._on_restore_progress)
        self._restore_worker.finished.connect(self._on_restore_finished)
        self._restore_worker.error.connect(self._on_restore_error)
        self._restore_worker.start()

    def _on_restore_progress(self, stage: str, current: int, total: int, message: str):
        # Update title with friendly stage name
        friendly = self._STAGE_LABELS.get(stage)
        if friendly:
            self._progress_title.setText(friendly)

        if total > 0:
            self._progress_bar.setRange(0, total)
            self._progress_bar.setValue(current)
            pct = int(current / total * 100) if total else 0
            self._progress_stats.setText(f"{current:,} / {total:,} files ({pct}%)")
            # ETA tracking
            self._eta_tracker.update(stage, current, total)
            eta_text = self._eta_tracker.format_stage_progress(stage, current, total)
            elapsed = self._format_elapsed(time.monotonic() - self._eta_start_time)
            parts = [p for p in (elapsed, eta_text) if p]
            self._progress_eta.setText(" · ".join(parts))
        else:
            self._progress_stats.setText("")

        self._progress_file.setText(message)

    def _on_restore_finished(self, success: bool):
        self.backup_now_btn.setEnabled(True)
        self._back_btn.setEnabled(True)

        # Check if the result is from a user-initiated cancellation.
        worker = self._restore_worker
        was_cancelled = worker is not None and worker.isInterruptionRequested()
        self._restore_worker = None

        if success:
            QMessageBox.information(
                self, "Restore Complete",
                "The iPod has been restored to the selected backup.\n\n"
                "The library view will now refresh."
            )
            # Reload the iTunesDB cache
            from ..app import iTunesDBCache
            cache = iTunesDBCache.get_instance()
            cache.invalidate()
            cache.start_loading()
        elif was_cancelled:
            QMessageBox.critical(
                self, "Restore Cancelled — iPod in Incomplete State",
                "The restore was cancelled while in progress.\n\n"
                "The iPod's files have been partially wiped and may not be "
                "usable until a full restore is completed.\n\n"
                "Please run Restore again immediately to bring the iPod "
                "back to a working state.",
            )
        else:
            QMessageBox.warning(
                self, "Restore Incomplete",
                "The restore completed with some errors.\n"
                "Check the log for details. Some files may not have been restored."
            )

        self.refresh()

    def _on_restore_error(self, error_msg: str):
        self.backup_now_btn.setEnabled(True)
        self._back_btn.setEnabled(True)
        self._restore_worker = None
        self._stack.setCurrentIndex(0)
        QMessageBox.critical(
            self, "Restore Failed",
            f"An error occurred while restoring the backup:\n\n{error_msg}"
        )
        self.refresh()

    # ── Delete ──────────────────────────────────────────────────────────

    def _on_delete(self, snapshot_id: str):
        """Delete a snapshot after confirmation.

        Works offline using ``_current_device_id`` — no device connection
        needed since we only touch local PC backup files.
        """
        reply = QMessageBox.question(
            self,
            "Delete Backup",
            "Delete this backup snapshot?\n\n"
            "Files shared with other snapshots will be preserved.\n"
            "Files unique to this snapshot will be permanently deleted.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        if not self._current_device_id:
            return

        from ..settings import get_settings
        from SyncEngine.backup_manager import BackupManager

        settings = get_settings()

        manager = BackupManager(
            device_id=self._current_device_id,
            backup_dir=settings.backup_dir,
        )

        if manager.delete_snapshot(snapshot_id):
            self.refresh()
        else:
            QMessageBox.warning(self, "Delete Failed", "Could not delete the snapshot.")

    # ── Cancel / Close ──────────────────────────────────────────────────

    def _on_cancel(self):
        """Cancel the current backup/restore operation."""
        if self._backup_worker and self._backup_worker.isRunning():
            self._backup_worker.requestInterruption()
        if self._restore_worker and self._restore_worker.isRunning():
            self._restore_worker.requestInterruption()

    def _on_close(self):
        """Go back to main view."""
        self.closed.emit()

    @staticmethod
    def _format_elapsed(seconds: float) -> str:
        """Format elapsed seconds as 'Elapsed: Xm Ys'."""
        s = int(seconds)
        if s < 2:
            return ""
        if s < 60:
            return f"Elapsed: {s}s"
        m, rem = divmod(s, 60)
        if rem == 0:
            return f"Elapsed: {m}m"
        return f"Elapsed: {m}m {rem}s"

    def _shutdown_workers(self):
        """Interrupt and wait on any running worker threads.

        Must be called before the widget is destroyed to avoid
        'QThread: Destroyed while thread is still running' errors.
        """
        for worker in (self._backup_worker, self._restore_worker):
            if worker is not None and worker.isRunning():
                worker.requestInterruption()
                worker.wait(5000)  # 5 s grace period

    def closeEvent(self, a0):
        self._shutdown_workers()
        super().closeEvent(a0)

    def deleteLater(self):
        self._shutdown_workers()
        super().deleteLater()
