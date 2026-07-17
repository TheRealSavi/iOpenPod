"""
ArtworkDB Writer for iPod Classic.

Writes the ArtworkDB binary file and associated .ithmb image files.

Artwork format ownership is deliberately conservative: required device
formats and known extra formats already present on-device are the writer's
normal rewrite targets when image data changes. Preserve-only passes keep
valid existing offsets in place, while unknown formats are logged and
preserved without decoding or rewriting. Format IDs resolve global-first,
with narrow device overrides supplied by the registry layer.

ArtworkDB structure:
    mhfd (file header)
      mhsd type=1 → mhli → mhii[] (image entries, one per unique album art)
        Each mhii has MHOD type=2 children containing MHNI (one per image format)
        Each MHNI has an MHOD type=3 child with the ithmb filename
      mhsd type=2 → mhla (empty, not used for music artwork)
      mhsd type=3 → mhlf → mhif[] (one per image format, describes ithmb file sizes)
"""

from __future__ import annotations

import logging
import os
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from iopenpod.artworkdb_shared.ithmb_paths import ithmb_filename, ithmb_filename_from_path
from iopenpod.device import ITHMB_FORMAT_MAP, ArtworkFormat
from iopenpod.device.durability import (
    durable_replace,
    durable_unlink,
    flush_written_file,
    open_unique_sibling_temp,
)
from iopenpod.device.path_safety import resolve_device_path

from .art_extractor import (
    art_hash,
    extract_art_with_source,
)
from .art_extractor import (
    extract_art_with_folder as _extract_art_with_folder,
)
from .artwork_types import (
    ArtworkEntry,
    ArtworkFormatPayload,
    ArtworkPayload,
    EncodedFormatPayload,
    ExistingFormatRef,
    IthmbLocation,
    PassthroughFormatRef,
)
from .artworkdb_chunks import build_artworkdb, read_existing_artwork
from .ithmb_codecs import (
    decode_pixels_for_format,
    default_stride_pixels,
    encode_image_for_format,
    expected_size_bytes,
    format_dimensions,
)
from .rgb565 import get_artwork_format_definitions, get_artwork_formats, image_from_bytes

logger = logging.getLogger(__name__)

ITHMB_MAX_SIZE_BYTES = 32 * 1000 * 1000
"""Performance budget for one mutable ITHMB shard before opening the next N."""

# Backward-compatible test/downstream hook. Production extraction uses
# ``extract_art_with_source`` unless this symbol has been monkeypatched.
extract_art_with_folder = _extract_art_with_folder


def _ithmb_filename(format_id: int, index: int) -> str:
    return ithmb_filename(format_id, index)


def _ithmb_filename_from_path(path: str, format_id: int) -> str:
    return ithmb_filename_from_path(path, format_id)


def _ithmb_file_index(filename: str, format_id: int) -> int | None:
    """Return N from the canonical ``F{format_id}_N.ithmb`` filename."""
    prefix = f"F{int(format_id)}_"
    suffix = ".ithmb"
    if not filename.startswith(prefix) or not filename.endswith(suffix):
        return None
    raw_index = filename[len(prefix) : -len(suffix)]
    try:
        return int(raw_index)
    except ValueError:
        return None


def _select_ithmb_rewrite_plan(
    existing_art: Mapping[int, dict],
    decisions: Mapping[int, TrackArtworkDecision],
    new_artwork: Mapping[ArtworkAssetRef, ArtworkPayload],
) -> tuple[dict[int, set[str]], dict[int, int]]:
    """Choose the lowest numbered file that can hold each new artwork format."""
    indexed_filenames: dict[int, dict[int, str]] = defaultdict(dict)
    for entry in existing_art.values():
        for raw_format_id, ref in entry.get("formats", {}).items():
            format_id = int(raw_format_id)
            filename = ref.ithmb_filename or _ithmb_filename_from_path(ref.path, format_id)
            index = _ithmb_file_index(filename, format_id)
            if index is not None and index >= 1:
                indexed_filenames[format_id][index] = filename

    preserved_bytes_by_file: dict[tuple[int, str], int] = defaultdict(int)
    seen_preserved_assets: set[ArtworkAssetRef] = set()
    for decision in decisions.values():
        if decision.kind not in (
            ArtworkDecisionKind.PRESERVE_EXISTING,
            ArtworkDecisionKind.PRESERVE_FALLBACK,
        ):
            continue
        if decision.asset_ref is None or decision.existing_entry is None:
            continue
        if decision.asset_ref in seen_preserved_assets:
            continue
        seen_preserved_assets.add(decision.asset_ref)
        for raw_format_id, ref in decision.existing_entry.get("formats", {}).items():
            format_id = int(raw_format_id)
            filename = ref.ithmb_filename or _ithmb_filename_from_path(ref.path, format_id)
            if _ithmb_file_index(filename, format_id) is not None:
                preserved_bytes_by_file[(format_id, filename)] += int(ref.size)

    new_payload_sizes_by_format: dict[int, list[int]] = defaultdict(list)
    for payload in new_artwork.values():
        for format_id, format_payload in payload.formats.items():
            if isinstance(format_payload, EncodedFormatPayload):
                new_payload_sizes_by_format[format_id].append(int(format_payload.size))

    rewrite_filenames: dict[int, set[str]] = {}
    writable_start_indices: dict[int, int] = {}
    for format_id, payload_sizes in new_payload_sizes_by_format.items():
        filenames = indexed_filenames.get(format_id, {})
        max_existing_index = max(filenames, default=0)
        total_new_bytes = sum(payload_sizes)
        largest_new_payload = max(payload_sizes)
        for index in range(1, max_existing_index + 2):
            filename = filenames.get(index, _ithmb_filename(format_id, index))
            total_bytes = preserved_bytes_by_file[(format_id, filename)] + total_new_bytes
            if total_bytes <= ITHMB_MAX_SIZE_BYTES:
                rewrite_filenames[format_id] = {filename}
                writable_start_indices[format_id] = index - 1
                break
        else:
            # A bulk sync can need more than one file. Start with the lowest
            # file that can hold one artwork payload; the writer opens the next
            # available number only after this one reaches its size budget.
            for index in range(1, max_existing_index + 2):
                filename = filenames.get(index, _ithmb_filename(format_id, index))
                total_bytes = (
                    preserved_bytes_by_file[(format_id, filename)]
                    + largest_new_payload
                )
                if total_bytes <= ITHMB_MAX_SIZE_BYTES:
                    rewrite_filenames[format_id] = {filename}
                    writable_start_indices[format_id] = index - 1
                    break
            else:
                raise RuntimeError(
                    f"Artwork format {format_id} has a {largest_new_payload}-byte "
                    f"payload, exceeding the {ITHMB_MAX_SIZE_BYTES}-byte ITHMB "
                    "file limit."
                )

    return rewrite_filenames, writable_start_indices


