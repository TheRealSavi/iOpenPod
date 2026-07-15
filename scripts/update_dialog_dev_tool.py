# ruff: noqa: E402

from __future__ import annotations

import sys
from typing import cast

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from iopenpod.gui.auto_updater import RELEASES_URL, InstallMethod, UpdateResult
from iopenpod.gui.styles import FONT_FAMILY, Colors, Metrics, button_css
from iopenpod.gui.widgets.updateDialog import UpdateAvailableDialog, UpdateStatusDialog

MethodChoice = InstallMethod | None


METHOD_CHOICES: tuple[tuple[str, MethodChoice], ...] = (
    ("Auto-detect current process", None),
    (
        "Source checkout",
        InstallMethod(
            "source_checkout",
            "Source checkout",
            "Pull the latest source and sync the development environment.",
        ),
    ),
    (
        "uv tool install",
        InstallMethod(
            "uv_tool",
            "uv tool install",
            "Update iOpenPod with uv from a terminal.",
        ),
    ),
    (
        "pipx",
        InstallMethod(
            "pipx",
            "pipx",
            "Update iOpenPod with pipx from a terminal.",
        ),
    ),
    (
        "Python virtual environment",
        InstallMethod(
            "pip_virtualenv",
            "Python virtual environment",
            "Upgrade iOpenPod inside the same virtual environment.",
        ),
    ),
    (
        "Python package",
        InstallMethod(
            "pip",
            "Python package",
            "Upgrade iOpenPod with the Python that launched the app.",
        ),
    ),
    (
        "macOS app",
        InstallMethod(
            "native_macos_app",
            "macOS app",
            "Use the built-in updater or download the latest macOS zip.",
        ),
    ),
    (
        "Windows native build",
        InstallMethod(
            "native_windows",
            "Windows native build",
            "Use the built-in updater or download the latest Windows zip.",
        ),
    ),
    (
        "Linux native archive",
        InstallMethod(
            "native_linux_archive",
            "Linux native archive",
            "Use the built-in updater for extracted release folders.",
        ),
    ),
    (
        "Linux AppImage",
        InstallMethod(
            "native_appimage",
            "Linux AppImage",
            "Replace the AppImage file with the new release asset.",
        ),
    ),
    (
        "Native build",
        InstallMethod(
            "native_binary",
            "Native build",
            "Use the matching release asset for your platform.",
        ),
    ),
)


PLATFORM_CHOICES: tuple[tuple[str, str], ...] = (
    (f"Current ({sys.platform})", sys.platform),
    ("macOS", "darwin"),
    ("Windows", "win32"),
    ("Linux", "linux"),
    ("Other", "other"),
)


def _sample_release_notes() -> str:
    return "\n".join(
        (
            "## Changes",
            "",
            "- Improved install-specific update instructions.",
            "- Added clearer release-note handling.",
            "- Tightened resize behavior in the update dialogs.",
        )
    )


def _asset_name(platform: str, method: MethodChoice) -> str:
    if method is not None and method.kind == "native_appimage":
        return "iOpenPod-Linux-x86_64.AppImage"
    if platform == "darwin":
        return "iOpenPod-macOS.zip"
    if platform == "win32":
        return "iOpenPod-Windows.zip"
    if platform == "linux":
        return "iOpenPod-Linux.tar.gz"
    return "iOpenPod-Release.zip"


