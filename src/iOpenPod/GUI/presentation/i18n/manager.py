"""Runtime language selection and Qt translator orchestration."""

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import (
    QCoreApplication,
    QLibraryInfo,
    QLocale,
    QObject,
    QTranslator,
    Signal,
)
from PySide6.QtWidgets import QApplication

from iOpenPod.app.core.settings.definitions import APPLICATION_LANGUAGE
from iOpenPod.app.core.settings.service import SettingsService

SYSTEM_LANGUAGE = "system"
ENGLISH_LANGUAGE = "en"


@dataclass(frozen=True, slots=True)
class LanguageOption:
    """A translated label paired with a stable locale identifier."""

    language_tag: str
    label: str


class I18nManager(QObject):
    """Own installed translators, locale state, and runtime language changes."""

    languageChanged = Signal(str)

    def __init__(
        self,
        application: QApplication,
        settings: SettingsService,
        translations_path: Path | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._application = application
        self._settings = settings
        self._translations_path = translations_path or Path(__file__).with_name(
            "translations"
        )
        self._application_translator: QTranslator | None = None
        self._qt_translator: QTranslator | None = None

        settings.settingChanged.connect(self._setting_changed)
        self.apply()

    @property
    def language(self) -> str:
        return self._settings.get(APPLICATION_LANGUAGE)

    @property
    def locale(self) -> QLocale:
        if self.language == SYSTEM_LANGUAGE:
            return QLocale.system()
        return QLocale(self.language)

    def set_language(self, language_tag: str) -> None:
        self._settings.set_global(APPLICATION_LANGUAGE, language_tag)

    def available_languages(self) -> tuple[LanguageOption, ...]:
        """List the system choice, English, and any packaged translation catalogs."""

        language_tags = {ENGLISH_LANGUAGE}
        if self._translations_path.is_dir():
            for catalog in self._translations_path.glob("iopenpod_*.qm"):
                language_tags.add(catalog.stem.removeprefix("iopenpod_"))

        translated_system = QCoreApplication.translate(
            "I18nManager",
            "System default",
        )
        localized = sorted(
            (
                LanguageOption(language_tag, _native_language_name(language_tag))
                for language_tag in language_tags
            ),
            key=lambda option: option.label.casefold(),
        )
        return (LanguageOption(SYSTEM_LANGUAGE, translated_system), *localized)

    def apply(self) -> None:
        """Install catalogs for the effective locale and notify presentation code."""

        self._remove_translators()
        locale = self.locale
        QLocale.setDefault(locale)

        application_translator = QTranslator(self)
        if application_translator.load(
            locale,
            "iopenpod",
            "_",
            str(self._translations_path),
        ):
            self._application.installTranslator(application_translator)
            self._application_translator = application_translator
        else:
            application_translator.deleteLater()

        qt_translator = QTranslator(self)
        qt_translations = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
        if qt_translator.load(locale, "qtbase", "_", qt_translations):
            self._application.installTranslator(qt_translator)
            self._qt_translator = qt_translator
        else:
            qt_translator.deleteLater()

        self.languageChanged.emit(self.language)

    def close(self) -> None:
        """Remove translators deterministically during tests or application shutdown."""

        self._remove_translators()

    def _remove_translators(self) -> None:
        if self._application_translator is not None:
            self._application.removeTranslator(self._application_translator)
            self._application_translator.deleteLater()
            self._application_translator = None
        if self._qt_translator is not None:
            self._application.removeTranslator(self._qt_translator)
            self._qt_translator.deleteLater()
            self._qt_translator = None

    def _setting_changed(self, key: str, _value: object) -> None:
        if key == APPLICATION_LANGUAGE.key:
            self.apply()


def _native_language_name(language_tag: str) -> str:
    locale = QLocale(language_tag)
    language = locale.nativeLanguageName().strip()
    territory = locale.nativeTerritoryName().strip()
    if not language:
        return language_tag
    if territory and "_" in language_tag:
        return f"{language} ({territory})"
    return language[0].upper() + language[1:]
