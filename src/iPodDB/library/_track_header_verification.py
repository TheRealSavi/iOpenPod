"""Native expectations that semantic Track projection cannot prove by itself."""

from functools import lru_cache

from iPodDB.iTunesDB.shared.chunk_defs.mhit import DEFINITION as MHIT
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.device_time import MAC_EPOCH_UNIX_OFFSET
from iPodDB.library._field_policy import DATE_FIELDS, METADATA_FIELDS, TRACK_FIELDS
from iPodDB.library._native_values import (
    encode_media_types,
    normalization_gain_to_native,
    volume_adjustment_to_native,
)
from iPodDB.library._projection import unknown_media_bits
from iPodDB.library.models import ContentAdvisory, MediaType, Track
from iPodDB.shared.binary_struct import binary_fields
from iPodDB.shared.chunk import GenericHeader, ParsedChunk
from iPodDB.shared.chunk_field import ChunkFieldValue

_VIDEO_MIRROR = next(
    f.schema for f in binary_fields(MhitHeader) if f.attribute_name == "video_flag_2"
)

# Identity, resource and browse-group verifiers establish these independently.
_VERIFIED_SEPARATELY = frozenset(
    (
        "child_count",
        "track_id",
        "db_track_id",
        "db_track_id_2",
        "filetype",
        "mp3_flag",
        "av_flag",
        "mpeg_audio_type",
        "gapless_audio_payload_size",
        "size_2",
        "sample_rate_2",
        "album_id",
        "artist_id_ref",
        "composer_id",
    )
)


@lru_cache(maxsize=16)
def unmodeled_header_ranges(length: int) -> tuple[tuple[int, int], ...]:
    """Header gaps and future extensions, located only from shared definitions."""
    ranges: list[tuple[int, int]] = []
    cursor = 0
    for start, end in sorted(
        (f.schema.offset, f.schema.offset + f.schema.size)
        for header in (GenericHeader, MhitHeader)
        for f in binary_fields(header)
    ):
        if cursor >= length:
            break
        if start > cursor:
            ranges.append((cursor, min(start, length)))
        cursor = max(cursor, end)
    if cursor < length:
        ranges.append((cursor, length))
    return tuple(ranges)


def track_field_expectations(
    source: ParsedChunk[MhitHeader] | None,
    before: Track | None,
    desired: Track,
    timezone_offset: int,
) -> dict[str, ChunkFieldValue]:
    """Retain every defined field unless its semantic dependency changed.

    New fields start with shared Chunk Definition defaults. This verifier uses
    source data and resolved intent, never an edited header or writer output.
    Artwork and group relationships have their own verification paths.
    """
    prior = source.header if source else None
    expected: dict[str, ChunkFieldValue] = {
        f.attribute_name: getattr(prior, f.attribute_name)
        if prior is not None
        else f.schema.default
        for f in binary_fields(MhitHeader)
        if f.attribute_name not in _VERIFIED_SEPARATELY
    }
    for owner, old, mapping in (
        (desired, before, TRACK_FIELDS),
        (desired.metadata, before.metadata if before else None, METADATA_FIELDS),
    ):
        for name, native in mapping.items():
            value = getattr(owner, name)
            if old is None or value != getattr(old, name):
                expected[native] = int(value) if isinstance(value, bool) else value

    meta = desired.metadata

    def changed(name: str) -> bool:
        return before is None or getattr(meta, name) != getattr(before.metadata, name)

    for name, native in DATE_FIELDS.items():
        if changed(name):
            value = getattr(meta, name)
            expected[native] = (
                value + MAC_EPOCH_UNIX_OFFSET + timezone_offset if value else 0
            )
    if changed("sample_rate_hz"):
        expected["sample_rate_1"] = meta.sample_rate_hz << 16
    if changed("checked"):
        expected["checked_flag"] = int(not meta.checked)
    if changed("played"):
        expected["not_played_flag"] = 1 if meta.played else 2
    if changed("content_advisory"):
        expected["explicit_flag"] = {
            ContentAdvisory.UNSPECIFIED: 0,
            ContentAdvisory.EXPLICIT: 1,
            ContentAdvisory.CLEAN: 2,
        }[meta.content_advisory]
    if changed("volume_adjustment_percent"):
        expected["volume"] = volume_adjustment_to_native(meta.volume_adjustment_percent)
    if changed("normalization_gain_db"):
        expected["sound_check"] = normalization_gain_to_native(
            meta.normalization_gain_db
        )
    if changed("lyrics"):
        expected["lyrics_flag"] = int(bool(meta.lyrics))

    if before is None or desired.media_types != before.media_types:
        expected["media_type"] = encode_media_types(
            desired.media_types,
            retained_unknown_bits=unknown_media_bits(prior.media_type) if prior else 0,
        )
        expected["video_flag"] = int(
            bool(
                set(desired.media_types)
                & {
                    MediaType.VIDEO,
                    MediaType.AUDIO_VIDEO,
                    MediaType.MUSIC_VIDEO,
                    MediaType.TV_SHOW,
                    MediaType.VIDEO_PODCAST,
                }
            )
        )
        header_length = (
            source.generic_header.header_length if source else MHIT.default_header_size
        )
        if _VIDEO_MIRROR.offset + _VIDEO_MIRROR.size <= header_length:
            expected["video_flag_2"] = expected["video_flag"]

    indicators = bytearray((prior or MhitHeader()).sort_mhod_indicators)
    for index, name in enumerate(
        (
            "sort_title",
            "sort_album",
            "sort_artist",
            "sort_album_artist",
            "sort_composer",
            "sort_show",
        )
    ):
        if changed(name):
            indicators[index] = (indicators[index] & ~1) | int(
                bool(getattr(meta, name))
            )
    expected["sort_mhod_indicators"] = bytes(indicators)
    if before is None or desired.artwork_id != before.artwork_id:
        for name in ("artwork_id_ref", "artwork_count", "artwork_size", "has_artwork"):
            expected.pop(name)
    return expected
