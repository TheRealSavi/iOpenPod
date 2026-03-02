"""
Bundled font loader for iOpenPod.

Registers Noto Sans, Noto Sans Mono, Noto Sans Symbols 2, and Noto Emoji from
the bundled ``assets/fonts/`` directory so the UI renders correctly on systems
that lack these fonts (e.g. Fedora Silverblue, minimal Linux installs).

Call ``load_bundled_fonts()`` once **after** QApplication is created but
**before** any widgets are shown.
"""

import logging
import os

from PyQt6.QtGui import QFont, QFontDatabase

log = logging.getLogger(__name__)

# Directory containing bundled .ttf font files, relative to project root.
_FONTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "assets",
    "fonts",
)

# Bundled font files → expected family name (for verification).
_BUNDLED_FONTS = {
    "NotoSans-Regular.ttf": "Noto Sans",
    "NotoSans-Italic.ttf": "Noto Sans",
    "NotoSansMono-Regular.ttf": "Noto Sans Mono",
    "NotoSansSymbols2-Regular.ttf": "Noto Sans Symbols 2",
    "NotoEmoji-Regular.ttf": "Noto Emoji",
}

# Substitution chain: when the primary font can't render a glyph, Qt falls
# back through this list.  Order matters – symbols before emoji so that
# single-codepoint dingbats (★☆✓ etc.) prefer the sharper Symbols 2 glyphs
# and emoji sequences (🎵💿📂) fall through to Noto Emoji.
_SUBSTITUTIONS = ["Noto Sans Symbols 2", "Noto Emoji"]


def load_bundled_fonts() -> list[str]:
    """Register all bundled fonts with Qt and configure substitution chains.

    Returns a list of family names that were successfully loaded.
    Must be called after ``QApplication()`` is constructed.
    """
    loaded_families: list[str] = []

    if not os.path.isdir(_FONTS_DIR):
        log.warning("Bundled fonts directory not found: %s", _FONTS_DIR)
        return loaded_families

    for filename, expected_family in _BUNDLED_FONTS.items():
        path = os.path.join(_FONTS_DIR, filename)
        if not os.path.isfile(path):
            log.warning("Missing bundled font file: %s", path)
            continue

        font_id = QFontDatabase.addApplicationFont(path)
        if font_id < 0:
            log.warning("Qt failed to load font: %s", path)
            continue

        families = QFontDatabase.applicationFontFamilies(font_id)
        if expected_family in families:
            if expected_family not in loaded_families:
                loaded_families.append(expected_family)
            log.debug("Loaded bundled font: %s → %s", filename, expected_family)
        else:
            log.warning(
                "Font %s registered unexpected families: %s (expected %s)",
                filename,
                families,
                expected_family,
            )
            loaded_families.extend(f for f in families if f not in loaded_families)

    # Register substitutions so the primary UI font falls back to symbol/emoji
    # fonts for glyphs it doesn't contain.
    for primary in ("Noto Sans", "Noto Sans Mono"):
        QFont.insertSubstitutions(primary, _SUBSTITUTIONS)

    if loaded_families:
        log.info("Bundled fonts available: %s", ", ".join(loaded_families))
    else:
        log.warning("No bundled fonts were loaded")

    return loaded_families
