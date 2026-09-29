"""Shared progress and action controls for active application statuses."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QProgressBar,
    QSizePolicy,
    QToolButton,
    QWidget,
)

from iOpenPod.app.core.status import ApplicationStatus, StatusMessage, StatusProgress
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT

_PROGRESS_SCALE = 10_000


class StatusControls(QWidget):
    """Render one status's optional progress and action in either status view."""

    def __init__(
        self, status: ApplicationStatus, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._status = status
        self._source = ""
        self._action_key = ""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(LAYOUT.space_xs)
        self.progress = QProgressBar(self)
        self.progress.setObjectName("sharedStatusProgress")
        self.progress.setFormat("%p%")
        self.progress.hide()
        layout.addWidget(self.progress)
        self.action = QToolButton(self)
        self.action.setObjectName("sharedStatusAction")
        self.action.setCursor(Qt.CursorShape.PointingHandCursor)
        self.action.clicked.connect(self._request_action)
        self.action.hide()
        layout.addWidget(self.action)
        self.hide()

    def set_status(self, value: StatusMessage | None) -> None:
        self._source = value.source if value is not None else ""
        self.setProperty("statusSource", self._source)
        progress = value.progress if value is not None else None
        action = value.action if value is not None else None
        if progress is None:
            self.progress.hide()
            self.progress.setToolTip("")
        else:
            self._set_progress(progress)
            self.progress.setAccessibleName(value.message if value is not None else "")
            self.progress.show()
        if action is None:
            self._action_key = ""
            self.action.hide()
        else:
            self._action_key = action.key
            self.action.setText(action.label)
            self.action.setAccessibleName(action.label)
            self.action.show()
        self.setVisible(progress is not None or action is not None)

    def _set_progress(self, value: StatusProgress) -> None:
        if value.total:
            self.progress.setRange(0, _PROGRESS_SCALE)
            self.progress.setValue(
                min(_PROGRESS_SCALE, value.current * _PROGRESS_SCALE // value.total)
            )
            self.progress.setTextVisible(True)
        else:
            self.progress.setRange(0, 0)
            self.progress.setTextVisible(False)
        self.progress.setToolTip(value.detail)

    def _request_action(self) -> None:
        self._status.request_action(self._source, self._action_key)


class StatusBarControls(StatusControls):
    """Follow the status whose text is currently shown in the global bar."""

    def __init__(
        self, status: ApplicationStatus, parent: QWidget | None = None
    ) -> None:
        super().__init__(status, parent)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        status.currentStatusChanged.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        self.set_status(self._status.current_status)
