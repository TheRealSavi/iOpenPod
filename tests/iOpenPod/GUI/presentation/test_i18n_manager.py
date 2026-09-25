"""Tests for locale identity and runtime language selection."""

from pathlib import Path

from PySide6.QtCore import QLocale, QObject
from PySide6.QtWidgets import QApplication
from pytest import MonkeyPatch

from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.core.settings.stores import (
    DeviceSettingsStore,
    GlobalSettingsStore,
)
from iOpenPod.GUI.presentation.i18n import manager as i18n_module
from iOpenPod.GUI.presentation.i18n.manager import (
    ENGLISH_LANGUAGE,
    SYSTEM_LANGUAGE,
    I18nManager,
)


def _application() -> QApplication:
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    return QApplication([])


APPLICATION = _application()


def test_language_options_keep_stable_identifiers(tmp_path: Path) -> None:
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    manager = I18nManager(APPLICATION, settings, tmp_path)

    try:
        options = manager.available_languages()
        identifiers = {option.language_tag for option in options}

        assert SYSTEM_LANGUAGE in identifiers
        assert ENGLISH_LANGUAGE in identifiers
        assert all(option.label for option in options)
    finally:
        manager.close()


def test_runtime_language_change_updates_setting_locale_and_signal(
    tmp_path: Path,
) -> None:
    original_locale = QLocale()
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    manager = I18nManager(APPLICATION, settings, tmp_path)
    changed: list[str] = []
    manager.languageChanged.connect(changed.append)

    try:
        manager.set_language(ENGLISH_LANGUAGE)

        assert manager.language == ENGLISH_LANGUAGE
        assert QLocale().language() is QLocale.Language.English
        assert changed[-1] == ENGLISH_LANGUAGE
    finally:
        manager.close()
        QLocale.setDefault(original_locale)


def test_translation_catalog_names_follow_qtranslator_locale_lookup(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    loads: list[tuple[str, str]] = []

    class RecordingTranslator(QObject):
        def load(
            self,
            _locale: QLocale,
            filename: str,
            prefix: str,
            _directory: str,
        ) -> bool:
            loads.append((filename, prefix))
            return False

    monkeypatch.setattr(i18n_module, "QTranslator", RecordingTranslator)
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    manager = I18nManager(APPLICATION, settings, tmp_path)

    try:
        assert loads == [("iopenpod", "_"), ("qtbase", "_")]
    finally:
        manager.close()
