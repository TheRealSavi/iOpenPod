"""
Settings page widget for iOpenPod.

macOS Ventura-style two-panel layout: fixed sidebar with navigation items
on the left, scrollable card-based content on the right.
"""
from __future__ import annotations

import hashlib
import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QDesktopServices, QFont
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..styles import (
    FONT_FAMILY,
    Colors,
    Metrics,
    back_btn_css,
    btn_css,
    combo_css,
    danger_btn_css,
    input_css,
    link_btn_css,
    make_scroll_area,
    resolve_accent_color,
    sidebar_nav_css,
    sidebar_nav_selected_css,
)

if TYPE_CHECKING:
    from app_core.services import DeviceSessionService, SettingsService


# ── Reusable row widgets ────────────────────────────────────────────────────

class SettingRow(QFrame):
    """A single setting row with label, description, and control on the right."""

    def __init__(self, title: str, description: str = ""):
        super().__init__()
        self.setStyleSheet(f"""
            QFrame {{
                background: {Colors.SURFACE};
                border: none;
                border-bottom: 1px solid {Colors.BORDER_SUBTLE};
                border-radius: 0px;
            }}
        """)

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(16, 14, 16, 14)
        self._layout.setSpacing(16)

        # Left side: title + description
        text_layout = QVBoxLayout()
        text_layout.setSpacing(3)

        self.title_label = QLabel(title)
        self.title_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_LG, QFont.Weight.DemiBold))
        self.title_label.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; background: transparent; border: none;")
        text_layout.addWidget(self.title_label)

        if description:
            self.desc_label = QLabel(description)
            self.desc_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
            self.desc_label.setStyleSheet(f"color: {Colors.TEXT_TERTIARY}; background: transparent; border: none;")
            self.desc_label.setWordWrap(True)
            text_layout.addWidget(self.desc_label)

        self._layout.addLayout(text_layout, stretch=1)
        self._text_layout = text_layout

    def add_control(self, widget: QWidget):
        """Add a control widget to the right side of the row."""
        widget.setStyleSheet(widget.styleSheet() + " background: transparent; border: none;")
        self._layout.addWidget(widget)

    def set_override_warning(self, visible: bool) -> None:
        """Show or hide a yellow 'overridden by device' warning under the title."""
        if not hasattr(self, "_override_label"):
            self._override_label = QLabel("Overridden by device settings")
            self._override_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
            self._override_label.setStyleSheet(
                f"color: {Colors.WARNING}; background: transparent; border: none;"
            )
            self._text_layout.addWidget(self._override_label)
        self._override_label.setVisible(visible)


class ToggleRow(SettingRow):
    """Setting row with a toggle switch (checkbox)."""

    changed = pyqtSignal(bool)

    def __init__(self, title: str, description: str = "", checked: bool = False):
        super().__init__(title, description)

        self.checkbox = QCheckBox()
        self.checkbox.setChecked(checked)
        self.checkbox.setStyleSheet(f"""
            QCheckBox {{
                background: transparent;
                border: none;
            }}
            QCheckBox::indicator {{
                width: {(38)}px;
                height: {(20)}px;
                border-radius: {(10)}px;
                background: {Colors.SURFACE_ACTIVE};
                border: 1px solid {Colors.BORDER};
            }}
            QCheckBox::indicator:hover {{
                background: {Colors.SURFACE_HOVER};
                border: 1px solid {Colors.BORDER_FOCUS};
            }}
            QCheckBox::indicator:checked {{
                background: {Colors.ACCENT};
                border: 1px solid {Colors.ACCENT};
            }}
            QCheckBox::indicator:checked:hover {{
                background: {Colors.ACCENT_HOVER};
                border: 1px solid {Colors.ACCENT_LIGHT};
            }}
        """)
        self.checkbox.toggled.connect(self.changed.emit)
        self.add_control(self.checkbox)

    @property
    def value(self) -> bool:
        return self.checkbox.isChecked()

    @value.setter
    def value(self, v: bool):
        self.checkbox.setChecked(v)


class ComboRow(SettingRow):
    """Setting row with a dropdown."""

    changed = pyqtSignal(str)

    def __init__(self, title: str, description: str = "",
                 options: list[str] | None = None, current: str = ""):
        super().__init__(title, description)

        self.combo = QComboBox()
        self.combo.setFixedWidth(130)
        self.combo.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        self.combo.setStyleSheet(combo_css())
        if options:
            self.combo.addItems(options)
        if current:
            idx = self.combo.findText(current)
            if idx >= 0:
                self.combo.setCurrentIndex(idx)
        self.combo.currentTextChanged.connect(self.changed.emit)
        self.add_control(self.combo)

    @property
    def value(self) -> str:
        return self.combo.currentText()


class SpinRow(SettingRow):
    """Setting row with a numeric spin box."""

    changed = pyqtSignal(int)

    def __init__(self, title: str, description: str = "",
                 minimum: int = 1, maximum: int = 99, current: int = 3):
        super().__init__(title, description)

        self.spin = QSpinBox()
        self.spin.setRange(minimum, maximum)
        self.spin.setValue(current)
        self.spin.setFixedWidth(80)
        self.spin.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        self.spin.setStyleSheet(input_css() + """
            QSpinBox {
                padding: 4px 8px;
                border-radius: 6px;
            }
        """)
        self.spin.valueChanged.connect(self.changed.emit)
        self.add_control(self.spin)

    @property
    def value(self) -> int:
        return self.spin.value()

    @value.setter
    def value(self, v: int):
        self.spin.setValue(v)


class FolderRow(SettingRow):
    """Setting row with folder path display and browse button."""

    changed = pyqtSignal(str)

    def __init__(self, title: str, description: str = "", path: str = "",
                 resolve_default_fn=None):
        super().__init__(title, description)
        self._resolve_default_fn = resolve_default_fn

        self.open_btn = QPushButton("Open \u2197")
        self.open_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.open_btn.setStyleSheet(link_btn_css())
        self.open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_btn.clicked.connect(self._open_location)
        self._text_layout.addWidget(self.open_btn)

        right_layout = QHBoxLayout()
        right_layout.setSpacing(8)

        self.path_label = QLabel(self._truncate(path) if path else "Not set")
        self.path_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.path_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; background: transparent; border: none;")
        self.path_label.setMinimumWidth(120)
        self.path_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        right_layout.addWidget(self.path_label)

        self.browse_btn = QPushButton("Browse…")
        self.browse_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.browse_btn.setFixedWidth(80)
        self.browse_btn.setStyleSheet(btn_css(
            bg=Colors.SURFACE_RAISED,
            bg_hover=Colors.SURFACE_ACTIVE,
            bg_press=Colors.SURFACE_ALT,
            border=f"1px solid {Colors.BORDER}",
            padding="4px 8px",
        ))
        self.browse_btn.clicked.connect(self._browse)
        right_layout.addWidget(self.browse_btn)

        container = QWidget()
        container.setLayout(right_layout)
        self.add_control(container)

        self._full_path = path
        self._update_open_btn()

    def _truncate(self, path: str) -> str:
        if len(path) > 40:
            return "…" + path[-38:]
        return path

    def _effective_path(self) -> str:
        if self._full_path:
            return self._full_path
        if self._resolve_default_fn:
            return self._resolve_default_fn()
        return ""

    def _update_open_btn(self):
        self.open_btn.setVisible(bool(self._effective_path()))

    def _open_location(self):
        path = self._effective_path()
        if path:
            import os
            os.makedirs(path, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Select Folder", self._full_path,
            QFileDialog.Option.ShowDirsOnly,
        )
        if folder:
            self._full_path = folder
            self.path_label.setText(self._truncate(folder))
            self._update_open_btn()
            self.changed.emit(folder)

    @property
    def value(self) -> str:
        return self._full_path

    @value.setter
    def value(self, v: str):
        self._full_path = v
        self.path_label.setText(self._truncate(v) if v else "Not set")
        self._update_open_btn()


class ResettableFolderRow(SettingRow):
    """Setting row with folder path, browse button, and X to reset to default."""

    changed = pyqtSignal(str)

    def __init__(self, title: str, description: str = "",
                 path: str = "", default_label: str = "Platform default",
                 resolve_default_fn=None):
        super().__init__(title, description)
        self._default_label = default_label
        self._resolve_default_fn = resolve_default_fn

        self.open_btn = QPushButton("Open \u2197")
        self.open_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.open_btn.setStyleSheet(link_btn_css())
        self.open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_btn.clicked.connect(self._open_location)
        self._text_layout.addWidget(self.open_btn)

        right_layout = QHBoxLayout()
        right_layout.setSpacing(8)

        self.path_label = QLabel(self._truncate(path) if path else default_label)
        self.path_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.path_label.setStyleSheet(
            f"color: {Colors.TEXT_SECONDARY}; background: transparent; border: none;"
        )
        self.path_label.setMinimumWidth(120)
        self.path_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        right_layout.addWidget(self.path_label)

        self.browse_btn = QPushButton("Browse\u2026")
        self.browse_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.browse_btn.setFixedWidth(80)
        self.browse_btn.setStyleSheet(btn_css(
            bg=Colors.SURFACE_RAISED,
            bg_hover=Colors.SURFACE_ACTIVE,
            bg_press=Colors.SURFACE_ALT,
            border=f"1px solid {Colors.BORDER}",
            padding="4px 8px",
        ))
        self.browse_btn.clicked.connect(self._browse)
        right_layout.addWidget(self.browse_btn)

        self.clear_btn = QPushButton("\u2715")
        self.clear_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.clear_btn.setFixedWidth(28)
        self.clear_btn.setToolTip("Reset to default")
        self.clear_btn.setStyleSheet(btn_css(
            bg="transparent",
            bg_hover=Colors.SURFACE_ACTIVE,
            bg_press=Colors.SURFACE_ALT,
            fg=Colors.TEXT_TERTIARY,
            border="none",
            padding="2px",
        ))
        self.clear_btn.clicked.connect(self._clear)
        right_layout.addWidget(self.clear_btn)

        container = QWidget()
        container.setLayout(right_layout)
        self.add_control(container)

        self._full_path = path
        self._update_clear_visibility()

    def _truncate(self, path: str) -> str:
        if len(path) > 40:
            return "\u2026" + path[-38:]
        return path

    def _effective_path(self) -> str:
        if self._full_path:
            return self._full_path
        if self._resolve_default_fn:
            return self._resolve_default_fn()
        return ""

    def _update_clear_visibility(self):
        self.clear_btn.setVisible(bool(self._full_path))
        # Open is always available as long as we can resolve a path.
        self.open_btn.setVisible(bool(self._effective_path()))

    def _open_location(self):
        path = self._effective_path()
        if path:
            import os
            os.makedirs(path, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Select Folder", self._full_path,
            QFileDialog.Option.ShowDirsOnly,
        )
        if folder:
            self._full_path = folder
            self.path_label.setText(self._truncate(folder))
            self._update_clear_visibility()
            self.changed.emit(folder)

    def _clear(self):
        self._full_path = ""
        self.path_label.setText(self._default_label)
        self._update_clear_visibility()
        self.changed.emit("")

    @property
    def value(self) -> str:
        return self._full_path

    @value.setter
    def value(self, v: str):
        self._full_path = v
        self.path_label.setText(self._truncate(v) if v else self._default_label)
        self._update_clear_visibility()


class ActionRow(SettingRow):
    """Setting row with an action button."""

    clicked = pyqtSignal()

    def __init__(self, title: str, description: str = "", button_text: str = "Run"):
        super().__init__(title, description)

        self.action_btn = QPushButton(button_text)
        self.action_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.action_btn.setFixedWidth(100)
        self.action_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.action_btn.setStyleSheet(btn_css(
            bg=Colors.SURFACE_RAISED,
            bg_hover=Colors.SURFACE_ACTIVE,
            bg_press=Colors.SURFACE_ALT,
            border=f"1px solid {Colors.BORDER}",
            padding="5px 12px",
        ))
        self.action_btn.clicked.connect(self.clicked.emit)
        self.add_control(self.action_btn)

    def set_enabled(self, enabled: bool):
        """Enable or disable the action button."""
        self.action_btn.setEnabled(enabled)


class FileRow(SettingRow):
    """Setting row with file path display and browse button (picks a file, not a folder)."""

    changed = pyqtSignal(str)

    def __init__(self, title: str, description: str = "", path: str = "",
                 filter_str: str = "All Files (*)"):
        super().__init__(title, description)
        self._filter_str = filter_str

        right_layout = QHBoxLayout()
        right_layout.setSpacing(8)

        self.path_label = QLabel(self._truncate(path) if path else "Auto-detect")
        self.path_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.path_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; background: transparent; border: none;")
        self.path_label.setMinimumWidth(120)
        self.path_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        right_layout.addWidget(self.path_label)

        self.browse_btn = QPushButton("Browse…")
        self.browse_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.browse_btn.setFixedWidth(80)
        self.browse_btn.setStyleSheet(btn_css(
            bg=Colors.SURFACE_RAISED,
            bg_hover=Colors.SURFACE_ACTIVE,
            bg_press=Colors.SURFACE_ALT,
            border=f"1px solid {Colors.BORDER}",
            padding="4px 8px",
        ))
        self.browse_btn.clicked.connect(self._browse)
        right_layout.addWidget(self.browse_btn)

        self.clear_btn = QPushButton("✕")
        self.clear_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.clear_btn.setFixedWidth(28)
        self.clear_btn.setToolTip("Reset to auto-detect")
        self.clear_btn.setStyleSheet(btn_css(
            bg="transparent",
            bg_hover=Colors.SURFACE_ACTIVE,
            bg_press=Colors.SURFACE_ALT,
            fg=Colors.TEXT_TERTIARY,
            border="none",
            padding="2px",
        ))
        self.clear_btn.clicked.connect(self._clear)
        right_layout.addWidget(self.clear_btn)

        container = QWidget()
        container.setLayout(right_layout)
        self.add_control(container)

        self._full_path = path

    def _truncate(self, path: str) -> str:
        if len(path) > 40:
            return "…" + path[-38:]
        return path

    def _browse(self):
        start_dir = str(Path(self._full_path).parent) if self._full_path else ""
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Select File", start_dir, self._filter_str,
        )
        if filepath:
            self._full_path = filepath
            self.path_label.setText(self._truncate(filepath))
            self.changed.emit(filepath)

    def _clear(self):
        self._full_path = ""
        self.path_label.setText("Auto-detect")
        self.changed.emit("")

    @property
    def value(self) -> str:
        return self._full_path

    @value.setter
    def value(self, v: str):
        self._full_path = v
        self.path_label.setText(self._truncate(v) if v else "Auto-detect")