@dataclass
class PendingArtworkWrite:
    """Result of a deferred write_artworkdb call.

    Holds the db_track_id to img_id mapping and temp file paths.  The caller must
    call ``commit()`` after the iTunesDB/CDB is also ready to ensure both
    databases are updated atomically.  Call ``abort()`` to clean up temp
    files without committing.
    """
    db_track_id_to_art_info: dict          # db_track_id → (img_id, src_img_size)
    _pending_renames: list = field(default_factory=list)  # [(temp, final), ...]
    _post_commit_cleanup: Callable[[], None] | None = None
    _committed: bool = False

    @property
    def db_id_to_art_info(self) -> dict:
        """Backward-compatible alias for db_track_id_to_art_info."""
        return self.db_track_id_to_art_info

    # Dict-like interface for compatibility with code expecting a plain dict
    def __getitem__(self, key):
        """Allow indexing like a dict: pending_aw[track_id] → (img_id, size)"""
        return self.db_track_id_to_art_info[key]

    def __setitem__(self, key, value):
        """Allow dict-like assignment."""
        self.db_track_id_to_art_info[key] = value

    def __contains__(self, key) -> bool:
        """Allow 'in' operator."""
        return key in self.db_track_id_to_art_info

    def __iter__(self):
        """Allow iteration over keys."""
        return iter(self.db_track_id_to_art_info)

    def __len__(self) -> int:
        """Allow len()."""
        return len(self.db_track_id_to_art_info)

    def get(self, key, default=None):
        """Dict-like get() with default."""
        return self.db_track_id_to_art_info.get(key, default)

    def keys(self):
        """Return dict keys."""
        return self.db_track_id_to_art_info.keys()

    def values(self):
        """Return dict values."""
        return self.db_track_id_to_art_info.values()

    def items(self):
        """Return dict items."""
        return self.db_track_id_to_art_info.items()

    def commit(self, before_replace: Callable[[], None] | None = None) -> None:
        """Atomically replace all temp files with final paths."""
        if self._committed:
            return
        for temp, final in self._pending_renames:
            if before_replace is not None:
                before_replace()
            durable_replace(temp, final)
        if self._post_commit_cleanup is not None:
            self._post_commit_cleanup()
        self._committed = True

    def abort(self, before_remove: Callable[[], None] | None = None) -> None:
        """Remove all temp files without committing."""
        if self._committed:
            return
        for temp, _final in self._pending_renames:
            try:
                if before_remove is not None:
                    before_remove()
                durable_unlink(temp, missing_ok=True)
            except OSError:
                pass


class ArtworkDecisionKind(StrEnum):
    """Per-track action for the final artwork state."""

    NEW_FROM_PC = "new_from_pc"
    PRESERVE_EXISTING = "preserve_existing"
    CLEAR_ART = "clear_art"
    PRESERVE_FALLBACK = "preserve_fallback"


@dataclass(frozen=True)
class ArtworkAssetRef:
    """Identifies the shared artwork payload for dedupe/reuse."""

    source: str
    value: str | int


@dataclass
class TrackArtworkDecision:
    """Resolved artwork action for one track in the final database."""

    db_track_id: int
    kind: ArtworkDecisionKind
    asset_ref: ArtworkAssetRef | None = None
    art_bytes: bytes | None = None
    src_img_size: int = 0
    source_path: str = ""
    existing_entry: dict | None = None


@dataclass
class ArtworkDecisionSummary:
    """Counters for structured writer logging."""

    preserved_unchanged: int = 0
    preserved_fallback: int = 0
    reencoded: int = 0
    cleared: int = 0
    shared_from_album: int = 0
    salvaged: int = 0
    dropped_invalid: int = 0


@dataclass
class ExistingArtworkFormats:
    """Existing formats for one entry in the writer's ownership model.

    ``required_known`` and ``extra_known`` contain valid known-format refs that
    can be carried forward directly. ``known_present`` tracks all known IDs
    observed on the entry, including invalid refs, so they can be regenerated
    when possible. Unknown refs are passthrough only: we may reference them for
    preserved artwork, but we never decode or rewrite their payloads unless
    a known-format repair is required.
    """

    required_known: dict[int, ExistingFormatRef] = field(default_factory=dict)
    extra_known: dict[int, ExistingFormatRef] = field(default_factory=dict)
    unknown_passthrough: dict[int, PassthroughFormatRef] = field(default_factory=dict)
    known_present: set[int] = field(default_factory=set)


def _decode_preserved_frame(ref: ExistingFormatRef, format_id: int, pixel_bytes: bytes, fmt_override=None):
    """Decode one preserved frame using format-aware codec rules."""
    return decode_pixels_for_format(
        format_id,
        pixel_bytes,
        ref.width,
        ref.height,
        ref.hpad,
        ref.vpad,
        fmt_override=fmt_override,
    )


def _get_track_artwork_hint(track) -> str:
    """Read the optional sync hint injected by the executor."""
    hint = _get_track_field(track, "_iop_artwork_sync_hint")
    return str(hint or "").strip().lower()


def _resolve_existing_art_entry(
    track,
    existing_art: dict[int, dict],
    existing_by_song_id: dict[int, int],
) -> tuple[int, dict] | None:
    """Resolve the currently linked artwork entry for a track, if any."""
    db_track_id = _get_track_field(track, "db_track_id")
    if not db_track_id:
        return None

    resolved_img_id = existing_by_song_id.get(db_track_id)
    if resolved_img_id is None:
        mhii_link = _get_track_field(track, "mhii_link")
        if not mhii_link:
            mhii_link = _get_track_field(track, "mhiiLink")
        if not mhii_link:
            mhii_link = _get_track_field(track, "artwork_id_ref")
        if mhii_link and mhii_link in existing_art:
            resolved_img_id = mhii_link

    if resolved_img_id is None:
        return None

    entry = existing_art.get(resolved_img_id)
    if not entry:
        return None
    return resolved_img_id, entry


def _validate_existing_format_ref(
    fmt_id: int,
    ref: ExistingFormatRef,
    device_format_defs: Mapping[int, ArtworkFormat],
) -> ExistingFormatRef | None:
    """Return preserve metadata if an existing ref is safe to reuse."""
    if not ref.path or ref.size <= 0 or not os.path.exists(ref.path):
        logger.warning(
            "ART: existing known format %d cannot be preserved; missing file or size (%s)",
            fmt_id,
            ref.path or "no path",
        )
        return None

    fmt_override = device_format_defs.get(fmt_id)
    expected_sizes = {
        expected_size_bytes(
            fmt_id,
            ref.stride_pixels,
            ref.stored_height,
            stride_pixels=ref.stride_pixels,
            fmt_override=fmt_override,
        ),
        expected_size_bytes(
            fmt_id,
            ref.width,
            ref.stored_height,
            stride_pixels=default_stride_pixels(fmt_id, ref.width, fmt_override=fmt_override),
            fmt_override=fmt_override,
        ),
    }
    expected_sizes.discard(0)
    if expected_sizes and ref.size not in expected_sizes:
        logger.debug(
            "ART: existing known format %d has size %d outside expected sizes %s; carrying forward on-device bytes",
            fmt_id,
            ref.size,
            sorted(expected_sizes),
        )

    return ref


