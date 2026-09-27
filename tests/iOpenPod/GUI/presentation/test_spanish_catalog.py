"""Verify the shipped Spanish catalog and its real runtime integration."""

import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from string import Formatter

import pytest
from PySide6.QtCore import QCoreApplication, QLocale, QTranslator
from PySide6.QtWidgets import QLabel, QTabWidget
from scripts.update_translations import extract_catalogs
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION

from iOpenPod.app.core.settings.definitions import MAX_BACKUPS
from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.core.settings.stores import DeviceSettingsStore, GlobalSettingsStore
from iOpenPod.app.display_text import source_text
from iOpenPod.GUI.pages.settings_page import SettingsPage
from iOpenPod.GUI.presentation.i18n.manager import I18nManager
from iOpenPod.GUI.presentation.i18n.text import track_count_text
from iOpenPod.GUI.presentation.i18n.workflow import workflow_text
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox

TRANSLATIONS = (
    Path(__file__).resolve().parents[4]
    / "src/iOpenPod/GUI/presentation/i18n/translations"
)
SOURCE = TRANSLATIONS / "iopenpod_es.ts"
COMPILED = TRANSLATIONS / "iopenpod_es.qm"


def _messages(path: Path) -> dict[tuple[str, str, str], ET.Element]:
    return {
        (
            context.findtext("name", ""),
            message.findtext("source", ""),
            message.findtext("comment", ""),
        ): message
        for context in ET.parse(path).findall("context")
        for message in context.findall("message")
        if (translation := message.find("translation")) is not None
        and translation.get("type") not in {"vanished", "obsolete"}
    }


def test_spanish_covers_current_sources_and_plural_metadata(tmp_path: Path) -> None:
    extracted = tmp_path / "iopenpod_es.ts"
    extract_catalogs([extracted])
    current = _messages(extracted)
    shipped = _messages(SOURCE)
    assert shipped.keys() == current.keys()
    for key, message in shipped.items():
        assert message.get("numerus") == current[key].get("numerus"), key


def test_spanish_is_finished_and_preserves_all_placeholders() -> None:
    root = ET.parse(SOURCE).getroot()
    assert root.get("language") == "es"
    assert root.get("sourcelanguage") == "en"
    messages = _messages(SOURCE)
    assert messages
    for key, message in messages.items():
        translation = message.find("translation")
        assert translation is not None and translation.get("type") is None, key
        source = key[1]
        if message.get("numerus") == "yes":
            forms = [form.text or "" for form in translation.findall("numerusform")]
            assert len(forms) == 2, key
        else:
            forms = [translation.text or ""]
        for form in forms:
            assert form.strip(), key
            assert "\ufffd" not in form, key
            assert Counter(re.findall(r"%L?(?:n|[1-9][0-9]*)", form)) == Counter(
                re.findall(r"%L?(?:n|[1-9][0-9]*)", source)
            ), key
            assert Counter(
                (field, spec, conversion)
                for _, field, spec, conversion in Formatter().parse(form)
                if field is not None
            ) == Counter(
                (field, spec, conversion)
                for _, field, spec, conversion in Formatter().parse(source)
                if field is not None
            ), key


def test_shipped_compiled_spanish_matches_every_source_translation() -> None:
    translator = QTranslator()
    assert translator.load(str(COMPILED))
    for (context, source, comment), message in _messages(SOURCE).items():
        translation = message.find("translation")
        assert translation is not None
        if message.get("numerus") == "yes":
            forms = translation.findall("numerusform")
            for count in (0, 1, 2, 21, 1000):
                expected = forms[0 if count == 1 else 1].text
                assert translator.translate(context, source, comment, count) == expected
        else:
            assert translator.translate(context, source, comment) == translation.text


@pytest.mark.parametrize("language", ["es", "es_ES", "es_MX", "es_AR"])
def test_spanish_regional_fallback_and_runtime_switching(language: str) -> None:
    original_locale = QLocale()
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    manager = I18nManager(APPLICATION, settings)
    try:
        spanish = next(
            option
            for option in manager.available_languages()
            if option.language_tag == "es"
        )
        assert spanish.label.startswith("Español")
        manager.set_language(language)
        assert QLocale().language() == QLocale.Language.Spanish
        assert QCoreApplication.translate("CommonActions", "Cancel") == "Cancelar"
        assert [track_count_text(count) for count in (0, 1, 2)] == [
            "0 pistas",
            "1 pista",
            "2 pistas",
        ]
        title = "Mi {title} %1 <episodio> — 曲.mp3"
        assert workflow_text(source_text("Downloading {title}…", title=title)) == (
            f"Descargando {title}…"
        )
        assert workflow_text(title) == title
        manager.set_language("en")
        assert QCoreApplication.translate("CommonActions", "Cancel") == "Cancel"
        assert track_count_text(2) == "2 tracks"
    finally:
        manager.close()
        QLocale.setDefault(original_locale)


def test_settings_language_picker_loads_spanish_and_keeps_pending_settings() -> None:
    original_locale = QLocale()
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    theme = ThemeManager(APPLICATION, settings)
    manager = I18nManager(APPLICATION, settings)
    manager.set_language("en")
    page = SettingsPage(settings, theme, manager)
    try:
        tabs = page.findChild(QTabWidget, "settingsTabs")
        assert tabs is not None
        # The language combo is identified by its stable es item, not its display text.
        languages = next(
            combo
            for combo in page.findChildren(AppComboBox)
            if combo.findData("es") >= 0
        )
        backups = page.findChild(AppComboBox, "maxBackups")
        assert backups is not None
        backups.setCurrentIndex(backups.findData(10))
        languages.setCurrentIndex(languages.findData("es"))
        APPLICATION.processEvents()
        assert manager.language == "es"
        assert tabs.tabText(0) == "Apariencia"
        assert tabs.tabText(1) == "Biblioteca"
        assert tabs.tabText(tabs.count() - 1) == "Acerca de"
        assert settings.get(MAX_BACKUPS) == 10
        assert backups.currentData() == 10
        note = page.findChild(QLabel, "pageMeta")
        assert note is not None
        assert note.text() == "Los cambios se guardan automáticamente."
        languages.setCurrentIndex(languages.findData("en"))
        APPLICATION.processEvents()
        assert tabs.tabText(0) == "Appearance"
        assert backups.currentData() == 10
    finally:
        page.close()
        theme.close()
        manager.close()
        QLocale.setDefault(original_locale)