class ToolRow(SettingRow):
    """Setting row showing tool status with a Download button."""

    download_clicked = pyqtSignal()

    def __init__(self, title: str, description: str = ""):
        super().__init__(title, description)

        # Optional inline status pills (used by FFmpeg row).
        self._lossy_pills_wrap = QWidget()
        pills_layout = QHBoxLayout(self._lossy_pills_wrap)
        pills_layout.setContentsMargins(0, 2, 0, 0)
        pills_layout.setSpacing(6)

        self._lossy_pills: dict[str, QLabel] = {}
        for key in ("aac", "aac_at", "libfdk_aac", "libmp3lame", "libshine"):
            pill = QLabel(key)
            pill.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
            pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pill.setMinimumWidth(104)
            self._lossy_pills[key] = pill
            pills_layout.addWidget(pill)
        pills_layout.addStretch(1)

        self._text_layout.addWidget(self._lossy_pills_wrap)
        self._lossy_pills_wrap.hide()

        right_layout = QHBoxLayout()
        right_layout.setSpacing(8)

        self.status_label = QLabel("Checking…")
        self.status_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.status_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; background: transparent; border: none;")
        right_layout.addWidget(self.status_label)

        self.download_btn = QPushButton("Download")
        self.download_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.download_btn.setFixedWidth(90)
        self.download_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.download_btn.setStyleSheet(btn_css(
            bg=Colors.ACCENT,
            bg_hover=Colors.ACCENT_LIGHT,
            bg_press=Colors.ACCENT,
            fg=Colors.TEXT_ON_ACCENT,
            border="none",
            padding="4px 8px",
        ))
        self.download_btn.clicked.connect(self.download_clicked.emit)
        self.download_btn.hide()
        right_layout.addWidget(self.download_btn)

        container = QWidget()
        container.setLayout(right_layout)
        self.add_control(container)

    def set_status(self, found: bool, path: str = ""):
        """Update the status display."""
        if found:
            display = path if len(path) <= 40 else "…" + path[-38:]
            self.status_label.setText(f"✓ {display}")
            self.status_label.setStyleSheet(f"color: {Colors.SUCCESS}; background: transparent; border: none;")
            self.download_btn.hide()
        else:
            self.status_label.setText("Not found")
            self.status_label.setStyleSheet(f"color: {Colors.WARNING}; background: transparent; border: none;")
            self.download_btn.show()

    def set_downloading(self):
        """Show downloading state."""
        self.download_btn.setEnabled(False)
        self.download_btn.setText("Downloading…")
        self.status_label.setText("Downloading…")
        self.status_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; background: transparent; border: none;")

    def set_lossy_encoder_statuses(self, statuses: dict[str, bool]):
        """Update lossy encoder pills (AAC + MP3) for FFmpeg rows."""
        any_visible = False
        for key, pill in self._lossy_pills.items():
            available = bool(statuses.get(key, False))
            if available:
                pill.setStyleSheet(
                    f"""
                    QLabel {{
                        color: {Colors.SUCCESS};
                        background: {Colors.SUCCESS_DIM};
                        border: 1px solid {Colors.SUCCESS_BORDER};
                        border-radius: {Metrics.BORDER_RADIUS_SM}px;
                        padding: 2px 8px;
                    }}
                    """
                )
            else:
                pill.setStyleSheet(
                    f"""
                    QLabel {{
                        color: {Colors.TEXT_TERTIARY};
                        background: {Colors.SURFACE_ALT};
                        border: 1px solid {Colors.BORDER_SUBTLE};
                        border-radius: {Metrics.BORDER_RADIUS_SM}px;
                        padding: 2px 8px;
                    }}
                    """
                )
            any_visible = True
        self._lossy_pills_wrap.setVisible(any_visible)


class _TokenRow(SettingRow):
    """Setting row with a token text input, validate button, and status."""

    token_changed = pyqtSignal(str)

    def __init__(self, title: str, description: str = "", link_url: str = ""):
        super().__init__(title, description)

        # Add a "Get token" link below the description if URL provided
        if link_url:
            link_btn = QPushButton("Get token ↗")
            link_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
            link_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            link_btn.setStyleSheet(link_btn_css())
            link_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(link_url)))
            # Insert into the left-side text layout (after title + description)
            self._text_layout.addWidget(link_btn)

        right_layout = QHBoxLayout()
        right_layout.setSpacing(8)

        self.status_label = QLabel("")
        self.status_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.status_label.setStyleSheet(
            f"color: {Colors.TEXT_SECONDARY}; background: transparent; border: none;"
        )
        right_layout.addWidget(self.status_label)

        self.token_input = QLineEdit()
        self.token_input.setPlaceholderText("Paste token here…")
        self.token_input.setFixedWidth(220)
        self.token_input.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.token_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_input.setStyleSheet(input_css())
        right_layout.addWidget(self.token_input)

        self.save_btn = QPushButton("Connect")
        self.save_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.save_btn.setFixedWidth(80)
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_btn.setStyleSheet(btn_css(
            bg=Colors.ACCENT,
            bg_hover=Colors.ACCENT_LIGHT,
            bg_press=Colors.ACCENT,
            fg=Colors.TEXT_ON_ACCENT,
            border="none",
            padding="4px 8px",
        ))
        self.save_btn.clicked.connect(self._on_save)
        right_layout.addWidget(self.save_btn)

        self.clear_btn = QPushButton("✕")
        self.clear_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.clear_btn.setFixedWidth(28)
        self.clear_btn.setToolTip("Disconnect")
        self.clear_btn.setStyleSheet(btn_css(
            bg="transparent",
            bg_hover=Colors.SURFACE_ACTIVE,
            bg_press=Colors.SURFACE_ALT,
            fg=Colors.TEXT_TERTIARY,
            border="none",
            padding="2px",
        ))
        self.clear_btn.clicked.connect(self._on_clear)
        self.clear_btn.hide()
        right_layout.addWidget(self.clear_btn)

        container = QWidget()
        container.setLayout(right_layout)
        self.add_control(container)

    def set_connected(self, username: str):
        """Show connected state with username."""
        self.status_label.setText(f"✓ Connected as {username}")
        self.status_label.setStyleSheet(
            f"color: {Colors.SUCCESS}; background: transparent; border: none;"
        )
        self.token_input.hide()
        self.save_btn.hide()
        self.clear_btn.show()

    def set_disconnected(self):
        """Show disconnected state with input visible."""
        self.status_label.setText("")
        self.token_input.setText("")
        self.token_input.show()
        self.save_btn.show()
        self.clear_btn.hide()
        self.save_btn.setText("Connect")

    def set_error(self, message: str):
        """Show an error after validation fails."""
        self.status_label.setText(f"✗ {message}")
        self.status_label.setStyleSheet(
            f"color: {Colors.WARNING}; background: transparent; border: none;"
        )

    def _on_save(self):
        token = self.token_input.text().strip()
        if token:
            self.token_changed.emit(token)

    def _on_clear(self):
        self.set_disconnected()
        self.token_changed.emit("")


def _sign_lastfm_params(params: dict[str, str], secret: str) -> str:
    """Generate an MD5 API signature for Last.fm API requests."""
    keys = sorted(k for k in params.keys() if k not in ("format", "callback"))
    string_to_sign = "".join(f"{k}{params[k]}" for k in keys) + secret
    return hashlib.md5(string_to_sign.encode("utf-8")).hexdigest()