def _log_unknown_existing_formats(
    classified: ExistingArtworkFormats,
    warned_unknown_contexts: set[tuple[int, str]],
) -> None:
    """Warn once for unknown formats while keeping their files outside writer ownership."""
    for fmt_id, meta in classified.unknown_passthrough.items():
        path = meta.path
        warning_key = (fmt_id, path)
        if warning_key in warned_unknown_contexts:
            continue
        logger.warning(
            "ART: encountered unknown artwork format %d at %s; leaving its ithmb file untouched",
            fmt_id,
            path or "unknown path",
        )
        warned_unknown_contexts.add(warning_key)


def _log_extra_known_existing_formats(
    classified: ExistingArtworkFormats,
    warned_extra_known_contexts: set[tuple[int, str]],
) -> None:
    """Warn once when we preserve or regenerate known formats outside the required set."""
    for fmt_id, meta in classified.extra_known.items():
        path = meta.path
        warning_key = (fmt_id, path)
        if warning_key in warned_extra_known_contexts:
            continue
        logger.warning(
            "ART: encountered extra known artwork format %d at %s; preserving/regenerating it because it is present on-device",
            fmt_id,
            path or "unknown path",
        )
        warned_extra_known_contexts.add(warning_key)


def _resolve_known_format_definition(
    fmt_id: int,
    device_format_defs: Mapping[int, ArtworkFormat],
) -> ArtworkFormat | None:
    """Resolve a format definition using device overrides first and global IDs second."""
    return device_format_defs.get(fmt_id) or ITHMB_FORMAT_MAP.get(fmt_id)


def _normalize_passthrough_format_ref(
    fmt_id: int,
    ref: ExistingFormatRef,
) -> PassthroughFormatRef | None:
    """Return raw metadata for a format we will reference without rewriting."""
    if not ref.path or ref.size <= 0 or not os.path.exists(ref.path):
        logger.warning(
            "ART: cannot preserve passthrough format %d as-is; missing file or size (%s)",
            fmt_id,
            ref.path or "no path",
        )
        return None

    return PassthroughFormatRef.from_existing_ref(ref)


def _classify_existing_entry_formats(
    existing_entry: dict | None,
    required_format_ids: list[int],
    device_format_defs: Mapping[int, ArtworkFormat],
) -> ExistingArtworkFormats:
    """Classify existing entry formats as required-known, extra-known, or unknown passthrough."""
    classified = ExistingArtworkFormats()
    if existing_entry is None:
        return classified

    required_set = set(required_format_ids)
    refs = existing_entry.get("formats", {})
    for raw_fmt_id, ref in refs.items():
        try:
            fmt_id = int(raw_fmt_id)
        except (TypeError, ValueError):
            logger.warning("ART: ignoring non-integer artwork format id %r", raw_fmt_id)
            continue

        known_def = _resolve_known_format_definition(fmt_id, device_format_defs)
        if known_def is None:
            meta = _normalize_passthrough_format_ref(fmt_id, ref)
            if meta is not None:
                classified.unknown_passthrough[fmt_id] = meta
            continue

        classified.known_present.add(fmt_id)
        meta = _validate_existing_format_ref(fmt_id, ref, device_format_defs)
        if meta is None:
            logger.warning(
                "ART: existing format %d has invalid geometry or payload size; will attempt regeneration if needed",
                fmt_id,
            )
            continue
        if fmt_id in required_set:
            classified.required_known[fmt_id] = meta
        else:
            classified.extra_known[fmt_id] = meta
    return classified


def _collect_rewrite_targets(
    decisions: Mapping[int, TrackArtworkDecision],
    required_format_ids: list[int],
    device_format_defs: Mapping[int, ArtworkFormat],
) -> tuple[dict[ArtworkAssetRef, list[int]], dict[ArtworkAssetRef, dict[int, PassthroughFormatRef]]]:
    """Resolve per-artwork known rewrite targets plus unknown passthrough refs."""
    target_ids_by_asset: dict[ArtworkAssetRef, set[int]] = defaultdict(set)
    passthrough_by_asset: dict[ArtworkAssetRef, dict[int, PassthroughFormatRef]] = defaultdict(dict)
    warned_unknown_contexts: set[tuple[int, str]] = set()
    warned_extra_known_contexts: set[tuple[int, str]] = set()

    for decision in decisions.values():
        existing_entry = decision.existing_entry or {}
        classified = _classify_existing_entry_formats(
            existing_entry,
            required_format_ids,
            device_format_defs,
        )
        _log_unknown_existing_formats(classified, warned_unknown_contexts)
        _log_extra_known_existing_formats(classified, warned_extra_known_contexts)

        if decision.asset_ref is None:
            continue

        # Required formats are mandatory for every live artwork entry. Any
        # known extra IDs already present on-device are also writer-owned
        # targets, even if their old payload needs regeneration.
        target_ids_by_asset[decision.asset_ref].update(required_format_ids)
        target_ids_by_asset[decision.asset_ref].update(classified.known_present)

        if decision.kind in (
            ArtworkDecisionKind.PRESERVE_EXISTING,
            ArtworkDecisionKind.PRESERVE_FALLBACK,
        ):
            passthrough_by_asset[decision.asset_ref].update(classified.unknown_passthrough)

    return (
        {asset_ref: sorted(fmt_ids) for asset_ref, fmt_ids in target_ids_by_asset.items()},
        dict(passthrough_by_asset),
    )


def _target_dimensions_for_format(
    fmt_id: int,
    device_formats: Mapping[int, tuple[int, int]],
    device_format_defs: Mapping[int, ArtworkFormat],
) -> tuple[int, int] | None:
    """Return encode dimensions for required or extra-known format IDs."""
    if fmt_id in device_formats:
        return device_formats[fmt_id]

    fmt = _resolve_known_format_definition(fmt_id, device_format_defs)
    if fmt is None:
        return None

    return format_dimensions(fmt_id, int(fmt.width), int(fmt.height), fmt_override=fmt)


def _required_device_format_ids(device_formats: Mapping[int, tuple[int, int]]) -> list[int]:
    """Return the format IDs that every live artwork entry must provide."""
    return sorted(device_formats.keys())


def _build_existing_song_index(existing_art: dict[int, dict]) -> dict[int, int]:
    """Map ArtworkDB song_id -> img_id for authoritative artwork lookup."""
    existing_by_song_id: dict[int, int] = {}
    for img_id, entry in existing_art.items():
        sid = int(entry.get("song_id", 0) or 0)
        if sid:
            existing_by_song_id[sid] = img_id
    return existing_by_song_id


