"""Pure, non-authorizing observations of captured firmware preference bytes.

These values describe saved state, never firmware adoption or permission to edit.
Display text is evidence-derived; callers may translate the labels. Unknown raw
values remain observable without making Library loading depend on interpretation.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PreferenceObservation:
    """One field's saved value, interpretation and limits, with no write authority."""

    key: str
    label: str
    raw_value: str
    value: str
    category: str = "Device"
    detail: str = ""
    known: bool = True


@dataclass(frozen=True, slots=True)
class PreferenceInspection:
    """Bounded observations and nonblocking interpretation issues for one file."""

    observations: tuple[PreferenceObservation, ...] = ()
    issues: tuple[str, ...] = ()
