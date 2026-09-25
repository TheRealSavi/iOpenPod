"""Settings expose encoder capabilities without overwriting hidden preferences."""

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication, QWidget

from iOpenPod.app.core.settings.definitions import (
    COMPUTE_SOUND_CHECK,
    LOSSY_ENCODER,
    ROCKBOX_METADATA_SUPPORT,
    SMART_QUALITY_BY_CONTENT_TYPE,
    TRANSCODE_LOSSLESS_TO_LOSSY,
)
from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.core.settings.stores import DeviceSettingsStore, GlobalSettingsStore
from iOpenPod.app.core.settings.transcoding import read_transcoder_settings
from iOpenPod.app.media.transcoding import BitrateMode
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iOpenPod.GUI.widgets.sync_settings import SyncSettings, TranscodingSettings


def _combo(widget: QWidget, name: str) -> AppComboBox:
    control = widget.findChild(AppComboBox, name)
    assert control is not None
    return control


def _app() -> QApplication:
    application = QApplication.instance()
    if isinstance(application, QApplication):
        return application
    return QApplication([])


def test_encoder_controls_follow_capabilities_and_retain_independent_values() -> None:
    application = _app()
    parent = QWidget()
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    changes = QSignalSpy(settings.settingChanged)
    widget = TranscodingSettings(settings, parent)
    widget.show()
    parent.show()
    application.processEvents()
    assert changes.count() == 0
    assert _combo(widget, "lossyQuality").isVisible()
    assert not _combo(widget, "bitrateMode").isVisible()
    encoder = _combo(widget, "lossyEncoder")
    encoder.setCurrentIndex(encoder.findData("libfdk_aac"))
    mode = _combo(widget, "bitrateMode")
    assert [mode.itemData(index) for index in range(mode.count())] == ["cbr", "vbr"]
    assert _combo(widget, "vbrQuality").count() == 5
    assert _combo(widget, "encoderAfterburner").isVisible()
    assert not _combo(widget, "encoderPns").isVisible()
    mode.setCurrentIndex(mode.findData("cbr"))
    bitrate = _combo(widget, "encoderBitrate")
    bitrate.setCurrentIndex(bitrate.findData(256))
    assert not _combo(widget, "vbrQuality").isVisible()
    encoder.setCurrentIndex(encoder.findData("aac_at"))
    assert [mode.itemData(index) for index in range(mode.count())] == [
        "cbr",
        "vbr",
        "abr",
        "cvbr",
    ]
    assert _combo(widget, "vbrQuality").count() == 15
    mode.setCurrentIndex(mode.findData("cvbr"))
    bitrate.setCurrentIndex(bitrate.findData(160))
    encoder.setCurrentIndex(encoder.findData("libfdk_aac"))
    assert read_transcoder_settings(settings).bitrate_mode is BitrateMode.CBR
    assert read_transcoder_settings(settings).bitrate_kbps == 256
    settings.set_global(LOSSY_ENCODER, "aac")
    assert _combo(widget, "encoderPns").isVisible()
    assert not _combo(widget, "encoderAfterburner").isVisible()
    assert _combo(widget, "vbrQuality").count() == 2
    before = changes.count()
    widget.retranslate_ui()
    assert changes.count() == before
    parent.close()


def test_policy_precedence_is_visible_and_optional_sync_settings_save() -> None:
    application = _app()
    parent = QWidget()
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    widget = TranscodingSettings(settings, parent)
    sync = SyncSettings(settings, parent)
    settings.set_global(TRANSCODE_LOSSLESS_TO_LOSSY, True)
    assert not _combo(widget, "transcodePcmToAlac").isEnabled()
    settings.set_global(SMART_QUALITY_BY_CONTENT_TYPE, False)
    assert not _combo(widget, "spokenWordMono").isEnabled()
    assert not _combo(widget, "spokenWordBitrate").isEnabled()
    settings.set_global(SMART_QUALITY_BY_CONTENT_TYPE, True)
    assert _combo(widget, "spokenWordBitrate").isEnabled()
    sound = _combo(sync, "computeSoundCheck")
    sound.setCurrentIndex(sound.findData(True))
    rockbox = _combo(sync, "rockboxMetadataSupport")
    rockbox.setCurrentIndex(rockbox.findData(True))
    assert settings.get(COMPUTE_SOUND_CHECK) is True
    assert settings.get(ROCKBOX_METADATA_SUPPORT) is True
    parent.close()
    application.processEvents()
