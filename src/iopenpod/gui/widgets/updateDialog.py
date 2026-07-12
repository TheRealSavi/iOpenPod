"""Update dialogs for iOpenPod."""

from __future__ import annotations

import sys

from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices, QFont
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from iopenpod.gui.auto_updater import (
    RELEASES_URL,
    InstallMethod,
    UpdateResult,
    build_update_guidance,
    detect_install_method,
)
from iopenpod.gui.styles import (
    FONT_FAMILY,
    MONO_FONT_FAMILY,
    Colors,
    Metrics,
    button_css,
    link_btn_css,
    panel_css,
)


def _plain_label(
    text: str,
    *,
    size: int = Metrics.FONT_MD,
    color: str = Colors.TEXT_SECONDARY,
    weight: QFont.Weight = QFont.Weight.Normal,
) -> QLabel:
    label = QLabel(text)
    label.setFont(QFont(FONT_FAMILY, size, weight))
    label.setWordWrap(True)
    label.setStyleSheet(f"color: {color}; background: transparent; border: none;")
    return label


def _panel(name: str) -> QFrame:
    frame = QFrame()
    frame.setObjectName(name)
    frame.setStyleSheet(
        panel_css(
            name,
            bg=Colors.SURFACE_ALT,
            border=f"1px solid {Colors.BORDER_SUBTLE}",
            radius=Metrics.BORDER_RADIUS,
        )
    )
    return frame