def _preserved_asset_ref(existing_img_id: int, existing_entry: dict) -> ArtworkAssetRef:
    """Keep MHII records that share the same ITHMB frames deduplicated."""
    locations: list[str] = []
    refs = existing_entry.get("formats", {})
    for raw_format_id, ref in sorted(refs.items(), key=lambda item: int(item[0])):
        format_id = int(raw_format_id)
        filename = ref.ithmb_filename or _ithmb_filename_from_path(ref.path, format_id)
        locations.append(
            f"{format_id}:{filename}:{int(ref.ithmb_offset)}:{int(ref.size)}"
        )
    if not locations:
        return ArtworkAssetRef("preserve", existing_img_id)
    return ArtworkAssetRef("preserve", "|".join(locations))


def _collect_track_artwork_decisions(
    tracks: list,
    pc_file_paths: dict[int, str],
    existing_art: dict[int, dict],
) -> tuple[dict[int, TrackArtworkDecision], ArtworkDecisionSummary]:
    """Resolve the desired final artwork state for every track."""
    decisions: dict[int, TrackArtworkDecision] = {}
    summary = ArtworkDecisionSummary()
    existing_by_song_id = _build_existing_song_index(existing_art)
    extracted_by_path: dict[str, tuple[bytes | None, str | None]] = {}

    for track in tracks:
        db_track_id = _get_track_field(track, "db_track_id")
        if not db_track_id:
            title = _get_track_field(track, "title") or "?"
            logger.warning("ART: track '%s' has no db_track_id, skipping", title)
            continue

        resolved_existing = _resolve_existing_art_entry(track, existing_art, existing_by_song_id)
        existing_entry = resolved_existing[1] if resolved_existing else None
        existing_img_id = resolved_existing[0] if resolved_existing else 0
        hint = _get_track_artwork_hint(track)
        pc_path = pc_file_paths.get(db_track_id)
        if hint == "clear_art":
            decisions[db_track_id] = TrackArtworkDecision(
                db_track_id=db_track_id,
                kind=ArtworkDecisionKind.CLEAR_ART,
                existing_entry=existing_entry,
            )
            summary.cleared += 1
            continue

        if hint == "preserve_existing" and existing_entry is not None:
            kind = (
                ArtworkDecisionKind.PRESERVE_EXISTING
                if pc_path and os.path.exists(pc_path)
                else ArtworkDecisionKind.PRESERVE_FALLBACK
            )
            decisions[db_track_id] = TrackArtworkDecision(
                db_track_id=db_track_id,
                kind=kind,
                asset_ref=_preserved_asset_ref(existing_img_id, existing_entry),
                src_img_size=int(existing_entry.get("src_img_size", 0) or 0),
                existing_entry=existing_entry,
            )
            if kind == ArtworkDecisionKind.PRESERVE_EXISTING:
                summary.preserved_unchanged += 1
            else:
                summary.preserved_fallback += 1
            continue

        if not pc_path:
            if existing_entry is not None:
                decisions[db_track_id] = TrackArtworkDecision(
                    db_track_id=db_track_id,
                    kind=ArtworkDecisionKind.PRESERVE_FALLBACK,
                    asset_ref=_preserved_asset_ref(existing_img_id, existing_entry),
                    src_img_size=int(existing_entry.get("src_img_size", 0) or 0),
                    existing_entry=existing_entry,
                )
                summary.preserved_fallback += 1
            else:
                decisions[db_track_id] = TrackArtworkDecision(
                    db_track_id=db_track_id,
                    kind=ArtworkDecisionKind.CLEAR_ART,
                    existing_entry=existing_entry,
                )
                summary.cleared += 1
            continue

        if not os.path.exists(pc_path):
            title = _get_track_field(track, "title") or "?"
            logger.warning("ART: PC file not found for '%s': %s", title, pc_path)
            if existing_entry is not None:
                decisions[db_track_id] = TrackArtworkDecision(
                    db_track_id=db_track_id,
                    kind=ArtworkDecisionKind.PRESERVE_FALLBACK,
                    asset_ref=_preserved_asset_ref(existing_img_id, existing_entry),
                    src_img_size=int(existing_entry.get("src_img_size", 0) or 0),
                    existing_entry=existing_entry,
                )
                summary.preserved_fallback += 1
            else:
                decisions[db_track_id] = TrackArtworkDecision(
                    db_track_id=db_track_id,
                    kind=ArtworkDecisionKind.CLEAR_ART,
                    existing_entry=existing_entry,
                )
                summary.cleared += 1
            continue

        source_cache_key = os.path.normcase(os.path.abspath(pc_path))
        cached_art = extracted_by_path.get(source_cache_key)
        if cached_art is None:
            if extract_art_with_folder is not _extract_art_with_folder:
                art_bytes = extract_art_with_folder(pc_path)
                art_source_path = pc_path if art_bytes is not None else None
            else:
                art_bytes, art_source_path = extract_art_with_source(pc_path)
            cached_art = (art_bytes, art_source_path)
            extracted_by_path[source_cache_key] = cached_art
        art_bytes, art_source_path = cached_art
        if art_bytes is None:
            decisions[db_track_id] = TrackArtworkDecision(
                db_track_id=db_track_id,
                kind=ArtworkDecisionKind.CLEAR_ART,
                existing_entry=existing_entry,
            )
            summary.cleared += 1
            continue

        digest = art_hash(art_bytes)
        decisions[db_track_id] = TrackArtworkDecision(
            db_track_id=db_track_id,
            kind=ArtworkDecisionKind.NEW_FROM_PC,
            asset_ref=ArtworkAssetRef("pc", digest),
            art_bytes=art_bytes,
            src_img_size=len(art_bytes),
            source_path=art_source_path or pc_path,
            existing_entry=existing_entry,
        )
        summary.reencoded += 1

    return decisions, summary


def _format_artwork_decision_progress(summary: ArtworkDecisionSummary) -> str:
    parts: list[str] = []
    preserved = summary.preserved_unchanged + summary.preserved_fallback
    if preserved:
        parts.append(f"preserving {preserved} existing")
    if summary.reencoded:
        parts.append(f"updating {summary.reencoded} changed/new")
    if summary.cleared:
        parts.append(f"clearing {summary.cleared}")
    if not parts:
        return "Artwork — verifying existing artwork links"
    return f"Artwork — verifying artwork links ({', '.join(parts)})"


