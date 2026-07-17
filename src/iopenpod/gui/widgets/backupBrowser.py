"""
Backup Browser Widget — full-page view for managing iPod device backups.

Displays a list of backup snapshots with summary stats, allowing the user
to create new backups, restore a specific snapshot, or delete old ones.
Accessed via the sidebar "Backups" button (centralStack index 3).
Supports multi-device: known backup devices are listed in the page sidebar,
and selecting one shows its snapshot history. Restore is only enabled when
the connected iPod matches the selected backup device."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QFont
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from iopenpod.application.device_identity import (
    resolve_ipod_image_color,
    resolve_ipod_product_image_filename,
)
from iopenpod.application.jobs import (
    BackupCreateRequest,
    BackupCreateWorker,
    BackupRestoreRequest,
    BackupRestoreWorker,
    backup_device_name_from_playlists,
    build_backup_device_context,
    delete_backup_snapshot,
    ensure_backup_folder,
    list_backup_devices_for_view,
    load_backup_snapshot_catalog,
)
from iopenpod.application.progress import ETATracker

from ..glyphs import glyph_pixmap
from ..styles import (
    FONT_FAMILY,
    MONO_FONT_FAMILY,
    Colors,
    Design,
    Metrics,
    accent_btn_css,
    back_btn_css,
    btn_css,
    danger_btn_css,
    make_scroll_area,
    panel_css,
    progress_bar_css,
    sidebar_nav_state,
    sidebar_panel_css,
)
from .browserChrome import chrome_action_btn_css
from .formatters import format_size

if TYPE_CHECKING:
    from iopenpod.application.services import (
        DeviceSessionService,
        LibraryCacheLike,
        LibraryService,
        SettingsService,
    )


def _ipod_pixmap_from_meta(meta: dict | None, size: int):
    """Return the best iPod product image for stored backup metadata."""
    from ..ipod_images import get_ipod_image

    meta = meta or {}
    family = meta.get("family") or meta.get("model_family") or ""
    pixmap = get_ipod_image(
        family,
        meta.get("generation", "") or "",
        size=size,
        color=meta.get("color", "") or "",
    )
    if pixmap and not pixmap.isNull():
        return pixmap
    return None


def _ipod_color_from_meta(meta: dict | None) -> tuple[int, int, int] | None:
    """Return the stored accent color for the resolved iPod product image."""

    meta = meta or {}
    family = meta.get("family") or meta.get("model_family") or ""
    filename = resolve_ipod_product_image_filename(
        family,
        meta.get("generation", "") or "",
        meta.get("color", "") or "",
    )
    return resolve_ipod_image_color(filename)


class BackupDeviceNavItem(QFrame):
    """Sidebar row representing a device with backup history."""

    clicked = pyqtSignal(str)

    def __init__(self, device_info: dict, *, connected: bool = False):
        super().__init__()
        self._device_id = device_info["device_id"]
        self._selected = False
        self._connected = connected

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(64)

        layout = QHBoxLayout(self)
        layout.setContentsMargins((8), (8), (10), (8))
        layout.setSpacing(8)

        self._icon = QLabel()
        self._icon.setFixedSize((38), (44))
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon.setStyleSheet("background: transparent; border: none;")
        px = _ipod_pixmap_from_meta(device_info.get("device_meta", {}), 38)
        if px:
            self._icon.setPixmap(px)
        else:
            self._icon.setText("iPod")
            self._icon.setFont(QFont(FONT_FAMILY, Metrics.FONT_XS))
        layout.addWidget(self._icon)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(1)

        self._name = QLabel(device_info.get("device_name") or self._device_id)
        self._name.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM, QFont.Weight.DemiBold))
        self._name.setStyleSheet("background: transparent; border: none;")
        text_col.addWidget(self._name)

        count = int(device_info.get("snapshot_count", 0) or 0)
        suffix = "backup" if count == 1 else "backups"
        sub_text = f"{count} {suffix}"
        if connected:
            sub_text += " · Connected"
        self._sub = QLabel(sub_text)
        self._sub.setFont(QFont(FONT_FAMILY, Metrics.FONT_XS))
        self._sub.setStyleSheet("background: transparent; border: none;")
        text_col.addWidget(self._sub)

        layout.addLayout(text_col, 1)
        self._apply_style()

    def setSelected(self, selected: bool) -> None:
        if self._selected == selected:
            return
        self._selected = selected
        self._apply_style()

    def _apply_style(self) -> None:
        state = sidebar_nav_state(self._selected)
        sub_color = Colors.SUCCESS if self._connected else Colors.TEXT_TERTIARY
        self.setStyleSheet(f"""
            QFrame {{
                background: {state.background};
                border: none;
                border-radius: {Metrics.BORDER_RADIUS_SM}px;
            }}
            QFrame:hover {{
                background: {state.hover_background};
                border: none;
            }}
        """)
        self._name.setStyleSheet(
            f"color: {state.text}; background: transparent; border: none;"
        )
        self._sub.setStyleSheet(
            f"color: {sub_color}; background: transparent; border: none;"
        )

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
        layout.setContentsMargins((16), (14), (16), (14))
        layout.setSpacing(12)

        # Left side: info
        info_layout = QVBoxLayout()
        info_layout.setSpacing(4)

        # Date/time row (with optional LATEST badge)
        date_row = QHBoxLayout()
        date_row.setSpacing(8)

        date_label = QLabel(snapshot_info.display_date)
        date_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_LG, QFont.Weight.DemiBold))
        date_label.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; background: transparent; border: none;")
        date_row.addWidget(date_label)

        if is_latest:
            latest_badge = QLabel("LATEST")
            latest_badge.setFont(QFont(FONT_FAMILY, (7), QFont.Weight.Bold))
            latest_badge.setStyleSheet(
                f"color: {Colors.ACCENT}; background: {Colors.ACCENT_DIM}; "
                f"border: none; border-radius: {(3)}px; padding: {(2)}px {(6)}px;"
            )
            latest_badge.setFixedHeight(18)
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
        btn_layout.setSpacing(6)

        _btn_w = (90)

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

    def __init__(
        self,
        settings_service: SettingsService,
        device_sessions: DeviceSessionService,
        libraries: LibraryService,
    ):
        super().__init__()

        self._settings_service = settings_service
        self._device_sessions = device_sessions
        self._library_cache: LibraryCacheLike = libraries.cache()
        self._backup_worker = None
        self._restore_worker = None
        self._eta_tracker = ETATracker()
        self._eta_start_time: float = 0.0
        self._current_device_id: str = ""       # sanitized id of the device we're viewing
        self._connected_device_id: str = ""     # sanitized id of the plugged-in iPod
        self._device_connected: bool = False
        self._backup_no_changes: bool = False
        self._viewing_device_name: str = ""     # display name of the viewed device
        self._devices: list[dict] = []
        self._device_nav_items: dict[str, BackupDeviceNavItem] = {}
        self._current_device_info: dict = {}

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Sidebar: back + device navigation ───────────────────────────
        self._sidebar = QFrame()
        self._sidebar.setObjectName("backupSidebar")
        # Backup device rows need a little more room than the main nav sidebar
        # to avoid right-edge clipping on some DPI/font combinations.
        self._sidebar.setFixedWidth(max(Metrics.SIDEBAR_WIDTH, 240))
        self._sidebar.setStyleSheet(sidebar_panel_css("backupSidebar"))
        sidebar_layout = QVBoxLayout(self._sidebar)
        margin = Design.SIDEBAR_OUTER_MARGIN
        sidebar_layout.setContentsMargins(margin, margin, margin, margin)
        sidebar_layout.setSpacing(8)

        back_btn = QPushButton("←")
        back_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_LG))
        back_btn.setToolTip("Back")
        back_btn.setStyleSheet(back_btn_css())
        back_btn.clicked.connect(self._on_close)
        self._back_btn = back_btn
        sidebar_layout.addWidget(back_btn, 0, Qt.AlignmentFlag.AlignLeft)

        nav_title = QLabel("Backups")
        nav_title.setFont(QFont(FONT_FAMILY, Metrics.FONT_HERO, QFont.Weight.Bold))
        nav_title.setStyleSheet(
            f"color: {Colors.TEXT_PRIMARY}; background: transparent; border: none;"
        )
        sidebar_layout.addWidget(nav_title)

        self._devices_subtitle = QLabel("")
        self._devices_subtitle.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self._devices_subtitle.setStyleSheet(
            f"color: {Colors.TEXT_TERTIARY}; background: transparent; border: none;"
        )
        sidebar_layout.addWidget(self._devices_subtitle)

        dev_scroll = make_scroll_area()
        self._devices_scroll_content = QWidget()
        self._devices_scroll_content.setStyleSheet("background: transparent;")
        self._devices_scroll_layout = QVBoxLayout(self._devices_scroll_content)
        # Keep a small inset on the right so card borders are not clipped by
        # the viewport edge/scrollbar.
        self._devices_scroll_layout.setContentsMargins(0, 0, 3, 0)
        self._devices_scroll_layout.setSpacing(4)
        self._devices_scroll_layout.addStretch()
        dev_scroll.setWidget(self._devices_scroll_content)
        sidebar_layout.addWidget(dev_scroll, 1)
        outer.addWidget(self._sidebar)

        # ── Main pane: device hero + stacked content ────────────────────
        main = QWidget()
        main.setStyleSheet("background: transparent;")
        main_layout = QVBoxLayout(main)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self._device_hero = QFrame()
        self._device_hero.setObjectName("backupDeviceHero")
        self._device_hero.setStyleSheet(panel_css(
            "backupDeviceHero",
            bg=Colors.BG_DARK,
            border=f"0px solid transparent; border-bottom: 1px solid {Colors.BORDER_SUBTLE}",
            radius=0,
        ))
        hero_layout = QHBoxLayout(self._device_hero)
        hero_layout.setContentsMargins((24), (18), (24), (18))
        hero_layout.setSpacing(18)

        self._device_art = QLabel()
        self._device_art.setFixedSize((112), (112))
        self._device_art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._device_art.setStyleSheet("background: transparent; border: none;")
        hero_layout.addWidget(self._device_art, 0, Qt.AlignmentFlag.AlignTop)

        hero_text = QVBoxLayout()
        hero_text.setContentsMargins(0, 2, 0, 0)
        hero_text.setSpacing(4)

        self._title_label = QLabel("Device Backups")
        self._title_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_PAGE_TITLE, QFont.Weight.Bold))
        self._title_label.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; background: transparent;")
        self._title_label.setWordWrap(True)
        hero_text.addWidget(self._title_label)

        self._device_model_label = QLabel("")
        self._device_model_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        self._device_model_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; background: transparent;")
        self._device_model_label.setWordWrap(True)
        hero_text.addWidget(self._device_model_label)

        self._size_label = QLabel("")
        self._size_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self._size_label.setStyleSheet(f"color: {Colors.TEXT_TERTIARY}; background: transparent;")
        self._size_label.setWordWrap(True)
        hero_text.addWidget(self._size_label)

        self._restore_status_label = QLabel("")
        self._restore_status_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self._restore_status_label.setStyleSheet(f"color: {Colors.TEXT_TERTIARY}; background: transparent;")
        hero_text.addWidget(self._restore_status_label)

        hero_actions = QHBoxLayout()
        hero_actions.setSpacing(8)

        self._open_folder_btn = QPushButton("Open")
        self._open_folder_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self._open_folder_btn.setToolTip("Open backup folder")
        self._open_folder_btn.setStyleSheet(chrome_action_btn_css())
        self._open_folder_btn.clicked.connect(self._on_open_folder)
        hero_actions.addWidget(self._open_folder_btn)

        self.backup_now_btn = QPushButton("Backup Now")
        self.backup_now_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM, QFont.Weight.DemiBold))
        self.backup_now_btn.setStyleSheet(chrome_action_btn_css())
        self.backup_now_btn.clicked.connect(self._on_backup_now)
        hero_actions.addWidget(self.backup_now_btn)
        hero_actions.addStretch()
        hero_text.addSpacing(6)
        hero_text.addLayout(hero_actions)
        hero_text.addStretch()

        hero_layout.addLayout(hero_text, 1)
        main_layout.addWidget(self._device_hero)

        self._stack = QStackedWidget()
        main_layout.addWidget(self._stack, 1)
        outer.addWidget(main, 1)

        # Page 0: Snapshot list
        self._list_page = QWidget()
        self._list_page.setStyleSheet("background: transparent;")
        list_layout = QVBoxLayout(self._list_page)
        list_layout.setContentsMargins((24), (8), (24), (24))
        list_layout.setSpacing(0)

        scroll = make_scroll_area()

        self._scroll_content = QWidget()
        self._scroll_content.setStyleSheet("background: transparent;")
        self._scroll_layout = QVBoxLayout(self._scroll_content)
        self._scroll_layout.setContentsMargins(0, 0, 0, 0)
        self._scroll_layout.setSpacing(8)
        self._scroll_layout.addStretch()

        scroll.setWidget(self._scroll_content)
        list_layout.addWidget(scroll)

        self._stack.addWidget(self._list_page)  # Index 0

        # Page 1: Progress overlay
        self._progress_page = QWidget()
        self._progress_page.setStyleSheet("background: transparent;")
        prog_layout = QVBoxLayout(self._progress_page)
        prog_layout.setContentsMargins((48), (48), (48), (48))
        prog_layout.setSpacing(16)
        prog_layout.addStretch()

        self._progress_title = QLabel("Creating backup…")
        self._progress_title.setFont(
            QFont(FONT_FAMILY, Metrics.FONT_PAGE_TITLE, QFont.Weight.Bold)
        )
        self._progress_title.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; background: transparent;")
        self._progress_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        prog_layout.addWidget(self._progress_title)

        self._progress_bar = QProgressBar()
        self._progress_bar.setFixedHeight(8)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setStyleSheet(progress_bar_css())
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

        prog_layout.addSpacing(8)

        self._progress_cancel_btn = QPushButton("Cancel")
        self._progress_cancel_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        self._progress_cancel_btn.setFixedWidth(120)
        self._progress_cancel_btn.setStyleSheet(btn_css(
            bg=Colors.SURFACE_RAISED,
            bg_hover=Colors.SURFACE_ACTIVE,
            bg_press=Colors.SURFACE_ALT,
            border=f"1px solid {Colors.BORDER}",
        ))
        self._progress_cancel_btn.clicked.connect(self._on_cancel)
        prog_layout.addWidget(
            self._progress_cancel_btn,
            alignment=Qt.AlignmentFlag.AlignCenter,
        )

        prog_layout.addStretch()

        self._stack.addWidget(self._progress_page)  # Index 1

        # Page 2: Empty state
        self._empty_page = QWidget()
        self._empty_page.setStyleSheet("background: transparent;")
        empty_layout = QVBoxLayout(self._empty_page)
        empty_layout.setContentsMargins((48), (48), (48), (48))
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

        empty_layout.addSpacing(12)

        self._empty_text = QLabel(
            "No backups yet.\n\n"
            "Click 'Backup Now' to create your first full device backup.\n"
            "Backups are stored on your PC and use content-addressable storage.\n"
            "Only new or changed files are stored, saving disk space."
        )
        self._empty_text.setFont(QFont(FONT_FAMILY, Metrics.FONT_LG))
        self._empty_text.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; background: transparent;")
        self._empty_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_text.setWordWrap(True)
        empty_layout.addWidget(self._empty_text)

        empty_layout.addStretch()

        self._stack.addWidget(self._empty_page)  # Index 2

    # ── Public API ──────────────────────────────────────────────────────

    def _connected_device_name(self) -> str:
        try:
            return backup_device_name_from_playlists(
                self._library_cache.get_playlists()
            )
        except Exception:
            return ""

    def refresh(self):
        """Reload the backup browser.

        The sidebar always lists known devices.  A connected iPod is included
        even before its first backup so the user can create one immediately.
        """
        settings = self._settings_service.get_effective_settings()
        device = self._device_sessions.current_session()
        inventory = list_backup_devices_for_view(
            settings.backup_dir,
            connected_ipod_path=device.device_path or "",
            connected_ipod_info=device.discovered_ipod,
            connected_device_name=self._connected_device_name(),
        )
        self._device_connected = inventory.device_connected
        self._connected_device_id = inventory.connected_device_id
        self._devices = inventory.devices
        self._populate_device_sidebar()

        if not self._devices:
            self._current_device_id = ""
            self._current_device_info = {}
            self._show_empty(
                "No backups found.\n\n"
                "Connect an iPod and click 'Backup Now' to create\n"
                "your first full device backup.",
                hide_hero=True,
            )
            return

        known_ids = {d["device_id"] for d in self._devices}
        if self._device_connected:
            target_id = self._connected_device_id
        elif self._current_device_id in known_ids:
            target_id = self._current_device_id
        else:
            target_id = self._devices[0]["device_id"]

        self._show_device_backups(target_id)

    def _show_device_backups(self, device_id: str):
        """Show snapshots for a specific device.

        Resolves whether restore is allowed (connected device must match).
        """
        settings = self._settings_service.get_effective_settings()
        self._current_device_id = device_id

        # Find device name for the title
        self._viewing_device_name = device_id
        self._current_device_info = {"device_id": device_id, "device_name": device_id}
        for d in self._devices:
            if d["device_id"] == device_id:
                self._viewing_device_name = d["device_name"]
                self._current_device_info = d
                break
        self._set_sidebar_selection(device_id)

        # Can restore only if connected device matches this device's backups
        can_restore = self._device_connected and self._connected_device_id == device_id
        catalog = load_backup_snapshot_catalog(device_id, settings.backup_dir)
        snapshots = catalog.snapshots
        total_backup_size = catalog.total_backup_size
        self._update_device_hero(
            self._current_device_info,
            snapshots,
            total_backup_size,
            can_restore,
        )

        if not snapshots:
            if self._device_connected and self._connected_device_id == device_id:
                self._show_empty(
                    "No backups yet.\n\n"
                    "Click 'Backup Now' to create your first full device backup.\n"
                    "Backups are stored on your PC and use content-addressable storage. \n"
                    "Only new or changed files are stored, saving disk space."
                )
            else:
                self._show_empty(
                    f"No backups for {self._viewing_device_name}.\n\n"
                    "Connect this device and click 'Backup Now' to get started."
                )
            return

        # Show list page
        self._stack.setCurrentIndex(0)

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
        """Legacy entry point: focus the first sidebar device."""
        if self._devices:
            self._show_device_backups(self._devices[0]["device_id"])
        else:
            self.refresh()

    def _populate_device_sidebar(self) -> None:
        """Rebuild the sidebar device navigation."""
        while self._devices_scroll_layout.count() > 1:
            item = self._devices_scroll_layout.takeAt(0)
            w = item.widget() if item else None
            if w:
                w.deleteLater()
        self._device_nav_items.clear()

        count = len(self._devices)
        if count:
            self._devices_subtitle.setText(
                f"{count} device{'s' if count != 1 else ''}"
            )
        else:
            self._devices_subtitle.setText("No devices yet")

        for dev in self._devices:
            connected = dev.get("device_id") == self._connected_device_id
            card = BackupDeviceNavItem(dev, connected=connected)
            card.clicked.connect(self._show_device_backups)
            self._device_nav_items[dev["device_id"]] = card
            self._devices_scroll_layout.insertWidget(
                self._devices_scroll_layout.count() - 1, card
            )

    def _set_sidebar_selection(self, device_id: str) -> None:
        for did, item in self._device_nav_items.items():
            item.setSelected(did == device_id)

    def _show_empty(self, text: str = "", *, hide_hero: bool = False):
        """Show the empty state page with optional custom text."""
        self._device_hero.setVisible(not hide_hero)
        self.backup_now_btn.setVisible(
            bool(self._current_device_id)
            and self._device_connected
            and self._connected_device_id == self._current_device_id
        )
        if text:
            self._empty_text.setText(text)
        self._stack.setCurrentIndex(2)

    def _update_device_hero(
        self,
        device_info: dict,
        snapshots: list,
        total_backup_size: int,
        can_restore: bool,
    ) -> None:
        """Update the device summary hero above the snapshot list."""
        self._device_hero.show()
        name = device_info.get("device_name") or device_info.get("device_id") or "iPod"
        meta = device_info.get("device_meta", {}) or {}
        self._title_label.setText(str(name))

        display_name = str(meta.get("display_name") or "")
        if display_name and display_name != name:
            model_text = display_name
        else:
            model_parts = [
                str(meta.get("family") or meta.get("model_family") or ""),
                str(meta.get("generation") or ""),
                str(meta.get("color") or ""),
            ]
            model_text = " · ".join(part for part in model_parts if part)
        self._device_model_label.setText(model_text or "iPod backup archive")

        snapshot_count = len(snapshots)
        latest_text = snapshots[0].display_date if snapshots else "No snapshots yet"
        self._size_label.setText(
            f"{snapshot_count} backup{'s' if snapshot_count != 1 else ''} · "
            f"{format_size(total_backup_size)} on disk · Latest: {latest_text}"
        )

        if can_restore:
            status = "Connected — backup and restore available"
            status_color = Colors.SUCCESS
        elif self._device_connected:
            status = "Different iPod connected — restore disabled"
            status_color = Colors.WARNING
        else:
            status = "Connect this iPod to restore snapshots"
            status_color = Colors.TEXT_TERTIARY
        self._restore_status_label.setText(status)
        self._restore_status_label.setStyleSheet(
            f"color: {status_color}; background: transparent;"
        )

        self.backup_now_btn.setVisible(can_restore)
        self._open_folder_btn.setVisible(bool(device_info.get("device_id")))
        self._apply_device_hero_style(meta)
        self._set_device_art(meta)

    def _apply_device_hero_style(self, meta: dict) -> None:
        """Tint the backup hero with the selected iPod's product color."""
        color = _ipod_color_from_meta(meta)
        self._device_art.setStyleSheet("background: transparent; border: none;")

        if not color:
            self._device_hero.setStyleSheet(f"""
                QFrame#backupDeviceHero {{
                    background: {Colors.BG_DARK};
                    border-bottom: 1px solid {Colors.BORDER_SUBTLE};
                }}
            """)
            self._open_folder_btn.setStyleSheet(chrome_action_btn_css())
            self.backup_now_btn.setStyleSheet(chrome_action_btn_css())
            return

        r, g, b = color
        if Colors._active_mode == "light":
            glass_bg = "rgba(0, 0, 0, 20)"
            glass_hover = "rgba(0, 0, 0, 28)"
            glass_press = "rgba(0, 0, 0, 14)"
            glass_border = "rgba(0, 0, 0, 24)"
        else:
            glass_bg = "rgba(255, 255, 255, 18)"
            glass_hover = "rgba(255, 255, 255, 35)"
            glass_press = "rgba(255, 255, 255, 12)"
            glass_border = "rgba(255, 255, 255, 15)"

        self._device_hero.setStyleSheet(f"""
            QFrame#backupDeviceHero {{
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba({r}, {g}, {b}, 80),
                    stop:1 {Colors.BG_DARK}
                );
                border-bottom: 1px solid rgba({r}, {g}, {b}, 40);
            }}
        """)
        overlay_css = btn_css(
            bg=glass_bg,
            bg_hover=glass_hover,
            bg_press=glass_press,
            fg=Colors.TEXT_PRIMARY,
            border=f"1px solid {glass_border}",
            padding="6px 10px",
            radius=Metrics.BORDER_RADIUS_SM,
        )
        self._open_folder_btn.setStyleSheet(overlay_css)
        self.backup_now_btn.setStyleSheet(overlay_css)

    def _set_device_art(self, meta: dict) -> None:
        """Set the hero artwork from backup metadata."""
        pixmap = _ipod_pixmap_from_meta(meta, 108)

        if pixmap is not None and not pixmap.isNull():
            self._device_art.setPixmap(pixmap)
            self._device_art.setText("")
            return

        px = glyph_pixmap("archive", Metrics.FONT_ICON_XL, Colors.TEXT_TERTIARY)
        if px:
            self._device_art.setPixmap(px)
            self._device_art.setText("")
        else:
            self._device_art.clear()
            self._device_art.setText("Backups")
            self._device_art.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))

    # ── Open backup folder ──────────────────────────────────────────────

    def _on_open_folder(self):
        """Open the backup directory in the OS file manager."""
        settings = self._settings_service.get_effective_settings()
        folder = ensure_backup_folder(settings.backup_dir, self._current_device_id)
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

        device = self._device_sessions.current_session()
        if not device.device_path:
            QMessageBox.warning(self, "No Device", "Please connect and select an iPod first.")
            return

        settings = self._settings_service.get_effective_settings()
        backup_context = build_backup_device_context(
            device.device_path,
            device.discovered_ipod,
            device_name=self._connected_device_name(),
        )
        device_storage = getattr(device, "storage", None)

        # Show progress page
        self._progress_title.setText("Scanning Device")
        self._progress_bar.setRange(0, 0)  # Indeterminate until we know total
        self._progress_file.setText("Discovering files on iPod…")
        self._progress_stats.setText("")
        self._progress_eta.setText("")
        self._progress_cancel_btn.setText("Cancel")
        self._progress_cancel_btn.setEnabled(True)
        self._stack.setCurrentIndex(1)
        self.backup_now_btn.setEnabled(False)
        self._back_btn.setEnabled(False)
        self._eta_tracker.start()
        self._eta_start_time = time.monotonic()
        self._backup_no_changes = False

        self._backup_worker = BackupCreateWorker(
            BackupCreateRequest(
                ipod_path=device.device_path,
                device_id=backup_context.device_id,
                device_name=backup_context.device_name,
                backup_dir=settings.backup_dir,
                max_backups=settings.max_backups,
                device_meta=backup_context.device_meta,
                reported_volume_format=str(
                    getattr(device_storage, "reported_volume_format", "") or ""
                ),
                expected_volume_identity_key=str(
                    getattr(device_storage, "volume_identity_key", "") or ""
                ),
            )
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
        self._progress_cancel_btn.setText("Cancel")
        self._progress_cancel_btn.setEnabled(True)

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
        self._progress_cancel_btn.setText("Cancel")
        self._progress_cancel_btn.setEnabled(True)
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

        device = self._device_sessions.current_session()
        if not device.device_path:
            QMessageBox.warning(
                self, "No Device",
                "Connect the iPod this backup belongs to before restoring."
            )
            return

        settings = self._settings_service.get_effective_settings()
        connected_context = build_backup_device_context(
            device.device_path,
            device.discovered_ipod,
            device_name=self._connected_device_name(),
        )
        device_storage = getattr(device, "storage", None)
        connected_id = connected_context.device_id

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
        self._progress_cancel_btn.setText("Cancel")
        self._progress_cancel_btn.setEnabled(True)
        self._stack.setCurrentIndex(1)
        self.backup_now_btn.setEnabled(False)
        self._back_btn.setEnabled(False)
        self._eta_tracker.start()
        self._eta_start_time = time.monotonic()

        self._restore_worker = BackupRestoreWorker(
            BackupRestoreRequest(
                snapshot_id=snapshot_id,
                ipod_path=device.device_path,
                device_id=connected_id,
                backup_dir=settings.backup_dir,
                reported_volume_format=str(
                    getattr(device_storage, "reported_volume_format", "") or ""
                ),
                expected_volume_identity_key=str(
                    getattr(device_storage, "volume_identity_key", "") or ""
                ),
            )
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
        self._progress_cancel_btn.setText("Cancel")
        self._progress_cancel_btn.setEnabled(True)

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
            cache = self._library_cache
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
        self._progress_cancel_btn.setText("Cancel")
        self._progress_cancel_btn.setEnabled(True)
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

        settings = self._settings_service.get_effective_settings()

        if delete_backup_snapshot(
            device_id=self._current_device_id,
            backup_dir=settings.backup_dir,
            snapshot_id=snapshot_id,
        ):
            self.refresh()
        else:
            QMessageBox.warning(self, "Delete Failed", "Could not delete the snapshot.")

    # ── Cancel / Close ──────────────────────────────────────────────────

    def _on_cancel(self):
        """Cancel the current backup/restore operation."""
        requested = False
        if self._backup_worker and self._backup_worker.isRunning():
            self._backup_worker.requestInterruption()
            requested = True
        if self._restore_worker and self._restore_worker.isRunning():
            self._restore_worker.requestInterruption()
            requested = True
        if requested:
            self._progress_cancel_btn.setEnabled(False)
            self._progress_cancel_btn.setText("Cancelling...")
            self._progress_title.setText("Cancelling")
            self._progress_file.setText(
                "Waiting for the current file operation to stop safely."
            )

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
