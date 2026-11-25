"""A welcoming entry point when no Active iPod is loaded."""

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import QLabel, QProgressBar, QVBoxLayout, QWidget

from iOpenPod.GUI.presentation.application_icon import application_pixmap
from iOpenPod.GUI.presentation.device_images import device_pixmap
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.themed_buttons import ActionButton, ActionButtonKind


class StartPage(QWidget):
    """Invite device selection through the shell's existing Device Picker."""

    chooseDeviceRequested = Signal()

    def __init__(
        self, parent: QWidget | None = None, *, theme: ThemeManager | None = None
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._loading_name: str | None = None
        self._device_image = ""
        self.setObjectName("startPage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg
        )
        layout.setSpacing(LAYOUT.space_md)
        layout.addStretch()

        self._logo = QLabel(self)
        self._logo.setObjectName("startLogo")
        self._logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._refresh_logo()
        if theme is not None:
            theme.deviceArtworkChanged.connect(self._refresh_logo)
        layout.addWidget(self._logo)

        self._title = QLabel(self)
        self._title.setObjectName("startTitle")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title.setTextFormat(Qt.TextFormat.PlainText)
        self._title.setWordWrap(True)
        layout.addWidget(self._title)

        self._description = QLabel(self)
        self._description.setObjectName("startDescription")
        self._description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._description.setWordWrap(True)
        layout.addWidget(self._description)

        self._choose = ActionButton(
            self.tr("Choose Device"), self, kind=ActionButtonKind.PRIMARY
        )
        self._choose.setObjectName("startChooseDevice")
        self._choose.setMinimumSize(
            LAYOUT.start_action_width, LAYOUT.control_height_large
        )
        self._choose.clicked.connect(self.chooseDeviceRequested)
        layout.addWidget(self._choose, 0, Qt.AlignmentFlag.AlignHCenter)
        self._progress = QProgressBar(self)
        self._progress.setObjectName("deviceLoadingProgress")
        self._progress.setRange(0, 0)
        self._progress.setTextVisible(False)
        self._progress.setFixedWidth(LAYOUT.start_action_width)
        self._progress.hide()
        layout.addWidget(self._progress, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch()
        self.setFocusProxy(self._choose)
        self.retranslate_ui()

    def set_busy(self, busy: bool) -> None:
        """Match navigation's device-selection availability."""
        self._choose.setEnabled(not busy)

    def set_loading_device(
        self, name: str | None, image_name: str = "iPodGeneric.png"
    ) -> None:
        self._loading_name = name
        self._device_image = image_name
        self._description.setVisible(name is None)
        self._choose.setVisible(name is None)
        self._progress.setVisible(name is not None)
        self._refresh_logo()
        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        if self._loading_name is not None:
            title = self.tr("Loading %1…").replace("%1", self._loading_name)
            self._title.setText(title)
            self._progress.setAccessibleName(title)
            return
        self._title.setText(self.tr("Welcome to iOpenPod"))
        self._description.setText(
            self.tr("Connect your iPod, then click Choose Device to get started.")
        )
        self._choose.setText(self.tr("Choose Device"))

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        elif event.type() == QEvent.Type.DevicePixelRatioChange:
            self._refresh_logo()
        super().changeEvent(event)

    def _refresh_logo(self) -> None:
        size, dpr = LAYOUT.start_logo_size, self.devicePixelRatioF()
        pixmap = (
            application_pixmap(size, dpr)
            if self._loading_name is None
            else device_pixmap(
                self._device_image,
                size,
                dpr,
                itunes_107=self._theme is not None and self._theme.itunes_107_artwork,
            )
        )
        self._logo.setPixmap(pixmap)
