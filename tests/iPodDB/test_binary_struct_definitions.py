import importlib
import pkgutil
from dataclasses import dataclass, fields, is_dataclass
from types import ModuleType

import pytest

import iPodDB.ArtworkDB.shared.chunk_defs.mhod_payloads as artwork_mhod_payloads
import iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads as itunes_mhod_payloads
import iPodDB.PhotosDB.shared.chunk_defs.mhod_payloads as photos_mhod_payloads
from iPodDB.ArtworkDB.shared.database_definition import (
    DATABASE_DEFINITION as ARTWORK_DATABASE_DEFINITION,
)
from iPodDB.iTunesDB.shared.database_definition import (
    DATABASE_DEFINITION as ITUNES_DATABASE_DEFINITION,
)
from iPodDB.PhotosDB.shared.database_definition import (
    DATABASE_DEFINITION as PHOTOS_DATABASE_DEFINITION,
)
from iPodDB.shared.binary_struct import (
    binary_struct_extent,
    validate_binary_struct_definition,
)
from iPodDB.shared.chunk import BinaryStruct, ChunkHeader
from iPodDB.shared.chunk_field import ChunkFieldSchema
from iPodDB.shared.chunk_field import chunk_field as cf
from iPodDB.shared.types import ChunkDefinition


@dataclass(frozen=True, slots=True)
class _OverlappingHeader(ChunkHeader):
    first: int = cf(0x0C, "u32")
    second: int = cf(0x0E, "u32")


@dataclass(frozen=True, slots=True)
class _ExtendedHeader(ChunkHeader):
    optional_field: int = cf(0x14, "u32")


def _definition(
    header_type: type[ChunkHeader],
    header_sizes: tuple[int, ...],
) -> ChunkDefinition[ChunkHeader]:
    return ChunkDefinition(
        marker=b"test",
        purpose="test definition",
        header_type=header_type,
        minimum_header_size=12,
        header_sizes=header_sizes,
        extent_type="length",
        body_kind="opaque",
        child_marker_groups=(),
    )


def test_every_registered_binary_header_has_a_valid_layout() -> None:
    for database_definition in (
        ARTWORK_DATABASE_DEFINITION,
        ITUNES_DATABASE_DEFINITION,
        PHOTOS_DATABASE_DEFINITION,
    ):
        for definition in database_definition.chunk_definitions:
            validate_binary_struct_definition(
                definition.header_type,
                supported_sizes=definition.header_sizes,
            )


def _payload_modules(package: ModuleType) -> tuple[ModuleType, ...]:
    return tuple(
        importlib.import_module(module.name)
        for module in pkgutil.iter_modules(package.__path__, package.__name__ + ".")
    )


def test_every_known_mhod_payload_binary_struct_has_a_valid_layout() -> None:
    modules = (
        *_payload_modules(artwork_mhod_payloads),
        *_payload_modules(itunes_mhod_payloads),
        *_payload_modules(photos_mhod_payloads),
    )
    struct_types = {
        value
        for module in modules
        for value in vars(module).values()
        if isinstance(value, type)
        and issubclass(value, BinaryStruct)
        and value.__module__ == module.__name__
        and is_dataclass(value)
        and all(
            isinstance(field.metadata.get("chunk"), ChunkFieldSchema)
            for field in fields(value)
        )
    }

    assert struct_types
    for struct_type in struct_types:
        validate_binary_struct_definition(
            struct_type,
            supported_sizes=(binary_struct_extent(struct_type),),
        )


def test_chunk_definition_rejects_overlapping_binary_fields() -> None:
    with pytest.raises(ValueError, match=r"second overlaps .*first"):
        _definition(_OverlappingHeader, (24,))


def test_chunk_definition_requires_each_field_to_fit_a_supported_size() -> None:
    with pytest.raises(ValueError, match=r"optional_field.*does not fit"):
        _definition(_ExtendedHeader, (20,))


def test_chunk_definition_allows_optional_fields_beyond_a_short_header() -> None:
    definition = _definition(_ExtendedHeader, (16, 24))

    assert definition.header_sizes == (16, 24)
