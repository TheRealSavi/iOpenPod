"""A bounded, selectable report surface for manual scrobbling results."""

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.scrobbling.models import ScrobbleResult
from iOpenPod.GUI.widgets.themed_buttons import (
    ActionButtonKind,
    apply_action_button_kind,
)


class ScrobbleReportDialog(QDialog):
    def __init__(self, result: ScrobbleResult, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("scrobbleReport")
        self.setWindowTitle(self.tr("Scrobbling report"))
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(820, 520)
        screen = self.screen().availableGeometry()
        self.resize(
            min(self.width(), screen.width() - 40),
            min(self.height(), screen.height() - 80),
        )
        layout = QVBoxLayout(self)
        self._text = QPlainTextEdit(self)
        self._text.setObjectName("scrobbleReportText")
        self._text.setReadOnly(True)
        parts = [result.summary, *result.notices, *result.issues]
        if result.cancelled:
            parts.insert(
                0,
                QCoreApplication.translate(
                    "ScrobbleController",
                    "Scrobbling cancelled. Pending listens are saved.",
                ),
            )
        self._text.setPlainText("\n\n".join(parts))
        layout.addWidget(self._text)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        copy = buttons.addButton(
            self.tr("Copy report"), QDialogButtonBox.ButtonRole.ActionRole
        )
        apply_action_button_kind(copy, ActionButtonKind.PRIMARY)
        apply_action_button_kind(
            buttons.button(QDialogButtonBox.StandardButton.Close),
            ActionButtonKind.SECONDARY,
        )
        copy.clicked.connect(self._copy_report)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)

    def _copy_report(self) -> None:
        QApplication.clipboard().setText(self._text.toPlainText())


def show_scrobble_report(result: ScrobbleResult, parent: QWidget) -> None:
    existing = parent.findChild(ScrobbleReportDialog, "scrobbleReport")
    if existing is not None:
        existing.close()
    ScrobbleReportDialog(result, parent).show()
