"""Choose streams for one Host Track before reviewing Sync."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QLocale, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.display_text import exception_text
from iOpenPod.app.media.inspection import MediaInspectionError
from iOpenPod.app.media.models import MediaScanMetadata, MediaStream, StreamKind
from iOpenPod.app.media.stream_selection import (
    MediaStreamSelection,
    SubtitleHandling,
    is_caption,
    preferred_stream,
    subtitle_handling,
)
from iOpenPod.app.media_stream_controller import MediaStreamController
from iOpenPod.GUI.presentation.i18n.workflow import workflow_text
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iOpenPod.GUI.widgets.checkable_combo_box import CheckableComboBox
from iOpenPod.GUI.widgets.media_stream_option import (
    StreamOption,
    StreamOptionDelegate,
    set_stream_option,
)
from iOpenPod.GUI.widgets.themed_buttons import (
    ActionButtonKind,
    apply_action_button_kind,
)
from storage import StorageError

if TYPE_CHECKING:
    from collections.abc import Callable

    from device_registry import DeviceProfile
    from iOpenPod.app.host_media_library import HostMediaSource
    from iOpenPod.app.media.inspection import MediaInspector


class MediaStreamsDialog(QDialog):
    def __init__(
        self,
        source: HostMediaSource,
        title: str,
        profile: DeviceProfile,
        selection: MediaStreamSelection | None,
        parent: QWidget | None = None,
        *,
        inspector: MediaInspector | None = None,
        save_selection: Callable[[MediaStreamSelection | None], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("mediaStreamsDialog")
        self.setWindowTitle(self.tr("Choose streams"))
        self.setModal(True)
        self.resize(640, 520)
        self._profile = profile
        self._initial = selection
        self._save_selection = save_selection
        self._metadata: MediaScanMetadata | None = None
        self._error = ""
        self.selection: MediaStreamSelection | None = selection
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg
        )
        layout.setSpacing(LAYOUT.space_sm)
        heading = QLabel(title, self)
        heading.setObjectName("dialogTitle")
        heading.setTextFormat(Qt.TextFormat.PlainText)
        heading.setWordWrap(True)
        layout.addWidget(heading)
        self._status = QLabel(self)
        self._status.setTextFormat(Qt.TextFormat.PlainText)
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        self.automatic = QCheckBox(self.tr("Use automatic stream selection"), self)
        self.automatic.setChecked(selection is None)
        self.automatic.setEnabled(False)
        layout.addWidget(self.automatic)
        self._choices = QWidget(self)
        self._choices.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        form = QFormLayout(self._choices)
        form.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        form.setVerticalSpacing(LAYOUT.space_xs)
        self._form = form
        self.video = AppComboBox(self)
        self.video.setObjectName("videoStream")
        self.audio = AppComboBox(self)
        self.audio.setObjectName("audioStream")
        self.subtitles = CheckableComboBox(self)
        self.subtitles.setObjectName("subtitleStreams")
        self.captions = CheckableComboBox(self)
        self.captions.setObjectName("captionStreams")
        for combo in (self.video, self.audio, self.subtitles, self.captions):
            StreamOptionDelegate(combo)
        form.addRow(self.tr("Video"), self.video)
        form.addRow(self.tr("Audio"), self.audio)
        form.addRow(self.tr("Subtitles"), self.subtitles)
        form.addRow(self.tr("Captions"), self.captions)
        self._choices.setEnabled(False)
        layout.addWidget(self._choices)
        layout.addStretch()
        note = QLabel(
            self.tr(
                "Choices are remembered for this Host file across scans and Syncs. Changed choices replace the iPod copy once. Text subtitle formatting may be simplified. Captions embedded inside video remain part of that video stream."
            ),
            self,
        )
        note.setWordWrap(True)
        self._note = note
        layout.addWidget(note)
        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setText(
            self.tr("Apply choices")
        )
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        apply_action_button_kind(
            self._buttons.button(QDialogButtonBox.StandardButton.Ok),
            ActionButtonKind.PRIMARY,
        )
        apply_action_button_kind(
            self._buttons.button(QDialogButtonBox.StandardButton.Cancel),
            ActionButtonKind.SECONDARY,
        )
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        self.automatic.toggled.connect(self._automatic_changed)
        layout.addWidget(self._buttons)
        self._controller = MediaStreamController(self, inspector=inspector)
        self._controller.inspected.connect(self._loaded)
        self._controller.failed.connect(self._failed)
        self.finished.connect(self._controller.cancel)
        self.retranslate_ui()
        self._controller.start(source)

    def _failed(self, value: object) -> None:
        self._error = (
            exception_text(value)
            if isinstance(value, Exception)
            else value
            if isinstance(value, str)
            else str(value)
        )
        self._render_status()

    def _render_status(self) -> None:
        self._status.setText(
            workflow_text(self._error)
            if self._error
            else self.tr("Reading available streams…")
            if self._metadata is None
            else self.tr("Choose the streams to include in the iPod copy.")
        )

    def retranslate_ui(self) -> None:
        self.setWindowTitle(self.tr("Choose streams"))
        self.automatic.setText(self.tr("Use automatic stream selection"))
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setText(
            self.tr("Apply choices")
        )
        for widget, label in (
            (self.video, self.tr("Video")),
            (self.audio, self.tr("Audio")),
            (self.subtitles, self.tr("Subtitles")),
            (self.captions, self.tr("Captions")),
        ):
            field_label = self._form.labelForField(widget)
            if isinstance(field_label, QLabel):
                field_label.setText(label)
        self._note.setText(
            self.tr(
                "Choices are remembered for this Host file across scans and Syncs. Changed choices replace the iPod copy once. Text subtitle formatting may be simplified. Captions embedded inside video remain part of that video stream."
            )
        )
        for combo in (self.video, self.audio):
            for index in range(combo.count()):
                stream = combo.itemData(index)
                combo.setItemText(
                    index,
                    self._stream_label(stream)
                    if isinstance(stream, MediaStream)
                    else self.tr("None"),
                )
                if isinstance(stream, MediaStream):
                    set_stream_option(combo, index, self._stream_option(stream))
        for widget in (self.subtitles, self.captions):
            widget.setPlaceholderText(self.tr("No separate streams found"))
            for index in range(widget.count()):
                item = widget.item(index)
                stream = item.data(Qt.ItemDataRole.UserRole)
                label = (
                    self._subtitle_label(stream)
                    if isinstance(stream, MediaStream)
                    else self.tr("No separate streams found")
                )
                item.setText(label)
                if isinstance(stream, MediaStream):
                    set_stream_option(widget, index, self._stream_option(stream))
            widget.refresh_summary()
        self._render_status()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

    def _subtitle_label(self, stream: MediaStream) -> str:
        handling = subtitle_handling(stream, self._profile)
        label = self._stream_label(stream)
        if handling is SubtitleHandling.UNSUPPORTED:
            label += self.tr(" — unavailable on this iPod (no supported conversion)")
        elif handling is SubtitleHandling.CONVERT:
            label += self.tr(" — convert to iPod text")
        return label

    def _loaded(self, value: object) -> None:
        if not isinstance(value, MediaScanMetadata):
            return
        if self._initial is not None:
            try:
                self._initial.validate(value, self._profile)
            except MediaInspectionError as error:
                self._failed(error)
                self._initial = None
        self._metadata = value
        self._fill_combo(
            self.video,
            value.video_streams,
            self._initial.video
            if self._initial
            else preferred_stream(value.video_streams),
            allow_none=not value.video_streams,
        )
        self._fill_combo(
            self.audio,
            value.audio_streams,
            self._initial.audio
            if self._initial
            else preferred_stream(value.audio_streams),
            allow_none=bool(value.video_streams),
        )
        for widget, captions in ((self.subtitles, False), (self.captions, True)):
            chosen = (
                (self._initial.captions if captions else self._initial.subtitles)
                if self._initial
                else None
            )
            for stream in value.streams:
                if (
                    stream.kind is not StreamKind.SUBTITLE
                    or is_caption(stream) is not captions
                ):
                    continue
                handling = subtitle_handling(stream, self._profile)
                label = self._subtitle_label(stream)
                widget.add_choice(
                    label,
                    stream,
                    checked=(
                        stream in chosen
                        if chosen is not None
                        else handling is not SubtitleHandling.UNSUPPORTED
                    ),
                    enabled=handling is not SubtitleHandling.UNSUPPORTED,
                )
                set_stream_option(
                    widget, widget.count() - 1, self._stream_option(stream)
                )
            widget.setEnabled(widget.count() > 0)
        self.automatic.setEnabled(True)
        self._automatic_changed(self.automatic.isChecked())
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)
        self._render_status()

    def _fill_combo(
        self,
        widget: AppComboBox,
        streams: tuple[MediaStream, ...],
        chosen: MediaStream | None,
        *,
        allow_none: bool,
    ) -> None:
        if allow_none:
            widget.addItem(self.tr("None"), None)
        for stream in streams:
            widget.addItem(self._stream_label(stream), stream)
            set_stream_option(widget, widget.count() - 1, self._stream_option(stream))
        for index in range(widget.count()):
            if widget.itemData(index) == chosen:
                widget.setCurrentIndex(index)
                break

    def _stream_label(self, stream: MediaStream) -> str:
        tags = {tag.name.casefold(): tag.value for tag in stream.tags}
        parts = [self.tr("Stream %1").replace("%1", str(stream.index))]
        parts.extend(value for key in ("language", "title") if (value := tags.get(key)))
        parts.append(stream.codec)
        if stream.width and stream.height:
            parts.append(f"{stream.width} x {stream.height}")
        if stream.channels:
            parts.append(self.tr("%1 channels").replace("%1", str(stream.channels)))
        if stream.sample_rate_hz:
            parts.append(f"{stream.sample_rate_hz} Hz")
        parts.extend(
            disposition.replace("_", " ")
            for disposition in (
                "default",
                "forced",
                "hearing_impaired",
                "visual_impaired",
                "comment",
            )
            if disposition in stream.dispositions
        )
        return " · ".join(parts)

    def _stream_option(self, stream: MediaStream) -> StreamOption:
        tags = {tag.name.casefold(): tag.value for tag in stream.tags}
        number = self.tr("Stream %1").replace("%1", str(stream.index))
        fallback_title = (
            self.tr("Video")
            if stream.kind is StreamKind.VIDEO
            else self.tr("Audio")
            if stream.kind is StreamKind.AUDIO
            else self.tr("Captions")
            if is_caption(stream)
            else self.tr("Subtitles")
        )
        title = tags.get("title") or fallback_title
        code = tags.get("language", "")
        language = QLocale.codeToLanguage(code)
        language_name = (
            QLocale.languageToString(language)
            if language not in (QLocale.Language.AnyLanguage, QLocale.Language.C)
            else code.upper()
            if code and code != "und"
            else self.tr("Language unspecified")
        )
        details = [language_name, stream.codec.upper()]
        if stream.width and stream.height:
            details.append(f"{stream.width} x {stream.height}")
        if stream.channels:
            details.append(self.tr("%1 channels").replace("%1", str(stream.channels)))
        if stream.sample_rate_hz:
            details.append(f"{stream.sample_rate_hz / 1000:g} kHz")
        for disposition, label in (
            ("default", self.tr("Default")),
            ("forced", self.tr("Forced")),
            ("hearing_impaired", self.tr("Hearing impaired")),
            ("visual_impaired", self.tr("Visual impaired")),
            ("comment", self.tr("Commentary")),
        ):
            if disposition in stream.dispositions:
                details.append(label)
        status = ""
        if stream.kind is StreamKind.SUBTITLE:
            handling = subtitle_handling(stream, self._profile)
            if handling is SubtitleHandling.UNSUPPORTED:
                status = self.tr("Unavailable on this iPod — no supported conversion")
            elif handling is SubtitleHandling.CONVERT:
                status = self.tr("Convert to iPod text")
            else:
                status = self.tr("Ready for iPod")
        return StreamOption(
            title, " · ".join(details), status, number, f"{language_name} · {title}"
        )

    def _automatic_changed(self, automatic: bool) -> None:
        self._choices.setEnabled(not automatic and self._metadata is not None)

    @staticmethod
    def _checked(widget: CheckableComboBox) -> tuple[MediaStream, ...]:
        return tuple(
            stream
            for index in range(widget.count())
            if (item := widget.item(index)).checkState() is Qt.CheckState.Checked
            and isinstance(stream := item.data(Qt.ItemDataRole.UserRole), MediaStream)
            and item.flags() & Qt.ItemFlag.ItemIsEnabled
        )

    def accept(self) -> None:
        if self._metadata is None:
            return
        if self.automatic.isChecked():
            self.selection = None
        else:
            video = self.video.currentData()
            audio = self.audio.currentData()
            try:
                selection = MediaStreamSelection(
                    video if isinstance(video, MediaStream) else None,
                    audio if isinstance(audio, MediaStream) else None,
                    self._checked(self.subtitles),
                    self._checked(self.captions),
                )
                selection.validate(self._metadata, self._profile)
            except (ValueError, MediaInspectionError) as error:
                self._failed(error)
                return
            self.selection = selection
        if self._save_selection is not None:
            try:
                self._save_selection(self.selection)
            except (OSError, StorageError, ValueError, RecursionError) as error:
                self._error = self.tr(
                    "The stream choices could not be saved. Your previous choices are unchanged. %1"
                ).replace("%1", str(error))
                self._render_status()
                return
        super().accept()
