from PyQt6.QtCore import QRegularExpression, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QCursor, QFont, QFontMetrics, QRegularExpressionValidator
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QProgressBar, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from iopenpod.application.device_identity import format_checksum_type_name

from ..glyphs import glyph_icon, glyph_pixmap
from ..ipod_images import get_ipod_image
from ..styles import (
    FONT_FAMILY,
    LABEL_PRIMARY,
    LABEL_SECONDARY,
    LABEL_TERTIARY,
    MONO_FONT_FAMILY,
    Colors,
    Design,
    Metrics,
    button_css,
    input_css,
    make_scroll_area,
    make_section_header,
    make_separator,
    make_sidebar_section_header,
    progress_bar_css,
    sidebar_panel_css,
)
from .formatters import format_duration_human as format_duration
from .formatters import format_size
from .sidebarNavButton import SidebarNavButton

# iTunes enforces 63 characters for iPod names; MHOD strings are UTF-16-LE
# so only printable Unicode is allowed (no control characters).
_MAX_IPOD_NAME_LEN = 63
_IPOD_NAME_RE = QRegularExpression(r"^[^\x00-\x1f\x7f]*$")


def _dash(value) -> str:
    return str(value) if value not in (None, "", 0, False, {}, []) else "—"


def _yes_no(value) -> str:
    return "Yes" if bool(value) else "No"


def _hex_id(value: int, width: int = 4) -> str:
    try:
        return f"0x{int(value):0{width}X}" if int(value) else "—"
    except (TypeError, ValueError):
        return "—"


def _compact_middle(value: str, *, max_chars: int = 34) -> str:
    text = str(value or "")
    if len(text) <= max_chars:
        return text or "—"
    head = max_chars // 2 - 1
    tail = max_chars - head - 3
    return f"{text[:head]}...{text[-tail:]}"


def _format_format_ids(formats: dict[int, tuple[int, int]]) -> str:
    if not formats:
        return "—"
    return ", ".join(str(fid) for fid in sorted(formats))


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


class TechInfoRow(QWidget):
    """A single row of technical info: label and value."""

    def __init__(self, label: str, value: str = ""):
        super().__init__()
        self.setStyleSheet("background: transparent; border: none;")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, (3), 0, (3))
        layout.setSpacing(6)

        self.label_widget = QLabel(label)
        self.label_widget.setFont(QFont(FONT_FAMILY, Metrics.FONT_XS))
        self.label_widget.setStyleSheet(LABEL_TERTIARY())
        self.label_widget.setSizePolicy(
            QSizePolicy.Policy.Maximum,
            QSizePolicy.Policy.Preferred,
        )
        layout.addWidget(self.label_widget)

        self.value_widget = QLabel(value)
        self.value_widget.setFont(QFont(MONO_FONT_FAMILY, Metrics.FONT_XS))
        self.value_widget.setStyleSheet(LABEL_SECONDARY())
        self.value_widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.value_widget.setMinimumWidth(0)
        self.value_widget.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.value_widget.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )
        layout.addWidget(self.value_widget, 1)

    def setValue(self, value: str, tooltip: str | None = None):
        """Update the value text."""
        text = value or "—"
        self.value_widget.setText(text)
        self.value_widget.setToolTip(tooltip if tooltip is not None else text)


