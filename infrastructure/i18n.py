"""Application internationalization backed by gettext catalogs."""

from __future__ import annotations

import gettext
from pathlib import Path

LANGUAGE_EN = "en"
LANGUAGE_ZH = "zh"
LANGUAGE_DE = "de"
LANGUAGE_FR = "fr"
LANGUAGE_ES = "es"
SUPPORTED_LANGUAGES = frozenset({
    LANGUAGE_EN,
    LANGUAGE_ZH,
    LANGUAGE_DE,
    LANGUAGE_FR,
    LANGUAGE_ES,
})

LANGUAGE_DISPLAY_NAMES = {
    LANGUAGE_EN: "English",
    LANGUAGE_ZH: "中文",
    LANGUAGE_DE: "Deutsch",
    LANGUAGE_FR: "Français",
    LANGUAGE_ES: "Español",
}

DOMAIN = "iopenpod"
LOCALE_DIR = Path(__file__).resolve().parents[1] / "locale"

_current_language = LANGUAGE_EN
_translation: gettext.NullTranslations = gettext.NullTranslations()


def normalize_language(language: object) -> str:
    """Return a supported language code, defaulting to English."""

    if isinstance(language, str):
        normalized = language.strip().lower().replace("_", "-")
        if normalized in {"zh", "zh-cn", "zh-hans", "chinese", "中文"}:
            return LANGUAGE_ZH
        if normalized in {"en", "en-us", "en-gb", "english"}:
            return LANGUAGE_EN
        if normalized in {"de", "de-de", "german", "deutsch"}:
            return LANGUAGE_DE
        if normalized in {"fr", "fr-fr", "french", "français", "francais"}:
            return LANGUAGE_FR
        if normalized in {"es", "es-es", "spanish", "español", "espanol"}:
            return LANGUAGE_ES
    return LANGUAGE_EN


def _gettext_language(language: str) -> str:
    return {
        LANGUAGE_ZH: "zh_CN",
        LANGUAGE_DE: "de",
        LANGUAGE_FR: "fr",
        LANGUAGE_ES: "es",
    }.get(language, "en")


def set_language(language: object) -> str:
    """Set the process-local UI language and return the normalized code."""

    global _current_language, _translation
    _current_language = normalize_language(language)
    if _current_language == LANGUAGE_EN:
        _translation = gettext.NullTranslations()
    else:
        _translation = gettext.translation(
            DOMAIN,
            localedir=LOCALE_DIR,
            languages=[_gettext_language(_current_language)],
            fallback=True,
        )
    return _current_language


def get_language() -> str:
    """Return the active process-local UI language code."""

    return _current_language


def language_display_name(language: object) -> str:
    """Return the selector label for a language code."""

    return LANGUAGE_DISPLAY_NAMES[normalize_language(language)]


def language_from_display_name(display_name: str) -> str:
    """Return a language code from a selector label."""

    for code, label in LANGUAGE_DISPLAY_NAMES.items():
        if display_name == label:
            return code
    return normalize_language(display_name)


def language_options() -> list[str]:
    """Return language selector options in a stable order."""

    return [
        LANGUAGE_DISPLAY_NAMES[LANGUAGE_EN],
        LANGUAGE_DISPLAY_NAMES[LANGUAGE_ZH],
        LANGUAGE_DISPLAY_NAMES[LANGUAGE_DE],
        LANGUAGE_DISPLAY_NAMES[LANGUAGE_FR],
        LANGUAGE_DISPLAY_NAMES[LANGUAGE_ES],
    ]


def tr(text: str) -> str:
    """Translate an English source string for the current UI language."""

    return _translation.gettext(text)
