"""Selective inverse Track projection; retained fields are never normalized."""

import math
from collections.abc import Mapping
from dataclasses import fields, replace
from typing import Any

from iPodDB.device_time import TimeConversion, possible_unix_date, unix_to_mac
from iPodDB.iTunesDB.builder.build_iTunesDB import (
    new_itunes_chunk,
    new_string_mhod,
    new_url_mhod,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhit import DEFINITION as MHIT
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader, header_size_for_version
from iPodDB.iTunesDB.shared.chunk_defs.mhod import DEFINITION as MHOD
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.chapter_data_mhod import (
    ChapterDataFlags,
    MhodChapterDataChapter,
    MhodChapterDataHedrHeader,
    MhodChapterDataPayload,
    MhodChapterDataPreamble,
    MhodChapterDataSeanHeader,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.string_mhod import (
    MhodStringPayload,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.url_mhod import MhodUrlPayload
from iPodDB.iTunesDB.shared.constants import MhodType
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
from iPodDB.library._track_header_expansion import (
    creation_header_length,
    extension_values,
    field_fits,
    required_header_length,
)
from iPodDB.library.models import ContentAdvisory, MediaType, Track, TrackMetadata
from iPodDB.library.native_chapters import interpret_native_chapters
from iPodDB.library.writing import (
    IssueSeverity,
    PreparedLyrics,
    PreparedMedia,
    TimedArtworkAsset,
    WriteIssue,
)
from iPodDB.shared.binary_struct import binary_fields
from iPodDB.shared.chunk import ChunkHeader, ParsedChunk
from iPodDB.shared.chunk_field import ChunkFieldValue

_VIDEO_MIRROR = next(
    f.schema for f in binary_fields(MhitHeader) if f.attribute_name == "video_flag_2"
)
_NOT_PLAYED = next(
    f.schema for f in binary_fields(MhitHeader) if f.attribute_name == "not_played_flag"
)
_SORT_INDICATORS = next(
    f.schema
    for f in binary_fields(MhitHeader)
    if f.attribute_name == "sort_mhod_indicators"
)


def _chapter_hedr() -> MhodChapterDataHedrHeader:
    return MhodChapterDataHedrHeader(
        atom_type=b"hedr", unk_0x08=1, unk_0x18=ChapterDataFlags.HAS_NAMED_CHAPTERS
    )


def _coordinate_chapter_artwork(
    chunk: ParsedChunk[MhitHeader],
    asset: TimedArtworkAsset,
    track_id: int,
    issues: list[WriteIssue],
) -> ParsedChunk[MhitHeader]:
    matches = [
        i
        for i, child in enumerate(chunk.children)
        if isinstance(child.payload, MhodChapterDataPayload)
    ]
    if not matches:
        return chunk
    index = matches[-1]
    child = chunk.children[index]
    payload = child.payload_as(MhodChapterDataPayload)
    if (
        payload.hedr is None
        or payload.hedr_trailing_data
        or any(atom.atom_type == b"hedr" for atom in payload.other_atoms)
        or not any(
            chapter.name_header is not None or chapter.name
            for chapter in payload.chapters
        )
    ):
        issues.append(
            WriteIssue(
                "chapter.artwork_ineligible",
                "Timed artwork has no complete, recognized named Chapter header. The retained "
                "Chapter data is unchanged; Classic chapter artwork may be unavailable.",
                IssueSeverity.WARNING,
                subject="track",
                record_id=track_id,
                field="metadata.chapters",
            )
        )
        return chunk
    # Explicit timed artwork with authored named Chapters enables both known
    # gates. Unknown header bits and all Chapter positions/atoms stay retained.
    payload = replace(
        payload,
        hedr=replace(
            payload.hedr,
            unk_0x18=int(
                payload.hedr.flags
                | ChapterDataFlags.HAS_NAMED_CHAPTERS
                | ChapterDataFlags.HAS_CHAPTER_ARTWORK
            ),
        ),
    )
    native = interpret_native_chapters(payload)
    times = tuple(sorted(frame.display_time_ms for frame in asset.frames))
    if tuple(chapter.start_ms for chapter in native.entries) != times:
        issues.append(
            WriteIssue(
                "chapter.artwork_timeline_mismatch",
                "Named Chapter positions and artwork image times differ. Classic "
                "image refresh compares their indices; playback needs device "
                "validation. No positions were changed.",
                IssueSeverity.WARNING,
                subject="track",
                record_id=track_id,
                field="metadata.chapters",
            )
        )
    children = list(chunk.children)
    children[index] = replace(child, payload=payload)
    return replace(chunk, children=tuple(children))


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
            if kind in (MhodType.PODCAST_GUID, MhodType.PODCAST_RSS_URL)
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
    old: Track | None,
    new: Track,
    timezone_offset: TimeConversion = 0,
    *,
    check_date_encoding: bool = True,
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
        try:
            if check_date_encoding:
                unix_to_mac(value, timezone_offset, utc=attr == "release_date")
            elif not possible_unix_date(value):
                raise ValueError("This date is outside the supported Unix date range.")
        except ValueError as failure:
            error("metadata." + attr, str(failure))
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
    if (
        (old is None or old.metadata != meta)
        and (
            old is None
            or old.metadata.volume_adjustment_percent != meta.volume_adjustment_percent
        )
        and not -100 <= meta.volume_adjustment_percent <= 100
    ):
        error(
            "metadata.volume_adjustment_percent",
            "Volume adjustment must be between -100 and 100 percent.",
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
    timezone_offset: TimeConversion,
    media: PreparedMedia | None,
    issues: list[WriteIssue],
    *,
    lyrics: PreparedLyrics | None = None,
    database_version: int | None = None,
    required_fields: Mapping[str, ChunkFieldValue] | None = None,
    timed_artwork: TimedArtworkAsset | None = None,
) -> ParsedChunk[MhitHeader]:
    if chunk is None:
        length = creation_header_length(database_version)
        chunk = new_itunes_chunk(
            MHIT,
            MhitHeader(
                track_id=native_id,
                db_track_id=persistent_id,
                db_track_id_2=persistent_id
                if field_fits("db_track_id_2", length)
                else 0,
            ),
        )
        chunk = replace(
            chunk,
            generic_header=replace(chunk.generic_header, header_length=length),
            # Supply the selected extent explicitly; generic construction uses
            # the shared definition's default when no header buffer is present.
            raw_header=bytes(length),
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
            values[native] = unix_to_mac(
                value, timezone_offset, utc=attr == "release_date"
            )
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
    needs_explicit_played_field = (
        (
            _NOT_PLAYED.offset + _NOT_PLAYED.size > chunk.generic_header.header_length
            or header.not_played_flag not in (1, 2)
        )
        and meta.played != (new.play_count > 0)
        and (old is None or new.play_count != old.play_count)
    )
    if meta.played != prior.played or needs_explicit_played_field:
        if (
            _NOT_PLAYED.offset + _NOT_PLAYED.size <= chunk.generic_header.header_length
            or (
                meta.played != (new.play_count > 0)
                and database_version is not None
                and (
                    header_size_for_version(database_version)
                    >= _NOT_PLAYED.offset + _NOT_PLAYED.size
                )
            )
        ):
            values["not_played_flag"] = 1 if meta.played else 2
        elif meta.played != (new.play_count > 0):
            # Original-format headers derive played state from the play count.
            issues.append(
                WriteIssue(
                    "track.unstorable",
                    "This iPod's database format stores played state only "
                    "through the play count.",
                    subject="track",
                    record_id=new.track_id,
                    field="metadata.played",
                )
            )
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
            attr == "volume_adjustment_percent"
            and value is not None
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
    if (
        _SORT_INDICATORS.offset
        < chunk.generic_header.header_length
        < _SORT_INDICATORS.offset + _SORT_INDICATORS.size
    ):
        prefix = chunk.raw_header[_SORT_INDICATORS.offset :]
        indicators[: len(prefix)] = prefix
    original_indicators = bytes(indicators)
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
    if bytes(indicators) != original_indicators:
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
            # Earlier iOpenPod writes omitted hedr. Complete only that simple
            # shape with Original-compatible headers during an explicit chapter
            # edit; retain unfamiliar atoms.
            repair_app_chapters = (
                payload.hedr is None
                and bool(meta.chapters)
                and payload.preamble == (0, 0, 0)
                and payload.sean.unk_0x08 == 0
                and payload.sean.unk_0x10 == 0
                and not payload.other_atoms
                and not payload.sean_trailing_data
                and not payload.trailing_data
                and not any(
                    c.other_atoms or c.name_trailing_data or c.trailing_data
                    for c in payload.chapters
                )
            )
            children = list(chunk.children)
            children[index] = replace(
                child,
                payload=replace(
                    payload,
                    chapters=chapters,
                    sean=(
                        replace(
                            payload.sean,
                            unk_0x08=MhodChapterDataSeanHeader().unk_0x08,
                        )
                        if repair_app_chapters
                        else payload.sean
                    ),
                    hedr=_chapter_hedr() if repair_app_chapters else payload.hedr,
                    chapter_atom_indices=(
                        ()
                        if chapter_membership_changed or repair_app_chapters
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
                _chapter_hedr(),
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
    if timed_artwork is not None:
        chunk = _coordinate_chapter_artwork(chunk, timed_artwork, new.track_id, issues)
    if media is not None:
        values.update(
            filetype=media.filetype,
            mp3_flag=media.mp3_flag,
            av_flag=media.audio_format_flag,
            mpeg_audio_type=media.mpeg_audio_type,
            gapless_audio_payload_size=media.gapless_audio_payload_size,
        )
        if (
            old is None and field_fits("size_2", chunk.generic_header.header_length)
        ) or header.size_2:
            values["size_2"] = new.size_bytes
    if lyrics is not None:
        values["size"] = lyrics.file.size
        if (
            old is None and field_fits("size_2", chunk.generic_header.header_length)
        ) or header.size_2:
            values["size_2"] = lyrics.file.size
    length = required_header_length(
        chunk,
        {**values, **(required_fields or {})},
        database_version,
        # An absent marker falls back to play count, even though its parser
        # default is 2. Explicit unplayed state can therefore require growth.
        required_presence=frozenset({"not_played_flag"})
        if "not_played_flag" in values and meta.played != (new.play_count > 0)
        else frozenset(),
    )
    if (
        _SORT_INDICATORS.offset
        < length
        < _SORT_INDICATORS.offset + _SORT_INDICATORS.size
        and bytes(indicators) != original_indicators
    ):
        # A default-valued clear would otherwise be silently skipped by the
        # bounded binary writer, leaving the original partial flags in place.
        raise ValueError("Cannot store edited sort flags in this Track header.")
    if length > chunk.generic_header.header_length:
        seeds = extension_values(chunk, new, length)
        # An explicitly edited primary video flag also supplies its new mirror.
        if "video_flag_2" in seeds and "video_flag" in values:
            seeds["video_flag_2"] = values["video_flag"]
        values = {**seeds, **values}
        chunk = replace(
            chunk,
            generic_header=replace(chunk.generic_header, header_length=length),
            raw_header=chunk.raw_header.ljust(length, b"\0"),
        )
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