class DeviceInfoCard(QFrame):
    """Card showing iPod device information and stats."""

    device_renamed = pyqtSignal(str)  # emits the new name
    eject_requested = pyqtSignal()    # emitted when the Eject button is clicked
    manage_storage_requested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._rename_edit: QLineEdit | None = None
        self._device_info = None
        self._device_display_name = "No Device"
        self.setObjectName("deviceInfoCard")
        self.setStyleSheet(f"""
            QFrame#deviceInfoCard {{
                background: {Colors.SURFACE_RAISED};
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-radius: {Design.PANEL_RADIUS}px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 10)
        layout.setSpacing(8)

        # ── Header: device identity, with ejection kept with the device ──
        header_layout = QHBoxLayout()
        header_layout.setSpacing(8)

        self.icon_label = QLabel()
        self._set_default_icon()
        self.icon_label.setFixedSize(44, 44)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setStyleSheet("background: transparent; border: none;")
        header_layout.addWidget(self.icon_label, 0, Qt.AlignmentFlag.AlignVCenter)

        name_layout = QVBoxLayout()
        name_layout.setSpacing(1)
        self._name_layout = name_layout

        self.name_label = QLabel("No Device")
        self.name_label.setFont(
            QFont(FONT_FAMILY, Metrics.FONT_SIDEBAR, QFont.Weight.DemiBold)
        )
        self.name_label.setStyleSheet(LABEL_PRIMARY())
        self.name_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.name_label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.name_label.setToolTip("Click to rename your iPod")
        self.name_label.mousePressEvent = lambda ev: self._start_rename()
        name_layout.addWidget(self.name_label)

        self.model_label = QLabel("Press Select to choose your iPod")
        self.model_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.model_label.setStyleSheet(LABEL_SECONDARY())
        self.model_label.setWordWrap(True)
        name_layout.addWidget(self.model_label)

        header_layout.addLayout(name_layout, 1)

        self.eject_button = QPushButton()
        self.eject_button.setFixedSize(
            Design.ICON_BUTTON_SIZE,
            Design.ICON_BUTTON_SIZE,
        )
        self.eject_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.eject_button.setToolTip("Safely eject the iPod from your system")
        self.eject_button.setStyleSheet(button_css("quiet", "sm", extra="padding: 0px;"))
        _ej = glyph_icon("eject", 14, Colors.TEXT_SECONDARY)
        if _ej:
            self.eject_button.setIcon(_ej)
            self.eject_button.setIconSize(QSize(14, 14))
        else:
            self.eject_button.setText("⏏")
        self.eject_button.setEnabled(False)
        self.eject_button.clicked.connect(self.eject_requested.emit)
        header_layout.addWidget(self.eject_button, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header_layout)

        self.library_summary_label = QLabel("— songs · — hours")
        self.library_summary_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.library_summary_label.setStyleSheet(LABEL_SECONDARY())
        layout.addWidget(self.library_summary_label)

        # ── Capacity: labelled bars make device and database usage legible ──
        self._capacity_widget = QWidget()
        self._capacity_widget.setStyleSheet("background: transparent; border: none;")
        capacity_layout = QVBoxLayout(self._capacity_widget)
        capacity_layout.setContentsMargins(0, 0, 0, 0)
        capacity_layout.setSpacing(0)
        cap_info = QPushButton()
        cap_info.setObjectName("storageManageButton")
        cap_info.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        cap_info.setAccessibleName("Manage storage")
        cap_info.setToolTip("Manage database storage")
        cap_info.setEnabled(False)
        cap_info.setStyleSheet(f"""
            QPushButton#storageManageButton {{
                background: transparent;
                border: none;
                border-radius: {(4)}px;
                padding: {(3)}px;
            }}
            QPushButton#storageManageButton:hover {{
                background: {Colors.SURFACE_HOVER};
            }}
            QPushButton#storageManageButton:pressed {{
                background: {Colors.SURFACE_ACTIVE};
            }}
            QPushButton#storageManageButton:disabled {{
                background: transparent;
            }}
        """)
        cap_info.clicked.connect(self.manage_storage_requested.emit)
        self.storage_manage_button = cap_info
        self.storage_manage_button.setMinimumHeight(Design.CONTROL_HEIGHT_SM)
        cap_info_layout = QVBoxLayout(cap_info)
        cap_info_layout.setContentsMargins(0, 0, 0, 0)
        cap_info_layout.setSpacing(4)

        storage_heading = QHBoxLayout()
        storage_heading.setContentsMargins(0, 0, 0, 0)
        self.storage_label = QLabel("Storage")
        self.storage_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_XS, QFont.Weight.DemiBold))
        self.storage_label.setStyleSheet(LABEL_TERTIARY())
        storage_heading.addWidget(self.storage_label)
        storage_heading.addStretch()
        self.storage_value_label = QLabel("—")
        self.storage_value_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_XS))
        self.storage_value_label.setStyleSheet(LABEL_SECONDARY())
        self.storage_value_label.setFixedWidth(88)
        self.storage_value_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        storage_heading.addWidget(self.storage_value_label)
        cap_info_layout.addLayout(storage_heading)

        self.storage_bar = QProgressBar()
        self.storage_bar.setFixedHeight(6)
        self.storage_bar.setTextVisible(False)
        self.storage_bar.setStyleSheet(progress_bar_css(
            height=6,
            radius=3,
            bg=Colors.BORDER_SUBTLE,
            chunk=(
                "qlineargradient(x1:0, y1:0, x2:1, y2:0, "
                f"stop:0 {Colors.ACCENT}, stop:1 {Colors.ACCENT_LIGHT})"
            ),
        ))
        cap_info_layout.addWidget(self.storage_bar)

        self.database_storage_widget = QWidget()
        self.database_storage_widget.setStyleSheet("background: transparent; border: none;")
        database_layout = QVBoxLayout(self.database_storage_widget)
        database_layout.setContentsMargins(0, 2, 0, 0)
        database_layout.setSpacing(4)

        database_heading = QHBoxLayout()
        database_heading.setContentsMargins(0, 0, 0, 0)
        database_label = QLabel("Database")
        database_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_XS, QFont.Weight.DemiBold))
        database_label.setStyleSheet(LABEL_TERTIARY())
        database_heading.addWidget(database_label)
        database_heading.addStretch()
        self.database_value_label = QLabel("—")
        self.database_value_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_XS))
        self.database_value_label.setStyleSheet(LABEL_SECONDARY())
        self.database_value_label.setFixedWidth(88)
        self.database_value_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        database_heading.addWidget(self.database_value_label)
        database_layout.addLayout(database_heading)

        self.database_bar = QProgressBar()
        self.database_bar.setObjectName("databaseStorageBar")
        self.database_bar.setFixedHeight(5)
        self.database_bar.setTextVisible(False)
        self.database_bar.setAccessibleName("Database storage usage")
        self.database_bar.setStyleSheet(progress_bar_css(
            height=5,
            radius=2,
            bg=Colors.BORDER_SUBTLE,
            chunk=Colors.WARNING,
        ))
        self.database_bar.hide()
        database_layout.addWidget(self.database_bar)
        self.database_storage_widget.hide()
        cap_info_layout.addWidget(self.database_storage_widget)
        capacity_layout.addWidget(cap_info)

        self._capacity_widget.hide()  # shown once we have disk info
        layout.addWidget(self._capacity_widget)

        # Technical details section (collapsible)
        self.tech_toggle = QPushButton("Technical Details")
        _chev = glyph_icon("chevron-right", (12), Colors.TEXT_TERTIARY)
        if _chev:
            self.tech_toggle.setIcon(_chev)
            self.tech_toggle.setIconSize(QSize((12), (12)))
        self.tech_toggle.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.tech_toggle.setStyleSheet(button_css(
            "quiet",
            "sm",
            extra=(
                "text-align: left; padding-left: 2px; padding-right: 2px; "
                "min-height: 28px;"
            ),
        ))
        self.tech_toggle.clicked.connect(self._toggle_tech_details)
        layout.addWidget(self.tech_toggle)

        # Technical details container.  The content is intentionally scrollable:
        # the diagnostic rows can be long, but expanding them should not resize
        # the whole app window.
        self.tech_container = make_scroll_area(vertical="as_needed")
        self.tech_container.setMaximumHeight(260)
        self.tech_container.hide()  # Hidden by default
        self.tech_content = QWidget()
        self.tech_content.setStyleSheet("background: transparent; border: none;")
        self.tech_container.setWidget(self.tech_content)
        tech_layout = QVBoxLayout(self.tech_content)
        tech_layout.setContentsMargins(0, (4), 0, 0)
        tech_layout.setSpacing(0)

        # Technical info rows — identity
        self.model_num_row = TechInfoRow("Model #:", "—")
        self.serial_row = TechInfoRow("Serial:", "—")
        self.firmware_row = TechInfoRow("Firmware:", "—")
        self.board_row = TechInfoRow("Board:", "—")
        self.family_id_row = TechInfoRow("Family ID:", "—")
        self.updater_family_id_row = TechInfoRow("Updater ID:", "—")
        self.product_type_row = TechInfoRow("Product:", "—")
        self.fw_guid_row = TechInfoRow("FW GUID:", "—")
        self.conflicts_row = TechInfoRow("Conflicts:", "—")

        # Technical info rows — USB / SCSI
        self.usb_vid_row = TechInfoRow("USB VID:", "—")
        self.usb_pid_row = TechInfoRow("USB PID:", "—")
        self.usb_serial_row = TechInfoRow("USB Serial:", "—")
        self.scsi_row = TechInfoRow("SCSI:", "—")
        self.bus_format_row = TechInfoRow("Bus/Format:", "—")
        self.usbstor_row = TechInfoRow("USBSTOR:", "—")
        self.usb_parent_row = TechInfoRow("USB Parent:", "—")
        self.id_method_row = TechInfoRow("ID Method:", "—")

        # Technical info rows — database / security
        self.db_version_row = TechInfoRow("Database:", "—")
        self.db_limit_row = TechInfoRow("DB Limit:", "—")
        self.device_db_version_row = TechInfoRow("Device DB:", "—")
        self.shadow_db_version_row = TechInfoRow("Shadow DB:", "—")
        self.sqlite_row = TechInfoRow("SQLite:", "—")
        self.db_id_row = TechInfoRow("DB ID:", "—")
        self.checksum_row = TechInfoRow("Checksum:", "—")
        self.hash_scheme_row = TechInfoRow("Hash Scheme:", "—")

        # Technical info rows — capabilities
        self.podcast_support_row = TechInfoRow("Podcasts:", "—")
        self.voice_memo_row = TechInfoRow("Voice Memos:", "—")
        self.sparse_art_row = TechInfoRow("Sparse Art:", "—")
        self.max_transfer_row = TechInfoRow("Max Transfer:", "—")
        self.max_file_row = TechInfoRow("Max File:", "—")
        self.audio_codecs_row = TechInfoRow("Audio:", "—")

        # Technical info rows — storage & artwork
        self.disk_size_row = TechInfoRow("Disk Size:", "—")
        self.free_space_row = TechInfoRow("Free Space:", "—")
        self.art_formats_row = TechInfoRow("Art Formats:", "—")
        self.photo_formats_row = TechInfoRow("Photo Formats:", "—")
        self.chapter_formats_row = TechInfoRow("Chapter Img:", "—")

        # Three grouped sections with hairline separators
        tech_layout.addWidget(make_section_header("Identity"))
        for w in (
            self.model_num_row, self.serial_row, self.firmware_row,
            self.board_row, self.family_id_row, self.updater_family_id_row,
            self.product_type_row, self.fw_guid_row, self.id_method_row,
            self.conflicts_row,
        ):
            tech_layout.addWidget(w)

        tech_layout.addWidget(make_separator())
        tech_layout.addWidget(make_section_header("USB / SCSI"))
        for w in (
            self.usb_vid_row, self.usb_pid_row, self.usb_serial_row,
            self.scsi_row, self.bus_format_row, self.usbstor_row,
            self.usb_parent_row,
        ):
            tech_layout.addWidget(w)

        tech_layout.addWidget(make_separator())
        tech_layout.addWidget(make_section_header("Database"))
        for w in (
            self.db_version_row, self.db_limit_row, self.device_db_version_row,
            self.shadow_db_version_row, self.sqlite_row, self.db_id_row,
            self.checksum_row, self.hash_scheme_row,
        ):
            tech_layout.addWidget(w)

        tech_layout.addWidget(make_separator())
        tech_layout.addWidget(make_section_header("Capabilities"))
        for w in (
            self.podcast_support_row, self.voice_memo_row,
            self.sparse_art_row, self.max_transfer_row,
            self.max_file_row, self.audio_codecs_row,
        ):
            tech_layout.addWidget(w)

        tech_layout.addWidget(make_separator())
        tech_layout.addWidget(make_section_header("Storage"))
        for w in (
            self.disk_size_row, self.free_space_row, self.art_formats_row,
            self.photo_formats_row, self.chapter_formats_row,
        ):
            tech_layout.addWidget(w)

        layout.addWidget(self.tech_container)

        # Save indicator — shown briefly after quick metadata writes
        self._save_label = QLabel()
        self._save_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_XS))
        self._save_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._save_label.setStyleSheet("background: transparent; border: none;")
        self._save_label.hide()
        layout.addWidget(self._save_label)

        self._save_hide_timer = QTimer(self)
        self._save_hide_timer.setSingleShot(True)
        self._save_hide_timer.timeout.connect(self._save_label.hide)

        self._tech_expanded = False

    def _set_default_icon(self) -> None:
        """Reset the header icon to the generic music fallback."""
        self.icon_label.clear()
        px = glyph_pixmap("music", (32), Colors.TEXT_SECONDARY)
        if px:
            self.icon_label.setPixmap(px)
        else:
            self.icon_label.setText("♪")
            self.icon_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_ICON_MD))

    def _start_rename(self, event=None):
        """Show an inline QLineEdit to rename the iPod."""
        current = self._device_display_name
        if current == "No Device" or self._rename_edit is not None:
            return

        self._rename_edit = _RenameLineEdit(current)
        self._rename_edit.setFont(
            QFont(FONT_FAMILY, Metrics.FONT_SIDEBAR, QFont.Weight.DemiBold)
        )
        self._rename_edit.setStyleSheet(
            input_css(radius=4, padding="1px 4px", font_size=Metrics.FONT_SIDEBAR)
        )
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
        edit = self._rename_edit
        self._rename_edit = None  # clear before hide() to prevent re-entrant call via focus_lost
        edit.hide()
        edit.deleteLater()
        self.name_label.show()

    def _finish_rename(self):
        """Accept the rename and emit the new name."""
        if self._rename_edit is None:
            return

        edit = self._rename_edit
        self._rename_edit = None  # prevent re-entrant call from .hide()

        new_name = edit.text().strip()
        old_name = self._device_display_name

        edit.hide()
        edit.deleteLater()
        self.name_label.show()

        if new_name and new_name != old_name:
            self._set_device_name(new_name)
            self.device_renamed.emit(new_name)

    def _toggle_tech_details(self):
        """Toggle technical details visibility."""
        self._tech_expanded = not self._tech_expanded
        self.tech_container.setVisible(self._tech_expanded)
        chev = "chevron-down" if self._tech_expanded else "chevron-right"
        icon = glyph_icon(chev, (12), Colors.TEXT_TERTIARY)
        if icon:
            self.tech_toggle.setIcon(icon)

    def resizeEvent(self, a0):
        super().resizeEvent(a0)
        self._refresh_name_label()

    def _set_device_name(self, text: str) -> None:
        self._device_display_name = text or "No Device"
        self._refresh_name_label()

    def _refresh_name_label(self) -> None:
        """Fit and elide the name based on the actual label width."""
        text = self._device_display_name or "No Device"
        max_w = self.name_label.width()
        if max_w <= 1:
            max_w = max(80, self.width() - 128)

        for size in (Metrics.FONT_SIDEBAR, Metrics.FONT_LG, Metrics.FONT_MD):
            font = QFont(FONT_FAMILY, size, QFont.Weight.DemiBold)
            metrics = QFontMetrics(font)
            if metrics.horizontalAdvance(text) <= max_w:
                self.name_label.setFont(font)
                self.name_label.setText(text)
                self.name_label.setToolTip("Click to rename your iPod")
                return

        font = QFont(FONT_FAMILY, Metrics.FONT_MD, QFont.Weight.DemiBold)
        metrics = QFontMetrics(font)
        elided = metrics.elidedText(text, Qt.TextElideMode.ElideRight, max_w)
        self.name_label.setFont(font)
        self.name_label.setText(elided)
        if text != "No Device":
            self.name_label.setToolTip(f"{text}\nClick to rename your iPod")
        else:
            self.name_label.setToolTip("Click to rename your iPod")

    def update_device_info(self, name: str, model: str = "", device_info=None):
        """Update device name and model."""
        self._device_info = device_info
        display = name or "No Device"
        self._set_device_name(display)
        self.model_label.setText(model)
        self.eject_button.setEnabled(bool(name) and display != "No Device")

        # Try to load real product photo from centralized store
        family = ""
        generation = ""
        color = ""
        dev = device_info
        if dev:
            family = getattr(dev, "model_family", "") or ""
            generation = getattr(dev, "generation", "") or ""
            color = getattr(dev, "color", "") or ""
        if not family and model:
            family = model

        photo = get_ipod_image(family, generation, 44, color) if family else None
        if photo and not photo.isNull():
            self.icon_label.setPixmap(photo)
            self.icon_label.setFont(QFont())  # Clear emoji font
        else:
            # Fallback to generic icon when no matching product photo exists.
            self._set_default_icon()

        if dev:
            field_sources = getattr(dev, "_field_sources", {})

            def source_tip(field: str, value: str) -> str:
                source = field_sources.get(field, "")
                if source and value != "—":
                    return f"{value}\nSource: {source}"
                return value

            self.model_num_row.setValue(dev.model_number or '—')
            self.serial_row.setValue(dev.serial or '—')
            self.firmware_row.setValue(dev.firmware or '—')
            self.board_row.setValue(dev.board or '—')
            self.fw_guid_row.setValue(dev.firewire_guid or '—')
            family_id = _dash(dev.family_id)
            self.family_id_row.setValue(
                family_id,
                source_tip("family_id", family_id),
            )
            self.updater_family_id_row.setValue(
                _dash(dev.updater_family_id),
                source_tip("updater_family_id", _dash(dev.updater_family_id)),
            )
            self.product_type_row.setValue(_dash(dev.product_type))
            conflicts = getattr(dev, "identity_conflicts", []) or []
            if conflicts:
                detail = "; ".join(
                    str(c.get("reason") or c.get("field") or c)
                    for c in conflicts
                    if isinstance(c, dict)
                ) or str(conflicts)
                self.conflicts_row.setValue(str(len(conflicts)), detail)
            else:
                self.conflicts_row.setValue("None")

            usb_vid = _hex_id(dev.usb_vid)
            self.usb_vid_row.setValue(usb_vid, source_tip("usb_vid", usb_vid))
            self.usb_pid_row.setValue(f"0x{dev.usb_pid:04X}" if dev.usb_pid else '—')
            usb_serial = _dash(dev.usb_serial)
            self.usb_serial_row.setValue(
                _compact_middle(usb_serial),
                source_tip("usb_serial", usb_serial),
            )
            scsi_bits = [
                bit for bit in (
                    dev.scsi_vendor,
                    dev.scsi_product,
                    dev.scsi_revision,
                )
                if bit
            ]
            scsi_text = " ".join(scsi_bits) if scsi_bits else "—"
            self.scsi_row.setValue(scsi_text)
            bus_bits = [
                bit for bit in (
                    dev.connected_bus,
                    dev.reported_volume_format,
                )
                if bit
            ]
            self.bus_format_row.setValue(" / ".join(bus_bits) if bus_bits else "—")
            usbstor = _dash(dev.usbstor_instance_id)
            self.usbstor_row.setValue(_compact_middle(usbstor), usbstor)
            usb_parent = _dash(
                dev.usb_grandparent_instance_id
                or dev.usb_parent_instance_id
            )
            self.usb_parent_row.setValue(_compact_middle(usb_parent), usb_parent)
            self.id_method_row.setValue(dev.identification_method or '—')

            self.checksum_row.setValue(format_checksum_type_name(dev.checksum_type))
            scheme_names = {-1: '—', 0: 'None', 1: 'Scheme 1', 2: 'Scheme 2'}
            self.hash_scheme_row.setValue(
                scheme_names.get(dev.hashing_scheme, str(dev.hashing_scheme))
            )
            self.device_db_version_row.setValue(
                f"0x{int(dev.db_version):X}" if dev.db_version else "—",
                source_tip(
                    "db_version",
                    f"0x{int(dev.db_version):X}" if dev.db_version else "—",
                ),
            )
            self.shadow_db_version_row.setValue(
                str(dev.shadow_db_version) if dev.shadow_db_version else "—"
            )
            caps = dev.capabilities
            max_database_bytes = int(
                getattr(caps, "max_database_bytes", 0) or 0
            )
            self.db_limit_row.setValue(
                format_size(max_database_bytes) if max_database_bytes else "—"
            )
            self.sqlite_row.setValue(
                _yes_no(dev.uses_sqlite_db or getattr(caps, "uses_sqlite_db", False))
            )

            podcast_known = "podcasts_supported" in field_sources
            self.podcast_support_row.setValue(
                _yes_no(
                    dev.podcasts_supported
                    if podcast_known else caps.supports_podcast
                )
            )
            voice_known = "voice_memos_supported" in field_sources
            self.voice_memo_row.setValue(
                _yes_no(dev.voice_memos_supported) if voice_known else "—"
            )
            self.sparse_art_row.setValue(
                _yes_no(dev.supports_sparse_artwork or caps.supports_sparse_artwork)
            )
            if dev.max_transfer_speed:
                self.max_transfer_row.setValue(
                    f"{int(dev.max_transfer_speed):,} KB/s"
                )
            else:
                self.max_transfer_row.setValue("—")
            if dev.max_file_size_gb:
                self.max_file_row.setValue(f"{dev.max_file_size_gb} GB")
            else:
                self.max_file_row.setValue("—")
            if dev.audio_codecs:
                codecs = ", ".join(sorted(str(k) for k in dev.audio_codecs))
                self.audio_codecs_row.setValue(_compact_middle(codecs), codecs)
            else:
                self.audio_codecs_row.setValue("—")

            # Storage
            if dev.disk_size_gb > 0:
                self.disk_size_row.setValue(f"{dev.disk_size_gb:.1f} GB")
            else:
                self.disk_size_row.setValue("—")
            if dev.free_space_gb > 0:
                self.free_space_row.setValue(f"{dev.free_space_gb:.1f} GB")
            else:
                self.free_space_row.setValue("—")

            # Capacity hero: compact bars directly under the device name
            if dev.disk_size_gb > 0:
                used_pct = int(((dev.disk_size_gb - dev.free_space_gb) / dev.disk_size_gb) * 100)
                self.storage_bar.setValue(max(0, min(100, used_pct)))
                storage_tip = (
                    f"Device storage: {dev.free_space_gb:.1f} GB free of "
                    f"{dev.disk_size_gb:.1f} GB"
                )
                self.storage_value_label.setText(f"{dev.free_space_gb:.0f} GB free")
                self._capacity_widget.setToolTip(storage_tip)
                self.storage_manage_button.setToolTip(storage_tip)
                self.storage_manage_button.setEnabled(True)
                self._capacity_widget.show()

            # Artwork formats
            if dev.artwork_formats:
                self.art_formats_row.setValue(_format_format_ids(dev.artwork_formats))
            else:
                self.art_formats_row.setValue('—')
            self.photo_formats_row.setValue(_format_format_ids(dev.photo_formats))
            self.chapter_formats_row.setValue(
                _format_format_ids(dev.chapter_image_formats)
            )

            if not getattr(self, "_refreshing_tech_details", False):
                QTimer.singleShot(
                    1800,
                    self._refresh_technical_details_from_current_device,
                )

    def _refresh_technical_details_from_current_device(self):
        """Refresh rows after background device validation fills richer fields."""
        dev = self._device_info
        if not dev:
            return
        self._refreshing_tech_details = True
        try:
            self.update_device_info(
                self.name_label.text(),
                self.model_label.text(),
                device_info=dev,
            )
        finally:
            self._refreshing_tech_details = False

    def update_database_info(self, version_hex: str, version_name: str, db_id: int):
        """Update database technical information."""
        self.db_version_row.setValue(f"{version_hex} ({version_name})")
        # Format database ID as hex
        if db_id:
            self.db_id_row.setValue(f"{db_id:016X}")
        else:
            self.db_id_row.setValue("—")

    def update_database_storage_info(
        self,
        database_size_bytes: int,
        max_database_bytes: int,
        database_path: str = "",
    ) -> None:
        """Update the compact iTunesDB/iTunesCDB size meter."""
        max_bytes = max(0, int(max_database_bytes or 0))
        size_bytes = max(0, int(database_size_bytes or 0))
        if max_bytes <= 0:
            self.database_bar.setValue(0)
            self.database_value_label.setText("—")
            self.database_bar.hide()
            self.database_storage_widget.hide()
            self.storage_manage_button.setMinimumHeight(Design.CONTROL_HEIGHT_SM)
            self.storage_manage_button.updateGeometry()
            return

        used_pct = int((size_bytes / max_bytes) * 100) if max_bytes else 0
        self.database_bar.setValue(max(0, min(100, used_pct)))
        chunk = Colors.DANGER if size_bytes > max_bytes else Colors.WARNING
        self.database_bar.setStyleSheet(progress_bar_css(
            height=5,
            radius=2,
            bg=Colors.BORDER_SUBTLE,
            chunk=chunk,
        ))
        size_text = format_size(size_bytes) or "0 B"
        max_text = format_size(max_bytes) or "—"
        db_name = str(database_path or "Database").replace("\\", "/").rsplit("/", 1)[-1]
        status = "over limit" if size_bytes > max_bytes else "used"
        self.database_bar.setToolTip(
            f"{db_name}: {size_text} of {max_text} database limit {status}"
        )
        self.database_value_label.setText(f"{used_pct}% used")
        self.storage_manage_button.setToolTip(
            f"Manage database storage\n{db_name}: {size_text} of {max_text} database limit {status}"
        )
        self.storage_manage_button.setEnabled(True)
        # QPushButton computes its size hint from its own label, not the
        # embedded layout. Reserve enough vertical space for both meters so
        # the database row is inside the button's painted content rect.
        self.storage_manage_button.setMinimumHeight(68)
        self.storage_manage_button.updateGeometry()
        self.database_storage_widget.show()
        self.database_bar.show()
        self._capacity_widget.show()

    def update_stats(self, tracks: int, albums: int, size_bytes: int, duration_ms: int,
                     videos: int = 0, podcasts: int = 0, audiobooks: int = 0):
        """Update the compact library summary beneath the device identity."""
        song_text = f"{tracks:,}" if tracks else "0"

        hours = (duration_ms or 0) / 3_600_000
        if hours >= 100:
            hours_text = f"{hours:,.0f}"
        elif hours >= 10:
            hours_text = f"{hours:.0f}"
        elif hours >= 1:
            hours_text = f"{hours:.1f}"
        else:
            hours_text = "0"

        self.library_summary_label.setText(
            f"{song_text} song{'s' if tracks != 1 else ''} · {hours_text} hours"
        )

        # Tooltip carries the precise size + playtime that no longer have
        # a dedicated line in the card.
        size_str = format_size(size_bytes)
        dur_str = format_duration(duration_ms)
        tip_parts = [p for p in (size_str, dur_str) if p]
        if tip_parts:
            self.library_summary_label.setToolTip(" · ".join(tip_parts))

    def show_save_indicator(self, state: str) -> None:
        """Show a brief status indicator after a quick metadata write.

        state: "saving" | "saved" | "error"
        """
        self._save_hide_timer.stop()
        if state == "saving":
            self._save_label.setStyleSheet(
                f"background: transparent; border: none; color: {Colors.TEXT_TERTIARY};"
            )
            self._save_label.setText("Saving…")
            self._save_label.show()
        elif state == "saved":
            self._save_label.setStyleSheet(
                f"background: transparent; border: none; color: {Colors.SUCCESS};"
            )
            self._save_label.setText("✓ Saved")
            self._save_label.show()
            self._save_hide_timer.start(2500)
        elif state == "error":
            self._save_label.setStyleSheet(
                f"background: transparent; border: none; color: {Colors.DANGER};"
            )
            self._save_label.setText("⚠ Save failed")
            self._save_label.show()
            self._save_hide_timer.start(4000)

    def clear(self):
        """Clear all info (when no device selected)."""
        self._device_info = None
        self._set_device_name("No Device")
        self.model_label.setText("Press Select to choose your iPod")
        self._set_default_icon()
        self.database_bar.setValue(0)
        self.database_bar.hide()
        self.database_storage_widget.hide()
        self.storage_value_label.setText("—")
        self.database_value_label.setText("—")
        self.storage_manage_button.setEnabled(False)
        self._capacity_widget.hide()
        self.library_summary_label.setText("— songs · — hours")
        self._save_label.hide()
        self._save_hide_timer.stop()
        self.eject_button.setEnabled(False)
        # Clear tech details
        for row in (
            self.model_num_row, self.serial_row, self.firmware_row,
            self.board_row, self.family_id_row, self.updater_family_id_row,
            self.product_type_row, self.fw_guid_row, self.conflicts_row,
            self.usb_vid_row, self.usb_pid_row, self.usb_serial_row,
            self.scsi_row, self.bus_format_row, self.usbstor_row,
            self.usb_parent_row, self.id_method_row,
            self.db_version_row, self.db_limit_row, self.device_db_version_row,
            self.shadow_db_version_row, self.sqlite_row, self.db_id_row,
            self.checksum_row, self.hash_scheme_row,
            self.podcast_support_row, self.voice_memo_row,
            self.sparse_art_row, self.max_transfer_row, self.max_file_row,
            self.audio_codecs_row, self.disk_size_row, self.free_space_row,
            self.art_formats_row, self.photo_formats_row,
            self.chapter_formats_row,
        ):
            row.setValue("—")


class Sidebar(QFrame):
    category_changed = pyqtSignal(str)
    device_renamed = pyqtSignal(str)  # emits new iPod name
    eject_requested = pyqtSignal()    # emitted when the Eject button is clicked
    tag_fixes_requested = pyqtSignal()
    manage_storage_requested = pyqtSignal()

    # Categories that only make sense on video-capable iPods
    _VIDEO_CATEGORIES = frozenset({"Videos", "Movies", "TV Shows", "Music Videos"})

    # Categories that only make sense when podcast support is present
    _PODCAST_CATEGORIES = frozenset({"Podcasts"})
    _PHOTO_CATEGORIES = frozenset({"Photos"})

    category_glyphs = {
        "Albums": "album",
        "Artists": "user",
        "Genres": "grid",
        "Tracks": "music",
        "Playlists": "playlist",
        "Photos": "photo",
        "Podcasts": "broadcast",
        "Audiobooks": "book",
        "Movies": "film",
        "TV Shows": "monitor",
        "Music Videos": "video",
        "Videos": "video",
    }

    def __init__(self):
        super().__init__()
        self._video_capabilities_visible = True
        self._podcast_capabilities_visible = True
        self._photo_capabilities_visible = True

        self.setObjectName("sidebar")
        self.setStyleSheet(sidebar_panel_css("sidebar"))

        self.sidebarLayout = QVBoxLayout(self)
        _outer = Design.SIDEBAR_OUTER_MARGIN
        self.sidebarLayout.setContentsMargins(_outer, _outer, _outer, _outer)
        self.sidebarLayout.setSpacing(6)
        self.setFixedWidth(Metrics.SIDEBAR_WIDTH)

        # Device info card at top
        self.device_card = DeviceInfoCard()
        self.device_card.device_renamed.connect(self.device_renamed)
        self.device_card.eject_requested.connect(self.eject_requested)
        self.device_card.manage_storage_requested.connect(self.manage_storage_requested)
        self.sidebarLayout.addWidget(self.device_card)

        # Device actions form one compact command group below the summary.
        device_actions = QWidget()
        device_actions.setObjectName("sidebarDeviceActions")
        device_actions.setStyleSheet("background: transparent; border: none;")
        device_actions_layout = QVBoxLayout(device_actions)
        device_actions_layout.setContentsMargins(0, 0, 0, 0)
        device_actions_layout.setSpacing(6)

        self.deviceSelectLayout = QHBoxLayout()
        self.deviceSelectLayout.setContentsMargins(0, 0, 0, 0)
        self.deviceSelectLayout.setSpacing(6)

        self.deviceButton = QPushButton("Select")
        self.rescanButton = QPushButton("Rescan")

        self.deviceButton.setStyleSheet(button_css("secondary", "sm"))
        self.rescanButton.setStyleSheet(button_css("secondary", "sm"))
        self.deviceButton.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.rescanButton.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))

        _icon_sz = QSize(Design.SIDEBAR_ICON_SIZE, Design.SIDEBAR_ICON_SIZE)
        _bi = glyph_icon("tablet", Design.SIDEBAR_ICON_SIZE, Colors.TEXT_SECONDARY)
        if _bi:
            self.deviceButton.setIcon(_bi)
            self.deviceButton.setIconSize(_icon_sz)
        _bi = glyph_icon("refresh", Design.SIDEBAR_ICON_SIZE, Colors.TEXT_SECONDARY)
        if _bi:
            self.rescanButton.setIcon(_bi)
            self.rescanButton.setIconSize(_icon_sz)

        self.deviceSelectLayout.addWidget(self.deviceButton)
        self.deviceSelectLayout.addWidget(self.rescanButton)
        device_actions_layout.addLayout(self.deviceSelectLayout)

        # The one primary command remains visually distinct.
        self.syncButton = QPushButton("Sync with PC")
        self.syncButton.setStyleSheet(button_css("primary", "md"))
        self.syncButton.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD, QFont.Weight.DemiBold))
        _bi = glyph_icon("download", Design.SIDEBAR_ICON_SIZE, Colors.TEXT_ON_ACCENT)
        if _bi:
            self.syncButton.setIcon(_bi)
            self.syncButton.setIconSize(_icon_sz)
        device_actions_layout.addWidget(self.syncButton)
        self.sidebarLayout.addWidget(device_actions)

        maintenance_section = QWidget()
        maintenance_layout = QVBoxLayout(maintenance_section)
        maintenance_layout.setContentsMargins(0, 0, 0, 0)
        maintenance_layout.setSpacing(0)
        maintenance_layout.addWidget(make_sidebar_section_header("Maintenance"))

        self.backupButton = SidebarNavButton("Backups", icon_name="archive")
        maintenance_layout.addWidget(self.backupButton)

        self.tagFixButton = SidebarNavButton(
            "Normalize Tags",
            icon_name="check-circle",
        )
        self.tagFixButton.setToolTip("Preview and apply iPod-friendly tag fixes across the whole library.")
        self.tagFixButton.setEnabled(False)
        self.tagFixButton.clicked.connect(self.tag_fixes_requested.emit)
        maintenance_layout.addWidget(self.tagFixButton)
        self.sidebarLayout.addWidget(maintenance_section)

        self.sidebarLayout.addSpacing(Design.SIDEBAR_SECTION_GAP)

        # ── Library section ───────────────────────────────────────
        library_section = QWidget()
        library_layout = QVBoxLayout(library_section)
        library_layout.setContentsMargins(0, 0, 0, 0)
        library_layout.setSpacing(2)

        lib_label = make_sidebar_section_header("Library")
        library_layout.addWidget(lib_label)

        # Only the category buttons scroll; the section header stays fixed.
        lib_scroll = make_scroll_area()

        lib_container = QWidget()
        lib_container.setStyleSheet("background: transparent;")
        lib_layout = QVBoxLayout(lib_container)
        lib_layout.setContentsMargins(0, 0, 0, 0)
        lib_layout.setSpacing(0)

        self.buttons = {}

        for category, icon_name in self.category_glyphs.items():
            btn = SidebarNavButton(category, icon_name=icon_name)

            btn.clicked.connect(
                lambda clicked, category=category: self.selectCategory(category))

            lib_layout.addWidget(btn)
            self.buttons[category] = btn

        lib_layout.addStretch()
        lib_scroll.setWidget(lib_container)
        library_layout.addWidget(lib_scroll, 1)  # stretch factor 1
        self.sidebarLayout.addWidget(library_section, 1)

        self.sidebarLayout.addSpacing(Design.SIDEBAR_SECTION_GAP)

        # Settings button at bottom
        self.settingsButton = SidebarNavButton("Settings", icon_name="settings")
        self.sidebarLayout.addWidget(self.settingsButton)

        self.selectedCategory = list(self.category_glyphs.keys())[0]
        self.selectCategory(self.selectedCategory)

    def updateDeviceInfo(self, name: str, model: str, tracks: int, albums: int,
                         size_bytes: int, duration_ms: int,
                         db_version_hex: str = "", db_version_name: str = "",
                         db_id: int = 0, videos: int = 0,
                         podcasts: int = 0, audiobooks: int = 0,
                         device_info=None, database_size_bytes: int = 0,
                         max_database_bytes: int = 0,
                         database_path: str = ""):
        """Update the device info card with current device data."""
        self.device_card.update_device_info(name, model, device_info=device_info)
        self.device_card.update_stats(tracks, albums, size_bytes, duration_ms,
                                      videos=videos, podcasts=podcasts, audiobooks=audiobooks)
        self.device_card.update_database_storage_info(
            database_size_bytes,
            max_database_bytes,
            database_path,
        )
        if db_version_hex:
            self.device_card.update_database_info(db_version_hex, db_version_name, db_id)

    def show_save_indicator(self, state: str) -> None:
        """Delegate save indicator to the device info card."""
        self.device_card.show_save_indicator(state)

    def clearDeviceInfo(self):
        """Clear device info when no device is selected."""
        self.device_card.clear()
        self.setTagFixesAvailable(False)
        self.setTagFixCount(0)
        # Show all categories again when no device is selected
        self.setVideoVisible(True)
        self.setPodcastVisible(True)
        self.setPhotoVisible(True)

    def setEjectAvailable(self, available: bool) -> None:
        """Allow safe eject even when device data cannot be loaded."""
        self.device_card.eject_button.setEnabled(available)

    def setTagFixesAvailable(self, available: bool) -> None:
        self.tagFixButton.setEnabled(available)

    def setTagFixCount(self, field_count: int, track_count: int = 0) -> None:
        """Update the pending normalization badge and explanatory tooltip."""

        field_count = max(0, int(field_count))
        track_count = max(0, int(track_count))
        self.tagFixButton.setBadgeCount(field_count)
        if field_count <= 0:
            self.tagFixButton.setToolTip(
                "Preview and apply iPod-friendly tag fixes across the whole library."
            )
            return
        field_word = "field" if field_count == 1 else "fields"
        track_word = "track" if track_count == 1 else "tracks"
        self.tagFixButton.setToolTip(
            f"{field_count:,} tag {field_word} can be normalized across "
            f"{track_count:,} {track_word}."
        )

    def _first_visible_category(self) -> str | None:
        preferred = self.buttons.get("Albums")
        if preferred is not None and preferred.isVisible():
            return "Albums"
        for category, btn in self.buttons.items():
            if btn.isVisible():
                return category
        return None

    def _ensure_selected_category_visible(self) -> None:
        selected_btn = self.buttons.get(self.selectedCategory)
        if selected_btn is not None and selected_btn.isVisible():
            self._style_nav_btn(self.selectedCategory, selected=True)
            return

        fallback = self._first_visible_category()
        if fallback is None:
            return
        self.selectCategory(fallback)

    def setLibraryTabsVisible(self, visible: bool):
        """Show or hide all library category tabs."""
        for label, btn in self.buttons.items():
            if visible:
                if label in self._VIDEO_CATEGORIES and not self._video_capabilities_visible:
                    btn.setVisible(False)
                elif label in self._PODCAST_CATEGORIES and not self._podcast_capabilities_visible:
                    btn.setVisible(False)
                elif label in self._PHOTO_CATEGORIES and not self._photo_capabilities_visible:
                    btn.setVisible(False)
                else:
                    btn.setVisible(True)
            else:
                btn.setVisible(False)

        if visible:
            self._ensure_selected_category_visible()

    def setVideoVisible(self, visible: bool):
        """Show or hide video-related sidebar categories.

        Called after device identification to hide video categories on iPods
        that don't support video (e.g. Mini, Nano 1G/2G, Shuffle, iPod 1G-4G).
        If the currently selected category is being hidden, switch to Albums.
        """
        self._video_capabilities_visible = visible
        for cat in self._VIDEO_CATEGORIES:
            btn = self.buttons.get(cat)
            if btn:
                btn.setVisible(visible)
        self._ensure_selected_category_visible()

    def setPodcastVisible(self, visible: bool):
        """Show or hide podcast sidebar categories.

        Called after device identification to hide podcasts on iPods
        that don't support them (pre-5G, Shuffle).
        """
        self._podcast_capabilities_visible = visible
        for cat in self._PODCAST_CATEGORIES:
            btn = self.buttons.get(cat)
            if btn:
                btn.setVisible(visible)
        self._ensure_selected_category_visible()

    def setPhotoVisible(self, visible: bool):
        self._photo_capabilities_visible = visible
        for cat in self._PHOTO_CATEGORIES:
            btn = self.buttons.get(cat)
            if btn:
                btn.setVisible(visible)
        self._ensure_selected_category_visible()

    def resetLibraryCategory(self) -> None:
        """Select the default library category and notify listeners."""
        previous = self.selectedCategory
        if previous != "Albums":
            self._style_nav_btn(previous, selected=False)
        self.selectedCategory = "Albums"
        self._style_nav_btn("Albums", selected=True)
        self.category_changed.emit("Albums")

    def selectCategory(self, category, force_emit: bool = False):
        btn = self.buttons.get(category)
        if btn is None or not btn.isVisible():
            fallback = self._first_visible_category()
            if fallback is None:
                return
            category = fallback

        if category == self.selectedCategory:
            self._style_nav_btn(category, selected=True)
            if force_emit:
                self.category_changed.emit(category)
            return

        self._style_nav_btn(self.selectedCategory, selected=False)
        self.selectedCategory = category
        self._style_nav_btn(category, selected=True)
        self.category_changed.emit(category)

    def _style_nav_btn(self, category: str, selected: bool):
        btn = self.buttons.get(category)
        if btn is None:
            return
        btn.setSelected(selected)
