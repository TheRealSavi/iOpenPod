"""Runtime holder for the immutable theme currently rendered by the GUI."""

from __future__ import annotations

from .theme_renderer import ResolvedTheme


class ThemeRuntime:
    """Own the active immutable resolved theme for GUI paint adapters.

    Theme changes are applied on the GUI thread. Callers can safely retain a
    ``ResolvedTheme`` returned by ``current`` because the renderer output is
    immutable; replacing the active value never mutates a prior theme.
    """

    def __init__(self, initial_theme: ResolvedTheme) -> None:
        self._current = initial_theme

    @property
    def current(self) -> ResolvedTheme:
        """Return the immutable resolved theme used by newly built styles."""

        return self._current

    def replace(self, resolved_theme: ResolvedTheme) -> None:
        """Make a freshly rendered theme active for future GUI styles."""

        self._current = resolved_theme
