"""
Backward-compatible re-export of settings (now lives at project root).

All settings logic has moved to ``settings.py`` at the repository root so
that non-GUI layers (SyncEngine, Writer, etc.) can import it without
depending on the GUI package.  This shim keeps existing ``from GUI.settings``
and ``from ..settings`` / ``from .settings`` imports working.
"""

from settings import (  # noqa: F401 – re-export everything
    AppSettings,
    get_settings,
    get_version,
    reload_settings,
    _default_data_dir,
    _default_settings_dir,
    _get_settings_dir,
    _get_settings_path,
)