def _convert_new_pc_art(
    decisions: dict[int, TrackArtworkDecision],
    required_format_ids: list[int],
    asset_target_format_ids: Mapping[ArtworkAssetRef, list[int]],
    device_formats: dict[int, tuple[int, int]],
    device_format_defs: Mapping[int, ArtworkFormat],
    progress_callback: Callable[[str], None] | None = None,
) -> dict[ArtworkAssetRef, ArtworkPayload]:
    """Convert only the PC-sourced artwork payloads that need re-encoding."""
    pc_art_map: dict[ArtworkAssetRef, bytes] = {}
    pc_art_source_paths: dict[ArtworkAssetRef, str] = {}
    for decision in decisions.values():
        if decision.kind != ArtworkDecisionKind.NEW_FROM_PC:
            continue
        if decision.asset_ref is None or decision.art_bytes is None:
            continue
        pc_art_map[decision.asset_ref] = decision.art_bytes
        if decision.source_path:
            pc_art_source_paths[decision.asset_ref] = decision.source_path

    unique_converted: dict[ArtworkAssetRef, ArtworkPayload] = {}
    if not pc_art_map:
        return unique_converted

    if progress_callback is not None:
        progress_callback(
            f"Artwork — converting {len(pc_art_map)} image{'s' if len(pc_art_map) != 1 else ''}"
        )

    required_format_id_set = set(required_format_ids)

    def _convert_one(asset_ref: ArtworkAssetRef, art_bytes: bytes) -> tuple[ArtworkAssetRef, ArtworkPayload | None]:
        source_path = pc_art_source_paths.get(asset_ref, "")
        try:
            img = image_from_bytes(art_bytes, source_path=source_path)
        except TypeError as exc:
            if "source_path" not in str(exc):
                raise
            img = image_from_bytes(art_bytes)
        if img is None:
            return asset_ref, None
        formats: dict[int, ArtworkFormatPayload] = {}
        target_format_ids = asset_target_format_ids.get(asset_ref, required_format_ids)
        for fmt_id in target_format_ids:
            dims = _target_dimensions_for_format(fmt_id, device_formats, device_format_defs)
            if dims is None:
                logger.warning(
                    "ART: format %d is not encodable for %s; skipping",
                    fmt_id,
                    asset_ref,
                )
                continue
            try:
                encoded = encode_image_for_format(
                    img,
                    fmt_id,
                    *dims,
                    fmt_override=device_format_defs.get(fmt_id),
                )
                formats[fmt_id] = encoded
            except Exception as exc:
                log_fn = logger.warning if fmt_id in required_format_id_set else logger.debug
                log_fn(
                    "ART: format %d conversion failed for %s: %s",
                    fmt_id,
                    asset_ref,
                    exc,
                )
        if not all(fmt_id in formats for fmt_id in required_format_id_set):
            missing = sorted(fmt_id for fmt_id in required_format_id_set if fmt_id not in formats)
            logger.warning(
                "ART: dropping rewritten artwork %s because required formats %s could not be generated",
                asset_ref,
                missing,
            )
            return asset_ref, None
        return asset_ref, ArtworkPayload(formats=formats, src_img_size=len(art_bytes))

    n_workers = max(1, min(len(pc_art_map), os.cpu_count() or 4))
    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        futs = {
            pool.submit(_convert_one, asset_ref, art_bytes): asset_ref
            for asset_ref, art_bytes in pc_art_map.items()
        }
        for fut in as_completed(futs):
            asset_ref, result = fut.result()
            if result is not None:
                unique_converted[asset_ref] = result
    return unique_converted


def _load_preserved_art_payloads(
    decisions: dict[int, TrackArtworkDecision],
    required_format_ids: list[int],
    asset_target_format_ids: Mapping[ArtworkAssetRef, list[int]],
    asset_passthrough_format_refs: Mapping[ArtworkAssetRef, dict[int, PassthroughFormatRef]],
    device_formats: dict[int, tuple[int, int]],
    device_format_defs: Mapping[int, ArtworkFormat],
    *,
    passthrough_known_formats: bool = False,
    rewrite_known_filenames: Mapping[int, set[str]] | None = None,
) -> tuple[dict[ArtworkAssetRef, ArtworkPayload], int, int]:
    """Load or salvage preserved on-device artwork for reuse."""
    preserve_entries: dict[ArtworkAssetRef, dict] = {}
    preserve_refs: dict[ArtworkAssetRef, dict] = {}
    ref_by_file_fmt: dict[tuple[str, int], list[tuple[int, ArtworkAssetRef, int]]] = defaultdict(list)
    rewrite_known_filenames = rewrite_known_filenames or {}

    def _should_rewrite_known_ref(fmt_id: int, ref: ExistingFormatRef) -> bool:
        if not passthrough_known_formats:
            return True
        filename = ref.ithmb_filename or _ithmb_filename_from_path(ref.path, fmt_id)
        return filename in rewrite_known_filenames.get(fmt_id, set())

    for decision in decisions.values():
        if decision.kind not in (
            ArtworkDecisionKind.PRESERVE_EXISTING,
            ArtworkDecisionKind.PRESERVE_FALLBACK,
        ):
            continue
        if decision.asset_ref is None or decision.existing_entry is None:
            continue
        if decision.asset_ref in preserve_entries or decision.asset_ref in preserve_refs:
            continue

        classified = _classify_existing_entry_formats(
            decision.existing_entry,
            required_format_ids,
            device_format_defs,
        )
        fmt_meta = {
            **classified.required_known,
            **classified.extra_known,
        }
        if fmt_meta:
            preserve_entries[decision.asset_ref] = {
                "fmt_meta": fmt_meta,
                "src_img_size": int(decision.existing_entry.get("src_img_size", 0) or 0),
            }
            for fmt_id, meta in fmt_meta.items():
                if _should_rewrite_known_ref(fmt_id, meta):
                    ref_by_file_fmt[(meta.path, fmt_id)].append(
                        (meta.ithmb_offset, decision.asset_ref, meta.size)
                    )
        preserve_refs[decision.asset_ref] = {
            "refs": decision.existing_entry.get("formats", {}),
            "src_img_size": int(decision.existing_entry.get("src_img_size", 0) or 0),
        }

    pixel_cache: dict[tuple[ArtworkAssetRef, int], bytes] = {}
    for (ithmb_path, fmt_id), items in ref_by_file_fmt.items():
        items.sort(key=lambda item: item[0])
        try:
            with open(ithmb_path, "rb") as src:
                for ithmb_offset, asset_ref, size in items:
                    src.seek(ithmb_offset)
                    pixel_bytes = src.read(size)
                    if len(pixel_bytes) == size:
                        pixel_cache[(asset_ref, fmt_id)] = pixel_bytes
                    else:
                        logger.debug("ART: short read for preserved %s fmt %d", asset_ref, fmt_id)
        except OSError as exc:
            logger.warning("ART: failed to read preserved ithmb %s: %s", ithmb_path, exc)

    unique_converted: dict[ArtworkAssetRef, ArtworkPayload] = {}
    dropped_invalid = 0
    for asset_ref, meta in preserve_entries.items():
        formats: dict[int, ArtworkFormatPayload] = {
            fmt_id: ref
            for fmt_id, ref in asset_passthrough_format_refs.get(asset_ref, {}).items()
        }
        for fmt_id, ref in meta["fmt_meta"].items():
            if not _should_rewrite_known_ref(fmt_id, ref):
                formats[fmt_id] = PassthroughFormatRef.from_existing_ref(ref)
            else:
                pixel_bytes = pixel_cache.get((asset_ref, fmt_id))
                if pixel_bytes:
                    formats[fmt_id] = EncodedFormatPayload.from_existing_ref(ref, pixel_bytes)
        if formats:
            unique_converted[asset_ref] = ArtworkPayload(
                formats=formats,
                src_img_size=meta["src_img_size"],
            )

    salvaged = 0
    for asset_ref, meta in preserve_refs.items():
        existing_payload = unique_converted.get(asset_ref)
        carried_formats: dict[int, ArtworkFormatPayload]
        if existing_payload is not None:
            carried_formats = dict(existing_payload.formats)
        else:
            carried_formats = {
                fmt_id: ref
                for fmt_id, ref in asset_passthrough_format_refs.get(asset_ref, {}).items()
            }
        target_format_ids = asset_target_format_ids.get(asset_ref, required_format_ids)
        missing_target = [
            fmt_id for fmt_id in target_format_ids if fmt_id not in carried_formats
        ]
        if not missing_target:
            continue

        source_img = None
        for fmt_id, ref in meta["refs"].items():
            if _resolve_known_format_definition(int(fmt_id), device_format_defs) is None:
                continue
            try:
                with open(ref.path, "rb") as src:
                    src.seek(ref.ithmb_offset)
                    pixel_bytes = src.read(ref.size)
                if len(pixel_bytes) != ref.size:
                    continue
                source_img = _decode_preserved_frame(
                    ref,
                    int(fmt_id),
                    pixel_bytes,
                    fmt_override=device_format_defs.get(int(fmt_id)),
                )
                if source_img is not None:
                    break
            except OSError:
                continue

        if source_img is None:
            unique_converted.pop(asset_ref, None)
            dropped_invalid += 1
            continue

        formats = dict(carried_formats)
        added_any = False
        for fmt_id in missing_target:
            dims = _target_dimensions_for_format(fmt_id, device_formats, device_format_defs)
            if dims is None:
                logger.warning(
                    "ART: format %d is not encodable for preserved artwork %s; skipping",
                    fmt_id,
                    asset_ref,
                )
                continue
            try:
                encoded = encode_image_for_format(
                    source_img,
                    fmt_id,
                    *dims,
                    fmt_override=device_format_defs.get(fmt_id),
                )
                formats[fmt_id] = encoded
                added_any = True
            except Exception as exc:
                log_fn = logger.warning if fmt_id in required_format_ids else logger.debug
                log_fn("ART: salvage re-encode failed for %s fmt %d: %s", asset_ref, fmt_id, exc)
        if all(fmt_id in formats for fmt_id in required_format_ids):
            unique_converted[asset_ref] = ArtworkPayload(
                formats=formats,
                src_img_size=meta["src_img_size"],
            )
            if added_any:
                salvaged += 1
        else:
            unique_converted.pop(asset_ref, None)
            dropped_invalid += 1

    return unique_converted, salvaged, dropped_invalid


