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
    BackupDeviceInventory,
    BackupRestoreFailure,
    BackupRestoreRequest,
    BackupRestoreWorker,
    BackupSnapshotCatalog,
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
    from iopenpod.application.runtime import Worker
    from iopenpod.application.services import (
        DeviceSessionService,
        LibraryCacheLike,
        LibraryService,
        SettingsService,
    )
    from iopenpod.sync.backup_manager import SnapshotInfo


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
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
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
        if self._device_id.startswith("unidentified_"):
            sub_text += " · Identity unresolved"
        self._sub = QLabel(sub_text)
        self._sub.setFont(QFont(FONT_FAMILY, Metrics.FONT_XS))
        self._sub.setStyleSheet("background: transparent; border: none;")
        text_col.addWidget(self._sub)
        self.setAccessibleName(
            f"{self._name.text()}, {sub_text}"
        )
        self.setAccessibleDescription("Select this iPod backup archive")

        layout.addLayout(text_col, 1)
        self._apply_style()

    def setSelected(self, selected: bool) -> None:
        if self._selected == selected:
            return
        self._selected = selected
        self.setAccessibleDescription(
            "Selected iPod backup archive"
            if selected
            else "Select this iPod backup archive"
        )
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
            QFrame:focus {{
                border: 2px solid {Colors.ACCENT};
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

    def keyPressEvent(self, a0):
        if a0 and a0.key() in {
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
            Qt.Key.Key_Space,
        }:
            self.clicked.emit(self._device_id)
            a0.accept()
            return
        super().keyPressEvent(a0)


# ── Snapshot card widget ────────────────────────────────────────────────────

class SnapshotCard(QFrame):
    """A card representing a single backup snapshot."""

    restore_requested = pyqtSignal(str)  # snapshot_id
    delete_requested = pyqtSignal(str)  # snapshot_id

    def __init__(
        self,
        snapshot_info: SnapshotInfo,
        *,
        is_initial: bool = False,
        is_latest: bool = False,
        can_restore: bool = True,
        restore_disabled_reason: str = "",
    ):
        super().__init__()
        self.snapshot_id = snapshot_info.id
        snapshot_is_valid = bool(getattr(snapshot_info, "is_valid", True))
        validation_error = str(
            getattr(snapshot_info, "validation_error", "")
            or "The backup catalog failed validation."
        )

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

        if getattr(snapshot_info, "reason", "") == "pre_restore_safety":
            safety_badge = QLabel("SAFETY CHECKPOINT")
            safety_badge.setFont(QFont(FONT_FAMILY, 7, QFont.Weight.Bold))
            safety_badge.setToolTip(
                "Verified automatically immediately before a restore"
            )
            safety_badge.setStyleSheet(
                f"color: {Colors.WARNING}; background: transparent; "
                f"border: 1px solid {Colors.WARNING}; border-radius: 3px; "
                "padding: 2px 6px;"
            )
            safety_badge.setFixedHeight(18)
            date_row.addWidget(safety_badge)

        if not snapshot_is_valid:
            invalid_badge = QLabel("UNAVAILABLE")
            invalid_badge.setFont(QFont(FONT_FAMILY, 7, QFont.Weight.Bold))
            invalid_badge.setToolTip(validation_error)
            invalid_badge.setAccessibleName("Backup unavailable")
            invalid_badge.setAccessibleDescription(validation_error)
            invalid_badge.setStyleSheet(
                f"color: {Colors.DANGER}; background: transparent; "
                f"border: 1px solid {Colors.DANGER}; border-radius: 3px; "
                "padding: 2px 6px;"
            )
            invalid_badge.setFixedHeight(18)
            date_row.addWidget(invalid_badge)

        date_row.addStretch()
        info_layout.addLayout(date_row)

        # Stats line
        stats_text = (
            f"{snapshot_info.file_count:,} files · "
            f"{format_size(snapshot_info.total_size)}"
            if snapshot_is_valid
            else "Backup catalog needs attention; its files were not deleted"
        )
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

        if not snapshot_is_valid:
            delta_text = "Restore disabled — validation details below"
            delta_color = Colors.DANGER
        elif delta_parts:
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

        self._invalid_detail_label: QLabel | None = None
        if not snapshot_is_valid:
            detail_label = QLabel(f"Why unavailable: {validation_error}")
            detail_label.setObjectName("invalidCatalogDetails")
            detail_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
            detail_label.setStyleSheet(
                f"color: {Colors.DANGER}; background: transparent; border: none;"
            )
            detail_label.setWordWrap(True)
            detail_label.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            detail_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByKeyboard
                | Qt.TextInteractionFlag.TextSelectableByMouse
            )
            detail_label.setAccessibleName("Backup catalog validation details")
            detail_label.setAccessibleDescription(validation_error)
            detail_label.setToolTip(validation_error)
            info_layout.addWidget(detail_label)
            self._invalid_detail_label = detail_label

        layout.addLayout(info_layout, stretch=1)

        # Right side: buttons
        btn_layout = QVBoxLayout()
        btn_layout.setSpacing(6)

        _btn_w = (90)

        # TODO: Allow pressing the restore even for incorrect iPods, but show a warning dialog that the backup may not belong to the connected device and may cause problems.
        self._restore_allowed = can_restore and snapshot_is_valid
        self._delete_allowed = snapshot_is_valid
        self._restore_btn = QPushButton("Restore")
        self._restore_btn.setFont(
            QFont(FONT_FAMILY, Metrics.FONT_MD, QFont.Weight.DemiBold)
        )
        self._restore_btn.setFixedWidth(_btn_w)
        self._restore_btn.setStyleSheet(accent_btn_css())
        self._restore_btn.clicked.connect(
            lambda: self.restore_requested.emit(self.snapshot_id)
        )
        if not self._restore_allowed:
            self._restore_btn.setEnabled(False)
            self._restore_btn.setToolTip(
                validation_error
                if not snapshot_is_valid
                else restore_disabled_reason or "Connect this device to restore"
            )
        btn_layout.addWidget(self._restore_btn)

        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        self._delete_btn.setFixedWidth(_btn_w)
        self._delete_btn.setStyleSheet(danger_btn_css())
        self._delete_btn.clicked.connect(
            lambda: self.delete_requested.emit(self.snapshot_id)
        )
        if not self._delete_allowed:
            delete_disabled_reason = (
                "Deletion is disabled because this backup catalog could not "
                "be validated. Keeping it prevents iOpenPod from deleting "
                "files that another backup may still need."
            )
            self._delete_btn.setEnabled(False)
            self._delete_btn.setToolTip(delete_disabled_reason)
            self._delete_btn.setAccessibleName("Delete backup unavailable")
            self._delete_btn.setAccessibleDescription(
                f"{delete_disabled_reason} {validation_error}"
            )
        btn_layout.addWidget(self._delete_btn)

        layout.addLayout(btn_layout)

    def setActionsEnabled(self, enabled: bool) -> None:
        """Enable card actions without overriding permanent safety gates."""
        self._restore_btn.setEnabled(enabled and self._restore_allowed)
        self._delete_btn.setEnabled(enabled and self._delete_allowed)


# ── Main backup browser widget ─────────────────────────────────────────────

class BackupBrowserWidget(QWidget):
    """Full-page backup browser, shown as centralStack index 3."""

    closed = pyqtSignal()  # Back button
    safe_eject_required = pyqtSignal()

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
        self._delete_worker: Worker | None = None
        self._delete_generation = 0
        self._delete_result: bool | None = None
        self._delete_error = ""
        self._archive_load_generation = 0
        self._archive_workers: list[Worker] = []
        self._archive_terminal_workers: set[int] = set()
        self._eta_tracker = ETATracker()
        self._eta_start_time: float = 0.0
        self._current_device_id: str = ""       # sanitized id of the device we're viewing
        self._connected_device_id: str = ""     # sanitized id of the plugged-in iPod
        self._device_connected: bool = False
        self._connected_identity_stable: bool = False
        self._backup_no_changes: bool = False
        self._restore_committing: bool = False
        self._viewing_device_name: str = ""     # display name of the viewed device
        self._devices: list[dict] = []
        self._device_nav_items: dict[str, BackupDeviceNavItem] = {}
        self._current_device_info: dict = {}
        self._snapshots_by_id: dict[str, SnapshotInfo] = {}
        self._snapshot_cards: list[SnapshotCard] = []
        self._completion_timer = QTimer(self)
        self._completion_timer.setSingleShot(True)
        self._completion_timer.timeout.connect(self._on_completion_timer)

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
        back_btn.setAccessibleName("Back to iPod library")
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
        self._progress_title.setAccessibleName("Backup and restore operation status")
        prog_layout.addWidget(self._progress_title)

        self._progress_bar = QProgressBar()
        self._progress_bar.setFixedHeight(8)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setAccessibleName("Backup and restore operation progress")
        self._progress_bar.setStyleSheet(progress_bar_css())
        prog_layout.addWidget(self._progress_bar)

        self._progress_file = QLabel("")
        self._progress_file.setFont(QFont(MONO_FONT_FAMILY, Metrics.FONT_SM))
        self._progress_file.setStyleSheet(f"color: {Colors.TEXT_TERTIARY}; background: transparent;")
        self._progress_file.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._progress_file.setWordWrap(True)
        self._progress_file.setAccessibleName("Current backup or restore detail")
        prog_layout.addWidget(self._progress_file)

        self._progress_stats = QLabel("")
        self._progress_stats.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        self._progress_stats.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; background: transparent;")
        self._progress_stats.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._progress_stats.setAccessibleName("Backup and restore file progress")
        prog_layout.addWidget(self._progress_stats)

        self._progress_eta = QLabel("")
        self._progress_eta.setFont(QFont(MONO_FONT_FAMILY, Metrics.FONT_SM))
        self._progress_eta.setStyleSheet(f"color: {Colors.TEXT_TERTIARY}; background: transparent;")
        self._progress_eta.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._progress_eta.setAccessibleName("Backup and restore elapsed time")
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
        self._progress_cancel_btn.setAccessibleName("Cancel backup or restore")
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

    def _active_operation_kind(self) -> str:
        """Return the operation whose terminal UI signal is still pending."""
        if self._restore_worker is not None:
            return "restore"
        if self._backup_worker is not None:
            return "backup"
        if getattr(self, "_delete_worker", None) is not None:
            return "delete"
        return ""

    def active_operation_kind(self) -> str:
        """Expose the active backup operation for app-close messaging."""
        return self._active_operation_kind()

    def app_close_block_notice(self) -> tuple[str, str]:
        """Return operation-specific guidance after an app close is refused."""
        operation = self._active_operation_kind()
        if operation == "restore":
            if self._restore_committing:
                return (
                    "Restore Still Finishing",
                    "iOpenPod is applying, flushing, and verifying a restore. "
                    "The app must remain open until the iPod reaches a safe "
                    "state.\n\nPlease wait for the restore result, then close "
                    "iOpenPod again.",
                )
            return (
                "Restore Cancellation Requested",
                "iOpenPod is stopping the restore before file changes begin. "
                "The app must remain open until the restore result confirms "
                "the iPod was left unchanged.\n\nPlease wait for that result, "
                "then close iOpenPod again.",
            )
        if operation == "delete":
            return (
                "Backup Cleanup Still Finishing",
                "iOpenPod is deleting the selected snapshot and safely checking "
                "which stored files are still needed by other backups.\n\n"
                "Please wait for the result, then close iOpenPod again.",
            )
        return (
            "Backup Cancellation Requested",
            "iOpenPod is stopping the backup safely. The app must remain open "
            "until the backup result confirms whether a verified snapshot was "
            "published.\n\nPlease wait for that result, then close iOpenPod "
            "again.",
        )

    def _cancel_completion_refresh(self) -> None:
        """Prevent a prior completion screen from replacing newer UI state."""
        if self._completion_timer.isActive():
            self._completion_timer.stop()

    def _schedule_completion_refresh(self) -> None:
        self._completion_timer.start(3500)

    def _on_completion_timer(self) -> None:
        if not self._is_busy():
            self.refresh()

    def _set_progress_accessibility(self, operation: str = "") -> None:
        """Reset progress semantics so assistive tech hears the current task."""
        if operation:
            label = operation.capitalize()
            detail_name = f"Current {operation} detail"
            cancel_name = f"Cancel {operation}"
        else:
            label = "Backup and restore operation"
            detail_name = "Current backup or restore detail"
            cancel_name = "Cancel backup or restore"

        self._progress_title.setAccessibleName(f"{label} status")
        self._progress_bar.setAccessibleName(f"{label} progress")
        self._progress_file.setAccessibleName(detail_name)
        self._progress_stats.setAccessibleName(f"{label} file progress")
        self._progress_eta.setAccessibleName(f"{label} elapsed time")
        self._progress_cancel_btn.setAccessibleName(cancel_name)
        for widget in (
            self._progress_title,
            self._progress_bar,
            self._progress_file,
            self._progress_stats,
            self._progress_eta,
        ):
            widget.setAccessibleDescription("")

    def _set_archive_actions_enabled(self, enabled: bool) -> None:
        """Freeze all archive navigation and mutation while a worker is owned."""
        self._back_btn.setEnabled(enabled)
        self._open_folder_btn.setEnabled(enabled)
        self.backup_now_btn.setEnabled(enabled)
        for item in self._device_nav_items.values():
            item.setEnabled(enabled)
        for card in self._snapshot_cards:
            card.setActionsEnabled(enabled)

    def refresh(self):
        """Reload the backup browser.

        The sidebar always lists known devices.  A connected iPod is included
        even before its first backup so the user can create one immediately.
        """
        if self._is_busy():
            return
        self._cancel_completion_refresh()
        self._set_progress_accessibility()
        settings = self._settings_service.get_effective_settings()
        device = self._device_sessions.current_session()
        self._archive_load_generation += 1
        generation = self._archive_load_generation
        self._show_archive_loading(
            "Loading backup archives…\n\n"
            "Checking each saved catalog without blocking the rest of iOpenPod.",
            hide_hero=True,
        )

        from iopenpod.application.runtime import ThreadPoolSingleton, Worker

        worker = Worker(
            list_backup_devices_for_view,
            settings.backup_dir,
            connected_ipod_path=device.device_path or "",
            connected_ipod_info=device.discovered_ipod,
            connected_device_name=self._connected_device_name(),
            connected_volume_identity_key=str(
                getattr(device.storage, "volume_identity_key", "") or ""
            ),
        )
        worker.signals.result.connect(
            lambda inventory, w=worker, token=generation, backup_dir=(
                settings.backup_dir
            ): self._on_inventory_worker_result(
                w,
                inventory,
                token,
                backup_dir,
            )
        )
        worker.signals.error.connect(
            lambda error, w=worker, token=generation: (
                self._on_archive_worker_error(
                    w,
                    error,
                    token,
                    "inventory",
                    "",
                )
            )
        )
        self._pin_archive_worker(
            worker,
            generation,
            phase="inventory",
        )
        ThreadPoolSingleton.get_instance().start(worker)

    def _on_inventory_worker_result(
        self,
        worker: Worker,
        inventory: BackupDeviceInventory,
        generation: int,
        backup_dir: str,
    ) -> None:
        self._archive_terminal_workers.add(id(worker))
        self._on_inventory_loaded(inventory, generation, backup_dir)

    def _on_inventory_loaded(
        self,
        inventory: BackupDeviceInventory,
        generation: int,
        backup_dir: str,
    ) -> None:
        """Apply an inventory only if it belongs to the newest refresh."""
        if generation != self._archive_load_generation or self._is_busy():
            return
        self._device_connected = inventory.device_connected
        self._connected_device_id = inventory.connected_device_id
        self._connected_identity_stable = inventory.connected_identity_stable
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

        self._begin_catalog_load(
            target_id,
            backup_dir,
            generation=generation,
        )

    def _show_device_backups(self, device_id: str):
        """Show snapshots for a specific device.

        Resolves whether restore is allowed (connected device must match).
        """
        if self._is_busy():
            return
        self._cancel_completion_refresh()
        self._set_progress_accessibility()
        settings = self._settings_service.get_effective_settings()
        self._archive_load_generation += 1
        self._begin_catalog_load(
            device_id,
            settings.backup_dir,
            generation=self._archive_load_generation,
        )

    def _begin_catalog_load(
        self,
        device_id: str,
        backup_dir: str,
        *,
        generation: int,
    ) -> None:
        """Load a device catalog in the shared pool without freezing Qt."""
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
        self._show_archive_loading(
            f"Loading backups for {self._viewing_device_name}…\n\n"
            "Validating snapshot catalogs and calculating stored size.",
            hide_hero=False,
        )

        from iopenpod.application.runtime import ThreadPoolSingleton, Worker

        worker = Worker(
            load_backup_snapshot_catalog,
            device_id,
            backup_dir,
        )
        worker.signals.result.connect(
            lambda catalog, w=worker, token=generation, did=device_id: (
                self._on_catalog_worker_result(
                    w,
                    catalog,
                    token,
                    did,
                )
            )
        )
        worker.signals.error.connect(
            lambda error, w=worker, token=generation, did=device_id: (
                self._on_archive_worker_error(
                    w,
                    error,
                    token,
                    "catalog",
                    did,
                )
            )
        )
        self._pin_archive_worker(
            worker,
            generation,
            phase="catalog",
            device_id=device_id,
        )
        ThreadPoolSingleton.get_instance().start(worker)

    def _on_catalog_worker_result(
        self,
        worker: Worker,
        catalog: BackupSnapshotCatalog,
        generation: int,
        device_id: str,
    ) -> None:
        self._archive_terminal_workers.add(id(worker))
        self._on_catalog_loaded(catalog, generation, device_id)

    def _on_catalog_loaded(
        self,
        catalog: BackupSnapshotCatalog,
        generation: int,
        device_id: str,
    ) -> None:
        """Apply catalog data only while its device selection is still current."""
        if (
            generation != self._archive_load_generation
            or device_id != self._current_device_id
            or self._is_busy()
        ):
            return
        self._apply_snapshot_catalog(catalog)

    def _apply_snapshot_catalog(self, catalog: BackupSnapshotCatalog) -> None:
        """Render a successfully loaded snapshot catalog on the Qt thread."""
        device_id = self._current_device_id
        can_backup = (
            self._device_connected
            and self._connected_device_id == device_id
        )
        # Destructive restore additionally requires a stable hardware identity.
        can_restore = can_backup and self._connected_identity_stable
        if not can_backup:
            restore_disabled_reason = "Connect this iPod to restore"
        elif not self._connected_identity_stable:
            restore_disabled_reason = (
                "Restore is disabled until iOpenPod can read this iPod's "
                "hardware serial number or FireWire GUID"
            )
        else:
            restore_disabled_reason = ""
        snapshots = catalog.snapshots
        self._snapshots_by_id = {
            snapshot.id: snapshot
            for snapshot in snapshots
        }
        total_backup_size = catalog.total_backup_size
        self._update_device_hero(
            self._current_device_info,
            snapshots,
            total_backup_size,
            can_backup,
            can_restore,
        )
        self._set_archive_actions_enabled(True)

        if not snapshots:
            if self._device_connected and self._connected_device_id == device_id:
                self._show_empty(
                    "No backups yet.\n\n"
                    "Click 'Backup Now' to create your first verified file backup.\n"
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

        self._clear_snapshot_cards()

        # Add snapshot cards
        num_snaps = len(snapshots)
        for idx, snap in enumerate(snapshots):
            card = SnapshotCard(
                snap,
                is_latest=(idx == 0),
                is_initial=(idx == num_snaps - 1),
                can_restore=can_restore,
                restore_disabled_reason=restore_disabled_reason,
            )
            card.restore_requested.connect(self._on_restore)
            card.delete_requested.connect(self._on_delete)
            self._snapshot_cards.append(card)
            self._scroll_layout.insertWidget(self._scroll_layout.count() - 1, card)

    def _show_archive_loading(self, text: str, *, hide_hero: bool) -> None:
        """Present a non-destructive loading state while a pooled worker runs."""
        self._snapshots_by_id = {}
        self._clear_snapshot_cards()
        self._device_hero.setVisible(not hide_hero)
        self._empty_text.setText(text)
        self._empty_text.setAccessibleName("Backup archive loading")
        self._empty_text.setAccessibleDescription(text.replace("\n", " "))
        self._stack.setCurrentIndex(2)
        self.backup_now_btn.setEnabled(False)
        self._open_folder_btn.setEnabled(False)

    def _clear_snapshot_cards(self) -> None:
        """Discard the rendered cards while preserving the layout stretch."""
        while self._scroll_layout.count() > 1:
            item = self._scroll_layout.takeAt(0)
            widget = item.widget() if item else None
            if widget:
                widget.deleteLater()
        self._snapshot_cards.clear()

    def _pin_archive_worker(
        self,
        worker: Worker,
        generation: int,
        *,
        phase: str,
        device_id: str = "",
    ) -> None:
        """Own a pooled worker until its terminal signal reaches the GUI."""
        self._archive_workers.append(worker)
        worker.signals.finished.connect(
            lambda w=worker, token=generation, kind=phase, did=device_id: (
                self._on_archive_worker_finished(w, token, kind, did)
            )
        )

    def _on_archive_worker_error(
        self,
        worker: Worker,
        error: object,
        generation: int,
        phase: str,
        device_id: str,
    ) -> None:
        self._archive_terminal_workers.add(id(worker))
        self._show_archive_load_error(
            error,
            generation,
            phase=phase,
            device_id=device_id,
        )

    def _on_archive_worker_finished(
        self,
        worker: Worker,
        generation: int,
        phase: str,
        device_id: str,
    ) -> None:
        """Release worker ownership, reporting cancellation as a load failure."""
        terminal_signal_seen = id(worker) in self._archive_terminal_workers
        self._archive_terminal_workers.discard(id(worker))
        try:
            self._archive_workers.remove(worker)
        except ValueError:
            pass
        if terminal_signal_seen:
            return
        self._show_archive_load_error(
            "The background load ended before returning a result.",
            generation,
            phase=phase,
            device_id=device_id,
        )

    @staticmethod
    def _background_error_text(error: object) -> str:
        if isinstance(error, tuple) and len(error) >= 2:
            detail = str(error[1]).strip()
            if detail:
                return detail
        return str(error).strip() or "Unknown backup archive error"

    def _show_archive_load_error(
        self,
        error: object,
        generation: int,
        *,
        phase: str,
        device_id: str,
    ) -> None:
        """Show a current load failure; stale worker failures stay silent."""
        if generation != self._archive_load_generation or self._is_busy():
            return
        if phase == "catalog" and device_id != self._current_device_id:
            return

        detail = self._background_error_text(error)
        self._snapshots_by_id = {}
        self._clear_snapshot_cards()
        if phase == "inventory":
            self._devices = []
            self._populate_device_sidebar()
            message = (
                "iOpenPod could not load the backup archive list.\n\n"
                "No backup files were changed. Check that the backup location "
                "is connected and readable, then open Backups again."
            )
            self._show_empty(message, hide_hero=True)
        else:
            message = (
                f"iOpenPod could not load backups for "
                f"{self._viewing_device_name}.\n\n"
                "No backup files were changed. You can open the backup folder "
                "to inspect the archive, then try again."
            )
            self._show_empty(message)
            self._open_folder_btn.setEnabled(True)
        self.backup_now_btn.setEnabled(False)
        self._back_btn.setEnabled(True)
        for item in self._device_nav_items.values():
            item.setEnabled(True)
        QMessageBox.critical(
            self,
            "Backup Archive Could Not Be Loaded",
            f"{message}\n\nDetails: {detail}",
        )

    def _show_device_picker(self):
        """Legacy entry point: focus the first sidebar device."""
        if self._is_busy():
            return
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
            card.setEnabled(not self._is_busy())
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
            self._empty_text.setAccessibleName("Backup archive status")
            self._empty_text.setAccessibleDescription(text.replace("\n", " "))
        self._stack.setCurrentIndex(2)

    def _update_device_hero(
        self,
        device_info: dict,
        snapshots: list,
        total_backup_size: int,
        can_backup: bool,
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
        elif can_backup:
            status = (
                "Connected — backup available; restore needs hardware identity"
            )
            status_color = Colors.WARNING
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

        self.backup_now_btn.setVisible(can_backup)
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
        if self._is_busy():
            return
        settings = self._settings_service.get_effective_settings()
        folder = ensure_backup_folder(settings.backup_dir, self._current_device_id)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    # ── Stage display labels ────────────────────────────────────────────

    _STAGE_LABELS = {
        "scanning": "Scanning Device",
        "hashing": "Processing Files",
        "verifying": "Verifying Integrity",
        "safety_backup": "Protecting Current iPod",
        "committing": "Applying Restore Safely",
        "cleaning": "Removing Changed Files",
        "restoring": "Copying Files to iPod",
        "finalizing": "Finalizing Restore",
        "no_changes": "Already Up to Date",
        "complete": "Complete",
    }

    # ── Backup Now ──────────────────────────────────────────────────────

    def _is_busy(self) -> bool:
        """True until the active worker's terminal UI handler has completed."""
        return bool(self._active_operation_kind())

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
        device_storage = getattr(device, "storage", None)
        backup_context = build_backup_device_context(
            device.device_path,
            device.discovered_ipod,
            device_name=self._connected_device_name(),
            volume_identity_key=str(
                getattr(device_storage, "volume_identity_key", "") or ""
            ),
        )

        # Show progress page
        self._cancel_completion_refresh()
        self._set_progress_accessibility("backup")
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
                identity_is_stable=backup_context.stable_identity,
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
        self._set_archive_actions_enabled(False)
        self._backup_worker.start()

    def _on_backup_progress(self, stage: str, current: int, total: int, message: str):
        # Track no-changes detection from the backup engine
        if stage == "no_changes":
            self._backup_no_changes = True

        # Update title with friendly stage name
        friendly = self._STAGE_LABELS.get(stage)
        if friendly:
            self._progress_title.setText(friendly)
            self._progress_title.setAccessibleDescription(friendly)

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
        self._progress_file.setAccessibleDescription(message)

    def _on_backup_finished(self, result):
        # Check if result is None because the user cancelled.
        worker = self._backup_worker
        was_cancelled = worker is not None and worker.isInterruptionRequested()
        no_changes = self._backup_no_changes
        show_completion = False

        if result:
            # Show brief success screen before returning to list
            show_completion = True
            elapsed = self._format_elapsed(time.monotonic() - self._eta_start_time)
            self._progress_title.setText("Backup Complete")
            self._progress_bar.setRange(0, 1)
            self._progress_bar.setValue(1)
            self._progress_stats.setText(
                f"{result.file_count:,} files · {format_size(result.total_size)}"
            )
            self._progress_file.setText("")
            self._progress_eta.setText(elapsed)
            self._progress_title.setAccessibleDescription(
                "Backup completed successfully"
            )
        elif no_changes:
            # No changes since last backup — show brief info then return
            show_completion = True
            elapsed = self._format_elapsed(time.monotonic() - self._eta_start_time)
            self._progress_title.setText("Already Up to Date")
            self._progress_bar.setRange(0, 1)
            self._progress_bar.setValue(1)
            self._progress_stats.setText("No files changed since last backup")
            self._progress_file.setText("")
            self._progress_eta.setText(elapsed)
            self._progress_title.setAccessibleDescription(
                "Backup is already up to date"
            )
        elif was_cancelled:
            QMessageBox.warning(self, "Backup Cancelled", "The backup was cancelled.")
        else:
            QMessageBox.warning(
                self, "Backup Failed",
                "The backup could not be completed.\n"
                "The backup location may be unavailable or not writable.\n\n"
                "Check the log for details.",
            )

        # Keep close/navigation blocked until all terminal UI work above is done.
        self._backup_worker = None
        self._progress_cancel_btn.setText("Cancel")
        self._progress_cancel_btn.setEnabled(True)
        self._set_archive_actions_enabled(True)
        if show_completion:
            self._schedule_completion_refresh()
        else:
            self.refresh()

    def _on_backup_error(self, error_msg: str):
        QMessageBox.critical(
            self, "Backup Failed",
            f"An error occurred while creating the backup:\n\n{error_msg}"
        )
        # Clear ownership only after the terminal handler has fully reported.
        self._backup_worker = None
        self._progress_cancel_btn.setText("Cancel")
        self._progress_cancel_btn.setEnabled(True)
        self._set_archive_actions_enabled(True)
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
        device_storage = getattr(device, "storage", None)
        connected_context = build_backup_device_context(
            device.device_path,
            device.discovered_ipod,
            device_name=self._connected_device_name(),
            volume_identity_key=str(
                getattr(device_storage, "volume_identity_key", "") or ""
            ),
        )
        connected_id = connected_context.device_id
        if not connected_context.stable_identity:
            QMessageBox.warning(
                self,
                "Stable iPod Identity Required",
                "iOpenPod cannot safely prove that this backup belongs to the "
                "connected iPod because no hardware serial number or FireWire "
                "GUID is available.\n\n"
                "Reconnect and rescan the iPod, then complete any Linux identity "
                "setup iOpenPod offers. Restore remains disabled rather than risk "
                "overwriting a different iPod.",
            )
            return
        snapshot = self._snapshots_by_id.get(snapshot_id)
        if snapshot is None or not bool(getattr(snapshot, "is_valid", True)):
            QMessageBox.critical(
                self,
                "Backup Unavailable",
                "This backup catalog could not be validated, so iOpenPod will "
                "not use it for a destructive restore.\n\n"
                f"{getattr(snapshot, 'validation_error', 'Snapshot not found')}",
            )
            return

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

        snapshot_reason = (
            "Automatic safety checkpoint"
            if getattr(snapshot, "reason", "") == "pre_restore_safety"
            else "Manual or pre-sync backup"
        )
        snapshot_details = (
            f"Device: {self._viewing_device_name}\n"
            f"Snapshot: {snapshot.display_date}\n"
            f"Type: {snapshot_reason}\n"
            f"Contents: {snapshot.file_count:,} files · "
            f"{format_size(snapshot.total_size)}\n\n"
        )
        reply = QMessageBox.warning(
            self,
            "Confirm Restore",
            "Restore the iPod to this backup snapshot?\n\n"
            f"{snapshot_details}"
            "Only the differences will be transferred — files that already\n"
            "match the backup will be left in place. Files not in the backup\n"
            "will be removed.\n\n"
            "Before changing anything, iOpenPod will create a verified safety\n"
            "backup of the iPod's current state. Once file changes begin, the\n"
            "restore will finish without cancellation to avoid leaving the\n"
            "iPod halfway restored.\n\n"
            "Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # Show progress
        self._cancel_completion_refresh()
        self._set_progress_accessibility("restore")
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
        self._restore_committing = False

        self._restore_worker = BackupRestoreWorker(
            BackupRestoreRequest(
                snapshot_id=snapshot_id,
                ipod_path=device.device_path,
                device_id=connected_id,
                backup_dir=settings.backup_dir,
                device_name=connected_context.device_name,
                device_meta=connected_context.device_meta,
                identity_is_stable=connected_context.stable_identity,
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
        self._set_archive_actions_enabled(False)
        self._restore_worker.start()

    def _on_restore_progress(self, stage: str, current: int, total: int, message: str):
        if stage in {
            "committing",
            "cleaning",
            "restoring",
            "finalizing",
        }:
            self._restore_committing = True
            self._progress_cancel_btn.setEnabled(False)
            self._progress_cancel_btn.setText("Finishing safely…")

        # Update title with friendly stage name
        friendly = self._STAGE_LABELS.get(stage)
        if friendly:
            self._progress_title.setText(friendly)
            self._progress_title.setAccessibleDescription(friendly)

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
        self._progress_file.setAccessibleDescription(message)

    def _on_restore_finished(self, success: bool):
        # Check if the result is from a user-initiated cancellation.
        worker = self._restore_worker
        was_cancelled = worker is not None and worker.isInterruptionRequested()

        if success:
            QMessageBox.information(
                self, "Restore Complete",
                "The iPod has been restored to the selected backup.\n\n"
                "The library view will now refresh.\n\n"
                "When you are ready to disconnect the iPod, use iOpenPod's "
                "Eject command first so all pending writes are safely flushed."
            )
            # Reload the iTunesDB cache
            cache = self._library_cache
            cache.invalidate()
            cache.start_loading()
        elif was_cancelled:
            QMessageBox.information(
                self,
                "Restore Cancelled Safely",
                "The restore was cancelled before file changes began. "
                "The iPod was not modified.",
            )
        else:
            QMessageBox.information(
                self,
                "Restore Not Started",
                "The restore stopped before file changes began. "
                "The iPod was not modified.",
            )

        # Keep the worker owned through the dialog/cache work above. A close
        # request in a nested dialog event loop must still be refused.
        self._restore_worker = None
        self._restore_committing = False
        self._progress_cancel_btn.setText("Cancel")
        self._progress_cancel_btn.setEnabled(True)
        self._set_archive_actions_enabled(True)
        self.refresh()

    def _on_restore_error(self, failure: BackupRestoreFailure | str):
        device_changed = bool(getattr(failure, "device_changed", False))
        content_verified = bool(getattr(failure, "content_verified", False))
        requires_safe_eject = bool(
            getattr(failure, "requires_safe_eject", False)
        )
        error_msg = str(getattr(failure, "message", failure))
        safety_snapshot_id = str(
            getattr(failure, "safety_snapshot_id", "") or ""
        )
        checkpoint_note = (
            f"\n\nSafety checkpoint ID: {safety_snapshot_id}"
            if safety_snapshot_id
            else ""
        )
        pending_safe_eject = requires_safe_eject and content_verified
        if pending_safe_eject:
            QMessageBox.warning(
                self,
                "Restore Applied — Finalizing with Safe Eject",
                f"{error_msg}\n\n"
                "The restored file contents were written and read back "
                "successfully, but iOpenPod has not marked this restore "
                "complete because the final volume flush is still pending.\n\n"
                "Keep the iPod connected. iOpenPod will now safely eject it to "
                "finish the flush; do not unplug or sync it first."
                f"{checkpoint_note}",
            )
        elif device_changed:
            QMessageBox.critical(
                self,
                "Restore Incomplete — Recovery Needed",
                f"{error_msg}\n\n"
                "The verified safety backup made immediately before this "
                "restore remains available on the computer."
                f"{checkpoint_note}",
            )
        else:
            QMessageBox.critical(
                self,
                "Restore Stopped Safely",
                f"The iPod was not changed.\n\n{error_msg}{checkpoint_note}",
            )
        # Clear ownership only after the recovery message has been seen.
        self._restore_worker = None
        self._restore_committing = False
        self._progress_cancel_btn.setText("Cancel")
        self._progress_cancel_btn.setEnabled(True)
        self._set_archive_actions_enabled(True)
        if pending_safe_eject:
            self.closed.emit()
            self.safe_eject_required.emit()
        else:
            self.refresh()

    # ── Delete ──────────────────────────────────────────────────────────

    def _on_delete(self, snapshot_id: str):
        """Delete a snapshot after confirmation.

        Works offline using ``_current_device_id`` — no device connection
        needed since we only touch local PC backup files.
        """
        if self._is_busy():
            return
        snapshot = self._snapshots_by_id.get(snapshot_id)
        if snapshot is None:
            QMessageBox.warning(
                self,
                "Backup Not Found",
                "This backup is no longer present. Refreshing the archive.",
            )
            self.refresh()
            return
        if not bool(getattr(snapshot, "is_valid", True)):
            validation_error = str(
                getattr(snapshot, "validation_error", "")
                or "The backup catalog failed validation."
            )
            QMessageBox.warning(
                self,
                "Delete Disabled — Catalog Needs Attention",
                "iOpenPod will not delete an invalid backup catalog because it "
                "cannot safely determine which stored files are still needed "
                "by other snapshots.\n\n"
                f"Validation details: {validation_error}",
            )
            return
        reply = QMessageBox.question(
            self,
            "Delete Backup",
            "Delete this backup snapshot?\n\n"
            f"Device: {self._viewing_device_name}\n"
            f"Snapshot: {snapshot.display_date}\n"
            f"Contents: {snapshot.file_count:,} files · "
            f"{format_size(snapshot.total_size)}\n\n"
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
        device_id = self._current_device_id
        self._archive_load_generation += 1
        self._delete_generation += 1
        generation = self._delete_generation
        self._delete_result = None
        self._delete_error = ""
        self._cancel_completion_refresh()
        self._set_progress_accessibility("backup cleanup")
        self._progress_title.setText("Deleting Backup Safely")
        self._progress_title.setAccessibleDescription(
            "Deleting the selected snapshot and checking shared backup files"
        )
        self._progress_bar.setRange(0, 0)
        self._progress_stats.setText("")
        self._progress_eta.setText("")
        self._progress_file.setText(
            "Removing the snapshot, then preserving every file still used by "
            "another backup…"
        )
        self._progress_file.setAccessibleDescription(self._progress_file.text())
        self._progress_cancel_btn.setText("Please wait…")
        self._progress_cancel_btn.setEnabled(False)
        self._stack.setCurrentIndex(1)
        self._set_archive_actions_enabled(False)

        from iopenpod.application.runtime import ThreadPoolSingleton, Worker

        worker = Worker(
            delete_backup_snapshot,
            device_id=device_id,
            backup_dir=settings.backup_dir,
            snapshot_id=snapshot_id,
        )
        self._delete_worker = worker
        worker.signals.result.connect(
            lambda result, w=worker, token=generation: (
                self._on_delete_worker_result(w, token, result)
            )
        )
        worker.signals.error.connect(
            lambda error, w=worker, token=generation: (
                self._on_delete_worker_error(w, token, error)
            )
        )
        worker.signals.finished.connect(
            lambda w=worker, token=generation: (
                self._on_delete_worker_finished(w, token)
            )
        )
        ThreadPoolSingleton.get_instance().start(worker)

    def _on_delete_worker_result(
        self,
        worker: Worker,
        generation: int,
        result: object,
    ) -> None:
        if worker is self._delete_worker and generation == self._delete_generation:
            self._delete_result = bool(result)

    def _on_delete_worker_error(
        self,
        worker: Worker,
        generation: int,
        error: object,
    ) -> None:
        if worker is self._delete_worker and generation == self._delete_generation:
            self._delete_error = self._background_error_text(error)

    def _on_delete_worker_finished(
        self,
        worker: Worker,
        generation: int,
    ) -> None:
        """Keep cleanup owned until its outcome has been presented to the user."""
        if worker is not self._delete_worker or generation != self._delete_generation:
            return

        result = self._delete_result
        error = self._delete_error
        if result is not True:
            if error:
                detail = error
            elif result is False:
                detail = (
                    "The snapshot was not deleted. It may have changed, "
                    "disappeared, or failed a safety check."
                )
            else:
                detail = "The background cleanup ended without returning a result."
            QMessageBox.critical(
                self,
                "Backup Delete Could Not Be Confirmed",
                f"{detail}\n\n"
                "iOpenPod will reload the archive now so its display matches "
                "what is safely present on disk.",
            )

        # Do not release ownership until any failure dialog above is dismissed.
        self._delete_worker = None
        self._delete_result = None
        self._delete_error = ""
        self._progress_cancel_btn.setText("Cancel")
        self._progress_cancel_btn.setEnabled(True)
        self._set_archive_actions_enabled(True)
        self.refresh()

    # ── Cancel / Close ──────────────────────────────────────────────────

    def _on_cancel(self):
        """Cancel the current backup/restore operation."""
        if getattr(self, "_restore_committing", False):
            return
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
        if self._is_busy():
            return
        self._cancel_completion_refresh()
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
        self._archive_load_generation += 1
        for archive_worker in tuple(self._archive_workers):
            archive_worker.cancel()
        for worker in (self._backup_worker, self._restore_worker):
            if worker is not None and worker.isRunning():
                worker.requestInterruption()
                worker.wait(5000)  # 5 s grace period

    def prepare_for_app_close(self, timeout_ms: int = 3000) -> bool:
        """Refuse shutdown until active workers deliver their terminal UI result.

        QThread signals are queued to the GUI thread. Waiting here can let a
        worker finish while preventing its recovery/error signal from being
        presented, so closing remains blocked until that handler clears the
        owned worker reference.
        """
        del timeout_ms  # Retained for API compatibility with older callers.
        if self._restore_worker is not None:
            if (
                self._restore_worker.isRunning()
                and not self._restore_committing
            ):
                self._restore_worker.requestInterruption()
            return False
        if self._backup_worker is not None:
            if self._backup_worker.isRunning():
                self._backup_worker.requestInterruption()
            return False
        if getattr(self, "_delete_worker", None) is not None:
            # Snapshot removal and shared-blob collection are intentionally
            # non-cancellable once dispatched. Keep the UI alive for the
            # authoritative result instead of hiding an uncertain outcome.
            return False
        return True

    def closeEvent(self, a0):
        self._shutdown_workers()
        super().closeEvent(a0)

    def deleteLater(self):
        self._shutdown_workers()
        super().deleteLater()
