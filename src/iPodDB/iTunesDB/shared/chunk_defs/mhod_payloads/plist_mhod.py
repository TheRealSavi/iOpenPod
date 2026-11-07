"""MHOD type 55 playlist properties with UTC Instant for plist date objects.

Plist date objects have UTC semantics, unlike ordinary MHIT calendar words. An
integer value with a date-like key is still an integer; this model does not infer
an epoch from names. See docs/datetime-engineering.md for boundary/precision policy.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import cast

from whenever import Instant

from iPodDB.shared.chunk import MhodPayload

type PlistValue = (
    bool
    | bytes
    | Instant
    | float
    | int
    | str
    | tuple[PlistValue, ...]
    | Mapping[str, PlistValue]
)


def freeze_plist_value(value: object) -> PlistValue:
    """Freeze properties and resolve authored dates to plistlib's precision.

    Python 3.12 plistlib exchanges microsecond datetime values. Floor an authored
    Instant to that precision here so the typed intent agrees with serialization;
    this is a nonblocking Host policy, not a firmware timestamp rule. Parsed dates
    already have this precision, and retained original payload bytes stay intact.
    """

    if isinstance(value, tuple):
        items = cast("tuple[object, ...]", value)
        return tuple(freeze_plist_value(item) for item in items)
    if isinstance(value, Mapping):
        source = cast("Mapping[object, object]", value)
        frozen: dict[str, PlistValue] = {}
        for key, item in source.items():
            if not isinstance(key, str):
                raise TypeError("plist dictionary keys must be strings")
            frozen[key] = freeze_plist_value(item)
        return MappingProxyType(frozen)
    if isinstance(value, Instant):
        return value.round("microsecond", mode="floor")
    if isinstance(value, bool | bytes | float | int | str):
        return value
    raise TypeError(f"unsupported plist value {type(value).__name__}")


@dataclass(frozen=True, slots=True)
class MhodPlistPayload(MhodPayload):
    data: bytes
    properties: Mapping[str, PlistValue] | None

    def __post_init__(self) -> None:
        if self.properties is not None:
            frozen = freeze_plist_value(self.properties)
            if not isinstance(frozen, Mapping):
                raise TypeError("plist properties must be a string-keyed mapping")
            object.__setattr__(self, "properties", frozen)
