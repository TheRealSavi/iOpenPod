"""Music and all-media scope controls for the iPod Tracks page."""

from PySide6.QtCore import QEvent, Signal
from PySide6.QtWidgets import QWidget

from iOpenPod.GUI.widgets.icon_segmented_control import IconSegmentedControl
from iOpenPod.GUI.widgets.themed_buttons import IconButton


class TrackMediaSwitch(IconSegmentedControl):
    """Keep exactly one media scope selected using the browser's view styling."""

    allMediaChanged = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        music = IconButton("music", "", checkable=True)
        all_media = IconButton("all-media", "", checkable=True)
        super().__init__((music, all_media), parent)
        self.setObjectName("tracksMediaScope")
        self._music = music
        self._music.setObjectName("tracksMusicOnly")
        self._all_media = all_media
        self._all_media.setObjectName("tracksAllMedia")
        self._all_media.toggled.connect(self.allMediaChanged.emit)
        self.retranslate_ui()

    def set_all_media(self, enabled: bool) -> None:
        """Select a scope and notify the page when it changes."""
        (self._all_media if enabled else self._music).setChecked(True)

    def retranslate_ui(self) -> None:
        self.setAccessibleName(self.tr("Track media types"))
        self._music.setAccessibleName(self.tr("Music only"))
        self._music.setToolTip(self.tr("Show music only"))
        self._all_media.setAccessibleName(self.tr("All media"))
        self._all_media.setToolTip(self.tr("Show all media types"))

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)