class UpdateDialogDevTool(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._open_dialogs: list[QDialog] = []

        self.setWindowTitle("Update Dialog Dev Tool")
        self.setMinimumSize(560, 640)
        self.setStyleSheet(f"QWidget {{ background: {Colors.DIALOG_BG}; color: {Colors.TEXT_PRIMARY}; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        title = QLabel("Update Dialog Dev Tool")
        title.setFont(QFont(FONT_FAMILY, Metrics.FONT_PAGE_TITLE, QFont.Weight.DemiBold))
        title.setStyleSheet("background: transparent; border: none;")
        root.addWidget(title)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)
        root.addLayout(form, 1)

        self.state_combo = QComboBox()
        self.state_combo.addItem("Update available", "available")
        self.state_combo.addItem("Up to date", "up_to_date")
        self.state_combo.addItem("Error", "error")
        self.state_combo.currentIndexChanged.connect(self._sync_controls)
        form.addRow("Dialog", self.state_combo)

        self.platform_combo = QComboBox()
        for label, value in PLATFORM_CHOICES:
            self.platform_combo.addItem(label, value)
        form.addRow("Platform", self.platform_combo)

        self.method_combo = QComboBox()
        for label, method in METHOD_CHOICES:
            self.method_combo.addItem(label, method)
        self.method_combo.setCurrentIndex(1)
        form.addRow("Install method", self.method_combo)

        self.current_version = QLineEdit("1.0.64")
        form.addRow("Current version", self.current_version)

        self.latest_version = QLineEdit("1.0.65")
        form.addRow("Latest version", self.latest_version)

        self.download_available = QCheckBox("Release asset available")
        self.download_available.setChecked(True)
        self.download_available.toggled.connect(self._sync_controls)
        form.addRow("", self.download_available)

        self.download_url = QLineEdit()
        self.download_url.setPlaceholderText("Generated from platform when empty")
        form.addRow("Download URL", self.download_url)

        self.release_page = QLineEdit(RELEASES_URL)
        form.addRow("Release page", self.release_page)

        size_row = QHBoxLayout()
        size_row.setContentsMargins(0, 0, 0, 0)
        size_row.setSpacing(8)
        self.preview_width = QSpinBox()
        self.preview_width.setRange(520, 1400)
        self.preview_width.setValue(760)
        self.preview_width.setSuffix(" px")
        self.preview_height = QSpinBox()
        self.preview_height.setRange(360, 1100)
        self.preview_height.setValue(620)
        self.preview_height.setSuffix(" px")
        size_row.addWidget(self.preview_width)
        size_row.addWidget(QLabel("x"))
        size_row.addWidget(self.preview_height)
        size_row.addStretch(1)
        form.addRow("Initial size", size_row)

        self.error_text = QPlainTextEdit("GitHub Releases could not be reached.")
        self.error_text.setFixedHeight(76)
        form.addRow("Error text", self.error_text)

        self.release_notes = QPlainTextEdit(_sample_release_notes())
        self.release_notes.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.release_notes.setMinimumHeight(150)
        form.addRow("Release notes", self.release_notes)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.addStretch(1)

        preview_btn = QPushButton("Preview Dialog")
        preview_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        preview_btn.setStyleSheet(button_css("primary", "md"))
        preview_btn.clicked.connect(self._preview_dialog)
        footer.addWidget(preview_btn)
        root.addLayout(footer)

        self._sync_controls()

    def _sync_controls(self) -> None:
        state = cast(str, self.state_combo.currentData())
        is_available = state == "available"
        is_error = state == "error"

        self.latest_version.setEnabled(is_available)
        self.download_available.setEnabled(is_available)
        self.download_url.setEnabled(is_available and self.download_available.isChecked())
        self.release_notes.setEnabled(is_available)
        self.error_text.setEnabled(is_error)

    def _build_result(self) -> UpdateResult:
        state = cast(str, self.state_combo.currentData())
        method = cast(MethodChoice, self.method_combo.currentData())
        platform = cast(str, self.platform_combo.currentData())

        download_url = ""
        if state == "available" and self.download_available.isChecked():
            download_url = self.download_url.text().strip()
            if not download_url:
                download_url = f"https://example.test/{_asset_name(platform, method)}"

        latest_version = self.latest_version.text().strip()
        if state != "available":
            latest_version = self.current_version.text().strip()

        error = ""
        if state == "error":
            error = self.error_text.toPlainText().strip() or "Update check failed."

        return UpdateResult(
            update_available=state == "available",
            current_version=self.current_version.text().strip(),
            latest_version=latest_version,
            download_url=download_url,
            release_notes=self.release_notes.toPlainText(),
            release_page=self.release_page.text().strip() or RELEASES_URL,
            error=error,
        )

    def _preview_dialog(self) -> None:
        state = cast(str, self.state_combo.currentData())
        method = cast(MethodChoice, self.method_combo.currentData())
        platform = cast(str, self.platform_combo.currentData())
        result = self._build_result()

        if state == "available":
            dialog: QDialog = UpdateAvailableDialog(
                result,
                self,
                method=method,
                platform=platform,
            )
        else:
            dialog = UpdateStatusDialog(
                result,
                self,
                method=method,
                platform=platform,
            )

        dialog.setModal(False)
        dialog.resize(self.preview_width.value(), self.preview_height.value())
        dialog.finished.connect(lambda _code, preview=dialog: self._forget_dialog(preview))
        self._open_dialogs.append(dialog)
        dialog.show()

    def _forget_dialog(self, dialog: QDialog) -> None:
        if dialog in self._open_dialogs:
            self._open_dialogs.remove(dialog)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    smoke_test = "--smoke-test" in args
    if smoke_test:
        args.remove("--smoke-test")

    app = QApplication.instance()
    if app is None:
        app = QApplication([sys.argv[0], *args])

    tool = UpdateDialogDevTool()
    tool.show()

    if smoke_test:
        app.processEvents()
        tool.close()
        return 0

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
