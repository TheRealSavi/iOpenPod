"""Explain and explicitly start the optional, per-user Phase download."""

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QResizeEvent, QShowEvent
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.phase_runtime_controller import PhaseRuntimeController
from iOpenPod.GUI.presentation.i18n.workflow import workflow_text
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.themed_buttons import (
    ActionButtonKind,
    apply_action_button_kind,
)


class PhaseRuntimeSetupDialog(QDialog):
    def __init__(
        self,
        controller: PhaseRuntimeController,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self.setObjectName("phaseRuntimeSetup")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(620, 330)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg
        )
        self._description = QLabel(self)
        self._description.setWordWrap(True)
        layout.addWidget(self._description)
        self._availability = QLabel(self)
        self._availability.setObjectName("phaseRuntimeAvailability")
        self._availability.setWordWrap(True)
        self._availability.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._availability)
        self._status = QLabel(self)
        self._status.setObjectName("phaseRuntimeStatus")
        self._status.setWordWrap(True)
        self._status.setTextFormat(Qt.TextFormat.PlainText)
        self._status.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self._status)
        self._details = QPlainTextEdit(self)
        self._details.setObjectName("phaseRuntimeDetails")
        self._details.setReadOnly(True)
        self._details.setMaximumBlockCount(100)
        layout.addWidget(self._details)
        self._progress = QProgressBar(self)
        self._progress.setRange(0, 0)
        layout.addWidget(self._progress)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        self._close = buttons.button(QDialogButtonBox.StandardButton.Close)
        self._close.setAutoDefault(False)
        self._install = buttons.addButton("", QDialogButtonBox.ButtonRole.ActionRole)
        self._install.setObjectName("installPhaseRuntime")
        self._install.setAutoDefault(False)
        apply_action_button_kind(self._install, ActionButtonKind.PRIMARY)
        self._install.clicked.connect(controller.install)
        self._cancel = buttons.addButton("", QDialogButtonBox.ButtonRole.ActionRole)
        self._cancel.setObjectName("cancelPhaseRuntime")
        self._cancel.setAutoDefault(False)
        apply_action_button_kind(self._cancel, ActionButtonKind.SECONDARY)
        self._cancel.clicked.connect(controller.cancel)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        controller.changed.connect(self._render)
        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        self.setWindowTitle(self.tr("Set Up Phase Analysis"))
        self._description.setText(
            self.tr(
                "Acoustic analysis is included with iOpenPod. Optional instrument analysis "
                "can help Phase follow vocals, instruments, and recurring musical phrases.\n\n"
                "Download it here to use it on this computer. Setup needs internet access, "
                "and the download and installed files can use several gigabytes of disk space. "
                "Acoustic analysis remains available if you skip or cancel setup."
            )
        )
        self._cancel.setText(self.tr("Cancel Setup"))
        self._details.setAccessibleName(self.tr("Setup error details"))
        self._render()

    def _render(self) -> None:
        controller = self._controller
        self._availability.setText(workflow_text(controller.availability))
        self._status.setText(workflow_text(controller.message))
        self._status.setVisible(bool(controller.message))
        self._details.setPlainText(workflow_text(controller.details))
        self._details.setVisible(bool(controller.details))
        self._install.setText(
            self.tr("Download and Reinstall")
            if controller.installed
            else self.tr("Download and Install")
        )
        self._install.setEnabled(controller.can_install and not controller.busy)
        self._install.setVisible(not controller.busy)
        self._cancel.setVisible(controller.busy)
        self._cancel.setEnabled(controller.busy and not controller.cancelling)
        self._close.setEnabled(not controller.busy)
        self._progress.setVisible(controller.busy)
        for button in (self._install, self._cancel):
            button.setMinimumWidth(
                button.fontMetrics().horizontalAdvance(button.text())
                + 2 * LAYOUT.space_lg
            )
        self._fit_content_height()

    def _fit_content_height(self) -> None:
        layout = self.layout()
        if layout is not None:
            # Wrapped explanations must remain readable when errors appear or
            # translations and narrower windows require more lines.
            required = layout.totalHeightForWidth(self.width())
            if required > self.height():
                self.resize(self.width(), required)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._fit_content_height()

    def showEvent(self, event: QShowEvent) -> None:
        self._controller.refresh()
        super().showEvent(event)

    def reject(self) -> None:
        if self._controller.busy:
            self._controller.cancel()
            return
        super().reject()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)
