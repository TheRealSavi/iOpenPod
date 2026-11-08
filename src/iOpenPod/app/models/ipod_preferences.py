"""Typed preference observations and explicit edits for the Active iPod."""

from dataclasses import dataclass
from enum import StrEnum

from device_registry import PreferencesSupport
from iPodDB.preferences import NamedPreferencesDocument, PreferencesDocument
from storage import FileFingerprint


class PreferenceFileStatus(StrEnum):
    AVAILABLE = "available"
    MISSING = "missing"
    UNREADABLE = "unreadable"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class IPodPreferenceChoice:
    value: int
    label: str


@dataclass(frozen=True, slots=True)
class IPodPreferenceEditSpec:
    """A qualified native domain, independent of any presentation widget."""

    value: int
    choices: tuple[IPodPreferenceChoice, ...] = ()
    minimum: int | None = None
    maximum: int | None = None


@dataclass(frozen=True, slots=True)
class IPodPreference:
    key: str
    title: str
    value: str
    edit: IPodPreferenceEditSpec | None = None
    detail: str = ""
    raw_value: str = ""
    category: str = ""


@dataclass(frozen=True, slots=True)
class IPodPreferenceSection:
    key: str
    title: str
    status: PreferenceFileStatus
    rows: tuple[IPodPreference, ...] = ()
    detail: str = ""


@dataclass(frozen=True, slots=True)
class IPodPreferenceEdit:
    section_key: str
    key: str
    value: int


@dataclass(frozen=True, slots=True)
class IPodPreferencesCatalog:
    """One captured source revision; display state never authorizes publication."""

    sections: tuple[IPodPreferenceSection, ...] = ()
    support: PreferencesSupport | None = None
    document: PreferencesDocument | NamedPreferencesDocument | None = None
    fingerprint: FileFingerprint | None = None
