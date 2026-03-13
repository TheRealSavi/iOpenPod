"""
Settings page widget for iOpenPod.

macOS Ventura-style two-panel layout: fixed sidebar with navigation items
on the left, scrollable card-based content on the right.
"""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal, pyqtSlot, Qt, QUrl

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QComboBox, QFrame, QScrollArea, QFileDialog,
    QLineEdit, QStackedWidget, QProgressDialog,
)
from PyQt6.QtGui import QFont, QDesktopServices
from pathlib import Path
from ..styles import (
    Colors, FONT_FAMILY, Metrics, btn_css, scrollbar_css,
    sidebar_nav_css, sidebar_nav_selected_css,
)


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
                background: {Colors.BORDER};
                border: 1px solid {Colors.SURFACE_ACTIVE};
            }}
            QCheckBox::indicator:checked {{
                background: {Colors.ACCENT};
                border: 1px solid {Colors.ACCENT};
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
        self.combo.setFixedWidth((130))
        self.combo.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        self.combo.setStyleSheet(f"""
            QComboBox {{
                background: {Colors.SURFACE_RAISED};
                border: 1px solid {Colors.BORDER};
                border-radius: {Metrics.BORDER_RADIUS_SM}px;
                color: {Colors.TEXT_PRIMARY};
                padding: {(5)}px {(10)}px;
            }}
            QComboBox:hover {{
                border: 1px solid {Colors.BORDER_FOCUS};
            }}
            QComboBox::drop-down {{
                border: none;
                width: {(22)}px;
            }}
            QComboBox::down-arrow {{
                image: none;
                border: none;
            }}
            QComboBox QAbstractItemView {{
                background: {Colors.DROPDOWN_BG};
                color: {Colors.TEXT_PRIMARY};
                selection-background-color: {Colors.ACCENT};
                border: 1px solid {Colors.BORDER};
                border-radius: 4px;
                padding: 2px;
                outline: none;
            }}
        """)
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


class FolderRow(SettingRow):
    """Setting row with folder path display and browse button."""

    changed = pyqtSignal(str)

    def __init__(self, title: str, description: str = "", path: str = ""):
        super().__init__(title, description)

        right_layout = QHBoxLayout()
        right_layout.setSpacing((8))

        self.path_label = QLabel(self._truncate(path) if path else "Not set")
        self.path_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.path_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; background: transparent; border: none;")
        self.path_label.setMinimumWidth((120))
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

    def _truncate(self, path: str) -> str:
        if len(path) > 40:
            return "…" + path[-38:]
        return path

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Select Folder", self._full_path,
            QFileDialog.Option.ShowDirsOnly,
        )
        if folder:
            self._full_path = folder
            self.path_label.setText(self._truncate(folder))
            self.changed.emit(folder)

    @property
    def value(self) -> str:
        return self._full_path

    @value.setter
    def value(self, v: str):
        self._full_path = v
        self.path_label.setText(self._truncate(v) if v else "Not set")


class ActionRow(SettingRow):
    """Setting row with an action button."""

    clicked = pyqtSignal()

    def __init__(self, title: str, description: str = "", button_text: str = "Run"):
        super().__init__(title, description)

        self.action_btn = QPushButton(button_text)
        self.action_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.action_btn.setFixedWidth((100))
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
        right_layout.setSpacing((8))

        self.path_label = QLabel(self._truncate(path) if path else "Auto-detect")
        self.path_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.path_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; background: transparent; border: none;")
        self.path_label.setMinimumWidth((120))
        self.path_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        right_layout.addWidget(self.path_label)

        self.browse_btn = QPushButton("Browse…")
        self.browse_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.browse_btn.setFixedWidth((80))
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
        self.clear_btn.setFixedWidth((28))
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

        right_layout = QHBoxLayout()
        right_layout.setSpacing((8))

        self.status_label = QLabel("Checking…")
        self.status_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.status_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; background: transparent; border: none;")
        right_layout.addWidget(self.status_label)

        self.download_btn = QPushButton("Download")
        self.download_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.download_btn.setFixedWidth((90))
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
            link_btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    border: none;
                    color: {Colors.ACCENT};
                    padding: 0;
                    text-align: left;
                }}
                QPushButton:hover {{ color: {Colors.ACCENT_LIGHT}; text-decoration: underline; }}
            """)
            link_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(link_url)))
            # Insert into the left-side text layout (after title + description)
            self._text_layout.addWidget(link_btn)

        right_layout = QHBoxLayout()
        right_layout.setSpacing((8))

        self.status_label = QLabel("")
        self.status_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.status_label.setStyleSheet(
            f"color: {Colors.TEXT_SECONDARY}; background: transparent; border: none;"
        )
        right_layout.addWidget(self.status_label)

        self.token_input = QLineEdit()
        self.token_input.setPlaceholderText("Paste token here…")
        self.token_input.setFixedWidth((220))
        self.token_input.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.token_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_input.setStyleSheet(f"""
            QLineEdit {{
                background: {Colors.SURFACE_RAISED};
                border: 1px solid {Colors.BORDER};
                border-radius: {Metrics.BORDER_RADIUS_SM}px;
                color: {Colors.TEXT_PRIMARY};
                padding: {(5)}px {(8)}px;
            }}
            QLineEdit:focus {{
                border: 1px solid {Colors.BORDER_FOCUS};
            }}
        """)
        right_layout.addWidget(self.token_input)

        self.save_btn = QPushButton("Connect")
        self.save_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.save_btn.setFixedWidth((80))
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
        self.clear_btn.setFixedWidth((28))
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


# ── Card container ──────────────────────────────────────────────────────────

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

        for i, row in enumerate(rows):
            if i > 0:
                sep = QFrame()
                sep.setFixedHeight(1)
                sep.setStyleSheet(
                    f"background: {Colors.BORDER_SUBTLE}; border: none;"
                )
                lay.addWidget(sep)

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


# ── Main settings page ─────────────────────────────────────────────────────

class SettingsPage(QWidget):
    """Two-panel settings view inspired by macOS Ventura System Settings."""

    closed = pyqtSignal()  # Emitted when user closes settings
    theme_changed = pyqtSignal()  # Emitted when theme or contrast changes

    def __init__(self):
        super().__init__()
        self._pending_lb_result: tuple[str, str] = ("", "")
        self._update_checker: object | None = None
        self._update_downloader: object | None = None
        self._update_progress: QProgressDialog | None = None

        main = QHBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)

        # ── Sidebar ─────────────────────────────────────────────────────────
        main.addWidget(self._build_sidebar())

        # ── Content stack ───────────────────────────────────────────────────
        self._stack = QStackedWidget()
        self._stack.setStyleSheet("background: transparent;")
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
        sidebar.setFixedWidth((240))
        sidebar.setStyleSheet(f"""
            QFrame#settingsSidebar {{
                background: {Colors.SURFACE};
                border-right: 1px solid {Colors.BORDER_SUBTLE};
            }}
        """)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins((16), (16), (16), (16))
        layout.setSpacing((4))

        # Back button
        back_btn = QPushButton("← Back")
        back_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_LG))
        back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        back_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                color: {Colors.ACCENT};
                padding: {(4)}px 0;
                text-align: left;
            }}
            QPushButton:hover {{ color: {Colors.ACCENT_LIGHT}; }}
        """)
        back_btn.clicked.connect(self._on_close)
        layout.addWidget(back_btn)

        # Title
        title = QLabel("Settings")
        title.setFont(QFont(FONT_FAMILY, Metrics.FONT_HERO, QFont.Weight.Bold))
        title.setStyleSheet(
            f"color: {Colors.TEXT_PRIMARY}; background: transparent; border: none;"
        )
        layout.addWidget(title)
        layout.addSpacing((12))

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

    def _select_page(self, index: int):
        """Switch visible page and update sidebar highlight."""
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
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            " QScrollArea > QWidget > QWidget { background: transparent; }"
            + scrollbar_css()
        )

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
        layout.addSpacing((20))

        for item in items:
            if isinstance(item, str):
                lbl = QLabel(item.upper())
                lbl.setFont(QFont(FONT_FAMILY, Metrics.FONT_XS, QFont.Weight.Bold))
                lbl.setStyleSheet(
                    f"color: {Colors.TEXT_TERTIARY}; background: transparent;"
                    f" border: none; padding-left: {(4)}px;"
                )
                layout.addWidget(lbl)
                layout.addSpacing((8))
            else:
                layout.addWidget(item)
                layout.addSpacing((20))

        layout.addStretch()
        scroll.setWidget(content)
        return scroll

    # ── Page builders ───────────────────────────────────────────────────────

    def _build_general_page(self) -> QScrollArea:
        self.theme_combo = ComboRow(
            "Theme",
            "Choose the color scheme for the interface. "
            "System follows your OS preference.",
            options=["Dark", "Light", "System"],
            current="Dark",
        )

        self.high_contrast = ComboRow(
            "Increased Contrast",
            "Boost text and border contrast for accessibility. "
            "System follows your OS accessibility setting.",
            options=["Off", "On", "System"],
            current="Off",
        )

        self.show_art = ToggleRow(
            "Track List Artwork",
            "Show album art thumbnails next to tracks in the list view.",
            checked=True,
        )

        from ..settings import get_version
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

        return self._make_page(
            "General",
            "Appearance",
            _SettingsCard(self.theme_combo, self.high_contrast, self.show_art),
            "About",
            _SettingsCard(self.version_row, self.bug_report_row),
        )

    def _build_sync_page(self) -> QScrollArea:
        self.music_folder = FolderRow(
            "Music Folder",
            "Default PC music library folder for sync. "
            "This is remembered between sessions.",
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
        self.rating_strategy = ComboRow(
            "Rating Conflict Strategy",
            "How to resolve rating conflicts when iPod and PC ratings differ. "
            "iPod/PC Wins uses that source (falling back to the other if zero). "
            "Highest/Lowest picks the max/min non-zero value. "
            "Average rounds to the nearest star.",
            options=["iPod Wins", "PC Wins", "Highest", "Lowest", "Average"],
            current="iPod Wins",
        )

        return self._make_page(
            "Sync",
            _SettingsCard(
                self.music_folder,
                self.write_back,
                self.compute_sound_check,
                self.rating_strategy,
            ),
        )

    def _build_transcoding_page(self) -> QScrollArea:
        self.aac_quality = ComboRow(
            "AAC Quality",
            "Quality preset for lossy transcodes (OGG, Opus, WMA → AAC). "
            "Uses the best available encoder automatically (libfdk_aac > "
            "AudioToolbox > built-in).",
            options=[
                "High (~320 kbps)",
                "Normal (~256 kbps)",
                "Compact (~128 kbps)",
                "Spoken Word (~64 kbps)",
            ],
            current="Normal (~256 kbps)",
        )
        self.prefer_lossy = ToggleRow(
            "Prefer Lossy Encoding",
            "Encode lossless sources (FLAC, WAV, AIFF) as AAC instead of "
            "ALAC. Saves iPod storage at the cost of quality.",
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
        self.sync_workers = ComboRow(
            "Parallel Workers",
            "Number of files to transcode/copy simultaneously. "
            "Auto uses your CPU core count (capped at 8). "
            "More workers = faster syncs with many transcodes.",
            options=["Auto", "1", "2", "4", "6", "8"],
            current="Auto",
        )

        return self._make_page(
            "Transcoding",
            _SettingsCard(
                self.aac_quality,
                self.prefer_lossy,
                self.video_crf,
                self.video_preset,
                self.sync_workers,
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
            "Automatically scrobble new iPod plays to ListenBrainz when "
            "you sync. Requires ListenBrainz to be connected below.",
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

        return self._make_page(
            "Scrobbling",
            _SettingsCard(
                self.scrobble_on_sync,
                self.listenbrainz_token_row,
            ),
        )

    def _build_storage_page(self) -> QScrollArea:
        self.transcode_cache_dir = FolderRow(
            "Transcode Cache",
            "Where transcoded files are cached to avoid re-encoding "
            "on future syncs. Leave empty for the default (~/iOpenPod/cache).",
        )
        self.settings_dir = FolderRow(
            "Settings Location",
            "Custom directory to store iOpenPod settings. Useful for "
            "portable setups or backups. Leave empty for the platform default.",
        )
        self.log_dir = FolderRow(
            "Log Location",
            "Where iOpenPod writes log files and crash reports. "
            "Leave empty for the default (~/iOpenPod/logs). "
            "Takes effect on next launch.",
        )
        self.reset_storage_row = ActionRow(
            "Reset to Default",
            "Clear all custom storage paths and use platform defaults.",
            button_text="Reset",
        )
        self.reset_storage_row.clicked.connect(self._reset_storage_defaults)

        return self._make_page(
            "Storage",
            _SettingsCard(
                self.transcode_cache_dir,
                self.settings_dir,
                self.log_dir,
                self.reset_storage_row,
            ),
        )

    def _build_backups_page(self) -> QScrollArea:
        self.backup_dir = FolderRow(
            "Backup Location",
            "Where full device backups are stored on your PC. "
            "Leave empty for the default (~/iOpenPod/backups).",
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

        return self._make_page(
            "Backups",
            _SettingsCard(
                self.backup_dir,
                self.backup_before_sync,
                self.max_backups,
            ),
        )

    # ── Settings I/O ────────────────────────────────────────────────────────

    def load_from_settings(self):
        """Populate UI controls from the current AppSettings."""
        from ..settings import get_settings
        s = get_settings()

        self.music_folder.value = s.music_folder
        self.write_back.value = s.write_back_to_pc
        self.compute_sound_check.value = s.compute_sound_check

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

        self.show_art.value = s.show_art_in_tracklist

        # Theme
        theme_display = {"dark": "Dark", "light": "Light", "system": "System"}
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

        self.transcode_cache_dir.value = s.transcode_cache_dir
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

        # AAC quality → combo text
        quality_map = {
            "high": "High (~320 kbps)", "normal": "Normal (~256 kbps)",
            "compact": "Compact (~128 kbps)", "spoken": "Spoken Word (~64 kbps)",
        }
        q_text = quality_map.get(s.aac_quality, "Normal (~256 kbps)")
        idx = self.aac_quality.combo.findText(q_text)
        if idx >= 0:
            self.aac_quality.combo.setCurrentIndex(idx)

        # Prefer lossy toggle
        self.prefer_lossy.value = s.prefer_lossy

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

        # Connect signals to auto-save (only once)
        if not hasattr(self, '_signals_connected'):
            self._signals_connected = True
            self.music_folder.changed.connect(self._save)
            self.write_back.changed.connect(self._save)
            self.compute_sound_check.changed.connect(self._save)
            self.rating_strategy.changed.connect(self._save)
            self.aac_quality.changed.connect(self._save)
            self.prefer_lossy.changed.connect(self._save)
            self.video_crf.changed.connect(self._save)
            self.video_preset.changed.connect(self._save)
            self.sync_workers.changed.connect(self._save)
            self.show_art.changed.connect(self._save)
            self.theme_combo.changed.connect(self._save)
            self.high_contrast.changed.connect(self._save)
            self.transcode_cache_dir.changed.connect(self._save)
            self.settings_dir.changed.connect(self._save)
            self.log_dir.changed.connect(self._save)
            self.ffmpeg_path.changed.connect(self._save_and_refresh_tools)
            self.fpcalc_path.changed.connect(self._save_and_refresh_tools)
            self.backup_dir.changed.connect(self._save)
            self.backup_before_sync.changed.connect(self._save)
            self.max_backups.changed.connect(self._save)
            self.scrobble_on_sync.changed.connect(self._save)

    def _save(self, *_args):
        """Read all controls back into AppSettings and persist."""
        from ..settings import get_settings
        s = get_settings()

        s.music_folder = self.music_folder.value
        s.write_back_to_pc = self.write_back.value
        s.compute_sound_check = self.compute_sound_check.value

        # Rating conflict strategy
        strategy_keys = {
            "iPod Wins": "ipod_wins", "PC Wins": "pc_wins",
            "Highest": "highest", "Lowest": "lowest", "Average": "average",
        }
        s.rating_conflict_strategy = strategy_keys.get(self.rating_strategy.value, "ipod_wins")

        s.scrobble_on_sync = self.scrobble_on_sync.value

        s.show_art_in_tracklist = self.show_art.value

        # Theme
        theme_keys = {"Dark": "dark", "Light": "light", "System": "system"}
        old_theme, old_hc = s.theme, s.high_contrast
        s.theme = theme_keys.get(self.theme_combo.value, "dark")

        # High contrast
        hc_keys = {"Off": "off", "On": "on", "System": "system"}
        s.high_contrast = hc_keys.get(self.high_contrast.value, "off")

        s.transcode_cache_dir = self.transcode_cache_dir.value
        s.settings_dir = self.settings_dir.value
        s.log_dir = self.log_dir.value
        s.ffmpeg_path = self.ffmpeg_path.value
        s.fpcalc_path = self.fpcalc_path.value
        s.backup_dir = self.backup_dir.value
        s.backup_before_sync = self.backup_before_sync.value

        # Parse max backups
        mb_text = self.max_backups.value
        s.max_backups = int(mb_text) if mb_text and mb_text != "Unlimited" else 0

        # Parse AAC quality preset
        quality_keys = {
            "High (~320 kbps)": "high", "Normal (~256 kbps)": "normal",
            "Compact (~128 kbps)": "compact", "Spoken Word (~64 kbps)": "spoken",
        }
        s.aac_quality = quality_keys.get(self.aac_quality.value, "normal")

        # Prefer lossy toggle
        s.prefer_lossy = self.prefer_lossy.value

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

        s.save()

        # If theme or contrast changed, apply immediately and notify
        if s.theme != old_theme or s.high_contrast != old_hc:
            Colors.apply_theme(s.theme, s.high_contrast)
            self.theme_changed.emit()

    # ── Event handlers ──────────────────────────────────────────────────────

    def _on_close(self):
        """Go back — settings are already saved on every change."""
        self.closed.emit()

    def _reset_storage_defaults(self):
        """Clear custom storage paths and revert to platform defaults."""
        self.transcode_cache_dir.value = ""
        self.settings_dir.value = ""
        self.log_dir.value = ""
        self._save()

    def _check_for_updates(self):
        """Check GitHub for a newer version in a background thread."""
        from PyQt6.QtWidgets import QMessageBox, QProgressDialog
        from GUI.auto_updater import (
            UpdateChecker, UpdateDownloader, UpdateResult,
            stage_update, launch_bootstrap_and_exit,
        )

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

            # Newer version available — ask the user
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
                # Open the release page in the browser instead
                QDesktopServices.openUrl(QUrl(result.release_page))
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

                answer2 = QMessageBox.question(
                    self, "Install Update & Restart?",
                    f"v{result.latest_version} is ready to install.\n\n"
                    "iOpenPod will close, apply the update, and "
                    "relaunch automatically.\n\n"
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
                            f"The update files are at:\n{staged}\n"
                            "You can copy them manually.",
                        )

            downloader.progress.connect(_on_progress)
            downloader.finished_download.connect(_on_finished)
            progress.canceled.connect(downloader.terminate)
            downloader.start()

        self._update_checker.result_ready.connect(_on_result)
        self._update_checker.start()

    def _save_and_refresh_tools(self, *_args):
        """Save settings then refresh tool status indicators."""
        self._save()
        self._refresh_tool_status()

    def _refresh_tool_status(self):
        """Check whether ffmpeg and fpcalc are reachable and update the UI."""
        from SyncEngine.transcoder import find_ffmpeg
        from SyncEngine.audio_fingerprint import find_fpcalc

        ffmpeg = find_ffmpeg()
        self.ffmpeg_tool.set_status(bool(ffmpeg), ffmpeg or "")

        fpcalc = find_fpcalc()
        self.fpcalc_tool.set_status(bool(fpcalc), fpcalc or "")

    def _download_ffmpeg(self):
        """Download FFmpeg in a background thread."""
        self.ffmpeg_tool.set_downloading()
        import threading

        def _do():
            from SyncEngine.dependency_manager import download_ffmpeg
            download_ffmpeg()
            from PyQt6.QtCore import QMetaObject, Qt as QtCore_Qt
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
            from PyQt6.QtCore import QMetaObject, Qt as QtCore_Qt
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

    # ── Scrobbling handlers ──────────────────────────────────────────────

    def _on_listenbrainz_token_changed(self, token: str):
        """Handle ListenBrainz token save/clear."""
        from ..settings import get_settings
        s = get_settings()

        if not token:
            # Disconnect
            s.listenbrainz_token = ""
            s.listenbrainz_username = ""
            s.save()
            return

        # Validate the token in a background thread
        self.listenbrainz_token_row.save_btn.setEnabled(False)
        self.listenbrainz_token_row.save_btn.setText("Validating…")

        import threading

        def _do_validate():
            from SyncEngine.scrobbler import listenbrainz_validate_token
            username = listenbrainz_validate_token(token)
            # Stash result so the slot can read it
            self._pending_lb_result = (token, username or "")
            from PyQt6.QtCore import QMetaObject, Qt as QtCore_Qt
            QMetaObject.invokeMethod(
                self, "_on_listenbrainz_validate_result",
                QtCore_Qt.ConnectionType.QueuedConnection,
            )

        threading.Thread(target=_do_validate, daemon=True).start()

    @pyqtSlot()
    def _on_listenbrainz_validate_result(self):
        """Called on main thread after ListenBrainz token validation."""
        token, username = self._pending_lb_result
        self.listenbrainz_token_row.save_btn.setEnabled(True)
        self.listenbrainz_token_row.save_btn.setText("Connect")

        if not username:
            self.listenbrainz_token_row.set_error("Invalid token")
            return

        from ..settings import get_settings
        s = get_settings()
        s.listenbrainz_token = token
        s.listenbrainz_username = username
        s.save()

        self.listenbrainz_token_row.set_connected(username)
