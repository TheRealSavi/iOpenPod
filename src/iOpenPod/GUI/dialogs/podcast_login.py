"""Password entry shared by Podcast discovery and existing Subscriptions."""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.podcasts.controller import (
    PodcastController,
    PodcastOperation,
    PodcastOperationFailure,
)
from iOpenPod.app.podcasts.credentials import PodcastCredentials
from iOpenPod.app.podcasts.errors import PodcastFeedError
from iOpenPod.GUI.presentation.i18n.workflow import workflow_text
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.themed_buttons import (
    ActionButtonKind,
    apply_action_button_kind,
)


class PodcastLoginFields(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.username = QLineEdit(self)
        self.username.setObjectName("podcastUsername")
        self.username.setMinimumHeight(LAYOUT.control_height)
        self.password = QLineEdit(self)
        self.password.setObjectName("podcastPassword")
        self.password.setMinimumHeight(LAYOUT.control_height)
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setInputMethodHints(
            Qt.InputMethodHint.ImhSensitiveData | Qt.InputMethodHint.ImhNoPredictiveText
        )
        self.remember = QCheckBox(self)
        self.remember.setObjectName("podcastRememberLogin")
        self.remember.setChecked(True)
        self._username_label = QLabel(self)
        self._password_label = QLabel(self)
        self._username_label.setBuddy(self.username)
        self._password_label.setBuddy(self.password)
        self._detail = QLabel(self)
        self._detail.setWordWrap(True)
        layout = QFormLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setVerticalSpacing(LAYOUT.space_xs)
        layout.addRow(self._username_label, self.username)
        layout.addRow(self._password_label, self.password)
        layout.addRow(self.remember)
        layout.addRow(self._detail)
        self.retranslate_ui()

    def credentials(self) -> PodcastCredentials:
        return PodcastCredentials(self.username.text(), self.password.text())

    def clear(self) -> None:
        self.username.clear()
        self.password.clear()

    def retranslate_ui(self) -> None:
        self._username_label.setText(self.tr("Username"))
        self._password_label.setText(self.tr("Password"))
        self.remember.setText(self.tr("Remember on this computer"))
        self._detail.setText(
            self.tr(
                "Saved logins stay in your computer's credential store, never on the iPod. Without remembering, this login lasts until iOpenPod closes."
            )
        )

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)


class PodcastLoginDialog(QDialog):
    def __init__(
        self,
        controller: PodcastController,
        subscription_id: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setObjectName("podcastLoginDialog")
        self.setMinimumWidth(440)
        self._controller = controller
        self._subscription_id = subscription_id
        self._pending = False
        self._fields = PodcastLoginFields(self)
        self._title = QLabel(self)
        self._title.setObjectName("dialogTitle")
        self._title.setWordWrap(True)
        self._title.setTextFormat(Qt.TextFormat.PlainText)
        subscription = controller.snapshot.subscription(subscription_id)
        self._title.setText(subscription.title if subscription else "")
        self._status = QLabel(self)
        self._status.setWordWrap(True)
        self._status.setTextFormat(Qt.TextFormat.PlainText)
        self._buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel, self)
        self._save = self._buttons.addButton("", QDialogButtonBox.ButtonRole.ActionRole)
        self._save.setObjectName("podcastSaveLogin")
        self._save.setDefault(True)
        apply_action_button_kind(self._save, ActionButtonKind.PRIMARY)
        self._forget = self._buttons.addButton(
            "", QDialogButtonBox.ButtonRole.ActionRole
        )
        self._forget.setObjectName("podcastForgetLogin")
        apply_action_button_kind(self._forget, ActionButtonKind.QUIET)
        self._save.clicked.connect(self._save_login)
        self._forget.clicked.connect(self._forget_login)
        self._buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg
        )
        layout.setSpacing(LAYOUT.space_sm)
        for widget in (self._title, self._fields, self._status):
            layout.addWidget(widget)
        layout.addStretch(1)
        layout.addWidget(self._buttons)
        controller.operationFailed.connect(self._failed)
        controller.operationSucceeded.connect(self._succeeded)
        controller.changed.connect(self._availability_changed)
        self.finished.connect(self._clear)
        self.retranslate_ui()
        self._availability_changed()

    def retranslate_ui(self) -> None:
        self.setWindowTitle(self.tr("Podcast Login"))
        self._save.setText(self.tr("Verify Login"))
        self._forget.setText(self.tr("Forget Login"))
        self._forget.setToolTip(
            self.tr("Remove this feed's saved and temporary login from this computer.")
        )

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

    def _save_login(self) -> None:
        if not self._controller.can_edit:
            return
        try:
            credentials = self._fields.credentials()
        except PodcastFeedError as error:
            self._status.setText(workflow_text(str(error)))
            return
        self._pending = True
        self._status.setText(self.tr("Checking login…"))
        self._controller.set_login(
            self._subscription_id,
            credentials,
            remember=self._fields.remember.isChecked(),
        )

    def _forget_login(self) -> None:
        self._pending = True
        self._controller.forget_login(self._subscription_id)

    def _failed(self, value: object) -> None:
        if (
            self._pending
            and isinstance(value, PodcastOperationFailure)
            and value.operation is PodcastOperation.LOGIN
        ):
            self._pending = False
            self._status.setText(workflow_text(value.message))

    def _succeeded(self, operation: object) -> None:
        if self._pending and operation is PodcastOperation.LOGIN:
            self.accept()

    def _availability_changed(self) -> None:
        if self._controller.snapshot.subscription(self._subscription_id) is None:
            self.reject()
            return
        self._fields.setEnabled(self._controller.can_edit)
        self._save.setEnabled(self._controller.can_edit)
        self._forget.setEnabled(self._controller.can_edit)

    def _clear(self, _result: int) -> None:
        self._pending = False
        self._fields.clear()
