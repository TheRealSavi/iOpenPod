"""MHOD type 55 playlist-property plist definition."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import cast

from iPodDB.shared.chunk import MhodPayload

type PlistValue = (
    bool
    | bytes
    | datetime
    | float
    | int
    | str
    | tuple[PlistValue, ...]
    | Mapping[str, PlistValue]
)


def freeze_plist_value(value: object) -> PlistValue:
    """Recursively freeze a typed plist value for an immutable Database Document."""

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
    if isinstance(value, bool | bytes | datetime | float | int | str):
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
