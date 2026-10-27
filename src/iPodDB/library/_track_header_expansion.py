"""Explicit extension policy; serialization itself never grows retained headers."""

from collections.abc import Mapping

from iPodDB.iTunesDB.shared.chunk_defs.mhit import DEFINITION as MHIT
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader, header_size_for_version
from iPodDB.library.models import Track
from iPodDB.shared.binary_struct import binary_fields
from iPodDB.shared.chunk import ParsedChunk
from iPodDB.shared.chunk_field import ChunkFieldValue


def creation_header_length(database_version: int | None) -> int:
    """Use the device's authoring layout, or the generic builder's default."""
    return (
        header_size_for_version(database_version)
        if database_version is not None
        else MHIT.default_header_size
    )


def field_fits(name: str, length: int) -> bool:
    schema = next(
        f.schema for f in binary_fields(MhitHeader) if f.attribute_name == name
    )
    return schema.offset + schema.size <= length


def optional_field_available(
    source: ParsedChunk[MhitHeader] | None, name: str, database_version: int | None
) -> bool:
    """An optional native reference may use retained bytes or authorized growth."""
    if source is None:
        length = creation_header_length(database_version)
    else:
        length = source.generic_header.header_length
        if database_version is not None:
            length = max(length, header_size_for_version(database_version))
    return field_fits(name, length)


def required_header_length(
    source: ParsedChunk[MhitHeader],
    values: Mapping[str, ChunkFieldValue],
    database_version: int | None,
    *,
    required_presence: frozenset[str] = frozenset(),
) -> int:
    """Grow only to encode intent that cannot fit, within device policy.

    Missing/insufficient capabilities leave the original extent in place so the
    strict binary writer rejects unrepresentable intent without losing evidence.
    ``required_presence`` handles fields whose absence has different semantics
    from their encoded default, such as an explicit unplayed marker.
    """
    length = source.generic_header.header_length
    required = max(
        (
            f.schema.offset + f.schema.size
            for f in binary_fields(MhitHeader)
            if f.attribute_name in required_presence
            or (
                f.attribute_name in values
                and (
                    values[f.attribute_name] != f.schema.default
                    or (
                        f.schema.encoding == "raw"
                        and isinstance(f.schema.default, bytes)
                        and f.schema.offset < length < f.schema.offset + f.schema.size
                        and source.raw_header[f.schema.offset : length]
                        != f.schema.default[: length - f.schema.offset]
                    )
                )
            )
        ),
        default=length,
    )
    if required <= length or database_version is None:
        return length
    supported = header_size_for_version(database_version)
    return supported if supported >= required else length


def extension_values(
    source: ParsedChunk[MhitHeader], desired: Track, length: int
) -> dict[str, ChunkFieldValue]:
    """Defaults and semantic seeds for newly exposed bytes, never retained fields.

    This policy consumes source evidence and intent, so verification can apply it
    without trusting the writer's edited header. Optional native mirrors and
    unknown fields otherwise keep the shared definitions' defaults.
    """
    old_length = source.generic_header.header_length
    if length <= old_length:
        return {}
    seeds: dict[str, ChunkFieldValue] = {
        "db_track_id_2": source.header.db_track_id,
        "not_played_flag": 1 if desired.metadata.played else 2,
        "bookmark_time_2": desired.metadata.bookmark_time_ms,
        "has_artwork": int(source.header.artwork_count > 0),
        "video_flag_2": source.header.video_flag,
        "purchased_aac_flag_2": source.header.purchased_aac_flag,
    }
    values: dict[str, ChunkFieldValue] = {}
    for field in binary_fields(MhitHeader):
        schema = field.schema
        end = schema.offset + schema.size
        if end <= old_length or end > length:
            continue
        if schema.offset < old_length:
            if schema.encoding != "raw":
                raise ValueError(
                    "Cannot expand a Track header ending inside a numeric field."
                )
            # E.g. a 328-byte MHIT ends inside a declared opaque byte range.
            assert isinstance(schema.default, bytes)
            prefix = source.raw_header[schema.offset : old_length]
            values[field.attribute_name] = prefix + schema.default[len(prefix) :]
        elif field.attribute_name in seeds:
            values[field.attribute_name] = seeds[field.attribute_name]
    return values
