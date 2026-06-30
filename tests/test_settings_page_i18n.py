from types import SimpleNamespace

from app_core.services import SettingsSnapshot
from GUI.widgets.settingsPage import SettingsPage
from infrastructure.i18n import get_language, set_language
from infrastructure.settings_schema import AppSettings


class _FakeSettingsService:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings

    def get_global_settings(self) -> AppSettings:
        return self.settings

    def get_effective_settings(self) -> AppSettings:
        return self.settings

    def save_global_settings(self, settings: AppSettings) -> SettingsSnapshot:
        self.settings = settings
        return SettingsSnapshot.from_settings(settings)


class _FakeDeviceSessions:
    def current_session(self) -> SimpleNamespace:
        return SimpleNamespace(
            device_path="",
            discovered_ipod=None,
            device_settings_loading=False,
        )


def test_settings_page_language_selector_saves_and_emits(qtbot) -> None:
    try:
        set_language("en")
        service = _FakeSettingsService(AppSettings())
        page = SettingsPage(service, _FakeDeviceSessions())
        qtbot.addWidget(page)
        page.load_from_settings()

        assert page.language_combo.title_label.text() == "Language"
        assert [
            page.language_combo.combo.itemText(index)
            for index in range(page.language_combo.combo.count())
        ] == ["English", "中文", "Deutsch", "Français", "Español"]
        assert page.language_combo.combo.currentText() == "English"

        with qtbot.waitSignal(page.language_changed, timeout=1000):
            page.language_combo.combo.setCurrentText("中文")

        assert service.settings.language == "zh"
        assert get_language() == "zh"
    finally:
        set_language("en")


def test_settings_page_language_selector_saves_additional_language(qtbot) -> None:
    try:
        set_language("en")
        service = _FakeSettingsService(AppSettings())
        page = SettingsPage(service, _FakeDeviceSessions())
        qtbot.addWidget(page)
        page.load_from_settings()

        with qtbot.waitSignal(page.language_changed, timeout=1000):
            page.language_combo.combo.setCurrentText("Deutsch")

        assert service.settings.language == "de"
        assert get_language() == "de"
    finally:
        set_language("en")


def test_settings_page_storage_labels_use_catalog(qtbot) -> None:
    try:
        set_language("zh")
        service = _FakeSettingsService(AppSettings(language="zh"))
        page = SettingsPage(service, _FakeDeviceSessions())
        qtbot.addWidget(page)
        page.load_from_settings()

        assert page.transcode_cache_dir.title_label.text() == "缓存位置"
        assert page.transcode_cache_dir.path_label.text() == "平台默认"
        assert page.max_cache_size.title_label.text() == "最大缓存大小"
        assert page.settings_dir.title_label.text() == "设置位置"
        assert page.log_dir.title_label.text() == "日志位置"
        assert page._section_labels[("Storage", "Locations")].text() == "位置"
    finally:
        set_language("en")


def test_settings_page_combo_rows_translate_display_but_keep_raw_values(qtbot) -> None:
    try:
        set_language("zh")
        service = _FakeSettingsService(AppSettings(language="zh"))
        page = SettingsPage(service, _FakeDeviceSessions())
        qtbot.addWidget(page)
        page.load_from_settings()

        assert page.sync_workers.combo.currentText() == "自动"
        assert page.sync_workers.value == "Auto"
        assert page.lossy_quality.combo.currentText() == "均衡"
        assert page.lossy_quality.value == "Balanced"
        assert page.rating_strategy.combo.currentText() == "iPod 优先"
        assert page.rating_strategy.value == "iPod Wins"

        page.backup_before_sync.value = "Ask Each Time"
        assert page.backup_before_sync.combo.currentText() == "每次询问"
        assert page.backup_before_sync.value == "Ask Each Time"
    finally:
        set_language("en")


def test_settings_page_non_storage_strings_use_catalog(qtbot) -> None:
    try:
        set_language("zh")
        service = _FakeSettingsService(AppSettings(language="zh"))
        page = SettingsPage(service, _FakeDeviceSessions())
        qtbot.addWidget(page)
        page.load_from_settings()

        assert page.write_back.desc_label.text() == (
            "同步时，将评分和音量均衡值写入电脑音乐文件。关闭时，不会修改电脑文件。"
        )
        assert page.ffmpeg_tool.desc_label.text() == (
            "转码和媒体探测所必需。包含 ffmpeg 和 ffprobe。"
        )
        assert page.scrobble_on_sync.title_label.text() == "同步时记录播放"
        assert page.backup_dir.title_label.text() == "备份位置"
    finally:
        set_language("en")
