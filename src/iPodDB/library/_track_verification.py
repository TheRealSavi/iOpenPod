"""Verify native Track identities and media facts hidden by semantic projection."""

import hashlib
import math
from dataclasses import replace

from iPodDB.device_time import TimeConversion
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.library._track_header_expansion import (
    creation_header_length,
    extension_values,
    field_fits,
    required_header_length,
)
from iPodDB.library._track_header_requirements import derived_header_requirements
from iPodDB.library._track_header_verification import (
    track_field_expectations,
    unmodeled_header_ranges,
)
from iPodDB.library.models import LibrarySnapshot, MediaKind
from iPodDB.library.writing import IdentityMapping, WriteIssue, WriteResources
from iPodDB.shared.binary_struct import binary_fields
from iPodDB.shared.chunk import DatabaseDocument
from iPodDB.shared.chunk_field import ChunkFieldValue

_SAMPLE_RATE_2 = next(
    f.schema for f in binary_fields(MhitHeader) if f.attribute_name == "sample_rate_2"
)


def verify_native_tracks(
    original: DatabaseDocument[MhbdHeader],
    checked: DatabaseDocument[MhbdHeader],
    before: LibrarySnapshot,
    desired: LibrarySnapshot,
    mappings: tuple[IdentityMapping, ...],
    resources: WriteResources,
    device_time: TimeConversion = 0,
    *,
    database_version: int | None = None,
    artwork_tracks: tuple[int, ...] = (),
    normalize_podcasts: bool = False,
) -> tuple[WriteIssue, ...]:
    """Compare reparsed fields with source identities and captured caller facts.

    Existing noncanonical values remain valid when their dependency is unchanged.
    New persistent identities cannot reuse either source identity, even for a
    deleted Track. Allocation decisions are not used as verification expectations.
    """
    source_chunks = {
        s.chunk.header.track_id: s.chunk for s in original.find_chunks(MhitHeader)
    }
    source = {identity: chunk.header for identity, chunk in source_chunks.items()}
    output = {s.chunk.header.track_id: s for s in checked.find_chunks(MhitHeader)}
    previous = {t.track_id: t for t in before.tracks}
    identities = {m.draft_id: m.output_id for m in mappings if m.subject == "track"}
    media = {m.track_id: m for m in resources.media}
    lyrics = {item.track_id: item for item in resources.lyrics}
    reserved = {
        identity
        for h in source.values()
        for identity in (h.db_track_id, h.db_track_id_2)
    }
    allocated: set[int] = set()
    issues: list[WriteIssue] = []
    header_requirements = derived_header_requirements(
        original, before, desired, database_version, artwork_tracks
    )
    expanded = False
    for track in desired.tracks:
        tagged = lyrics.get(track.track_id)
        if tagged is not None:
            track = replace(track, size_bytes=tagged.file.size)
        selection = output.get(identities.get(track.track_id, track.track_id))
        if selection is None:
            continue  # The semantic verification reports the missing Track.
        output_chunk = selection.chunk
        actual = output_chunk.header
        prior = source.get(track.track_id)
        prior_track = previous.get(track.track_id)
        original_chunk = source_chunks.get(track.track_id)
        expected_fields = track_field_expectations(
            original_chunk, prior_track, track, device_time, database_version
        )
        if (
            normalize_podcasts
            and (track.media_kind is MediaKind.PODCAST or track.metadata.podcast)
            and field_fits("db_id_2_ref", output_chunk.generic_header.header_length)
        ):
            expected_fields["db_id_2_ref"] = (
                original.header.db_id_2 or checked.header.db_id_2
            )
        prepared = media.get(track.track_id)
        if prepared is not None:
            expected_fields.update(
                mpeg_audio_type=prepared.mpeg_audio_type,
                gapless_audio_payload_size=prepared.gapless_audio_payload_size,
            )

        def error(
            field: str,
            expected: ChunkFieldValue | str,
            value: ChunkFieldValue | str,
            *,
            record_id: int = track.track_id,
            native_id: int = actual.track_id,
            offset: int = output_chunk.offset,
        ) -> None:
            issues.append(
                WriteIssue(
                    "verification.track_native",
                    "Prepared Track has inconsistent native identity or media facts.",
                    phase="verification",
                    subject="track",
                    record_id=record_id,
                    field=field,
                    detail=f"Native Track {native_id}: expected {expected!r}; actual {value!r}.",
                    offset=offset,
                    artifact="iTunesDB",
                )
            )

        def check(
            field: str, expected: ChunkFieldValue, value: ChunkFieldValue
        ) -> None:
            # Retained diagnostics may contain NaN. It is not a new mismatch
            # merely because Python considers NaN unequal to itself.
            unchanged_nan = (
                isinstance(expected, float)
                and isinstance(value, float)
                and math.isnan(expected)
                and math.isnan(value)
            )
            if value != expected and not unchanged_nan:
                error(field, expected, value)

        extension: dict[str, ChunkFieldValue] = {}
        if original_chunk is not None:
            extent_fields = dict(expected_fields)
            for binary_field in binary_fields(MhitHeader):
                schema = binary_field.schema
                if schema.encoding != "raw" or not (
                    schema.offset
                    < original_chunk.generic_header.header_length
                    < schema.offset + schema.size
                ):
                    continue
                # Native byte changes, rather than text changes or parser
                # defaults, decide whether this partial field needs growth.
                assert isinstance(schema.default, bytes)
                prefix = original_chunk.raw_header[schema.offset :]
                retained = prefix + schema.default[len(prefix) :]
                if expected_fields.get(binary_field.attribute_name) == retained:
                    extent_fields.pop(binary_field.attribute_name, None)
            length = required_header_length(
                original_chunk,
                {**extent_fields, **header_requirements.get(track.track_id, {})},
                database_version,
            )
            check("header_length", length, output_chunk.generic_header.header_length)
            expanded |= length > original_chunk.generic_header.header_length
            try:
                extension = extension_values(original_chunk, track, length)
            except ValueError as failure:
                error(
                    "header_length",
                    str(failure),
                    output_chunk.generic_header.header_length,
                )
            if "video_flag_2" in extension:
                extension["video_flag_2"] = expected_fields["video_flag"]
            if (
                "sort_mhod_indicators" in extension
                and "sort_mhod_indicators" in extent_fields
            ):
                extension["sort_mhod_indicators"] = expected_fields[
                    "sort_mhod_indicators"
                ]
            expected_fields.update(
                {
                    name: value
                    for name, value in extension.items()
                    # Artwork reconciliation owns fields excluded above.
                    if name in expected_fields
                }
            )
        if prior is not None:
            check("db_track_id", prior.db_track_id, actual.db_track_id)
            check(
                "db_track_id_2",
                extension.get("db_track_id_2", prior.db_track_id_2),
                actual.db_track_id_2,
            )
        else:
            length = creation_header_length(database_version)
            check("header_length", length, output_chunk.generic_header.header_length)
            expanded = True
            if (
                not actual.db_track_id
                or actual.db_track_id in reserved
                or actual.db_track_id in allocated
            ):
                error(
                    "db_track_id",
                    "an unused nonzero persistent identity",
                    actual.db_track_id,
                )
            allocated.add(actual.db_track_id)
            check(
                "db_track_id_2",
                actual.db_track_id if field_fits("db_track_id_2", length) else 0,
                actual.db_track_id_2,
            )

        if prepared is not None:
            check("filetype", prepared.filetype, actual.filetype)
            check("mp3_flag", prepared.mp3_flag, actual.mp3_flag)
            check("av_flag", prepared.audio_format_flag, actual.av_flag)
            check("mpeg_audio_type", prepared.mpeg_audio_type, actual.mpeg_audio_type)
            check(
                "gapless_audio_payload_size",
                prepared.gapless_audio_payload_size,
                actual.gapless_audio_payload_size,
            )
            check("size", prepared.file.size, actual.size)
            # The secondary size is optional in retained source formats.
            check(
                "size_2",
                track.size_bytes
                if (
                    prior is None
                    and field_fits("size_2", creation_header_length(database_version))
                )
                or (prior is not None and prior.size_2)
                else 0,
                actual.size_2,
            )
        elif prior is not None:
            check("filetype", prior.filetype, actual.filetype)
            check("mp3_flag", prior.mp3_flag, actual.mp3_flag)
            check("av_flag", prior.av_flag, actual.av_flag)
            check("mpeg_audio_type", prior.mpeg_audio_type, actual.mpeg_audio_type)
            check(
                "gapless_audio_payload_size",
                prior.gapless_audio_payload_size,
                actual.gapless_audio_payload_size,
            )
            check(
                "size_2",
                tagged.file.size
                if tagged is not None and prior.size_2
                else prior.size_2,
                actual.size_2,
            )

        if (
            prior_track is None
            or track.metadata.sample_rate_hz != prior_track.metadata.sample_rate_hz
        ):
            check(
                "sample_rate_2",
                float(track.metadata.sample_rate_hz),
                actual.sample_rate_2,
            )
        elif prior is not None:
            check("sample_rate_2", prior.sample_rate_2, actual.sample_rate_2)
        schemas = {f.attribute_name: f.schema for f in binary_fields(MhitHeader)}
        for field, expected in expected_fields.items():
            schema = schemas[field]
            if (
                schema.encoding == "raw"
                and schema.offset
                < len(output_chunk.raw_header)
                < schema.offset + schema.size
            ):
                assert isinstance(schema.default, bytes)
                prefix = output_chunk.raw_header[schema.offset :]
                check(field, expected, prefix + schema.default[len(prefix) :])
            else:
                check(field, expected, getattr(actual, field))
        original_header = original_chunk.raw_header if original_chunk else b""
        output_header = output_chunk.raw_header
        float_start = _SAMPLE_RATE_2.offset
        float_end = float_start + _SAMPLE_RATE_2.size
        if (
            prior_track is not None
            and track.metadata.sample_rate_hz == prior_track.metadata.sample_rate_hz
            and len(original_header) >= float_end
        ):
            # Float equality hides signed zero and NaN payload/signaling bits.
            # An unchanged dependency must preserve their exact source encoding.
            check(
                "sample_rate_2",
                original_header[float_start:float_end],
                output_header[float_start:float_end],
            )
        if len(output_header) < len(original_header):
            error(
                "raw_header",
                f"at least {len(original_header)} bytes",
                len(output_header),
            )
        for start, end in unmodeled_header_ranges(len(output_header)):
            expected_bytes = original_header[start:end].ljust(end - start, b"\0")
            actual_bytes = output_header[start:end]
            if actual_bytes != expected_bytes:
                error(
                    "raw_header",
                    f"SHA-256 {hashlib.sha256(expected_bytes).hexdigest()} for header range 0x{start:X}:0x{end:X}",
                    hashlib.sha256(actual_bytes).hexdigest(),
                    offset=selection.chunk.offset + start,
                )
    expected_version = (
        max(original.header.version, database_version)
        if expanded and database_version is not None
        else original.header.version
    )
    if checked.header.version != expected_version:
        issues.append(
            WriteIssue(
                "verification.database_version",
                "Prepared database has an unexpected format version.",
                phase="verification",
                field="version",
                artifact="iTunesDB",
            )
        )
    return tuple(issues)