def write_artworkdb(
    ipod_path: str,
    tracks: list,
    pc_file_paths: dict | None = None,
    start_img_id: int = 100,
    reference_artdb_path: str | None = None,
    artwork_formats: dict[int, tuple[int, int]] | None = None,
    defer_commit: bool = False,
    progress_callback: Callable[[str], None] | None = None,
    before_device_mutation: Callable[[], None] | None = None,
) -> dict | PendingArtworkWrite:
    """
    Write ArtworkDB and ithmb files for an iPod.

    This function:
    1. Extracts album art from PC source files
    2. Preserves existing art for tracks without PC source files
    3. Converts art to RGB565 at multiple sizes
    4. Writes ithmb files (pixel data) to temp paths
    5. Writes ArtworkDB binary (metadata) to temp path
    6. Returns a mapping of track db_track_id to img_id for iTunesDB mhiiLink

    When ``defer_commit=True``, files are written to temp paths but NOT
    renamed to their final locations.  The caller receives a
    ``PendingArtworkWrite`` object and must call ``.commit()`` after the
    iTunesDB is also ready, or ``.abort()`` on failure.  This ensures
    both databases are updated atomically.

    Args:
        ipod_path: iPod mount point (e.g., "E:" or "/media/ipod")
        tracks: List of track dicts or TrackInfo objects with at least 'db_track_id' and 'album'
        pc_file_paths: Dict mapping track db_track_id → PC source file path
                       (if None, tries to extract art from iPod copies)
        start_img_id: Starting image ID (default 100, matching iTunes behavior)
        reference_artdb_path: Path to existing ArtworkDB for copying header fields
        artwork_formats: Device-specific format table {correlationID: (w,h)}.
                         If None, auto-detected from existing ArtworkDB / SysInfo.
        defer_commit: If True, return a PendingArtworkWrite instead of committing
                      immediately.

    Returns:
        If ``defer_commit=False`` (default): dict mapping track db_track_id →
        (img_id, src_img_size), or empty dict if no artwork found.

        If ``defer_commit=True``: a ``PendingArtworkWrite`` with the
        mapping in ``.db_track_id_to_art_info`` and a ``.commit()`` method.
    """
    artwork_subtree = os.path.join("iPod_Control", "Artwork")
    artwork_dir = str(
        resolve_device_path(
            ipod_path,
            artwork_subtree,
            allowed_subtree=artwork_subtree,
        )
    )
    if not os.path.isdir(artwork_dir):
        if before_device_mutation is not None:
            before_device_mutation()
        os.makedirs(artwork_dir, exist_ok=True)

    def _prog(msg: str) -> None:
        if progress_callback is not None:
            progress_callback(msg)

    normalized_pc_paths: dict[int, str] = {}
    if pc_file_paths:
        for key, path in pc_file_paths.items():
            try:
                db_track_id = int(key)
            except (TypeError, ValueError):
                continue
            if db_track_id > 0:
                normalized_pc_paths[db_track_id] = str(path)

    if artwork_formats is None:
        artwork_formats = get_artwork_formats(ipod_path)
    device_formats = artwork_formats
    device_format_defs = get_artwork_format_definitions(ipod_path)
    required_format_ids = _required_device_format_ids(device_formats)
    logger.info("ART: using formats %s", required_format_ids)
    if not required_format_ids:
        raise RuntimeError(
            "No artwork format definitions are available for this iPod; "
            "cannot write ArtworkDB safely."
        )

    ref_mhfd = None
    if reference_artdb_path and os.path.exists(reference_artdb_path):
        with open(reference_artdb_path, "rb") as f:
            ref_mhfd = f.read()

    artworkdb_path = os.path.join(artwork_dir, "ArtworkDB")
    existing_art = read_existing_artwork(artworkdb_path, artwork_dir)
    if existing_art:
        logger.info("ART: read %d existing image entries from ArtworkDB", len(existing_art))

    _prog(f"Artwork — scanning {len(tracks)} tracks")
    decisions, decision_summary = _collect_track_artwork_decisions(
        tracks,
        normalized_pc_paths,
        existing_art,
    )
    _prog(_format_artwork_decision_progress(decision_summary))
    logger.info(
        "ART decisions: preserve=%d fallback=%d reencode=%d clear=%d",
        decision_summary.preserved_unchanged,
        decision_summary.preserved_fallback,
        decision_summary.reencoded,
        decision_summary.cleared,
    )

    asset_target_format_ids, asset_passthrough_format_refs = _collect_rewrite_targets(
        decisions,
        required_format_ids,
        device_format_defs,
    )

    unique_converted = _convert_new_pc_art(
        decisions,
        required_format_ids,
        asset_target_format_ids,
        device_formats,
        device_format_defs,
        progress_callback=progress_callback,
    )
    rewrite_filenames, writable_start_indices = (
        _select_ithmb_rewrite_plan(existing_art, decisions, unique_converted)
        if unique_converted
        else ({}, {})
    )
    preserved_converted, salvaged_preserved, dropped_invalid = _load_preserved_art_payloads(
        decisions,
        required_format_ids,
        asset_target_format_ids,
        asset_passthrough_format_refs,
        device_formats,
        device_format_defs,
        # Rewrite only the lowest file that has room for the new artwork. Other
        # files retain their existing track links without extra device I/O.
        passthrough_known_formats=True,
        rewrite_known_filenames=rewrite_filenames,
    )
    unique_converted.update(preserved_converted)
    decision_summary.salvaged = salvaged_preserved
    decision_summary.dropped_invalid += dropped_invalid

    if salvaged_preserved:
        logger.info(
            "ART: salvaged %d preserved artwork entr%s via decode/re-encode fallback",
            salvaged_preserved,
            "ies" if salvaged_preserved != 1 else "y",
        )

    entries: list[ArtworkEntry] = []
    entry_asset_keys: dict[int, ArtworkAssetRef] = {}
    img_id = start_img_id

    for track in tracks:
        db_track_id = _get_track_field(track, "db_track_id")
        if not db_track_id:
            continue
        decision = decisions.get(db_track_id)
        if decision is None or decision.kind == ArtworkDecisionKind.CLEAR_ART:
            continue
        if decision.asset_ref is None:
            continue
        converted = unique_converted.get(decision.asset_ref)
        if converted is None:
            decision_summary.dropped_invalid += 1
            continue

        # Preserved old MHII ids are only asset lookup keys. The rewritten
        # ArtworkDB owns fresh image ids, and mhbd_writer uses the returned
        # db_track_id mapping below to rewrite every track's mhii_link.
        entry = ArtworkEntry(
            img_id,
            db_track_id,
            str(decision.asset_ref.value) if decision.asset_ref.source == "pc" else None,
            int(converted.src_img_size),
            dict(converted.formats),
            [db_track_id],
        )
        entries.append(entry)
        entry_asset_keys[entry.img_id] = decision.asset_ref
        img_id += 1

    logger.info(
        "ART result: %d live entries from %d unique payloads (%d dropped invalid)",
        len(entries),
        len(set(entry_asset_keys.values())),
        decision_summary.dropped_invalid,
    )

    # --- Step 3: Write ithmb files ---
    format_ids = sorted({fmt_id for entry in entries for fmt_id in entry.formats.keys()})
    writable_format_ids = sorted(
        {
            fmt_id
            for entry in entries
            for fmt_id, img_info in entry.formats.items()
            if isinstance(img_info, EncodedFormatPayload)
        }
    )
    passthrough_only_format_ids = sorted(set(format_ids) - set(writable_format_ids))
    if passthrough_only_format_ids:
        logger.info(
            "ART: preserving passthrough-only formats without rewriting files: %s",
            passthrough_only_format_ids,
        )
    protected_passthrough_filenames: dict[int, set[str]] = defaultdict(set)
    for entry in entries:
        for fmt_id, img_info in entry.formats.items():
            if isinstance(img_info, PassthroughFormatRef):
                filename = img_info.ithmb_filename or _ithmb_filename_from_path(img_info.path, fmt_id)
                protected_passthrough_filenames[fmt_id].add(filename)

    n_unique = len(set(entry_asset_keys.values()))
    writable_asset_keys = {
        entry_asset_keys[entry.img_id]
        for entry in entries
        if any(isinstance(img_info, EncodedFormatPayload) for img_info in entry.formats.values())
    }
    n_writable = len(writable_asset_keys)
    n_preserved = max(0, n_unique - n_writable)
    if n_writable and n_preserved:
        _prog(
            f"Artwork — writing {n_writable} changed/new image"
            f"{'s' if n_writable != 1 else ''}, preserving {n_preserved} existing"
        )
    elif n_writable:
        _prog(
            f"Artwork — writing {n_writable} changed/new image"
            f"{'s' if n_writable != 1 else ''}"
        )
    elif n_unique:
        _prog(
            f"Artwork — updating artwork index "
            f"({n_unique} existing image{'s' if n_unique != 1 else ''}, no image data rewritten)"
        )
    elif decision_summary.cleared:
        _prog("Artwork — updating artwork index (clearing artwork links)")
    else:
        _prog("Artwork — updating artwork index (no live artwork)")
    # Map entry img_id -> {format_id: IthmbLocation} for MHNI.
    # The filename matters: large libraries can span F{id}_1.ithmb,
    # F{id}_2.ithmb, ... and preserved refs may already live in any N.
    format_locations_map: dict[int, dict[int, IthmbLocation]] = {}
    # Track image sizes for MHIF (one size per format across all entries).
    # Use observed payload sizes so preserved mixed-format databases don't get
    # forced into current-device assumptions.
    image_sizes = {}
    for fmt_id in format_ids:
        observed_sizes = [
            int(entry.formats[fmt_id].size)
            for entry in entries
            if fmt_id in entry.formats and int(entry.formats[fmt_id].size) > 0
        ]
        if not observed_sizes:
            continue
        c = Counter(observed_sizes)
        image_sizes[fmt_id] = c.most_common(1)[0][0]
        if len(c) > 1:
            logger.warning(
                "ART: format %d has mixed payload sizes %s; using most common %d in MHIF",
                fmt_id,
                sorted(c.keys()),
                image_sizes[fmt_id],
            )

    # Write ithmb files to temp paths first — originals stay intact until
    # both ithmb AND ArtworkDB are fully written and verified.
    ithmb_temp_paths: dict[tuple[int, int], Path] = {}  # (fmt_id, file_index) -> temp path
    ithmb_final_paths: dict[tuple[int, int], str] = {}  # (fmt_id, file_index) -> final path
    ithmb_files = {}
    ithmb_state: dict[int, dict[str, int]] = {
        fmt_id: {"index": writable_start_indices.get(fmt_id, 0), "offset": 0}
        for fmt_id in writable_format_ids
    }

    def _close_current_ithmb(fmt_id: int) -> None:
        handle = ithmb_files.pop(fmt_id, None)
        if handle is not None:
            try:
                flush_written_file(handle)
            finally:
                handle.close()

    def _open_next_ithmb(fmt_id: int) -> None:
        _close_current_ithmb(fmt_id)
        state = ithmb_state[fmt_id]
        protected = protected_passthrough_filenames.get(fmt_id, set())
        while True:
            state["index"] += 1
            filename = _ithmb_filename(fmt_id, state["index"])
            if filename not in protected:
                break
        state["offset"] = 0
        final = os.path.join(artwork_dir, filename)
        ithmb_final_paths[(fmt_id, state["index"])] = final
        if before_device_mutation is not None:
            before_device_mutation()
        temp, temp_file = open_unique_sibling_temp(final, mode="wb")
        ithmb_temp_paths[(fmt_id, state["index"])] = temp
        ithmb_files[fmt_id] = temp_file

    def _write_encoded_ithmb_payload(fmt_id: int, data: bytes) -> IthmbLocation:
        state = ithmb_state[fmt_id]
        if fmt_id not in ithmb_files:
            _open_next_ithmb(fmt_id)
        elif state["offset"] > 0 and state["offset"] + len(data) > ITHMB_MAX_SIZE_BYTES:
            _open_next_ithmb(fmt_id)

        filename = _ithmb_filename(fmt_id, state["index"])
        offset = state["offset"]
        ithmb_files[fmt_id].write(data)
        state["offset"] += len(data)
        return IthmbLocation(filename, offset)

    def _passthrough_location(fmt_id: int, ref: PassthroughFormatRef) -> IthmbLocation:
        filename = ref.ithmb_filename or _ithmb_filename_from_path(ref.path, fmt_id)
        return IthmbLocation(filename, int(ref.ithmb_offset))

    # Track which unique images have been written to avoid ithmb duplication
    art_payload_written: dict[ArtworkAssetRef, dict[int, IthmbLocation]] = {}
    try:
        try:
            # Write each unique image only once; per-track entries sharing
            # the same art_hash reuse the same ithmb offsets.
            for entry in entries:
                asset_ref = entry_asset_keys[entry.img_id]
                if asset_ref in art_payload_written:
                    # Already written — reuse offsets
                    format_locations_map[entry.img_id] = dict(art_payload_written[asset_ref])
                else:
                    locations: dict[int, IthmbLocation] = {}
                    for fmt_id in format_ids:
                        if fmt_id not in entry.formats:
                            continue
                        img_info = entry.formats[fmt_id]
                        if isinstance(img_info, EncodedFormatPayload):
                            locations[fmt_id] = _write_encoded_ithmb_payload(fmt_id, img_info.data)
                        elif isinstance(img_info, PassthroughFormatRef):
                            locations[fmt_id] = _passthrough_location(fmt_id, img_info)
                    art_payload_written[asset_ref] = locations
                    format_locations_map[entry.img_id] = dict(locations)

            # Each completed ithmb temp file is synchronized before the atomic
            # rename so a successful database commit never references cached-only
            # artwork payloads.
        finally:
            for fmt_id in list(ithmb_files.keys()):
                _close_current_ithmb(fmt_id)
    except Exception:
        for temp in ithmb_temp_paths.values():
            try:
                if before_device_mutation is not None:
                    before_device_mutation()
                durable_unlink(temp, missing_ok=True)
            except OSError:
                pass
        raise

    # --- Step 4: Build ArtworkDB binary ---
    next_id = start_img_id + len(entries)
    artdb_data = build_artworkdb(
        entries,
        format_locations_map,
        format_ids,
        image_sizes,
        next_id,
        ref_mhfd,
    )

    # Write ArtworkDB to temp file
    artdb_path = os.path.join(artwork_dir, "ArtworkDB")
    artdb_temp: Path | None = None
    try:
        if before_device_mutation is not None:
            before_device_mutation()
        artdb_temp, artdb_file = open_unique_sibling_temp(artdb_path, mode="wb")
        with artdb_file as f:
            f.write(artdb_data)
            flush_written_file(f)
    except Exception:
        # Clean up all temp files on failure
        for tp in ithmb_temp_paths.values():
            try:
                if before_device_mutation is not None:
                    before_device_mutation()
                durable_unlink(tp, missing_ok=True)
            except OSError:
                pass
        if artdb_temp is not None:
            try:
                if before_device_mutation is not None:
                    before_device_mutation()
                durable_unlink(artdb_temp, missing_ok=True)
            except OSError:
                pass
        raise

    # --- Atomic commit: all temp files are complete, swap them in ---
    # os.replace is atomic on NTFS and POSIX — old files are only removed
    # when the new file is fully in place.

    # --- Step 5: Build db_track_id → (img_id, src_img_size) mapping ---
    # This is the sole outbound contract for track artwork refs: each track id
    # receives the new rewritten MHII id, never a stale preserved lookup id.
    db_track_id_to_art_info: dict[int, tuple[int, int]] = {}
    for entry in entries:
        db_track_id_to_art_info[entry.db_track_id] = (entry.img_id, entry.src_img_size)

    # Collect all pending renames (ithmb temps + artworkdb temp)
    pending_renames = []
    for key in sorted(ithmb_temp_paths.keys()):
        pending_renames.append((ithmb_temp_paths[key], ithmb_final_paths[key]))
    pending_renames.append((artdb_temp, artdb_path))

    def _post_commit_cleanup() -> None:
        # Keep ithmb files we did not explicitly rewrite. The writer only
        # owns required device formats plus any known extra formats it chose
        # to regenerate for live artwork entries.
        return None

    if defer_commit:
        logger.info(
            "ART: prepared %d unique images, %d MHII entries (per-track) — commit deferred",
            len(art_payload_written),
            len(entries),
        )
        return PendingArtworkWrite(
            db_track_id_to_art_info=db_track_id_to_art_info,
            _pending_renames=pending_renames,
            _post_commit_cleanup=_post_commit_cleanup,
        )

    # Immediate commit (legacy behaviour)
    try:
        for temp, final in pending_renames:
            if before_device_mutation is not None:
                before_device_mutation()
            durable_replace(temp, final)
        _post_commit_cleanup()
    except Exception:
        # If any replace fails, clean up remaining temps
        for temp, _final in pending_renames:
            try:
                if before_device_mutation is not None:
                    before_device_mutation()
                durable_unlink(temp, missing_ok=True)
            except OSError:
                pass
        raise

    logger.info(
        "Wrote ithmb files: %d unique images, %d MHII entries (per-track)",
        len(art_payload_written),
        len(entries),
    )
    for key in sorted(ithmb_final_paths.keys()):
        final = ithmb_final_paths[key]
        size = os.path.getsize(final)
        logger.info("  %s: %d bytes", os.path.basename(final), size)
    for fmt_id in passthrough_only_format_ids:
        logger.info("  F%d_N.ithmb: preserved in place", fmt_id)

    return db_track_id_to_art_info


def _get_track_field(track, field: str):
    """Get a field from a track dict or dataclass."""
    if isinstance(track, dict):
        if field == "db_track_id":
            return track.get("db_track_id", track.get("db_id"))
        return track.get(field)
    if field == "db_track_id":
        return getattr(track, "db_track_id", getattr(track, "db_id", None))
    return getattr(track, field, None)
