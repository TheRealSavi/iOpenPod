"""Shared Track volume slider with native steps and a magnetic zero point."""

from PySide6.QtCore import QCoreApplication, QEvent, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSlider, QVBoxLayout, QWidget

_ZERO_MAGNET_THRESHOLD = 12


class VolumeAdjustment(QWidget):
    """Preview drags and emit explicit selections, including a mixed-value zero."""

    valueEdited = Signal(int)

    def __init__(self, value: int | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("volumeAdjustmentWidget")
        self.setMinimumWidth(230)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)
        self._value_label = QLabel(self)
        self._value_label.setObjectName("volumeAdjustmentValueLabel")
        self._value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._value_label)

        self.slider = QSlider(Qt.Orientation.Horizontal, self)
        self.slider.setObjectName("volumeAdjustmentSlider")
        self.slider.setRange(-255, 255)
        self.slider.setSingleStep(1)
        self.slider.setPageStep(16)
        self.slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.slider.setTickInterval(64)
        self.slider.setTracking(False)
        self.setFocusProxy(self.slider)
        layout.addWidget(self.slider)

        scale = QHBoxLayout()
        scale.setContentsMargins(0, 0, 0, 0)
        scale.setSpacing(6)
        for text, alignment, stretch in (
            ("\N{MINUS SIGN}100%", Qt.AlignmentFlag.AlignLeft, 0),
            ("0%", Qt.AlignmentFlag.AlignCenter, 1),
            ("+100%", Qt.AlignmentFlag.AlignRight, 0),
        ):
            label = QLabel(text, self)
            label.setAlignment(alignment)
            scale.addWidget(label, stretch)
        layout.addLayout(scale)
        self.set_value(value)
        self.slider.sliderMoved.connect(self._preview)
        self.slider.valueChanged.connect(self._commit)
        self.slider.sliderReleased.connect(self._released)
        self._retranslate()

    @property
    def value(self) -> int:
        return self.slider.value()

    def set_value(self, value: int | None) -> None:
        """Load or reset a value without emitting an edit or snapping it to zero."""
        self._display_value = value
        blocked = self.slider.blockSignals(True)
        try:
            self.slider.setValue(value if value is not None else 0)
        finally:
            self.slider.blockSignals(blocked)
        self._refresh_label()

    def _refresh_label(self) -> None:
        value = self._display_value
        text = (
            QCoreApplication.translate("EditorLabels", "Mixed values")
            if value is None
            else QCoreApplication.translate("TrackActions", "No adjustment (0%)")
            if value == 0
            else f"{round(value / 255 * 100):+d}%"
        )
        self._value_label.setText(text)

    def _preview(self, value: int) -> None:
        value = 0 if abs(value) <= _ZERO_MAGNET_THRESHOLD else value
        if value == 0 and self.slider.sliderPosition() != 0:
            blocked = self.slider.blockSignals(True)
            try:
                self.slider.setSliderPosition(0)
            finally:
                self.slider.blockSignals(blocked)
        self._display_value = value
        self._refresh_label()

    def _commit(self, value: int) -> None:
        value = 0 if abs(value) <= _ZERO_MAGNET_THRESHOLD else value
        self.set_value(value)
        self.valueEdited.emit(value)

    def _released(self) -> None:
        # Qt can emit sliderReleased before updating value when tracking is off.
        self._commit(self.slider.sliderPosition())

    def _retranslate(self) -> None:
        self.slider.setAccessibleName(
            QCoreApplication.translate("TrackActions", "Volume adjustment")
        )
        self._refresh_label()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self._retranslate()
        super().changeEvent(event)