class _LastFmAuthRow(SettingRow):
    """Setting row with Last.fm inputs, automatic browser auth, and status."""

    credentials_changed = pyqtSignal(str, str, str, str)

    _token_fetched_sig = pyqtSignal(str)
    _token_error_sig = pyqtSignal(str)
    _session_success_sig = pyqtSignal(str, str)
    _session_waiting_sig = pyqtSignal()
    _session_error_sig = pyqtSignal(str)

    def __init__(self, title: str, description: str = "", link_url: str = ""):
        super().__init__(title, description)

        self._polling_timer = QTimer(self)
        self._polling_timer.setInterval(3000)
        self._polling_timer.timeout.connect(self._poll_session)
        self._current_token = ""
        self._is_polling = False

        self._token_fetched_sig.connect(self._on_token_fetched)
        self._token_error_sig.connect(self._on_token_error)
        self._session_success_sig.connect(self._on_session_success)
        self._session_waiting_sig.connect(self._on_session_waiting)
        self._session_error_sig.connect(self._on_session_error)

        if link_url:
            link_btn = QPushButton("Get API keys ↗")
            link_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
            link_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            link_btn.setStyleSheet(link_btn_css())
            link_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(link_url)))
            self._text_layout.addWidget(link_btn)

        right_layout = QVBoxLayout()
        right_layout.setSpacing(8)
        right_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)

        self.status_label = QLabel("")
        self.status_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.status_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; background: transparent; border: none;")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        right_layout.addWidget(self.status_label)

        # Inputs container
        self.inputs_widget = QWidget()
        inputs_layout = QVBoxLayout(self.inputs_widget)
        inputs_layout.setContentsMargins(0, 0, 0, 0)
        inputs_layout.setSpacing(4)

        self.api_key_input = QLineEdit()
        self.api_key_input.setPlaceholderText("API Key")
        self.api_key_input.setFixedWidth(220)
        self.api_key_input.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.api_key_input.setStyleSheet(input_css())
        inputs_layout.addWidget(self.api_key_input)

        self.api_secret_input = QLineEdit()
        self.api_secret_input.setPlaceholderText("API Secret")
        self.api_secret_input.setFixedWidth(220)
        self.api_secret_input.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.api_secret_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_secret_input.setStyleSheet(input_css())
        inputs_layout.addWidget(self.api_secret_input)

        right_layout.addWidget(self.inputs_widget)

        # Buttons container
        btn_layout = QHBoxLayout()
        btn_layout.setAlignment(Qt.AlignmentFlag.AlignRight)

        self.connect_btn = QPushButton("Connect in Browser")
        self.connect_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.connect_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.connect_btn.setStyleSheet(btn_css(
            bg=Colors.ACCENT, bg_hover=Colors.ACCENT_LIGHT, bg_press=Colors.ACCENT,
            fg=Colors.TEXT_ON_ACCENT, border="none", padding="4px 12px"
        ))
        self.connect_btn.clicked.connect(self._start_auth_flow)
        btn_layout.addWidget(self.connect_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.setStyleSheet(btn_css(
            bg="transparent", bg_hover=Colors.SURFACE_ACTIVE, bg_press=Colors.SURFACE_ALT,
            fg=Colors.TEXT_TERTIARY, border="none", padding="4px 8px"
        ))
        self.cancel_btn.clicked.connect(self._cancel_auth)
        self.cancel_btn.hide()
        btn_layout.addWidget(self.cancel_btn)

        self.clear_btn = QPushButton("✕ Disconnect")
        self.clear_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_btn.setStyleSheet(btn_css(
            bg="transparent", bg_hover=Colors.SURFACE_ACTIVE, bg_press=Colors.SURFACE_ALT,
            fg=Colors.TEXT_TERTIARY, border="none", padding="4px 8px"
        ))
        self.clear_btn.clicked.connect(self._on_clear)
        self.clear_btn.hide()
        btn_layout.addWidget(self.clear_btn)

        right_layout.addLayout(btn_layout)

        container = QWidget()
        container.setLayout(right_layout)
        self.add_control(container)

    def set_connected(self, username: str):
        self.status_label.setText(f"✓ Connected as {username}")
        self.status_label.setStyleSheet(f"color: {Colors.SUCCESS}; background: transparent; border: none;")
        self.inputs_widget.hide()
        self.connect_btn.hide()
        self.cancel_btn.hide()
        self.clear_btn.show()
        self._polling_timer.stop()

    def set_disconnected(self, api_key: str = "", api_secret: str = ""):
        self.status_label.setText("")
        if api_key: 
            self.api_key_input.setText(api_key)
        if api_secret: 
            self.api_secret_input.setText(api_secret)
        self.api_key_input.setEnabled(True)
        self.api_secret_input.setEnabled(True)
        self.inputs_widget.show()
        self.connect_btn.show()
        self.connect_btn.setEnabled(True)
        self.cancel_btn.hide()
        self.clear_btn.hide()
        self._polling_timer.stop()

    def set_error(self, message: str):
        self.status_label.setText(f"✗ {message}")
        self.status_label.setStyleSheet(f"color: {Colors.WARNING}; background: transparent; border: none;")

    def _start_auth_flow(self):
        api_key = self.api_key_input.text().strip()
        api_secret = self.api_secret_input.text().strip()
        
        if not api_key or not api_secret:
            self.set_error("API Key and Secret required")
            return

        self.status_label.setText("Fetching token...")
        self.status_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; background: transparent; border: none;")
        self.api_key_input.setEnabled(False)
        self.api_secret_input.setEnabled(False)
        self.connect_btn.hide()
        self.cancel_btn.show()

        def _fetch_task():
            try:
                params = {"method": "auth.getToken", "api_key": api_key}
                params["api_sig"] = _sign_lastfm_params(params, api_secret)
                params["format"] = "json"
                url = "https://ws.audioscrobbler.com/2.0/?" + urllib.parse.urlencode(params)
                with urllib.request.urlopen(url, timeout=10) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    self._token_fetched_sig.emit(data["token"])
            except Exception as e:
                self._token_error_sig.emit(str(e))
        
        threading.Thread(target=_fetch_task, daemon=True).start()

    @pyqtSlot(str)
    def _on_token_fetched(self, token: str):
        if not self.cancel_btn.isVisible():
            return
        self._current_token = token
        api_key = self.api_key_input.text().strip()
        auth_url = f"http://www.last.fm/api/auth/?api_key={api_key}&token={token}"
        QDesktopServices.openUrl(QUrl(auth_url))
        
        self.status_label.setText("Waiting for browser approval...")
        self.status_label.setStyleSheet(f"color: {Colors.ACCENT}; background: transparent; border: none;")
        self._is_polling = False
        self._polling_timer.start()

    @pyqtSlot(str)
    def _on_token_error(self, err: str):
        if not self.cancel_btn.isVisible():
            return
        self.set_error(f"Token fetch failed: {err}")
        self.cancel_btn.hide()
        self.connect_btn.show()
        self.api_key_input.setEnabled(True)
        self.api_secret_input.setEnabled(True)

    def _poll_session(self):
        if self._is_polling:
            return
        self._is_polling = True
        
        api_key = self.api_key_input.text().strip()
        api_secret = self.api_secret_input.text().strip()
        token = self._current_token

        def _poll_task():
            try:
                params = {"method": "auth.getSession", "api_key": api_key, "token": token}
                params["api_sig"] = _sign_lastfm_params(params, api_secret)
                params["format"] = "json"
                url = "https://ws.audioscrobbler.com/2.0/?" + urllib.parse.urlencode(params)
                with urllib.request.urlopen(url, timeout=10) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    # THE FIX: We are now grabbing "name" from the JSON and emitting both!
                    self._session_success_sig.emit(data["session"]["key"], data["session"]["name"])
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", errors="replace")
                try:
                    err_data = json.loads(body)
                    if err_data.get("error") == 14:
                        # Error 14: This token has not been authorized
                        self._session_waiting_sig.emit()
                        return
                except Exception:
                    pass
                self._session_error_sig.emit(f"HTTP {e.code}")
            except Exception as e:
                self._session_error_sig.emit(str(e))

        threading.Thread(target=_poll_task, daemon=True).start()

    @pyqtSlot(str, str)
    def _on_session_success(self, session_key: str, username: str):
        if not self.cancel_btn.isVisible():
            return
        self._polling_timer.stop()
        self._is_polling = False
        
        api_key = self.api_key_input.text().strip()
        api_secret = self.api_secret_input.text().strip()
        self.cancel_btn.hide() 
        
        # Emit all 4 arguments here!
        self.credentials_changed.emit(api_key, api_secret, session_key, username)

    @pyqtSlot()
    def _on_session_waiting(self):
        if not self.cancel_btn.isVisible():
            return
        self._is_polling = False
        
    @pyqtSlot(str)
    def _on_session_error(self, err: str):
        if not self.cancel_btn.isVisible():
            return
        self._polling_timer.stop()
        self._is_polling = False
        self.set_error(f"Auth failed: {err}")
        self.cancel_btn.hide()
        self.connect_btn.show()
        self.api_key_input.setEnabled(True)
        self.api_secret_input.setEnabled(True)

    def _cancel_auth(self):
        self._polling_timer.stop()
        self._is_polling = False
        self.status_label.setText("Canceled")
        self.status_label.setStyleSheet(f"color: {Colors.TEXT_TERTIARY}; background: transparent; border: none;")
        self.cancel_btn.hide()
        self.connect_btn.show()
        self.api_key_input.setEnabled(True)
        self.api_secret_input.setEnabled(True)

    def _on_clear(self):
        self.set_disconnected()
        self.credentials_changed.emit("", "", "", "")


# ── Card container ──────────────────────────────────────────────────────────

class _CacheSizeRow(SettingRow):
    """Setting row showing live transcode-cache usage with a Clear button."""

    def __init__(self, settings_service: SettingsService):
        super().__init__("Cache Status", "Calculating…")
        self._settings_service = settings_service
        self._clear_btn = QPushButton("Clear Cache")
        self._clear_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self._clear_btn.setFixedWidth(110)
        self._clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear_btn.setStyleSheet(danger_btn_css())
        self._clear_btn.clicked.connect(self._on_clear)
        self.add_control(self._clear_btn)
        self.refresh()

    def refresh(self) -> None:
        """Update the displayed size from the cache index (fast — no disk scan)."""
        try:
            from SyncEngine.transcode_cache import TranscodeCache
            s = self._settings_service.get_effective_settings()
            cache_dir = Path(s.transcode_cache_dir) if s.transcode_cache_dir else None
            stats = TranscodeCache.get_instance(
                cache_dir,
                max_cache_size_gb=s.max_cache_size_gb,
            ).stats()
            gb = stats["total_size_gb"]
            count = stats["total_files"]
            max_gb = stats.get("max_size_gb", 0.0)
            if max_gb > 0:
                self.desc_label.setText(f"{gb:.2f} GB used of {max_gb:.0f} GB · {count:,} files")
            else:
                self.desc_label.setText(f"{gb:.2f} GB · {count:,} files")
            self._clear_btn.setEnabled(count > 0)
        except Exception as exc:
            self.desc_label.setText(f"Unavailable ({exc})")

    def _on_clear(self) -> None:
        from PyQt6.QtWidgets import QMessageBox

        from SyncEngine.transcode_cache import TranscodeCache
        reply = QMessageBox.question(
            self,
            "Clear Transcode Cache",
            "Delete all cached transcoded files?\n\n"
            "They will be re-created on the next sync.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            s = self._settings_service.get_effective_settings()
            cache_dir = Path(s.transcode_cache_dir) if s.transcode_cache_dir else None
            n = TranscodeCache.get_instance(
                cache_dir,
                max_cache_size_gb=s.max_cache_size_gb,
            ).clear()
            self.desc_label.setText(f"Cleared — {n:,} files removed")
            self._clear_btn.setEnabled(False)
        except Exception as exc:
            self.desc_label.setText(f"Error clearing cache: {exc}")


class _SettingsCard(QFrame):
    """Ventura-style rounded card containing grouped setting rows."""

    def __init__(self, *rows: QWidget):
        super().__init__()
        self.setObjectName("settingsCard")
        self.setStyleSheet(f"""
            QFrame#settingsCard {{
                background: {Colors.SURFACE_ALT};
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-radius: {Metrics.BORDER_RADIUS_LG}px;
            }}
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._rows: list[QWidget] = []
        self._seps: list[QFrame | None] = []

        for i, row in enumerate(rows):
            sep = None
            if i > 0:
                sep = QFrame()
                sep.setFixedHeight(1)
                sep.setStyleSheet(
                    f"background: {Colors.BORDER_SUBTLE}; border: none;"
                )
                lay.addWidget(sep)

            self._seps.append(sep)
            self._rows.append(row)

            if isinstance(row, SettingRow):
                name = f"cr{i}"
                row.setObjectName(name)
                row.setStyleSheet(f"""
                    QFrame#{name} {{
                        background: transparent;
                        border: none;
                        border-radius: 0;
                    }}
                """)
            lay.addWidget(row)

    def set_row_visible(self, row: QWidget, visible: bool) -> None:
        """Show or hide a row and keep surrounding separators consistent.

        A separator before row[i] is shown when row[i] is visible and at
        least one row above it is also visible — covering the case where
        hidden rows leave a gap between two visible rows.
        """
        row.setVisible(visible)
        any_visible_above = False
        for i, r in enumerate(self._rows):
            sep = self._seps[i]
            shown = not r.isHidden()
            if sep is not None:
                sep.setVisible(shown and any_visible_above)
            if shown:
                any_visible_above = True


# ── Main settings page ─────────────────────────────────────────────────────

class SettingsPage(QWidget):
    """Two-panel settings view inspired by macOS Ventura System Settings."""

    closed = pyqtSignal()  # Emitted when user closes settings
    theme_changed = pyqtSignal()  # Emitted when theme or contrast changes
    artwork_appearance_changed = pyqtSignal()  # Emitted when artwork UI styling changes

    def __init__(
        self,
        settings_service: SettingsService,
        device_sessions: DeviceSessionService,
    ):
        super().__init__()
        self._settings_service = settings_service
        self._device_sessions = device_sessions
        self._pending_lb_result: tuple[str, str, str, str, str, bool] = ("", "", "global", "", "", False)
        self._pending_lastfm_result: tuple[str, str, str, str, str, str, str, bool] = ("", "", "", "", "global", "", "", False)
        self._update_checker: object | None = None
        self._update_downloader: object | None = None
        self._update_progress: QProgressDialog | None = None
        self._settings_scope = "global"
        self._loading_settings = False
        self._device_settings_pending = False
        self._section_labels: dict[tuple[str, str], QLabel] = {}

        main = QHBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)

        # ── Sidebar ─────────────────────────────────────────────────────────
        main.addWidget(self._build_sidebar())

        # ── Content stack ───────────────────────────────────────────────────
        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_general_page())      # 0
        self._stack.addWidget(self._build_sync_page())          # 1
        self._stack.addWidget(self._build_transcoding_page())   # 2
        self._stack.addWidget(self._build_tools_page())         # 3
        self._stack.addWidget(self._build_scrobbling_page())    # 4
        self._stack.addWidget(self._build_storage_page())       # 5
        self._stack.addWidget(self._build_backups_page())       # 6
        main.addWidget(self._stack, stretch=1)

        # Select first page
        self._select_page(0)

    # ── Sidebar construction ────────────────────────────────────────────────

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("settingsSidebar")
        sidebar.setFixedWidth(240)
        sidebar.setStyleSheet(f"""
            QFrame#settingsSidebar {{
                background: {Colors.SURFACE};
                border-right: 1px solid {Colors.BORDER_SUBTLE};
            }}
        """)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins((16), (16), (16), (16))
        layout.setSpacing(4)

        # Back button
        back_btn = QPushButton("←")
        back_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_LG))
        back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        back_btn.setToolTip("Back")
        back_btn.setStyleSheet(back_btn_css())
        back_btn.clicked.connect(self._on_close)
        layout.addWidget(back_btn)

        # Title
        title = QLabel("Settings")
        title.setFont(QFont(FONT_FAMILY, Metrics.FONT_HERO, QFont.Weight.Bold))
        title.setStyleSheet(
            f"color: {Colors.TEXT_PRIMARY}; background: transparent; border: none;"
        )
        layout.addWidget(title)
        layout.addSpacing(8)
        layout.addWidget(self._build_scope_switch())
        layout.addSpacing(12)

        # Navigation items
        self._nav_buttons: list[QPushButton] = []
        nav_items = [
            "General", "Sync", "Transcoding",
            "External Tools", "Scrobbling", "Storage", "Backups",
        ]
        for i, name in enumerate(nav_items):
            btn = QPushButton(name)
            btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_LG))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, idx=i: self._select_page(idx))
            self._nav_buttons.append(btn)
            layout.addWidget(btn)

        layout.addStretch()
        return sidebar

    def _build_scope_switch(self) -> QFrame:
        """Build the Global / Device segmented settings scope control."""
        frame = QFrame()
        frame.setObjectName("settingsScopeSwitch")
        frame.setFixedHeight(34)
        frame.setStyleSheet(f"""
            QFrame#settingsScopeSwitch {{
                background: {Colors.SURFACE_ALT};
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-radius: {Metrics.BORDER_RADIUS_SM}px;
            }}
        """)
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(3)

        self._scope_global_btn = QPushButton("Global")
        self._scope_device_btn = QPushButton("Device")
        for btn in (self._scope_global_btn, self._scope_device_btn):
            btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM, QFont.Weight.DemiBold))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(26)
            lay.addWidget(btn, stretch=1)

        self._scope_global_btn.clicked.connect(lambda: self.set_settings_scope("global"))
        self._scope_device_btn.clicked.connect(lambda: self.set_settings_scope("device"))
        self._update_scope_switch_style()
        return frame

    def _update_scope_switch_style(self) -> None:
        if not hasattr(self, "_scope_global_btn"):
            return
        for scope, btn in (("global", self._scope_global_btn), ("device", self._scope_device_btn)):
            selected = self._settings_scope == scope
            btn.setStyleSheet(btn_css(
                bg=Colors.ACCENT if selected else "transparent",
                bg_hover=Colors.ACCENT_LIGHT if selected else Colors.SURFACE_ACTIVE,
                bg_press=Colors.ACCENT if selected else Colors.SURFACE_ALT,
                fg=Colors.TEXT_ON_ACCENT if selected else Colors.TEXT_SECONDARY,
                border="none",
                padding="4px 8px",
            ))

    def set_settings_scope(self, scope: str) -> None:
        """Switch between PC/global settings and the selected iPod settings."""
        scope = "device" if scope == "device" else "global"
        if scope == "device" and not self._current_device_context():
            scope = "global"
        if self._settings_scope == scope:
            self.load_from_settings()
            return
        self._settings_scope = scope
        self._update_scope_switch_style()
        self.load_from_settings()

    def _select_page(self, index: int):
        """Switch visible page and update sidebar highlight."""
        if 0 <= index < len(self._nav_buttons) and self._nav_buttons[index].isHidden():
            index = 0
        for i, btn in enumerate(self._nav_buttons):
            btn.setStyleSheet(sidebar_nav_selected_css() if i == index else sidebar_nav_css())
        self._stack.setCurrentIndex(index)

    # ── Page factory ────────────────────────────────────────────────────────

    def _make_page(self, title: str, *items) -> QScrollArea:
        """Build a scrollable content page.

        *items* can be:
          - ``str``  → rendered as a small uppercase section header
          - ``QWidget`` → added directly (usually a _SettingsCard)
        """
        scroll = make_scroll_area()

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(content)
        layout.setContentsMargins((32), (24), (32), (32))
        layout.setSpacing(0)

        # Page title
        title_label = QLabel(title)
        title_label.setFont(
            QFont(FONT_FAMILY, Metrics.FONT_PAGE_TITLE, QFont.Weight.Bold)
        )
        title_label.setStyleSheet(
            f"color: {Colors.TEXT_PRIMARY}; background: transparent; border: none;"
        )
        layout.addWidget(title_label)
        layout.addSpacing(20)

        for item in items:
            if isinstance(item, str):
                lbl = QLabel(item.upper())
                lbl.setFont(QFont(FONT_FAMILY, Metrics.FONT_XS, QFont.Weight.Bold))
                lbl.setStyleSheet(
                    f"color: {Colors.TEXT_TERTIARY}; background: transparent;"
                    f" border: none; padding-left: {(4)}px;"
                )
                self._section_labels[(title, item)] = lbl
                layout.addWidget(lbl)
                layout.addSpacing(8)
            else:
                layout.addWidget(item)
                layout.addSpacing(20)

        layout.addStretch()
        scroll.setWidget(content)
        return scroll

    # ── Page builders ───────────────────────────────────────────────────────

    def _build_general_page(self) -> QScrollArea:
        self.use_global_settings = ToggleRow(
            "Use Global Settings",
            "Ignore this iPod's settings file and use the PC settings "
            "while this iPod is selected.",
            checked=False,
        )
        self.reset_device_settings = ActionRow(
            "Reset Device Settings",
            "Copy the current global values into this iPod's settings file.",
            button_text="Reset",
        )
        self.reset_device_settings.clicked.connect(self._reset_device_settings_to_global)

        self.theme_combo = ComboRow(
            "Theme",
            "Choose the color scheme for the interface. "
            "System follows your OS preference.",
            options=[
                "Dark", "Light", "System",
                "Catppuccin Mocha", "Catppuccin Macchiato",
                "Catppuccin Frappé", "Catppuccin Latte",
            ],
            current="Dark",
        )

        self.high_contrast = ComboRow(
            "Increased Contrast",
            "Boost text and border contrast for accessibility. "
            "System follows your OS accessibility setting.",
            options=["Off", "On", "System"],
            current="Off",
        )

        self.font_scale = ComboRow(
            "Font Size",
            "Scale text size across the interface for accessibility.",
            options=["75%", "90%", "100%", "110%", "125%", "150%"],
            current="100%",
        )

        self.accent_color = ComboRow(
            "Accent Color",
            "Customize the accent color used throughout the interface. "
            "Match iPod uses the body color of your connected iPod.",
            options=[
                "Blue (Default)", "Match iPod",
                "Red", "Orange", "Gold", "Green",
                "Teal", "Purple", "Pink",
            ],
            current="Blue (Default)",
        )

        self.show_art = ToggleRow(
            "Track List Artwork",
            "Show album art thumbnails next to tracks in the list view.",
            checked=True,
        )
        self.rounded_artwork = ToggleRow(
            "Rounded Artwork",
            "Round album art corners in grid cards and track lists. "
            "This only changes how artwork is drawn in iOpenPod and does not "
            "modify anything written to your iPod.",
            checked=False,
        )
        self.sharpen_artwork = ToggleRow(
            "Sharpen Artwork",
            "Apply a subtle display-only sharpening pass to album art in grid cards "
            "and track lists. This does not modify artwork written to your iPod.",
            checked=True,
        )

        from infrastructure.version import get_version
        self.version_row = ActionRow(
            f"iOpenPod v{get_version()}",
            "Check for a newer version of iOpenPod.",
            button_text="Check",
        )
        self.version_row.clicked.connect(self._check_for_updates)

        self.bug_report_row = ActionRow(
            "Report a Bug",
            "Open the GitHub issue tracker to report problems or request features.",
            button_text="Open",
        )
        self.bug_report_row.clicked.connect(
            lambda: QDesktopServices.openUrl(
                QUrl("https://github.com/TheRealSavi/iOpenPod/issues")
            )
        )

        self.kofi_row = ActionRow(
            "Support iOpenPod",
            "iOpenPod is and always will be completely free and open source. "
            "If you like it and would like to support me, it is so very appreciated.",
            button_text="Ko-fi",
        )
        from GUI.glyphs import glyph_icon
        heart_icon = glyph_icon("heart", 14, "#ff5f75")
        if heart_icon:
            self.kofi_row.action_btn.setIcon(heart_icon)
        self.kofi_row.clicked.connect(
            lambda: QDesktopServices.openUrl(
                QUrl("https://ko-fi.com/johngibbons")
            )
        )

        self._manage_card = _SettingsCard(
            self.use_global_settings,
            self.reset_device_settings,
        )
        self._appearance_card = _SettingsCard(
            self.theme_combo,
            self.high_contrast,
            self.accent_color,
            self.font_scale,
            self.show_art,
            self.rounded_artwork,
            self.sharpen_artwork,
        )
        self._about_card = _SettingsCard(
            self.version_row,
            self.bug_report_row,
            self.kofi_row,
        )

        return self._make_page(
            "General",
            "Manage",
            self._manage_card,
            "Appearance",
            self._appearance_card,
            "About",
            self._about_card,
        )

    def _build_sync_page(self) -> QScrollArea:
        self.sync_workers = ComboRow(
            "Parallel Workers",
            "Overall concurrent sync work. This controls how many files can be "
            "prepared, fingerprinted, transcoded, or copied at once. "
            "Auto uses your CPU core count (capped at 8).",
            options=["Auto", "1", "2", "4", "6", "8"],
            current="Auto",
        )
        self.device_write_workers = ComboRow(
            "Parallel Writes",
            "Simultaneous writes to the iPod filesystem. "
            "Set to 1 for HDD-based iPods to reduce fragmentation risk. "
            "Auto uses an HDD-safe default when the device looks like a hard-drive iPod.",
            options=["Auto", "1", "2", "4"],
            current="Auto",
        )
        self.write_back = ToggleRow(
            "Write Back to PC",
            "While syncing, write ratings and sound check values into your "
            "PC music files. When off, no changes are made to your PC files.",
        )
        self.compute_sound_check = ToggleRow(
            "Compute Sound Check",
            "Analyze loudness of files missing ReplayGain/iTunNORM tags "
            "using ffmpeg, then write the result back into your PC files "
            "and sync to iPod. Sound Check values are always synced to iPod "
            "regardless of this setting.",
        )
        self.rotate_tall_photos = ToggleRow(
            "Rotate Tall Photos on Device",
            "For portrait-heavy photos, rotate the device viewing caches "
            "clockwise when that uses more of the iPod's landscape photo "
            "screen. The original PC files are not modified.",
        )
        self.fit_photo_thumbnails = ToggleRow(
            "Fit Thumbnails",
            "Use aspect-fit for device photo thumbnail formats. "
            "When off (default), thumbnails use iTunes-style crop-to-fill.",
        )
        self.rating_strategy = ComboRow(
            "Rating Conflict Strategy",
            "How to resolve rating conflicts when iPod and PC ratings differ. "
            "iPod/PC Wins uses that source (falling back to the other if zero). "
            "Highest/Lowest picks the max/min non-zero value. "
            "Average rounds to the nearest star.",
            options=["iPod Wins", "PC Wins", "Highest", "Lowest", "Average"],
            current="iPod Wins",
        )

        self._sync_card = _SettingsCard(
            self.write_back,
            self.compute_sound_check,
            self.rotate_tall_photos,
            self.fit_photo_thumbnails,
            self.rating_strategy,
        )

        return self._make_page(
            "Sync",
            "Behavior",
            self._sync_card,
            "Performance",
            _SettingsCard(
                self.sync_workers,
                self.device_write_workers,
            ),
        )

    def _build_transcoding_page(self) -> QScrollArea:
        self.lossy_encoder = ComboRow(
            "Lossy Encoder",
            "Choose which lossy encoder to use."
            "Auto chooses the best available.",
            options=[
                "Auto",
                "libfdk_aac",
                "aac_at",
                "aac",
                "libmp3lame",
                "libshine"
            ],
            current="Auto",
        )
        self.lossy_quality = ComboRow(
            "Music Quality",
            "Audio quality preset for music tracks. "
            "High: 256 kbps / best VBR. Balanced: 192 kbps. Compact: 128 kbps / smaller VBR.",
            options=["High Quality", "Balanced", "Compact"],
            current="Balanced",
        )
        self.bitrate_mode = ComboRow(
            "Bitrate Mode",
            "CBR uses a fixed target bitrate. VBR targets a quality level and lets "
            "the encoder choose bitrate per frame — typically better quality per byte.",
            options=["CBR", "VBR"],
            current="CBR",
        )
        self.music_lossy_cbr_bitrate = ComboRow(
            "Music Bitrate",
            "Target CBR bitrate for music tracks.",
            options=["96 kbps", "128 kbps", "160 kbps", "192 kbps", "224 kbps", "256 kbps", "320 kbps"],
            current="192 kbps",
        )
        self.vbr_level = ComboRow(
            "VBR Quality Level",
            "Quality level for VBR encoding. Higher = better quality, larger files.",
            options=["q0 (Best)", "q1", "q2", "q3", "q4", "q5", "q6", "q7", "q8", "q9 (Smallest)"],
            current="q4",
        )
        self.spoken_lossy_cbr_bitrate = ComboRow(
            "Spoken Word Bitrate",
            "Target bitrate for podcasts and audiobooks (Always uses CBR despite set Bitrate Mode). "
            "Pair with 'Mono for Spoken Word' for best results.",
            options=["32 kbps", "48 kbps", "64 kbps", "80 kbps", "96 kbps"],
            current="64 kbps",
        )
        self.prefer_lossy = ToggleRow(
            "Prefer Lossy Encoding",
            "Encode lossless sources (ALAC, FLAC, WAV, AIFF) as your selected "
            "lossy format instead of ALAC. Saves iPod storage at the cost "
            "of quality.",
        )
        self.video_crf = ComboRow(
            "Video Quality (CRF)",
            "Quality level for H.264 video transcodes. Lower CRF = better "
            "quality but larger files. Resolution and codec are always "
            "forced to iPod-compatible values.",
            options=[
                "18 (High)", "20 (Good)", "23 (Balanced)",
                "26 (Low)", "28 (Very Low)",
            ],
            current="23 (Balanced)",
        )
        self.video_preset = ComboRow(
            "Video Encode Speed",
            "Slower presets produce slightly better quality at the same CRF, "
            "but take much longer.",
            options=["ultrafast", "veryfast", "fast", "medium", "slow"],
            current="fast",
        )
        self.mono_for_spoken = ToggleRow(
            "Mono for Spoken Word",
            "Downmix to mono when encoding podcasts and audiobooks. "
            "Mono at lowbites sounds significantly better than stereo and "
            "cuts file sizes in half.",
        )
        self.smart_quality_by_type = ToggleRow(
            "Smart Quality by Content Type",
            "Enable separate quality settings for podcasts and audiobooks."
            "Music tracks are unaffected.",
        )
        self.normalize_sample_rate = ToggleRow(
            "Normalize to 44.1 kHz",
            "Always output audio at 44.1 kHz (CD rate). "
            "Recommended for early iPods (1G-4G) that can have trouble with 48 kHz ALAC."
            "When off, sample rate is reduced to 48 kHz as iPods can only decode 48 kHz or lower",
        )

        self.aac_cutoff = ComboRow(
            "Bandwidth Cutoff",
            "Maximum frequency the encoder will output. Lowering this (16–18 kHz) "
            "frees bits for the mid-range and can eliminate high-frequency squeaks "
            "at lower bitrates. Auto lets the encoder decide. Applies to all AAC encoders.",
            options=["Auto", "20 kHz", "19 kHz", "18 kHz", "17 kHz", "16 kHz", "15 kHz"],
            current="Auto",
        )
        self.fdk_afterburner = ToggleRow(
            "libfdk_aac Afterburner",
            "Enables a quality-enhancement post-processing pass in libfdk_aac. "
            "Improves output at the cost of slightly longer encode times. "
            "Only affects the libfdk_aac encoder.",
        )
        self.aac_tns = ToggleRow(
            "Temporal Noise Shaping (TNS)",
            "Shapes quantization noise around transients to reduce pre-echo "
            "(smearing before drum hits). Disabling saves a few bits per block. "
            "Affects the native aac encoder only.",
        )
        self.aac_pns = ToggleRow(
            "Perceptual Noise Substitution (PNS)",
            "Replaces noise-like frequency bands with synthetic noise, saving bits. "
            "Can cause sandpaper or hissing artifacts if the encoder mistakes tonal "
            "content for noise. Off by default. Affects the native aac encoder only.",
        )
        self.aac_ms_stereo = ToggleRow(
            "Mid/Side Stereo",
            "Encodes stereo as Sum (Mid) and Difference (Side) rather than Left/Right. "
            "Concentrates bits where the signal is strongest, particularly on centred "
            "content. Affects the native aac encoder only.",
        )
        self.aac_intensity_stereo = ToggleRow(
            "Intensity Stereo",
            "Merges high-frequency stereo bands into a single channel with direction "
            "metadata. Saves bits at low bitrates but can cause stereo image wobble. "
            "Affects the native aac encoder only.",
        )

        self._audio_card = _SettingsCard(
            self.lossy_encoder,
            self.lossy_quality,
            self.bitrate_mode,
            self.music_lossy_cbr_bitrate,
            self.vbr_level,
            self.prefer_lossy,
            self.normalize_sample_rate,
        )

        self._spoken_card = _SettingsCard(
            self.smart_quality_by_type,
            self.spoken_lossy_cbr_bitrate,
            self.mono_for_spoken,
        )

        self._advanced_aac_card = _SettingsCard(
            self.aac_cutoff,
            self.fdk_afterburner,
            self.aac_tns,
            self.aac_pns,
            self.aac_ms_stereo,
            self.aac_intensity_stereo,
        )

        return self._make_page(
            "Transcoding",
            "Audio",
            self._audio_card,
            "Spoken Word",
            self._spoken_card,
            "Advanced AAC",
            self._advanced_aac_card,
            "Video",
            _SettingsCard(
                self.video_crf,
                self.video_preset,
            ),
        )

    def _build_tools_page(self) -> QScrollArea:
        self.ffmpeg_tool = ToolRow(
            "FFmpeg",
            "Required for transcoding FLAC, OGG, and other formats "
            "to iPod-compatible audio.",
        )
        self.ffmpeg_tool.download_clicked.connect(self._download_ffmpeg)

        self.fpcalc_tool = ToolRow(
            "fpcalc (Chromaprint)",
            "Required for acoustic fingerprinting, which identifies "
            "tracks even after re-encoding.",
        )
        self.fpcalc_tool.download_clicked.connect(self._download_fpcalc)

        self.ffmpeg_path = FileRow(
            "FFmpeg Path Override",
            "Point to a custom ffmpeg binary. Leave empty to auto-detect.",
            filter_str="FFmpeg (ffmpeg ffmpeg.exe);;All Files (*)",
        )
        self.fpcalc_path = FileRow(
            "fpcalc Path Override",
            "Point to a custom fpcalc binary. Leave empty to auto-detect.",
            filter_str="fpcalc (fpcalc fpcalc.exe);;All Files (*)",
        )

        return self._make_page(
            "External Tools",
            "Status",
            _SettingsCard(self.ffmpeg_tool, self.fpcalc_tool),
            "Path Overrides",
            _SettingsCard(self.ffmpeg_path, self.fpcalc_path),
        )

    def _build_scrobbling_page(self) -> QScrollArea:
        self.scrobble_on_sync = ToggleRow(
            "Scrobble on Sync",
            "Automatically scrobble new iPod plays to connected services when "
            "you sync.",
            checked=True,
        )
        self.listenbrainz_token_row = _TokenRow(
            "ListenBrainz",
            "Connect your ListenBrainz account to scrobble iPod plays. "
            "Copy your user token from the link below.",
            link_url="https://listenbrainz.org/settings/",
        )
        self.listenbrainz_token_row.token_changed.connect(
            self._on_listenbrainz_token_changed
        )

        self.lastfm_auth_row = _LastFmAuthRow(
            "Last.fm",
            "Connect your Last.fm account to scrobble iPod plays. "
            "You will need to provide your Last.fm API Key and API Secret.",
            link_url="https://www.last.fm/api/account/create",
        )
        self.lastfm_auth_row.credentials_changed.connect(
            self._on_lastfm_credentials_changed
        )

        return self._make_page(
            "Scrobbling",
            "General",
            _SettingsCard(
                self.scrobble_on_sync,
            ),
            "Services",
            _SettingsCard(
                self.listenbrainz_token_row,
                self.lastfm_auth_row,
            ),
        )

    def _build_storage_page(self) -> QScrollArea:
        from infrastructure.settings_paths import default_cache_dir
        self.transcode_cache_dir = ResettableFolderRow(
            "Cache Location",
            "Where transcoded files are cached to avoid re-encoding "
            "on future syncs.",
            default_label="Platform default",
            resolve_default_fn=default_cache_dir,
        )
        self.max_cache_size = ComboRow(
            "Max Cache Size",
            "Oldest cached files are automatically removed (LRU) to stay "
            "within this limit. Set to Unlimited if storage is not a concern.",
            options=["Unlimited", "1 GB", "2 GB", "5 GB", "10 GB", "20 GB", "50 GB"],
            current="5 GB",
        )
        self.cache_status = _CacheSizeRow(self._settings_service)
        import os as _os

        from infrastructure.settings_paths import default_data_dir, get_settings_dir
        self.settings_dir = ResettableFolderRow(
            "Settings Location",
            "Custom directory to store iOpenPod settings. Useful for "
            "portable setups or backups.",
            default_label="Platform default",
            resolve_default_fn=get_settings_dir,
        )
        self.log_dir = ResettableFolderRow(
            "Log Location",
            "Where iOpenPod writes log files and crash reports. "
            "Takes effect on next launch.",
            default_label="Platform default",
            resolve_default_fn=lambda: _os.path.join(default_data_dir(), "logs"),
        )

        return self._make_page(
            "Storage",
            "Transcode Cache",
            _SettingsCard(
                self.transcode_cache_dir,
                self.max_cache_size,
                self.cache_status,
            ),
            "Locations",
            _SettingsCard(
                self.settings_dir,
                self.log_dir,
            ),
        )

    def _build_backups_page(self) -> QScrollArea:
        import os as _os2

        from infrastructure.settings_paths import default_data_dir as _ddd
        self.backup_dir = FolderRow(
            "Backup Location",
            "Where full device backups are stored on your PC. "
            "Leave empty for the platform default.",
            resolve_default_fn=lambda: _os2.path.join(_ddd(), "backups"),
        )
        self.backup_before_sync = ToggleRow(
            "Backup Before Sync",
            "Automatically create a full device backup before each sync. "
            "Recommended — allows you to restore your iPod if a sync "
            "goes wrong.",
            checked=True,
        )
        self.max_backups = ComboRow(
            "Max Backups",
            "Maximum number of backup snapshots to keep per device. "
            "Oldest backups are automatically removed when the limit "
            "is exceeded.",
            options=["5", "10", "20", "Unlimited"],
            current="10",
        )

        self._backups_card = _SettingsCard(
            self.backup_dir,
            self.backup_before_sync,
            self.max_backups,
        )

        return self._make_page(
            "Backups",
            self._backups_card,
        )

    def _current_device_context(self) -> tuple[str, str] | None:
        """Return (iPod root, settings key) for the selected device."""
        try:
            session = self._device_sessions.current_session()
            root = session.device_path or ""
            if not root:
                return None
            return root, self._settings_service.device_settings_key(
                root,
                session.discovered_ipod,
            )
        except Exception:
            return None

    def _sync_scope_availability(self) -> None:
        has_device = self._current_device_context() is not None
        loading_device_settings = False
        if has_device:
            try:
                loading_device_settings = (
                    self._device_sessions.current_session().device_settings_loading
                )
            except Exception:
                loading_device_settings = False
        if hasattr(self, "_scope_device_btn"):
            self._scope_device_btn.setEnabled(has_device)
            self._scope_device_btn.setText("Device..." if loading_device_settings else "Device")
            self._scope_device_btn.setToolTip(
                "Loading device settings..."
                if loading_device_settings
                else ("" if has_device else "Select an iPod to edit device settings")
            )
        if not has_device and self._settings_scope == "device":
            self._settings_scope = "global"
        self._update_scope_switch_style()

    def _set_section_visible(self, page_title: str, section: str, visible: bool) -> None:
        label = self._section_labels.get((page_title, section))
        if label is not None:
            label.setVisible(visible)

    def _set_device_rows_enabled(self, enabled: bool) -> None:
        rows = [
            self.accent_color,
            self.show_art,
            self.write_back,
            self.compute_sound_check,
            self.rotate_tall_photos,
            self.fit_photo_thumbnails,
            self.rating_strategy,
            self.lossy_encoder,
            self.lossy_quality,
            self.bitrate_mode,
            self.music_lossy_cbr_bitrate,
            self.vbr_level,
            self.spoken_lossy_cbr_bitrate,
            self.prefer_lossy,
            self.mono_for_spoken,
            self.smart_quality_by_type,
            self.normalize_sample_rate,
            self.aac_cutoff,
            self.fdk_afterburner,
            self.aac_tns,
            self.aac_pns,
            self.aac_ms_stereo,
            self.aac_intensity_stereo,
            self.video_crf,
            self.video_preset,
            self.sync_workers,
            self.device_write_workers,
            self.scrobble_on_sync,
            self.listenbrainz_token_row,
            self.lastfm_auth_row,
            self.backup_before_sync,
        ]
        for row in rows:
            row.setEnabled(enabled)

    def _device_overridable_rows(self) -> list:
        return [
            self.accent_color, self.show_art, self.write_back,
            self.compute_sound_check, self.rotate_tall_photos,
            self.fit_photo_thumbnails, self.rating_strategy,
            self.lossy_encoder, self.lossy_quality, self.bitrate_mode,
            self.music_lossy_cbr_bitrate, self.vbr_level,
            self.spoken_lossy_cbr_bitrate, self.prefer_lossy,
            self.mono_for_spoken, self.smart_quality_by_type,
            self.normalize_sample_rate, self.aac_cutoff,
            self.fdk_afterburner, self.aac_tns, self.aac_pns,
            self.aac_ms_stereo, self.aac_intensity_stereo,
            self.video_crf, self.video_preset, self.sync_workers,
            self.device_write_workers,
            self.scrobble_on_sync, self.listenbrainz_token_row,
            self.lastfm_auth_row,
            self.backup_before_sync,
        ]

    def _update_override_warnings(self) -> None:
        """Show yellow 'overridden by device' labels in global view when a device
        has its own settings file and use_global_settings is off."""
        if self._settings_scope != "global":
            for row in self._device_overridable_rows():
                row.set_override_warning(False)
            return
        ctx = self._current_device_context()
        show = False
        if ctx:
            root, key = ctx
            try:
                state = self._settings_service.get_device_settings_for_edit(root, key)
                show = state.exists and not state.use_global_settings
            except Exception:
                pass
        for row in self._device_overridable_rows():
            row.set_override_warning(show)

    def _apply_scope_visibility(self) -> None:
        """Show the settings that belong to the active Global/Device scope."""
        self._sync_scope_availability()
        device_scope = self._settings_scope == "device"

        self._manage_card.setVisible(device_scope)
        self._set_section_visible("General", "Manage", device_scope)
        self._appearance_card.set_row_visible(self.theme_combo, not device_scope)
        self._appearance_card.set_row_visible(self.high_contrast, not device_scope)
        self._appearance_card.set_row_visible(self.font_scale, not device_scope)
        self._appearance_card.set_row_visible(self.rounded_artwork, not device_scope)
        self._appearance_card.set_row_visible(self.sharpen_artwork, not device_scope)
        self._about_card.setVisible(not device_scope)
        self._set_section_visible("General", "About", not device_scope)

        self._backups_card.set_row_visible(self.backup_dir, not device_scope)
        self._backups_card.set_row_visible(self.max_backups, not device_scope)

        hidden_pages = {3, 5} if device_scope else set()
        for i, btn in enumerate(self._nav_buttons):
            btn.setVisible(i not in hidden_pages)
        if self._stack.currentIndex() in hidden_pages:
            self._select_page(0)
        else:
            self._select_page(self._stack.currentIndex())

        ignored = device_scope and self.use_global_settings.value
        self._set_device_rows_enabled(not ignored)
        self.use_global_settings.setEnabled(True)
        self.reset_device_settings.setEnabled(device_scope)
        if self._device_settings_pending:
            self._set_device_rows_enabled(False)
            self.use_global_settings.setEnabled(False)
            self.reset_device_settings.setEnabled(False)

        self._update_override_warnings()

    # ── Settings I/O ────────────────────────────────────────────────────────

    def load_from_settings(self):
        """Populate UI controls from the current AppSettings."""
        self._sync_scope_availability()
        self._device_settings_pending = False
        state = None
        ctx = self._current_device_context() if self._settings_scope == "device" else None
        if ctx:
            root, key = ctx
            try:
                self._device_settings_pending = (
                    self._device_sessions.current_session().device_settings_loading
                )
            except Exception:
                self._device_settings_pending = False
            if self._device_settings_pending:
                s = self._settings_service.get_global_settings()
            else:
                state = self._settings_service.get_device_settings_for_edit(root, key)
                s = state.settings
        else:
            self._settings_scope = "global"
            s = self._settings_service.get_global_settings()
        self._loading_settings = True
        self.use_global_settings.value = bool(state.use_global_settings) if state else False

        self.write_back.value = s.write_back_to_pc
        self.compute_sound_check.value = s.compute_sound_check
        self.rotate_tall_photos.value = s.rotate_tall_photos_for_device
        self.fit_photo_thumbnails.value = s.fit_photo_thumbnails

        # Rating conflict strategy
        strategy_display = {
            "ipod_wins": "iPod Wins", "pc_wins": "PC Wins",
            "highest": "Highest", "lowest": "Lowest", "average": "Average",
        }
        rs_text = strategy_display.get(s.rating_conflict_strategy, "iPod Wins")
        idx = self.rating_strategy.combo.findText(rs_text)
        if idx >= 0:
            self.rating_strategy.combo.setCurrentIndex(idx)

        # Scrobbling
        self.scrobble_on_sync.value = s.scrobble_on_sync
        
        if s.listenbrainz_token and s.listenbrainz_username:
            self.listenbrainz_token_row.set_connected(s.listenbrainz_username)
        else:
            self.listenbrainz_token_row.set_disconnected()
            
        if s.lastfm_session_key and s.lastfm_username:
            self.lastfm_auth_row.set_connected(s.lastfm_username)
        else:
            self.lastfm_auth_row.set_disconnected(s.lastfm_api_key, s.lastfm_api_secret)

        self.show_art.value = s.show_art_in_tracklist
        self.rounded_artwork.value = s.rounded_artwork
        self.sharpen_artwork.value = s.sharpen_artwork

        # Theme
        theme_display = {
            "dark": "Dark", "light": "Light", "system": "System",
            "catppuccin-mocha": "Catppuccin Mocha",
            "catppuccin-macchiato": "Catppuccin Macchiato",
            "catppuccin-frappe": "Catppuccin Frappé",
            "catppuccin-latte": "Catppuccin Latte",
        }
        theme_text = theme_display.get(s.theme, "Dark")
        idx = self.theme_combo.combo.findText(theme_text)
        if idx >= 0:
            self.theme_combo.combo.setCurrentIndex(idx)

        # High contrast
        hc_display = {"off": "Off", "on": "On", "system": "System"}
        hc_text = hc_display.get(s.high_contrast, "Off")
        idx = self.high_contrast.combo.findText(hc_text)
        if idx >= 0:
            self.high_contrast.combo.setCurrentIndex(idx)

        # Accent color
        accent_display = {
            "blue": "Blue (Default)", "match-ipod": "Match iPod",
            "red": "Red", "orange": "Orange", "gold": "Gold",
            "green": "Green", "teal": "Teal", "purple": "Purple",
            "pink": "Pink",
        }
        ac_text = accent_display.get(s.accent_color, "Blue (Default)")
        idx = self.accent_color.combo.findText(ac_text)
        if idx >= 0:
            self.accent_color.combo.setCurrentIndex(idx)

        # Font scale
        idx = self.font_scale.combo.findText(s.font_scale)
        if idx >= 0:
            self.font_scale.combo.setCurrentIndex(idx)

        self.transcode_cache_dir.value = s.transcode_cache_dir
        # Max cache size combo
        _size_map = {0.0: "Unlimited", 1.0: "1 GB", 2.0: "2 GB", 5.0: "5 GB",
                     10.0: "10 GB", 20.0: "20 GB", 50.0: "50 GB"}
        _size_text = _size_map.get(float(s.max_cache_size_gb), "5 GB")
        idx = self.max_cache_size.combo.findText(_size_text)
        if idx >= 0:
            self.max_cache_size.combo.setCurrentIndex(idx)
        self.cache_status.refresh()
        self.settings_dir.value = s.settings_dir
        self.log_dir.value = s.log_dir
        self.ffmpeg_path.value = s.ffmpeg_path
        self.fpcalc_path.value = s.fpcalc_path

        self.backup_dir.value = s.backup_dir
        self.backup_before_sync.value = s.backup_before_sync

        # Refresh tool status indicators
        self._refresh_tool_status()

        # Max backups → combo text
        max_map = {0: "Unlimited", 5: "5", 10: "10", 20: "20"}
        mb_text = max_map.get(s.max_backups, "10")
        idx = self.max_backups.combo.findText(mb_text)
        if idx >= 0:
            self.max_backups.combo.setCurrentIndex(idx)

        # Lossy encoder — also rebuilds bitrate_mode/vbr_level options for the encoder
        desired_enc = "Auto" if s.lossy_encoder == "auto" else s.lossy_encoder
        selected_enc = self._refresh_encoder_options(desired=desired_enc)
        self._update_encoder_dependent_combos(selected_enc)

        # Lossy quality (Auto mode)
        quality_display = {"high": "High Quality", "balanced": "Balanced", "compact": "Compact"}
        q_text = quality_display.get(s.lossy_quality, "Balanced")
        idx = self.lossy_quality.combo.findText(q_text)
        if idx >= 0:
            self.lossy_quality.combo.setCurrentIndex(idx)

        # Bitrate mode (manual encoder mode)
        bm_text = {"vbr": "VBR", "abr": "ABR", "cvbr": "CVBR"}.get(s.bitrate_mode, "CBR")
        idx = self.bitrate_mode.combo.findText(bm_text)
        if idx >= 0:
            self.bitrate_mode.combo.setCurrentIndex(idx)

        # Music CBR bitrate
        cbr_text = f"{s.music_lossy_cbr_bitrate} kbps"
        idx = self.music_lossy_cbr_bitrate.combo.findText(cbr_text)
        if idx >= 0:
            self.music_lossy_cbr_bitrate.combo.setCurrentIndex(idx)

        # VBR level
        vbr_text = self._vbr_level_to_text(selected_enc, s.vbr_level)
        idx = self.vbr_level.combo.findText(vbr_text)
        if idx >= 0:
            self.vbr_level.combo.setCurrentIndex(idx)

        self._update_lossy_visibility()
        self._update_advanced_aac_visibility(selected_enc)

        # Spoken word bitrate
        spk_text = f"{s.spoken_lossy_cbr_bitrate} kbps"
        idx = self.spoken_lossy_cbr_bitrate.combo.findText(spk_text)
        if idx >= 0:
            self.spoken_lossy_cbr_bitrate.combo.setCurrentIndex(idx)

        # Prefer lossy toggle
        self.prefer_lossy.value = s.prefer_lossy

        # Audio encoding options
        self.mono_for_spoken.value = s.mono_for_spoken
        self.smart_quality_by_type.value = s.smart_quality_by_type
        self.normalize_sample_rate.value = s.normalize_sample_rate

        # Advanced AAC
        cutoff_display = {0: "Auto", 15000: "15 kHz", 16000: "16 kHz", 17000: "17 kHz",
                          18000: "18 kHz", 19000: "19 kHz", 20000: "20 kHz"}
        c_text = cutoff_display.get(s.aac_cutoff, "Auto")
        idx = self.aac_cutoff.combo.findText(c_text)
        if idx >= 0:
            self.aac_cutoff.combo.setCurrentIndex(idx)
        self.fdk_afterburner.value = s.fdk_afterburner
        self.aac_tns.value = s.aac_tns
        self.aac_pns.value = s.aac_pns
        self.aac_ms_stereo.value = s.aac_ms_stereo
        self.aac_intensity_stereo.value = s.aac_intensity_stereo

        self._update_smart_quality_visibility()

        # Video CRF → combo text
        crf_map = {18: "18 (High)", 20: "20 (Good)", 23: "23 (Balanced)", 26: "26 (Low)", 28: "28 (Very Low)"}
        crf_text = crf_map.get(s.video_crf, "23 (Balanced)")
        idx = self.video_crf.combo.findText(crf_text)
        if idx >= 0:
            self.video_crf.combo.setCurrentIndex(idx)

        # Video preset → combo text
        idx = self.video_preset.combo.findText(s.video_preset)
        if idx >= 0:
            self.video_preset.combo.setCurrentIndex(idx)

        # Sync workers → combo text
        workers_map = {0: "Auto", 1: "1", 2: "2", 4: "4", 6: "6", 8: "8"}
        sw_text = workers_map.get(s.sync_workers, "Auto")
        idx = self.sync_workers.combo.findText(sw_text)
        if idx >= 0:
            self.sync_workers.combo.setCurrentIndex(idx)

        write_workers_map = {0: "Auto", 1: "1", 2: "2", 4: "4"}
        dww_text = write_workers_map.get(s.device_write_workers, "Auto")
        idx = self.device_write_workers.combo.findText(dww_text)
        if idx >= 0:
            self.device_write_workers.combo.setCurrentIndex(idx)

        self._apply_scope_visibility()

        # Connect signals to auto-save (only once)
        if not hasattr(self, '_signals_connected'):
            self._signals_connected = True
            self.use_global_settings.changed.connect(self._save)
            self.write_back.changed.connect(self._save)
            self.compute_sound_check.changed.connect(self._save)
            self.rotate_tall_photos.changed.connect(self._save)
            self.fit_photo_thumbnails.changed.connect(self._save)
            self.rating_strategy.changed.connect(self._save)
            self.lossy_encoder.changed.connect(self._save)
            self.lossy_encoder.changed.connect(self._on_encoder_changed)
            self.lossy_quality.changed.connect(self._save)
            self.bitrate_mode.changed.connect(self._save)
            self.bitrate_mode.changed.connect(self._on_bitrate_mode_changed)
            self.music_lossy_cbr_bitrate.changed.connect(self._save)
            self.vbr_level.changed.connect(self._save)
            self.spoken_lossy_cbr_bitrate.changed.connect(self._save)
            self.prefer_lossy.changed.connect(self._save)
            self.mono_for_spoken.changed.connect(self._save)
            self.smart_quality_by_type.changed.connect(self._save)
            self.smart_quality_by_type.changed.connect(self._update_smart_quality_visibility)
            self.normalize_sample_rate.changed.connect(self._save)
            self.aac_cutoff.changed.connect(self._save)
            self.fdk_afterburner.changed.connect(self._save)
            self.aac_tns.changed.connect(self._save)
            self.aac_pns.changed.connect(self._save)
            self.aac_ms_stereo.changed.connect(self._save)
            self.aac_intensity_stereo.changed.connect(self._save)
            self.video_crf.changed.connect(self._save)
            self.video_preset.changed.connect(self._save)
            self.sync_workers.changed.connect(self._save)
            self.device_write_workers.changed.connect(self._save)
            self.show_art.changed.connect(self._save)
            self.rounded_artwork.changed.connect(self._save)
            self.sharpen_artwork.changed.connect(self._save)
            self.accent_color.changed.connect(self._save)
            self.theme_combo.changed.connect(self._save)
            self.high_contrast.changed.connect(self._save)
            self.font_scale.changed.connect(self._save)
            self.transcode_cache_dir.changed.connect(self._save)
            self.max_cache_size.changed.connect(self._save)
            self.settings_dir.changed.connect(self._save)
            self.log_dir.changed.connect(self._save)
            self.ffmpeg_path.changed.connect(self._save_and_refresh_tools)
            self.fpcalc_path.changed.connect(self._save_and_refresh_tools)
            self.backup_dir.changed.connect(self._save)
            self.backup_before_sync.changed.connect(self._save)
            self.max_backups.changed.connect(self._save)
            self.scrobble_on_sync.changed.connect(self._save)
        self._loading_settings = False

    # ── Lossy encoder reactive helpers ───────────────────────────────────────

    def _refresh_encoder_options(self, desired: str = "Auto") -> str:
        """Repopulate the lossy encoder combo based on what ffmpeg actually supports."""
        aac_avail: set[str] = set()
        mp3_avail: set[str] = set()
        try:
            from SyncEngine.transcoder import (
                available_aac_encoders,
                available_mp3_encoders,
                find_ffmpeg,
            )
            ffmpeg_path = self._settings_service.get_effective_settings().ffmpeg_path
            if find_ffmpeg(ffmpeg_path):
                aac_avail = set(available_aac_encoders(ffmpeg_path))
                mp3_avail = set(available_mp3_encoders(ffmpeg_path))
        except Exception:
            pass

        options = ["Auto"]
        for enc in ("libfdk_aac", "aac_at", "aac"):
            if enc in aac_avail:
                options.append(enc)
        for enc in ("libmp3lame", "libshine"):
            if enc in mp3_avail:
                options.append(enc)
        if len(options) == 1:
            options += ["libfdk_aac", "aac_at", "aac", "libmp3lame", "libshine"]

        combo = self.lossy_encoder.combo
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(options)
        idx = combo.findText(desired) if desired in options else 0
        combo.setCurrentIndex(idx)
        combo.blockSignals(False)
        return options[idx]

    def _update_encoder_dependent_combos(self, encoder_text: str) -> None:
        """Repopulate bitrate_mode and vbr_level combos to match the selected encoder."""
        if encoder_text == "aac_at":
            bm_options = ["CBR", "ABR", "CVBR", "VBR"]
        elif encoder_text in ("libfdk_aac", "libmp3lame"):
            bm_options = ["CBR", "VBR"]
        else:
            bm_options = ["CBR"]

        bm_combo = self.bitrate_mode.combo
        current_bm = bm_combo.currentText()
        bm_combo.blockSignals(True)
        bm_combo.clear()
        bm_combo.addItems(bm_options)
        idx = bm_combo.findText(current_bm)
        bm_combo.setCurrentIndex(max(0, idx))
        bm_combo.blockSignals(False)

        vbr_combo = self.vbr_level.combo
        current_vbr = vbr_combo.currentText()
        vbr_combo.blockSignals(True)
        vbr_combo.clear()
        if encoder_text == "libfdk_aac":
            vbr_combo.addItems([
                "VBR 1 (Low)", "VBR 2", "VBR 3", "VBR 4", "VBR 5 (High)",
            ])
            default_idx = 3  # VBR 4
        elif encoder_text == "aac_at":
            vbr_combo.addItems([
                "q0 (Best)", "q1", "q2", "q3", "q4", "q5", "q6", "q7",
                "q8", "q9", "q10", "q11", "q12", "q13", "q14 (Lowest)",
            ])
            default_idx = 9  # q9 mid-range
        else:
            vbr_combo.addItems([
                "q0 (Best)", "q1", "q2", "q3", "q4", "q5", "q6", "q7", "q8", "q9 (Smallest)",
            ])
            default_idx = 4  # q4
        idx = vbr_combo.findText(current_vbr)
        vbr_combo.setCurrentIndex(idx if idx >= 0 else default_idx)
        vbr_combo.blockSignals(False)

    def _update_lossy_visibility(self) -> None:
        """Show/hide rows based on current encoder and bitrate_mode selections."""
        if not hasattr(self, "_audio_card"):
            return
        enc = self.lossy_encoder.value
        is_auto = enc == "Auto"
        is_vbr = self.bitrate_mode.value == "VBR"
        self._audio_card.set_row_visible(self.lossy_quality, is_auto)
        self._audio_card.set_row_visible(self.bitrate_mode, not is_auto)
        self._audio_card.set_row_visible(self.music_lossy_cbr_bitrate, not is_auto and not is_vbr)
        self._audio_card.set_row_visible(self.vbr_level, not is_auto and is_vbr)

    def _on_encoder_changed(self, encoder_text: str) -> None:
        self._update_encoder_dependent_combos(encoder_text)
        self._update_lossy_visibility()
        self._update_advanced_aac_visibility(encoder_text)

    def _update_advanced_aac_visibility(self, encoder_text: str) -> None:
        if not hasattr(self, "_advanced_aac_card"):
            return
        is_fdk = encoder_text == "libfdk_aac"
        is_native = encoder_text == "aac"
        is_specific_aac = encoder_text in ("libfdk_aac", "aac_at", "aac")

        # Only show for a manually chosen AAC encoder
        self._advanced_aac_card.setVisible(is_specific_aac)
        self._set_section_visible("Transcoding", "Advanced AAC", is_specific_aac)
        if not is_specific_aac:
            return

        # Bandwidth cutoff applies to every specific AAC encoder
        self._advanced_aac_card.set_row_visible(self.aac_cutoff, True)

        # fdk_afterburner is only meaningful for libfdk_aac
        self._advanced_aac_card.set_row_visible(self.fdk_afterburner, is_fdk)

        # PNS / TNS / M/S / IS are only controllable on the native aac encoder
        self._advanced_aac_card.set_row_visible(self.aac_tns, is_native)
        self._advanced_aac_card.set_row_visible(self.aac_pns, is_native)
        self._advanced_aac_card.set_row_visible(self.aac_ms_stereo, is_native)
        self._advanced_aac_card.set_row_visible(self.aac_intensity_stereo, is_native)

    def _on_bitrate_mode_changed(self, _: str) -> None:
        self._update_lossy_visibility()

    def _update_smart_quality_visibility(self) -> None:
        if not hasattr(self, "_spoken_card"):
            return
        enabled = self.smart_quality_by_type.value
        self._spoken_card.set_row_visible(self.spoken_lossy_cbr_bitrate, enabled)
        self._spoken_card.set_row_visible(self.mono_for_spoken, enabled)

    @staticmethod
    def _vbr_text_to_level(encoder: str, text: str) -> int:
        if encoder == "libfdk_aac":
            try:
                return int(text.split()[1])
            except (IndexError, ValueError):
                return 4
        elif encoder == "aac_at":
            try:
                return max(0, min(14, int(text.lstrip("q").split()[0])))
            except (IndexError, ValueError):
                return 9
        else:
            try:
                return int(text.lstrip("q").split()[0])
            except (IndexError, ValueError):
                return 4

    @staticmethod
    def _vbr_level_to_text(encoder: str, level: int) -> str:
        if encoder == "libfdk_aac":
            lbl = max(1, min(5, level))
            labels = {1: "VBR 1 (Low)", 5: "VBR 5 (High)"}
            return labels.get(lbl, f"VBR {lbl}")
        elif encoder == "aac_at":
            q = max(0, min(14, level))
            labels = {0: "q0 (Best)", 14: "q14 (Lowest)"}
            return labels.get(q, f"q{q}")
        else:
            q = max(0, min(9, level))
            labels = {0: "q0 (Best)", 9: "q9 (Smallest)"}
            return labels.get(q, f"q{q}")

    # ── Settings persistence ─────────────────────────────────────────────────

    def _read_controls_into_settings(self, s, include_global_only: bool) -> None:
        """Copy visible control values into an AppSettings object."""
        s.write_back_to_pc = self.write_back.value
        s.compute_sound_check = self.compute_sound_check.value
        s.rotate_tall_photos_for_device = self.rotate_tall_photos.value
        s.fit_photo_thumbnails = self.fit_photo_thumbnails.value

        # Rating conflict strategy
        strategy_keys = {
            "iPod Wins": "ipod_wins", "PC Wins": "pc_wins",
            "Highest": "highest", "Lowest": "lowest", "Average": "average",
        }
        s.rating_conflict_strategy = strategy_keys.get(self.rating_strategy.value, "ipod_wins")

        s.scrobble_on_sync = self.scrobble_on_sync.value

        # Lossy encoder
        enc_text = self.lossy_encoder.value
        s.lossy_encoder = "auto" if enc_text == "Auto" else enc_text

        # Lossy quality (Auto mode preset)
        quality_keys = {"High Quality": "high", "Balanced": "balanced", "Compact": "compact"}
        s.lossy_quality = quality_keys.get(self.lossy_quality.value, "balanced")

        # Manual encoder settings
        s.bitrate_mode = {"VBR": "vbr", "ABR": "abr", "CVBR": "cvbr"}.get(self.bitrate_mode.value, "cbr")
        cbr_str = self.music_lossy_cbr_bitrate.value.replace(" kbps", "")
        s.music_lossy_cbr_bitrate = int(cbr_str) if cbr_str.isdigit() else 192
        s.vbr_level = self._vbr_text_to_level(enc_text, self.vbr_level.value)

        s.show_art_in_tracklist = self.show_art.value

        if include_global_only:
            s.rounded_artwork = self.rounded_artwork.value
            s.sharpen_artwork = self.sharpen_artwork.value
            # Theme
            theme_keys = {
                "Dark": "dark", "Light": "light", "System": "system",
                "Catppuccin Mocha": "catppuccin-mocha",
                "Catppuccin Macchiato": "catppuccin-macchiato",
                "Catppuccin Frappé": "catppuccin-frappe",
                "Catppuccin Latte": "catppuccin-latte",
            }
            s.theme = theme_keys.get(self.theme_combo.value, "dark")

            # High contrast
            hc_keys = {"Off": "off", "On": "on", "System": "system"}
            s.high_contrast = hc_keys.get(self.high_contrast.value, "off")

        # Accent color
        accent_keys = {
            "Blue (Default)": "blue", "Match iPod": "match-ipod",
            "Red": "red", "Orange": "orange", "Gold": "gold",
            "Green": "green", "Teal": "teal", "Purple": "purple",
            "Pink": "pink",
        }
        s.accent_color = accent_keys.get(self.accent_color.value, "blue")

        if include_global_only:
            s.transcode_cache_dir = self.transcode_cache_dir.value
            # Parse max cache size
            _size_keys = {"Unlimited": 0.0, "1 GB": 1.0, "2 GB": 2.0, "5 GB": 5.0,
                          "10 GB": 10.0, "20 GB": 20.0, "50 GB": 50.0}
            s.max_cache_size_gb = _size_keys.get(self.max_cache_size.value, 5.0)
            s.settings_dir = self.settings_dir.value
            s.log_dir = self.log_dir.value
            s.ffmpeg_path = self.ffmpeg_path.value
            s.fpcalc_path = self.fpcalc_path.value
            s.backup_dir = self.backup_dir.value
        s.backup_before_sync = self.backup_before_sync.value

        if include_global_only:
            # Parse max backups
            mb_text = self.max_backups.value
            s.max_backups = int(mb_text) if mb_text and mb_text != "Unlimited" else 0

        spk_str = self.spoken_lossy_cbr_bitrate.value.replace(" kbps", "")
        s.spoken_lossy_cbr_bitrate = int(spk_str) if spk_str.isdigit() else 64

        # Prefer lossy toggle
        s.prefer_lossy = self.prefer_lossy.value

        # Audio encoding options
        s.mono_for_spoken = self.mono_for_spoken.value
        s.smart_quality_by_type = self.smart_quality_by_type.value
        s.normalize_sample_rate = self.normalize_sample_rate.value

        # Advanced AAC
        cutoff_keys = {"Auto": 0, "15 kHz": 15000, "16 kHz": 16000, "17 kHz": 17000,
                       "18 kHz": 18000, "19 kHz": 19000, "20 kHz": 20000}
        s.aac_cutoff = cutoff_keys.get(self.aac_cutoff.value, 0)
        s.fdk_afterburner = self.fdk_afterburner.value
        s.aac_tns = self.aac_tns.value
        s.aac_pns = self.aac_pns.value
        s.aac_ms_stereo = self.aac_ms_stereo.value
        s.aac_intensity_stereo = self.aac_intensity_stereo.value

        # Parse video CRF (extract leading integer)
        crf_text = self.video_crf.value
        try:
            s.video_crf = int(crf_text.split()[0])
        except (ValueError, IndexError):
            s.video_crf = 23

        # Video preset (stored as-is)
        s.video_preset = self.video_preset.value or "fast"

        # Parse sync workers
        sw_text = self.sync_workers.value
        s.sync_workers = int(sw_text) if sw_text and sw_text != "Auto" else 0

        dww_text = self.device_write_workers.value
        s.device_write_workers = (
            int(dww_text) if dww_text and dww_text != "Auto" else 0
        )

        if include_global_only:
            # Font scale
            scale_keys = {
                "75%": "75%", "90%": "90%", "100%": "100%",
                "110%": "110%", "125%": "125%", "150%": "150%",
            }
            s.font_scale = scale_keys.get(self.font_scale.value, "100%")

    def _apply_theme_change_if_needed(self, before) -> None:
        s = self._settings_service.get_effective_settings()
        after = (s.theme, s.high_contrast, s.accent_color, s.font_scale)
        if after != before:
            accent_hex = resolve_accent_color(
                s.accent_color, self._current_ipod_image(),
            )
            Colors.apply_theme(s.theme, s.high_contrast, accent_hex)
            Metrics.apply_font_scale(s.font_scale)
            self.theme_changed.emit()

    def _reset_device_settings_to_global(self) -> None:
        """Reset the selected iPod settings file from current global settings."""
        if self._device_settings_pending:
            return
        ctx = self._current_device_context()
        if not ctx:
            return

        effective_before = self._settings_service.get_effective_settings()
        theme_before = (
            effective_before.theme,
            effective_before.high_contrast,
            effective_before.accent_color,
            effective_before.font_scale,
        )

        root, key = ctx
        self._settings_service.reset_device_settings_to_global(
            root,
            key,
            use_global_settings=self.use_global_settings.value,
        )
        self.load_from_settings()
        self._apply_theme_change_if_needed(theme_before)

    def _save(self, *_args):
        """Read controls back into the active settings scope and persist."""
        if self._loading_settings or self._device_settings_pending:
            return

        effective_before = self._settings_service.get_effective_settings()
        artwork_before = (
            effective_before.show_art_in_tracklist,
            effective_before.rounded_artwork,
            effective_before.sharpen_artwork,
        )
        theme_before = (
            effective_before.theme,
            effective_before.high_contrast,
            effective_before.accent_color,
            effective_before.font_scale,
        )

        ctx = self._current_device_context() if self._settings_scope == "device" else None
        if ctx:
            root, key = ctx
            state = self._settings_service.get_device_settings_for_edit(root, key)
            s = state.settings
            self._read_controls_into_settings(s, include_global_only=False)
            self._settings_service.save_device_settings(
                root,
                s,
                use_global_settings=self.use_global_settings.value,
                device_key=key,
            )
            effective_after = self._settings_service.get_effective_settings()
            self._apply_scope_visibility()
            self._apply_theme_change_if_needed(theme_before)
            if artwork_before != (
                effective_after.show_art_in_tracklist,
                effective_after.rounded_artwork,
                effective_after.sharpen_artwork,
            ):
                self.artwork_appearance_changed.emit()
            return

        s = self._settings_service.get_global_settings()
        old_cache_limit = s.max_cache_size_gb
        self._read_controls_into_settings(s, include_global_only=True)
        limit_lowered = (
            old_cache_limit > 0
            and (s.max_cache_size_gb == 0 or s.max_cache_size_gb < old_cache_limit)
        )
        self._settings_service.save_global_settings(s)
        effective_after = self._settings_service.get_effective_settings()

        # If limit was lowered, evict immediately so cache stays within bounds.
        if limit_lowered:
            try:
                from SyncEngine.transcode_cache import TranscodeCache
                cache_dir = Path(s.transcode_cache_dir) if s.transcode_cache_dir else None
                TranscodeCache.get_instance(
                    cache_dir,
                    max_cache_size_gb=s.max_cache_size_gb,
                ).trim_to_limit()
                self.cache_status.refresh()
            except Exception:
                pass

        self._apply_theme_change_if_needed(theme_before)
        if artwork_before != (
            effective_after.show_art_in_tracklist,
            effective_after.rounded_artwork,
            effective_after.sharpen_artwork,
        ):
            self.artwork_appearance_changed.emit()

    @staticmethod
    def _current_ipod_image() -> str:
        """Return the image filename for the currently connected iPod, or ''."""
        try:
            from ipod_device import get_current_device
            dev = get_current_device()
            if not dev:
                return ""
            from ipod_device import image_for_model, resolve_image_filename
            if dev.model_number:
                img = image_for_model(dev.model_number)
                if img:
                    return img
            if dev.model_family and dev.generation:
                return resolve_image_filename(
                    dev.model_family, dev.generation, dev.color or "",
                )
        except Exception:
            pass
        return ""

    # ── Event handlers ──────────────────────────────────────────────────────

    def _on_close(self):
        """Go back — settings are already saved on every change."""
        self.closed.emit()

    def _check_for_updates(self):
        """Check GitHub for a newer version in a background thread."""
        from PyQt6.QtWidgets import QMessageBox

        from GUI.auto_updater import UpdateChecker, UpdateResult

        self.version_row.action_btn.setEnabled(False)
        self.version_row.action_btn.setText("Checking…")

        self._update_checker = UpdateChecker(self)

        def _on_result(result: UpdateResult):
            self.version_row.action_btn.setEnabled(True)
            self.version_row.action_btn.setText("Check")

            if result.error:
                QMessageBox.warning(self, "Update Check Failed", result.error)
                return

            if not result.update_available:
                QMessageBox.information(
                    self, "Up to Date",
                    f"You are running the latest version (v{result.current_version}).",
                )
                return

            self._handle_update_result(result)

        self._update_checker.result_ready.connect(_on_result)
        self._update_checker.start()

    def _handle_update_result(self, result):
        """Show update-available UI and optionally download/install."""
        from PyQt6.QtWidgets import QMessageBox, QProgressDialog

        from GUI.auto_updater import (
            UpdateDownloader,
            launch_bootstrap_and_exit,
            stage_update,
            update_log_path,
        )

        notes_preview = result.release_notes[:500]
        if len(result.release_notes) > 500:
            notes_preview += "…"

        import sys as _sys

        if not getattr(_sys, "frozen", False):
            # Running from source — no point downloading a binary
            QMessageBox.information(
                self, "Update Available",
                f"A new version is available: v{result.latest_version}\n"
                f"(current: v{result.current_version})\n\n"
                f"{notes_preview}\n\n"
                "You are running from source.\n"
                "Run 'git pull' to get the latest changes.",
            )
            return

        answer = QMessageBox.question(
            self, "Update Available",
            f"A new version is available: v{result.latest_version}\n"
            f"(current: v{result.current_version})\n\n"
            f"{notes_preview}\n\n"
            f"Download now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        if not result.download_url:
            QMessageBox.information(
                self, "No Binary Available",
                "No pre-built binary was found for your platform.\n\n"
                f"Visit {result.release_page} to download manually.",
            )
            QDesktopServices.openUrl(QUrl(result.release_page))
            return

        # Start download with progress dialog
        progress = QProgressDialog(
            "Downloading update…", "Cancel", 0, 100, self,
        )
        progress.setWindowTitle("iOpenPod Update")
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        # Keep a reference so it isn't garbage-collected
        self._update_progress = progress

        checksum_url = result.download_url + ".sha256"
        downloader = UpdateDownloader(result.download_url, checksum_url, self)
        self._update_downloader = downloader

        def _on_progress(downloaded: int, total: int):
            if progress.wasCanceled():
                return
            pct = int(downloaded * 100 / total) if total else 0
            progress.setValue(pct)

        def _on_finished(path_str: str):
            # Disconnect cancel so closing the dialog doesn't kill
            # the already-finished downloader or interfere with staging.
            try:
                progress.canceled.disconnect()
            except TypeError:
                pass
            progress.close()
            self._update_progress = None
            if not path_str:
                QMessageBox.warning(
                    self, "Download Failed",
                    "The update could not be downloaded.\n"
                    "Check your internet connection and try again.",
                )
                return

            from pathlib import Path as _Path
            archive = _Path(path_str)

            # Stage the update (extract to temp dir)
            staged = stage_update(archive)
            if not staged:
                QMessageBox.warning(
                    self, "Update Failed",
                    "Could not extract the update archive.\n\n"
                    f"The archive is at:\n{archive}\n"
                    "You can extract it manually.",
                )
                return

            log_path = update_log_path()
            answer2 = QMessageBox.question(
                self, "Install Update & Restart?",
                f"v{result.latest_version} is ready to install.\n\n"
                "iOpenPod will close, apply the update, and "
                "relaunch automatically.\n\n"
                f"If anything goes wrong, check the log at:\n{log_path}\n\n"
                "Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer2 == QMessageBox.StandardButton.Yes:
                if launch_bootstrap_and_exit(staged):
                    # Bootstrap is running — close the app so it
                    # can replace our files and relaunch.
                    from PyQt6.QtWidgets import QApplication
                    app = QApplication.instance()
                    if app:
                        app.quit()
                else:
                    QMessageBox.warning(
                        self, "Update Failed",
                        "Could not start the update installer.\n\n"
                        f"The update files are at:\n{staged}\n\n"
                        f"Check the log for details:\n{log_path}",
                    )

        downloader.progress.connect(_on_progress)
        downloader.finished_download.connect(_on_finished)
        progress.canceled.connect(downloader.terminate)
        downloader.start()

    def _save_and_refresh_tools(self, *_args):
        """Save settings then refresh tool status indicators."""
        self._save()
        self._refresh_tool_status()

    def _refresh_tool_status(self):
        """Check whether ffmpeg and fpcalc are reachable and update the UI."""
        from SyncEngine.audio_fingerprint import find_fpcalc
        from SyncEngine.transcoder import (
            available_aac_encoders,
            available_mp3_encoders,
            find_ffmpeg,
        )

        settings = self._settings_service.get_effective_settings()
        ffmpeg = find_ffmpeg(settings.ffmpeg_path)
        self.ffmpeg_tool.set_status(bool(ffmpeg), ffmpeg or "")
        aac_enc = available_aac_encoders(settings.ffmpeg_path) if ffmpeg else set()
        mp3_enc = available_mp3_encoders(settings.ffmpeg_path) if ffmpeg else set()
        self.ffmpeg_tool.set_lossy_encoder_statuses(
            {
                "aac": "aac" in aac_enc,
                "aac_at": "aac_at" in aac_enc,
                "libfdk_aac": "libfdk_aac" in aac_enc,
                "libmp3lame": "libmp3lame" in mp3_enc,
                "libshine": "libshine" in mp3_enc,
            }
        )

        fpcalc = find_fpcalc(settings.fpcalc_path)
        self.fpcalc_tool.set_status(bool(fpcalc), fpcalc or "")

    def _download_ffmpeg(self):
        """Download FFmpeg in a background thread."""
        self.ffmpeg_tool.set_downloading()
        import threading

        def _do():
            from SyncEngine.dependency_manager import download_ffmpeg
            download_ffmpeg()
            from PyQt6.QtCore import QMetaObject
            from PyQt6.QtCore import Qt as QtCore_Qt
            QMetaObject.invokeMethod(
                self, "_on_ffmpeg_downloaded",
                QtCore_Qt.ConnectionType.QueuedConnection,
            )

        threading.Thread(target=_do, daemon=True).start()

    def _download_fpcalc(self):
        """Download fpcalc in a background thread."""
        self.fpcalc_tool.set_downloading()
        import threading

        def _do():
            from SyncEngine.dependency_manager import download_fpcalc
            download_fpcalc()
            from PyQt6.QtCore import QMetaObject
            from PyQt6.QtCore import Qt as QtCore_Qt
            QMetaObject.invokeMethod(
                self, "_on_fpcalc_downloaded",
                QtCore_Qt.ConnectionType.QueuedConnection,
            )

        threading.Thread(target=_do, daemon=True).start()

    @pyqtSlot()
    def _on_ffmpeg_downloaded(self):
        """Called on main thread after FFmpeg download completes."""
        self._refresh_tool_status()
        self.ffmpeg_tool.download_btn.setEnabled(True)
        self.ffmpeg_tool.download_btn.setText("Download")

    @pyqtSlot()
    def _on_fpcalc_downloaded(self):
        """Called on main thread after fpcalc download completes."""
        self._refresh_tool_status()
        self.fpcalc_tool.download_btn.setEnabled(True)
        self.fpcalc_tool.download_btn.setText("Download")

    # ── ListenBrainz Scrobbling handlers ───────────────────────────────────

    def _save_listenbrainz_credentials(
        self,
        token: str,
        username: str,
        scope: str | None = None,
        root: str | None = None,
        key: str | None = None,
        use_global: bool | None = None,
    ) -> None:
        if scope is None:
            ctx = self._current_device_context() if self._settings_scope == "device" else None
            if ctx:
                root, key = ctx
                scope = "device"
            else:
                scope = "global"

        if scope == "device" and root and key:
            state = self._settings_service.get_device_settings_for_edit(root, key)
            s = state.settings
            s.listenbrainz_token = token
            s.listenbrainz_username = username
            self._settings_service.save_device_settings(
                root,
                s,
                use_global_settings=self.use_global_settings.value if use_global is None else use_global,
                device_key=key,
            )
            return

        s = self._settings_service.get_global_settings()
        s.listenbrainz_token = token
        s.listenbrainz_username = username
        self._settings_service.save_global_settings(s)

    def _on_listenbrainz_token_changed(self, token: str):
        """Handle ListenBrainz token save/clear."""
        if not token:
            # Disconnect
            self._save_listenbrainz_credentials("", "")
            return

        ctx = self._current_device_context() if self._settings_scope == "device" else None
        if ctx:
            root, key = ctx
            pending_scope = "device"
            pending_use_global = self.use_global_settings.value
        else:
            root, key = "", ""
            pending_scope = "global"
            pending_use_global = False

        # Validate the token in a background thread
        self.listenbrainz_token_row.save_btn.setEnabled(False)
        self.listenbrainz_token_row.save_btn.setText("Validating…")

        import threading

        def _do_validate():
            from SyncEngine.scrobbler import listenbrainz_validate_token
            username = listenbrainz_validate_token(token)
            # Stash result so the slot can read it
            self._pending_lb_result = (
                token,
                username or "",
                pending_scope,
                root,
                key,
                pending_use_global,
            )
            from PyQt6.QtCore import QMetaObject
            from PyQt6.QtCore import Qt as QtCore_Qt
            QMetaObject.invokeMethod(
                self, "_on_listenbrainz_validate_result",
                QtCore_Qt.ConnectionType.QueuedConnection,
            )

        threading.Thread(target=_do_validate, daemon=True).start()

    @pyqtSlot()
    def _on_listenbrainz_validate_result(self):
        """Called on main thread after ListenBrainz token validation."""
        pending = self._pending_lb_result
        token, username, scope, root, key, use_global = pending
        self.listenbrainz_token_row.save_btn.setEnabled(True)
        self.listenbrainz_token_row.save_btn.setText("Connect")

        if not username:
            self.listenbrainz_token_row.set_error("Invalid token")
            return

        self._save_listenbrainz_credentials(
            token,
            username,
            scope=scope,
            root=root,
            key=key,
            use_global=use_global,
        )

        self.listenbrainz_token_row.set_connected(username)

    # ── Last.fm Scrobbling handlers ────────────────────────────────────────

    def _save_lastfm_credentials(
        self,
        api_key: str,
        api_secret: str,
        session_key: str,
        username: str,
        scope: str | None = None,
        root: str | None = None,
        key: str | None = None,
        use_global: bool | None = None,
    ) -> None:
        if scope is None:
            ctx = self._current_device_context() if self._settings_scope == "device" else None
            if ctx:
                root, key = ctx
                scope = "device"
            else:
                scope = "global"

        if scope == "device" and root and key:
            state = self._settings_service.get_device_settings_for_edit(root, key)
            s = state.settings
            s.lastfm_api_key = api_key
            s.lastfm_api_secret = api_secret
            s.lastfm_session_key = session_key
            s.lastfm_username = username
            self._settings_service.save_device_settings(
                root,
                s,
                use_global_settings=self.use_global_settings.value if use_global is None else use_global,
                device_key=key,
            )
            return

        s = self._settings_service.get_global_settings()
        s.lastfm_api_key = api_key
        s.lastfm_api_secret = api_secret
        s.lastfm_session_key = session_key
        s.lastfm_username = username
        self._settings_service.save_global_settings(s)

    def _on_lastfm_credentials_changed(self, api_key: str, api_secret: str, session_key: str, username: str):
        """Handle Last.fm credentials save/clear."""
        # If session_key is empty, the user clicked "Disconnect"
        if not session_key:
            # We still save the API key & secret so they don't have to type them again later
            self._save_lastfm_credentials(api_key, api_secret, "", "")
            self.lastfm_auth_row.set_disconnected(api_key, api_secret)
            return

        ctx = self._current_device_context() if self._settings_scope == "device" else None
        if ctx:
            root, key = ctx
            scope = "device"
            use_global = self.use_global_settings.value
        else:
            root, key = "", ""
            scope = "global"
            use_global = False

        # Save the successfully fetched session key and username
        self._save_lastfm_credentials(
            api_key,
            api_secret,
            session_key,
            username,
            scope=scope,
            root=root,
            key=key,
            use_global=use_global,
        )
        self.lastfm_auth_row.set_connected(username)

    @pyqtSlot()
    def _on_lastfm_validate_result(self):
        """Called on main thread after Last.fm session validation."""
        pending = self._pending_lastfm_result
        api_key, api_secret, session_key, username, scope, root, key, use_global = pending
        self.lastfm_auth_row.save_btn.setEnabled(True)
        self.lastfm_auth_row.save_btn.setText("Connect")

        if not username:
            self.lastfm_auth_row.set_error("Invalid session or credentials")
            return

        self._save_lastfm_credentials(
            api_key,
            api_secret,
            session_key,
            username,
            scope=scope,
            root=root,
            key=key,
            use_global=use_global,
        )

        self.lastfm_auth_row.set_connected(username)