class _CommandPanel(QFrame):
    def __init__(self, commands: tuple[str, ...]):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setObjectName("UpdateCommandPanel")
        self.setStyleSheet(
            panel_css(
                "UpdateCommandPanel",
                bg=Colors.DIALOG_BG,
                border=f"1px solid {Colors.BORDER_SUBTLE}",
                radius=Metrics.BORDER_RADIUS_SM,
            )
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        title = _plain_label(
            "Terminal command",
            size=Metrics.FONT_SM,
            color=Colors.TEXT_TERTIARY,
            weight=QFont.Weight.DemiBold,
        )
        header.addWidget(title)
        header.addStretch(1)

        self.copy_btn = QPushButton("Copy")
        self.copy_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_btn.setStyleSheet(button_css("secondary", "sm"))
        self.copy_btn.clicked.connect(self._copy_commands)
        header.addWidget(self.copy_btn)
        layout.addLayout(header)

        self._command_text = "\n".join(commands)
        command_label = QLabel(self._command_text)
        command_label.setFont(QFont(MONO_FONT_FAMILY, Metrics.FONT_MD))
        command_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        command_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        command_label.setStyleSheet(
            f"""
            QLabel {{
                color: {Colors.TEXT_PRIMARY};
                background: transparent;
                border: none;
                line-height: 1.35;
            }}
            """
        )
        layout.addWidget(command_label)

    def _copy_commands(self) -> None:
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(self._command_text)
        self.copy_btn.setText("Copied")
        QTimer.singleShot(1400, lambda: self.copy_btn.setText("Copy"))


class UpdateAvailableDialog(QDialog):
    """Rich update-available dialog with install-specific instructions."""

    def __init__(
        self,
        result: UpdateResult,
        parent: QWidget | None = None,
        *,
        method: InstallMethod | None = None,
        platform: str = sys.platform,
    ):
        super().__init__(parent)
        self._update_result = result
        self.selected_action = "dismiss"
        self._method = detect_install_method(platform=platform) if method is None else method
        self._guidance = build_update_guidance(
            result,
            method=self._method,
            platform=platform,
        )

        self.setWindowTitle("iOpenPod Update")
        self.setModal(True)
        self.setMinimumWidth(660)
        self.setStyleSheet(f"QDialog {{ background: {Colors.DIALOG_BG}; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 22, 22, 18)
        root.setSpacing(16)

        content = QScrollArea()
        content.setObjectName("UpdateDialogContent")
        content.setWidgetResizable(True)
        content.setFrameShape(QFrame.Shape.NoFrame)
        content.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        content.setStyleSheet(
            f"""
            QScrollArea#UpdateDialogContent {{
                background: {Colors.DIALOG_BG};
                border: none;
            }}
            QScrollArea#UpdateDialogContent > QWidget > QWidget {{
                background: {Colors.DIALOG_BG};
            }}
            """
        )

        content_body = QWidget()
        content_body.setObjectName("UpdateDialogContentBody")
        content_body.setStyleSheet(f"background: {Colors.DIALOG_BG};")

        content_layout = QVBoxLayout(content_body)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(16)
        content_layout.addLayout(self._build_header(), 0)
        content_layout.addWidget(self._build_guidance_panel(), 0)
        content_layout.addWidget(self._build_notes_panel(), 1)
        content.setWidget(content_body)

        root.addWidget(content, 1)
        root.addLayout(self._build_footer(), 0)

    def _build_header(self) -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.setSpacing(8)

        eyebrow = _plain_label(
            "Update available",
            size=Metrics.FONT_SM,
            color=Colors.ACCENT,
            weight=QFont.Weight.DemiBold,
        )
        layout.addWidget(eyebrow)

        latest = self._update_result.latest_version or "new release"
        title = _plain_label(
            f"iOpenPod v{latest} is ready",
            size=Metrics.FONT_PAGE_TITLE,
            color=Colors.TEXT_PRIMARY,
            weight=QFont.Weight.DemiBold,
        )
        layout.addWidget(title)

        current = self._update_result.current_version or "unknown"
        sub = _plain_label(
            f"Installed: v{current}  |  Latest: v{latest}",
            size=Metrics.FONT_MD,
            color=Colors.TEXT_SECONDARY,
        )
        layout.addWidget(sub)
        return layout

    def _build_guidance_panel(self) -> QFrame:
        frame = _panel("UpdateGuidancePanel")
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        label = _plain_label(
            self._guidance.install_label,
            size=Metrics.FONT_XL,
            color=Colors.TEXT_PRIMARY,
            weight=QFont.Weight.DemiBold,
        )
        layout.addWidget(label)
        layout.addWidget(_plain_label(self._guidance.summary))

        for index, step in enumerate(self._guidance.steps, start=1):
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(10)

            chip = QLabel(str(index))
            chip_size = max(24, Metrics.FONT_SM * 2)
            chip.setFixedSize(chip_size, chip_size)
            chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chip.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM, QFont.Weight.DemiBold))
            chip.setStyleSheet(
                f"""
                QLabel {{
                    color: {Colors.TEXT_ON_ACCENT};
                    background: {Colors.ACCENT};
                    border: none;
                    border-radius: {chip_size // 2}px;
                }}
                """
            )
            row.addWidget(chip, alignment=Qt.AlignmentFlag.AlignTop)
            row.addWidget(_plain_label(step, color=Colors.TEXT_PRIMARY), stretch=1)
            layout.addLayout(row)

        if self._guidance.commands:
            layout.addWidget(_CommandPanel(self._guidance.commands))

        return frame

    def _build_notes_panel(self) -> QFrame:
        frame = _panel("UpdateNotesPanel")
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        layout.addWidget(
            _plain_label(
                "Release notes",
                size=Metrics.FONT_XL,
                color=Colors.TEXT_PRIMARY,
                weight=QFont.Weight.DemiBold,
            )
        )

        notes = (self._update_result.release_notes or "").strip()
        if not notes:
            notes = "No release notes were included with this release."

        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        browser.setMinimumHeight(130)
        browser.setStyleSheet(
            f"""
            QTextBrowser {{
                color: {Colors.TEXT_SECONDARY};
                background: {Colors.DIALOG_BG};
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-radius: {Metrics.BORDER_RADIUS_SM}px;
                padding: 10px;
            }}
            """
        )
        browser.setMarkdown(notes)
        layout.addWidget(browser)
        return frame

    def _build_footer(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        release_btn = QPushButton("Release Page")
        release_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        release_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        release_btn.setStyleSheet(link_btn_css())
        release_btn.clicked.connect(self._open_release_page)
        layout.addWidget(release_btn)

        layout.addStretch(1)

        later_btn = QPushButton("Later")
        later_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        later_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        later_btn.setStyleSheet(button_css("quiet", "md"))
        later_btn.clicked.connect(self.reject)
        layout.addWidget(later_btn)

        if self._guidance.can_auto_install:
            install_btn = QPushButton(self._guidance.auto_install_label)
            install_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
            install_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            install_btn.setStyleSheet(button_css("primary", "md"))
            install_btn.clicked.connect(self._select_install)
            layout.addWidget(install_btn)
        else:
            done_btn = QPushButton("Done")
            done_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
            done_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            done_btn.setStyleSheet(button_css("primary", "md"))
            done_btn.clicked.connect(self.accept)
            layout.addWidget(done_btn)

        return layout

    def _open_release_page(self) -> None:
        url = self._update_result.release_page or RELEASES_URL
        QDesktopServices.openUrl(QUrl(url))
        self.selected_action = "open_release"

    def _select_install(self) -> None:
        self.selected_action = "install"
        self.accept()


class UpdateStatusDialog(QDialog):
    """Manual update-check result dialog for up-to-date and error states."""

    def __init__(
        self,
        result: UpdateResult,
        parent: QWidget | None = None,
        *,
        method: InstallMethod | None = None,
        platform: str = sys.platform,
    ):
        super().__init__(parent)
        self._update_result = result
        method = detect_install_method(platform=platform) if method is None else method

        self.setWindowTitle("iOpenPod Updates")
        self.setModal(True)
        self.setMinimumWidth(520)
        self.setStyleSheet(f"QDialog {{ background: {Colors.DIALOG_BG}; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 22, 22, 18)
        root.setSpacing(14)

        if result.error:
            title = "Could not check for updates"
            body = result.error
            accent = Colors.WARNING
        else:
            title = "iOpenPod is up to date"
            version = result.current_version or "unknown"
            body = f"You are running v{version}. Install method: {method.label}."
            accent = Colors.SUCCESS

        root.addWidget(
            _plain_label(
                title,
                size=Metrics.FONT_PAGE_TITLE,
                color=Colors.TEXT_PRIMARY,
                weight=QFont.Weight.DemiBold,
            )
        )

        status = _panel("UpdateStatusPanel")
        status.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        status_layout = QVBoxLayout(status)
        status_layout.setContentsMargins(16, 14, 16, 14)
        status_layout.setSpacing(8)

        status_layout.addWidget(
            _plain_label(
                method.label if not result.error else "Update check",
                size=Metrics.FONT_XL,
                color=accent,
                weight=QFont.Weight.DemiBold,
            )
        )
        status_layout.addWidget(_plain_label(body, color=Colors.TEXT_PRIMARY))
        if not result.error:
            status_layout.addWidget(_plain_label(method.detail))
        root.addWidget(status, 0)
        root.addStretch(1)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(10)

        release_btn = QPushButton("Release Page")
        release_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        release_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        release_btn.setStyleSheet(link_btn_css())
        release_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(result.release_page or RELEASES_URL))
        )
        footer.addWidget(release_btn)
        footer.addStretch(1)

        close_btn = QPushButton("Close")
        close_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(button_css("primary", "md"))
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)
        root.addLayout(footer, 0)
