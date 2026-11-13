"""Hallmark · existing iOpenPod dialog rhythm · listen, name, save.

Pre-emit critique: P5 H5 E4 S5 R5 V4. Porcelain/Slate, German at 200%,
loading, ready, invalid name, saving, cancellation and stale-device states.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QCoreApplication, QEvent, QLocale, Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.tone_preview import TonePreview
from iOpenPod.GUI.presentation.i18n.workflow import workflow_text
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.themed_buttons import ActionButton, ActionButtonKind
from iPodDB.alarms import create_alarm_tone

if TYPE_CHECKING:
    from iOpenPod.app.extras_controller import ExtrasController
    from iOpenPod.app.tone_conversion_controller import ToneConversionController
    from iPodDB.library import Track


class ToneConversionDialog(QDialog):
    previewRequested = Signal()

    def __init__(
        self,
        track: Track,
        conversion: ToneConversionController,
        extras: ExtrasController,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("toneConversionDialog")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setMinimumWidth(440)
        self._conversion, self._extras = conversion, extras
        self._target = extras.active_ipod
        self._saving = False
        self._save_error = ""
        self._preview = TonePreview(self)
        self._title = QLabel(track.title, self)
        self._title.setTextFormat(Qt.TextFormat.PlainText)
        self._title.setProperty("extrasHeading", True)
        self._title.setWordWrap(True)
        self._intro = QLabel(self)
        self._intro.setWordWrap(True)
        self._intro.setProperty("extrasMuted", True)
        self._progress = QProgressBar(self)
        self._progress.setRange(0, 0)
        self._progress.setTextVisible(False)
        self._detail = QLabel(self)
        self._detail.setWordWrap(True)
        self._detail.setTextFormat(Qt.TextFormat.PlainText)
        self._name_label = QLabel(self)
        self._name = QLineEdit(self)
        self._name.setObjectName("toneName")
        self._name.setMaxLength(253)
        self._name.setText(track.title.strip()[:80] or self.tr("New tone"))
        self._name_label.setBuddy(self._name)
        self._error = QLabel(self)
        self._error.setObjectName("toneError")
        self._error.setProperty("extrasError", True)
        self._error.setWordWrap(True)
        self._error.setTextFormat(Qt.TextFormat.PlainText)
        self._listen = ActionButton(parent=self, glyph="play")
        self._listen.setObjectName("toneConversionListen")
        self._cancel = ActionButton(parent=self)
        self._save = ActionButton(parent=self, kind=ActionButtonKind.PRIMARY)
        self._save.setObjectName("toneSave")
        self._save.setDefault(True)
        actions = QHBoxLayout()
        actions.addWidget(self._listen)
        actions.addStretch(1)
        actions.addWidget(self._cancel)
        actions.addWidget(self._save)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg
        )
        layout.setSpacing(LAYOUT.space_md)
        for widget in (
            self._title,
            self._intro,
            self._progress,
            self._detail,
            self._name_label,
            self._name,
            self._error,
        ):
            layout.addWidget(widget)
        layout.addLayout(actions)
        conversion.changed.connect(self._update)
        extras.changed.connect(self._update)
        self._name.textChanged.connect(self._validate)
        self._listen.clicked.connect(self._toggle_preview)
        self._cancel.clicked.connect(self.reject)
        self._save.clicked.connect(self._save_tone)
        self._preview.changed.connect(self._listen_label)
        self._preview.failed.connect(self._show_error)
        self.finished.connect(self._closed)
        self._retranslate()
        self._update()

    def _update(self) -> None:
        if self._extras.active_ipod is not self._target:
            self._saving = False
            self.reject()
            return
        result = self._conversion.arrangement
        if self._saving and not self._extras.busy:
            self._saving = False
            if self._extras.message:
                self._save_error = self._extras.message
            elif result is not None and any(
                item.name == self._name.text().strip() and item.notes == result.notes
                for item in self._extras.catalog.tones
            ):
                self.accept()
                return
        self._progress.setVisible(self._conversion.busy or self._saving)
        self._name.setEnabled(not self._saving)
        self._cancel.setEnabled(not self._saving)
        self._listen.setEnabled(result is not None and not self._saving)
        if self._saving:
            self._detail.setText(self.tr("Saving tone…"))
        elif self._conversion.busy:
            self._detail.setText(workflow_text(self._conversion.message))
        elif result is not None:
            self._detail.setText(
                self.tr("%1 seconds · from %2 in the track")
                .replace("%1", QLocale().toString(result.duration_ms / 1000, "f", 1))
                .replace(
                    "%2",
                    f"{int(result.source_start_seconds) // 60}:{int(result.source_start_seconds) % 60:02d}",
                )
            )
        else:
            self._detail.setText("")
        self._validate()
        if self._conversion.error:
            self._show_error(self._conversion.error)
        elif self._save_error:
            self._show_error(self._save_error)

    def _validate(self) -> None:
        result = self._conversion.arrangement
        error = ""
        if result is not None:
            try:
                create_alarm_tone(self._name.text().strip(), result.notes)
                names = {
                    "Beep",
                    *(
                        sound.tone_name
                        for sound in self._extras.catalog.alarm_sounds
                        if sound.tone_name
                    ),
                }
                if self._name.text().strip() in names:
                    error = self.tr(
                        "A tone with this name already exists. Choose another name."
                    )
            except ValueError as failure:
                error = workflow_text(str(failure))
            if not self._extras.busy and not self._extras.catalog.can_create_tone:
                error = self.tr(
                    "A tone cannot be added. Refresh Tones and check that fewer than 19 custom tones are saved."
                )
        self._error.setText(workflow_text(error))
        self._error.setVisible(bool(error))
        self._name.setAccessibleDescription(workflow_text(error))
        self._save.setEnabled(
            result is not None
            and not error
            and not self._saving
            and self._extras.can_write
            and self._extras.catalog.can_create_tone
        )

    def _save_tone(self) -> None:
        result = self._conversion.arrangement
        if result is None or not self._save.isEnabled():
            return
        self._preview.stop()
        self._save_error = ""
        self._saving = True
        if not self._extras.create_tone(self._name.text().strip(), result.notes):
            self._saving = False
            self._save_error = self.tr(
                "The iPod is busy. Try saving again when it is ready."
            )
        self._update()

    def _toggle_preview(self) -> None:
        if self._preview.playing:
            self._preview.stop()
        elif self._conversion.arrangement is not None:
            self.previewRequested.emit()
            self._preview.play(self._conversion.arrangement.notes)

    def _listen_label(self) -> None:
        self._listen.setText(
            self.tr("Stop") if self._preview.playing else self.tr("Listen")
        )

    def _show_error(self, error: str) -> None:
        self._error.setText(error)
        self._error.show()

    def _closed(self, _result: int) -> None:
        self._preview.stop()
        self._conversion.cancel()

    def reject(self) -> None:
        if not self._saving:
            super().reject()

    def _retranslate(self) -> None:
        self.setWindowTitle(self.tr("Convert to tone"))
        self._intro.setText(
            self.tr(
                "A short melody for your iPod's alarms. Listen to the arrangement before saving; the iPod's speaker will sound different."
            )
        )
        self._name_label.setText(self.tr("Tone name"))
        self._cancel.setText(QCoreApplication.translate("CommonActions", "Cancel"))
        self._save.setText(self.tr("Save tone"))
        self._listen_label()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self._retranslate()
            self._update()
        super().changeEvent(event)
