"""Known Photo Database MHOD meanings over the shared binary layouts."""

from collections.abc import Mapping
from types import MappingProxyType

from iPodDB.ArtworkDB.shared.mhod_payload_spec_registry import (
    MHOD_DEFINITIONS as ARTWORK_MHOD_DEFINITIONS,
)
from iPodDB.ArtworkDB.shared.mhod_payload_spec_registry import ArtworkMhodDefinition
from iPodDB.PhotosDB.shared.constants import PhotosMhodType

PhotosMhodDefinition = ArtworkMhodDefinition

MHOD_DEFINITIONS: Mapping[PhotosMhodType, PhotosMhodDefinition] = MappingProxyType(
    {
        PhotosMhodType(int(mhod_type)): definition
        for mhod_type, definition in ARTWORK_MHOD_DEFINITIONS.items()
    }
)

__all__ = ["MHOD_DEFINITIONS", "PhotosMhodDefinition"]
