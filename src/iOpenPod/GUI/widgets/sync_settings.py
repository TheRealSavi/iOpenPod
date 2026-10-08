"""Sync and transcoder preferences with capability-specific encoder controls."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from iOpenPod.app.core.settings.definitions import (
    COMPUTE_SOUND_CHECK,
    FIT_THUMBNAILS,
    LOSSY_ENCODER,
    LOSSY_QUALITY,
    NORMALIZE_SAMPLE_RATE,
    NORMALIZE_TAGS_AFTER_SYNC,
    RETRANSCODE_LOSSY,
    ROCKBOX_METADATA_SUPPORT,
    ROTATE_TALL_PHOTOS,
    SMART_QUALITY_BY_CONTENT_TYPE,
    SPOKEN_WORD_BITRATE,
    SPOKEN_WORD_MONO,
    TRANSCODE_LOSSLESS_TO_LOSSY,
    TRANSCODE_PCM_TO_ALAC,
    SettingDefinition,
)
from iOpenPod.app.core.settings.transcoding import (
    BANDWIDTH_CUTOFFS,
    ENCODER_BITRATES,
    encoder_bitrate,
    encoder_bitrate_mode,
    encoder_cutoff,
    encoder_option,
    encoder_vbr_quality,
)
from iOpenPod.app.media.transcoding import (
    SUPPORTED_BITRATE_MODES,
    VBR_QUALITIES,
    BitrateMode,
    LossyEncoder,
)
from iOpenPod.app.scrobbling.settings import SCROBBLE_DURING_SYNC
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iOpenPod.GUI.widgets.setting_group import SettingGroup, SettingRow
from iOpenPod.GUI.widgets.settings_editor import ScopedSettingBinding, SettingsEditor

if TYPE_CHECKING:
    from collections.abc import Sequence

    from iOpenPod.app.core.settings.service import SettingsService


class _Choice[Value](SettingRow):
    """Bind a choice to one typed setting without writes during reconstruction."""

    def __init__(
        self,
        settings: SettingsEditor,
        definition: SettingDefinition[Value],
        name: str,
        parent: QWidget,
    ) -> None:
        self.combo = AppComboBox(parent)
        self.combo.setObjectName(name)
        super().__init__("", "", self.combo, parent)
        self._binding = ScopedSettingBinding(settings, definition, self, self.combo)

    def configure(
        self,
        choices: Sequence[tuple[str, Value]],
        definition: SettingDefinition[Value] | None = None,
    ) -> None:
        self._binding.configure(choices, definition)


class SyncSettings(QWidget):
    """Optional Sync behavior, persisted through the shared Settings service."""

    def __init__(
        self,
        settings: SettingsService,
        parent: QWidget,
        *,
        editor: SettingsEditor | None = None,
    ) -> None:
        super().__init__(parent)
        scope = editor or SettingsEditor(settings, self)
        self._title = QLabel(self)
        self._title.setObjectName("sectionTitle")
        self._sound_check = _Choice(
            scope, COMPUTE_SOUND_CHECK, "computeSoundCheck", self
        )
        self._normalize = _Choice(
            scope, NORMALIZE_TAGS_AFTER_SYNC, "normalizeTagsAfterSync", self
        )
        self._rotate = _Choice(scope, ROTATE_TALL_PHOTOS, "rotateTallPhotos", self)
        self._fit = _Choice(scope, FIT_THUMBNAILS, "fitThumbnails", self)
        self._rockbox = _Choice(
            scope, ROCKBOX_METADATA_SUPPORT, "rockboxMetadataSupport", self
        )
        self._scrobble = _Choice(
            scope, SCROBBLE_DURING_SYNC, "scrobbleDuringSync", self
        )
        self._rows = (
            self._scrobble,
            self._sound_check,
            self._normalize,
            self._rotate,
            self._fit,
            self._rockbox,
        )
        group = SettingGroup(self)
        group.setMaximumWidth(960)
        for row in self._rows:
            group.add_row(row)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(LAYOUT.space_xs)
        layout.addWidget(self._title)
        layout.addWidget(group)
        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        self._title.setText(self.tr("Sync behavior"))
        for row in self._rows:
            row.configure(((self.tr("Off"), False), (self.tr("On"), True)))
        self._scrobble.set_copy(
            self.tr("Scrobble during Sync"),
            self.tr(
                "Submit pending iPod plays to connected services before syncing media. Failed submissions are saved for retry."
            ),
        )
        self._sound_check.set_copy(
            self.tr("Compute Sound Check"),
            self.tr(
                "Analyze loudness when usable Sound Check or ReplayGain values are "
                "missing. This adds analysis time; the iPod controls whether playback "
                "uses Sound Check. Host files stay unchanged."
            ),
        )
        self._normalize.set_copy(
            self.tr("Normalize Tags After Sync"),
            self.tr(
                "Apply iPod-specific metadata cleanup to the committed iPod Library. "
                "Host files stay unchanged."
            ),
        )
        self._rotate.set_copy(
            self.tr("Rotate Tall Photos on Device"),
            self.tr(
                "Rotate portrait Photo viewing copies when they fit the iPod screen "
                "better. Original Photos stay unchanged."
            ),
        )
        self._fit.set_copy(
            self.tr("Fit Thumbnails"),
            self.tr(
                "Fit the entire Photo inside small grid and list thumbnails, adding "
                "padding as needed. Off crops only those thumbnails to fill. All "
                "other Photo viewing copies always fit the entire image with padding."
            ),
        )
        self._rockbox.set_copy(
            self.tr("Rockbox Metadata Support"),
            self.tr(
                "Write Library metadata into synced media files for Rockbox, which "
                "reads file tags. This uses additional space and processing; Apple's "
                "iPod firmware reads the Library database instead."
            ),
        )


class TranscodingSettings(QWidget):
    """Present only the controls supported by the selected encoder."""

    def __init__(
        self,
        settings: SettingsService,
        parent: QWidget,
        *,
        editor: SettingsEditor | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = editor or SettingsEditor(settings, self)
        self._audio_title = QLabel(self)
        self._spoken_title = QLabel(self)
        self._advanced_title = QLabel(self)
        for title in (self._audio_title, self._spoken_title, self._advanced_title):
            title.setObjectName("sectionTitle")
        self._encoder = _Choice(self._settings, LOSSY_ENCODER, "lossyEncoder", self)
        self._quality = _Choice(self._settings, LOSSY_QUALITY, "lossyQuality", self)
        self._mode = _Choice(
            self._settings,
            encoder_bitrate_mode(LossyEncoder.FDK_AAC),
            "bitrateMode",
            self,
        )
        self._bitrate = _Choice(
            self._settings,
            encoder_bitrate(LossyEncoder.FDK_AAC),
            "encoderBitrate",
            self,
        )
        self._vbr = _Choice(
            self._settings,
            encoder_vbr_quality(LossyEncoder.FDK_AAC),
            "vbrQuality",
            self,
        )
        self._lossless = _Choice(
            self._settings,
            TRANSCODE_LOSSLESS_TO_LOSSY,
            "transcodeLosslessToLossy",
            self,
        )
        self._lossy = _Choice(
            self._settings, RETRANSCODE_LOSSY, "retranscodeLossy", self
        )
        self._alac = _Choice(
            self._settings, TRANSCODE_PCM_TO_ALAC, "transcodePcmToAlac", self
        )
        self._sample_rate = _Choice(
            self._settings, NORMALIZE_SAMPLE_RATE, "normalizeSampleRate", self
        )
        self._smart = _Choice(
            self._settings,
            SMART_QUALITY_BY_CONTENT_TYPE,
            "smartQualityByContentType",
            self,
        )
        self._mono = _Choice(self._settings, SPOKEN_WORD_MONO, "spokenWordMono", self)
        self._spoken_bitrate = _Choice(
            self._settings, SPOKEN_WORD_BITRATE, "spokenWordBitrate", self
        )
        self._cutoff = _Choice(
            self._settings,
            encoder_cutoff(LossyEncoder.FDK_AAC),
            "bandwidthCutoff",
            self,
        )
        self._afterburner = _Choice(
            self._settings,
            encoder_option(LossyEncoder.FDK_AAC, "afterburner"),
            "encoderAfterburner",
            self,
        )
        self._tns = _Choice(
            self._settings, encoder_option(LossyEncoder.AAC, "tns"), "encoderTns", self
        )
        self._pns = _Choice(
            self._settings, encoder_option(LossyEncoder.AAC, "pns"), "encoderPns", self
        )
        self._mid_side = _Choice(
            self._settings,
            encoder_option(LossyEncoder.AAC, "mid-side-stereo"),
            "encoderMidSideStereo",
            self,
        )
        self._intensity = _Choice(
            self._settings,
            encoder_option(LossyEncoder.AAC, "intensity-stereo"),
            "encoderIntensityStereo",
            self,
        )
        self._boolean_rows = (
            self._lossless,
            self._lossy,
            self._alac,
            self._sample_rate,
            self._smart,
            self._mono,
            self._afterburner,
            self._tns,
            self._pns,
            self._mid_side,
            self._intensity,
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(LAYOUT.space_xs)
        for title, rows in (
            (
                self._audio_title,
                (
                    self._encoder,
                    self._quality,
                    self._mode,
                    self._bitrate,
                    self._vbr,
                    self._lossless,
                    self._lossy,
                    self._alac,
                    self._sample_rate,
                ),
            ),
            (self._spoken_title, (self._smart, self._mono, self._spoken_bitrate)),
            (
                self._advanced_title,
                (
                    self._cutoff,
                    self._afterburner,
                    self._tns,
                    self._pns,
                    self._mid_side,
                    self._intensity,
                ),
            ),
        ):
            layout.addWidget(title)
            group = SettingGroup(self)
            group.setMaximumWidth(960)
            for row in rows:
                group.add_row(row)
            layout.addWidget(group)
        self._settings.changed.connect(self._refresh_encoder)
        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        self._audio_title.setText(self.tr("Audio transcoding"))
        self._spoken_title.setText(self.tr("Spoken Word"))
        self._advanced_title.setText(self.tr("Encoder settings"))
        self._encoder.configure(
            (
                (self.tr("Auto"), "auto"),
                (self.tr("Apple AAC (aac_at)"), "aac_at"),
                (self.tr("Fraunhofer AAC (libfdk_aac)"), "libfdk_aac"),
                (self.tr("FFmpeg AAC (aac)"), "aac"),
                (self.tr("LAME MP3 (libmp3lame)"), "libmp3lame"),
            )
        )
        self._quality.configure(
            (
                (self.tr("Compact"), "compact"),
                (self.tr("Balanced"), "balanced"),
                (self.tr("High Quality"), "high"),
            )
        )
        for row in self._boolean_rows:
            row.configure(((self.tr("Off"), False), (self.tr("On"), True)))
        self._spoken_bitrate.configure(
            tuple((f"{value} kbps", value) for value in (32, 48, 64, 80, 96))
        )
        self._encoder.set_copy(
            self.tr("Lossy encoder"),
            self.tr(
                "Auto selects the highest-quality available encoder supported by your "
                "iPod. Explicit choices require that encoder in FFmpeg; missing tools or "
                "encoders are reported before Sync writes anything."
            ),
        )
        self._quality.set_copy(
            self.tr("Quality"),
            self.tr(
                "Compact favors smaller files, Balanced balances quality and space, and "
                "High Quality favors fidelity. Spoken Word uses its own bitrate."
            ),
        )
        self._mode.set_copy(
            self.tr("Bitrate Mode"),
            self.tr(
                "CBR targets a fixed bitrate; VBR targets quality. ABR targets an average "
                "bitrate and CVBR constrains variation. Available modes depend on the encoder."
            ),
        )
        self._bitrate.set_copy(
            self.tr("Bitrate"),
            self.tr(
                "Target bitrate for CBR, ABR, or CVBR. Higher values generally improve "
                "quality and use more space. Device limits are checked before encoding."
            ),
        )
        self._lossless.set_copy(
            self.tr("Transcode Lossless into Lossy"),
            self.tr(
                "Encode all lossless audio with the selected lossy encoder. This takes "
                "precedence over WAV and AIFF to ALAC and permanently discards detail "
                "in the device copy. Host originals stay unchanged."
            ),
        )
        self._lossy.set_copy(
            self.tr("Retranscode Lossy into Lossy"),
            self.tr(
                "Re-encode even compatible lossy audio using the selected encoder. "
                "This can reduce size but adds encoding time and generation loss."
            ),
        )
        self._alac.set_copy(
            self.tr("Transcode WAV and AIFF to ALAC"),
            self.tr(
                "Compress compatible WAV and AIFF audio losslessly when ALAC is supported. "
                "Lossless into Lossy and Spoken Word take precedence."
            ),
        )
        self._sample_rate.set_copy(
            self.tr("Normalize to 44.1 kHz"),
            self.tr(
                "Reduce sample rates above 44.1 kHz to 44.1 kHz for smaller files and "
                "smoother iPod playback. Lower sample rates are preserved. Device limits "
                "still apply when this is off."
            ),
        )
        self._smart.set_copy(
            self.tr("Smart quality by Content Type"),
            self.tr(
                "Podcasts and Audiobooks always use lossy Spoken Word settings, including "
                "already compatible files. Music uses the audio settings above."
            ),
        )
        self._mono.set_copy(
            self.tr("Spoken Word Mono"),
            self.tr(
                "Downmix Podcasts and Audiobooks to mono when Smart quality is on, "
                "making a low bitrate more useful for speech."
            ),
        )
        self._spoken_bitrate.set_copy(
            self.tr("Spoken Word Bitrate"),
            self.tr(
                "CBR bitrate for Podcasts and Audiobooks when Smart quality is on. "
                "This overrides music quality and bitrate mode."
            ),
        )
        self._cutoff.set_copy(
            self.tr("Bandwidth cutoff"),
            self.tr(
                "Limit high frequencies to devote more bits to audible detail. "
                "Auto lets the encoder choose."
            ),
        )
        self._afterburner.set_copy(
            self.tr("Afterburner"),
            self.tr("Improve Fraunhofer AAC quality with additional encoding work."),
        )
        self._tns.set_copy(
            self.tr("Temporal Noise Shaping (TNS)"),
            self.tr(
                "Shape FFmpeg AAC coding noise around transients to reduce pre-echo."
            ),
        )
        self._pns.set_copy(
            self.tr("Perceptual Noise Substitution (PNS)"),
            self.tr(
                "Replace noise-like bands with synthetic noise to save bits in FFmpeg AAC. "
                "Off avoids possible noise artifacts."
            ),
        )
        self._mid_side.set_copy(
            self.tr("Mid/Side Stereo"),
            self.tr(
                "Allow FFmpeg AAC or LAME MP3 to encode stereo as shared and differing information."
            ),
        )
        self._intensity.set_copy(
            self.tr("Intensity Stereo"),
            self.tr(
                "Allow FFmpeg AAC to share high-frequency stereo detail, saving bits "
                "at a possible cost to stereo imaging."
            ),
        )
        self._refresh_encoder()

    def _refresh_encoder(self) -> None:
        encoder = LossyEncoder(self._settings.get(LOSSY_ENCODER))
        manual = encoder is not LossyEncoder.AUTO
        self._quality.setVisible(not manual)
        self._mode.setVisible(manual)
        self._advanced_title.setVisible(manual)
        if manual:
            self._mode.configure(
                tuple(
                    (mode.upper(), str(mode))
                    for mode in SUPPORTED_BITRATE_MODES[encoder]
                ),
                encoder_bitrate_mode(encoder),
            )
            self._bitrate.configure(
                tuple((f"{value} kbps", value) for value in ENCODER_BITRATES),
                encoder_bitrate(encoder),
            )
            self._vbr.configure(
                tuple((str(value), value) for value in VBR_QUALITIES[encoder]),
                encoder_vbr_quality(encoder),
            )
            self._cutoff.configure(
                tuple(
                    (self.tr("Auto") if not value else f"{value // 1000} kHz", value)
                    for value in BANDWIDTH_CUTOFFS
                ),
                encoder_cutoff(encoder),
            )
        vbr = (
            manual
            and self._settings.get(encoder_bitrate_mode(encoder))
            == BitrateMode.VBR.value
        )
        self._bitrate.setVisible(manual and not vbr)
        self._vbr.setVisible(vbr)
        self._vbr.set_copy(
            self.tr("VBR Quality"),
            self.tr("Lower values mean higher quality and larger files for LAME MP3.")
            if encoder is LossyEncoder.MP3
            else self.tr(
                "Higher values mean higher quality and larger files for this AAC encoder."
            ),
        )
        self._cutoff.setVisible(manual)
        self._afterburner.setVisible(encoder is LossyEncoder.FDK_AAC)
        for row in (self._tns, self._pns, self._intensity):
            row.setVisible(encoder is LossyEncoder.AAC)
        self._mid_side.setVisible(encoder in (LossyEncoder.AAC, LossyEncoder.MP3))
        self._mid_side.configure(
            ((self.tr("Off"), False), (self.tr("On"), True)),
            encoder_option(
                LossyEncoder.MP3 if encoder is LossyEncoder.MP3 else LossyEncoder.AAC,
                "mid-side-stereo",
            ),
        )
        spoken = self._settings.get(SMART_QUALITY_BY_CONTENT_TYPE)
        # Device overrides remain editable so even an unused value can be unset.
        self._mono.setEnabled(spoken or self._settings.device)
        self._spoken_bitrate.setEnabled(spoken or self._settings.device)
        self._alac.setEnabled(
            self._settings.device or not self._settings.get(TRANSCODE_LOSSLESS_TO_LOSSY)
        )
