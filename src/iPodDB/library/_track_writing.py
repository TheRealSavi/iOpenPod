"""Selective inverse Track projection; retained fields are never normalized."""

import math
from dataclasses import fields, replace
from typing import Any

from iPodDB.iTunesDB.builder.build_iTunesDB import (
    new_itunes_chunk,
    new_string_mhod,
    new_url_mhod,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhit import DEFINITION as MHIT
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod import DEFINITION as MHOD
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.chapter_data_mhod import (
    MhodChapterDataChapter,
    MhodChapterDataPayload,
    MhodChapterDataPreamble,
    MhodChapterDataSeanHeader,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.string_mhod import (
    MhodStringPayload,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.url_mhod import MhodUrlPayload
from iPodDB.iTunesDB.shared.constants import MhodType
from iPodDB.iTunesDB.shared.device_time import MAC_EPOCH_UNIX_OFFSET
from iPodDB.library._field_policy import (
    DATE_FIELDS,
    METADATA_FIELDS,
    METADATA_TEXT,
    TRACK_FIELDS,
    TRACK_POLICY,
    TRACK_TEXT,
    FieldOwnership,
    value_at,
)
from iPodDB.library._native_values import (
    encode_media_types,
    normalization_gain_from_native,
    normalization_gain_to_native,
    volume_adjustment_to_native,
)
from iPodDB.library._projection import unknown_media_bits
from iPodDB.library.models import ContentAdvisory, MediaType, Track, TrackMetadata
from iPodDB.library.writing import (
    IssueSeverity,
    PreparedLyrics,
    PreparedMedia,
    WriteIssue,
)
from iPodDB.shared.binary_struct import binary_fields
from iPodDB.shared.chunk import ChunkHeader, ParsedChunk

_VIDEO_MIRROR = next(
    f.schema for f in binary_fields(MhitHeader) if f.attribute_name == "video_flag_2"
)


def edit_text[H: ChunkHeader](
    chunk: ParsedChunk[H],
    kind: MhodType,
    value: str,
    *,
    first: bool = False,
) -> ParsedChunk[H]:
    children = list(chunk.children)
    matches = [
        i
        for i, child in enumerate(children)
        if isinstance(child.header, MhodHeader)
        and child.header.mhod_type == kind
        and isinstance(child.payload, MhodStringPayload | MhodUrlPayload)
    ]
    if matches:
        index = matches[0] if first else matches[-1]
        child = children[index]
        assert isinstance(child.payload, MhodStringPayload | MhodUrlPayload)
        children[index] = replace(child, payload=replace(child.payload, value=value))
    else:
        new = (
            new_url_mhod(kind, value)
            if kind in (MhodType.PODCAST_ENCLOSURE_URL, MhodType.PODCAST_RSS_URL)
            else new_string_mhod(kind, value)
        )
        # MHODs precede MHIPs in Playlist child groups.
        index = next(
            (
                i
                for i, child in enumerate(children)
                if child.generic_header.header_marker != b"mhod"
            ),
            len(children),
        )
        children.insert(index, new)
    return replace(chunk, children=tuple(children))


def validate_track(
    old: Track | None, new: Track, timezone_offset: int = 0
) -> tuple[WriteIssue, ...]:
    issues: list[WriteIssue] = []

    def error(field: str, message: str) -> None:
        issues.append(
            WriteIssue(
                "track.invalid_value",
                message,
                subject="track",
                record_id=new.track_id,
                field=field,
            )
        )

    baseline = old or Track(new.track_id, "", "", "", 0)
    for policy in TRACK_POLICY:
        if policy.ownership in (
            FieldOwnership.DERIVED,
            FieldOwnership.RETAINED,
        ) and value_at(new, policy.path) != value_at(baseline, policy.path):
            error(
                policy.path,
                "This field is derived or retained; edit "
                + (", ".join(policy.dependencies) or "the corresponding Library fields")
                + " instead.",
            )
    for owner, prior, prefix in (
        (new, old, ""),
        (new.metadata, old.metadata if old else None, "metadata."),
    ):
        for item in fields(owner):
            value = getattr(owner, item.name)
            if prior is not None and value == getattr(prior, item.name):
                continue
            if isinstance(value, str):
                try:
                    value.encode("utf-16-le")
                except UnicodeEncodeError:
                    error(
                        prefix + item.name,
                        "Text contains an invalid Unicode character.",
                    )
            if isinstance(value, float) and not math.isfinite(value):
                error(prefix + item.name, "Use a finite number.")
    if (old is None or old.rating != new.rating) and not 0 <= new.rating <= 100:
        error("rating", "Rating must be between 0 and 100.")
    schemas = {f.attribute_name: f.schema for f in binary_fields(MhitHeader)}
    for owner, prior_owner, mapping, prefix in (
        (new, old, TRACK_FIELDS, ""),
        (new.metadata, old.metadata if old else None, METADATA_FIELDS, "metadata."),
    ):
        for attr, native in mapping.items():
            value = getattr(owner, attr)
            if prior_owner is not None and value == getattr(prior_owner, attr):
                continue
            schema = schemas[native]
            if not 0 <= value < 1 << (schema.size * 8):
                error(
                    prefix + attr,
                    f"This value must fit an unsigned {schema.size * 8}-bit field.",
                )
    for attr in DATE_FIELDS:
        value = getattr(new.metadata, attr)
        if old is not None and value == getattr(old.metadata, attr):
            continue
        if not -86400 < timezone_offset < 86400:
            error(
                "metadata." + attr,
                "The source timezone is invalid; this date cannot be edited reliably.",
            )
        elif (
            value
            and not 0 < value + MAC_EPOCH_UNIX_OFFSET + timezone_offset <= 0xFFFFFFFF
        ):
            error(
                "metadata." + attr, "This date is outside the unsigned iPod date range."
            )
    meta = new.metadata
    if (
        old is None
        or old.length_ms != new.length_ms
        or any(
            getattr(old.metadata, field) != getattr(meta, field)
            for field in ("start_time_ms", "stop_time_ms", "bookmark_time_ms")
        )
    ):
        if (
            meta.start_time_ms < 0
            or meta.stop_time_ms < 0
            or (meta.stop_time_ms and meta.stop_time_ms < meta.start_time_ms)
        ):
            error("metadata.stop_time_ms", "Playback end must follow playback start.")
        if (
            meta.start_time_ms > new.length_ms
            or meta.stop_time_ms > new.length_ms
            or meta.bookmark_time_ms > new.length_ms
        ):
            error(
                "metadata.start_time_ms",
                "Playback positions must fit within the Track duration.",
            )
    if old is None or old.metadata != meta:
        if (
            old is None
            or old.metadata.volume_adjustment_percent != meta.volume_adjustment_percent
        ) and not -100 <= meta.volume_adjustment_percent <= 100:
            error(
                "metadata.volume_adjustment_percent",
                "Volume adjustment must be between -100 and 100 percent.",
            )
        if (
            meta.played is False
            and new.play_count > 0
            and (old is None or old.metadata.played != meta.played)
        ):
            error(
                "metadata.played",
                "A Track with a positive play count cannot be marked unplayed.",
            )
    if (
        old is None
        or old.length_ms != new.length_ms
        or old.metadata.chapters != meta.chapters
    ):
        positions = tuple(chapter.start_ms for chapter in meta.chapters)
        if positions != tuple(sorted(positions)) or any(
            p < 0 or p > new.length_ms for p in positions
        ):
            error(
                "metadata.chapters",
                "Chapter positions must be ordered and fit within the Track duration.",
            )
    return tuple(issues)


def edit_track(
    chunk: ParsedChunk[MhitHeader] | None,
    old: Track | None,
    new: Track,
    native_id: int,
    persistent_id: int,
    timezone_offset: int,
    media: PreparedMedia | None,
    issues: list[WriteIssue],
    *,
    lyrics: PreparedLyrics | None = None,
) -> ParsedChunk[MhitHeader]:
    if chunk is None:
        chunk = new_itunes_chunk(
            MHIT,
            MhitHeader(
                track_id=native_id,
                db_track_id=persistent_id,
                db_track_id_2=persistent_id,
            ),
        )
    header = chunk.header
    values: dict[str, Any] = {}
    for attr, kind in TRACK_TEXT.items():
        value = getattr(new, attr)
        if old is None or value != getattr(old, attr):
            chunk = edit_text(chunk, kind, value)
    for attr, native in TRACK_FIELDS.items():
        value = getattr(new, attr)
        if old is None or value != getattr(old, attr):
            values[native] = value
    meta = new.metadata
    prior = old.metadata if old else TrackMetadata()
    for attr, kind in METADATA_TEXT.items():
        value = getattr(meta, attr)
        if value != getattr(prior, attr):
            if attr == "location":
                value = ":" + value.replace("/", ":")
            chunk = edit_text(chunk, kind, value)
    for attr, native in METADATA_FIELDS.items():
        value = getattr(meta, attr)
        if value != getattr(prior, attr):
            values[native] = int(value) if isinstance(value, bool) else value
    for attr, native in DATE_FIELDS.items():
        value = getattr(meta, attr)
        if value != getattr(prior, attr):
            if not -86400 < timezone_offset < 86400:
                raise ValueError(
                    "The source timezone is invalid; dates cannot be edited reliably."
                )
            encoded = value + MAC_EPOCH_UNIX_OFFSET + timezone_offset if value else 0
            if value and not 0 < encoded <= 0xFFFFFFFF:
                raise ValueError(f"{attr} is outside the iPod date range.")
            values[native] = encoded
    if old is None or new.media_types != old.media_types:
        values["media_type"] = encode_media_types(
            new.media_types,
            retained_unknown_bits=unknown_media_bits(header.media_type),
        )
        values["video_flag"] = int(
            any(
                kind in new.media_types
                for kind in (
                    MediaType.VIDEO,
                    MediaType.AUDIO_VIDEO,
                    MediaType.MUSIC_VIDEO,
                    MediaType.TV_SHOW,
                    MediaType.VIDEO_PODCAST,
                )
            )
        )
        if (
            _VIDEO_MIRROR.offset + _VIDEO_MIRROR.size
            <= chunk.generic_header.header_length
        ):
            values["video_flag_2"] = values["video_flag"]
    if meta.sample_rate_hz != prior.sample_rate_hz:
        values["sample_rate_1"] = meta.sample_rate_hz << 16
        values["sample_rate_2"] = float(meta.sample_rate_hz)
    if meta.checked != prior.checked or old is None:
        values["checked_flag"] = int(not meta.checked)
    if meta.played != prior.played:
        values["not_played_flag"] = 1 if meta.played else 2
    if meta.content_advisory != prior.content_advisory:
        values["explicit_flag"] = {
            ContentAdvisory.UNSPECIFIED: 0,
            ContentAdvisory.EXPLICIT: 1,
            ContentAdvisory.CLEAN: 2,
        }[meta.content_advisory]
    for attr in ("volume_adjustment_percent", "normalization_gain_db"):
        value = getattr(meta, attr)
        if value == getattr(prior, attr):
            continue
        if attr == "volume_adjustment_percent":
            encoded = volume_adjustment_to_native(value)
            actual: float | None = encoded / 255 * 100
            values["volume"] = encoded
        else:
            encoded = normalization_gain_to_native(value)
            actual = normalization_gain_from_native(encoded)
            values["sound_check"] = encoded
        if (
            value is not None
            and actual is not None
            and not math.isclose(value, actual, abs_tol=1e-9)
        ):
            issues.append(
                WriteIssue(
                    "track.quantized",
                    f"The iPod will store {actual:.6g} for {attr}.",
                    IssueSeverity.WARNING,
                    subject="track",
                    record_id=new.track_id,
                    field="metadata." + attr,
                )
            )
    if meta.lyrics != prior.lyrics:
        values["lyrics_flag"] = int(bool(meta.lyrics))
    indicators = bytearray(header.sort_mhod_indicators)
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
        if getattr(meta, name) != getattr(prior, name):
            # Only bit zero describes override presence. Retain collation and
            # other source bits even when the sort text changes or is cleared.
            indicators[index] = (indicators[index] & ~1) | int(
                bool(getattr(meta, name))
            )
    if bytes(indicators) != header.sort_mhod_indicators:
        values["sort_mhod_indicators"] = bytes(indicators)
    if meta.chapters != prior.chapters:
        matches = [
            i
            for i, child in enumerate(chunk.children)
            if isinstance(child.payload, MhodChapterDataPayload)
        ]
        if matches:
            index = matches[-1]
            child = chunk.children[index]
            payload = child.payload
            assert isinstance(payload, MhodChapterDataPayload)
            # Positional chapter edits retain each chapter's unknown atoms. A
            # structural edit with opaque chapter data cannot safely rebind it.
            chapter_membership_changed = len(meta.chapters) != len(payload.chapters)
            if chapter_membership_changed and (
                payload.other_atoms
                or any(c.other_atoms or c.trailing_data for c in payload.chapters)
            ):
                raise ValueError(
                    "Chapter membership cannot change while unknown chapter data needs preservation."
                )
            chapters = tuple(
                replace(payload.chapters[i], name=c.title, start_pos_ms=c.start_ms)
                if i < len(payload.chapters)
                else MhodChapterDataChapter(c.title, c.start_ms, ())
                for i, c in enumerate(meta.chapters)
            )
            children = list(chunk.children)
            children[index] = replace(
                child,
                payload=replace(
                    payload,
                    chapters=chapters,
                    chapter_atom_indices=(
                        ()
                        if chapter_membership_changed
                        else payload.chapter_atom_indices
                    ),
                    hedr_atom_index=(
                        None if chapter_membership_changed else payload.hedr_atom_index
                    ),
                ),
            )
            chunk = replace(chunk, children=tuple(children))
        elif meta.chapters:
            payload = MhodChapterDataPayload(
                MhodChapterDataPreamble(0, 0, 0),
                MhodChapterDataSeanHeader(atom_type=b"sean"),
                None,
                tuple(
                    MhodChapterDataChapter(c.title, c.start_ms, ())
                    for c in meta.chapters
                ),
                (),
            )
            chunk = chunk.append_child(
                new_itunes_chunk(
                    MHOD, MhodHeader(mhod_type=MhodType.CHAPTER_DATA), payload=payload
                )
            )
    if media is not None:
        values.update(
            filetype=media.filetype,
            mp3_flag=media.mp3_flag,
            av_flag=media.audio_format_flag,
            mpeg_audio_type=media.mpeg_audio_type,
            gapless_audio_payload_size=media.gapless_audio_payload_size,
        )
        if old is None or header.size_2:
            values["size_2"] = new.size_bytes
    if lyrics is not None:
        values["size"] = lyrics.file.size
        if old is None or header.size_2:
            values["size_2"] = lyrics.file.size
    result = replace(chunk, header=replace(header, **values))
    # Aggregate representability errors for every changed fixed field.
    for field in binary_fields(result.header):
        if field.attribute_name not in values:
            continue
        value = getattr(result.header, field.attribute_name)
        schema = field.schema
        if isinstance(value, int) and schema.encoding != "raw":
            signed = "i" in schema.encoding
            bits = schema.size * 8
            low, high = (
                (-(1 << (bits - 1)), (1 << (bits - 1)) - 1)
                if signed
                else (0, (1 << bits) - 1)
            )
            if not low <= value <= high:
                issues.append(
                    WriteIssue(
                        "track.field_range",
                        f"{field.attribute_name} is outside its {bits}-bit range.",
                        subject="track",
                        record_id=new.track_id,
                        field=field.attribute_name,
                    )
                )
    return result
