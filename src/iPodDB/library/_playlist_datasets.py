"""Dataset ownership and supported structural rules, private to the Library adapter."""

from collections import Counter
from dataclasses import replace

from iPodDB.iTunesDB.builder.build_iTunesDB import new_itunes_chunk
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhip import DEFINITION as MHIP
from iPodDB.iTunesDB.shared.chunk_defs.mhip import MhipHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import DEFINITION as MHSD
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import MhypHeader
from iPodDB.library._field_policy import BROWSE_FIELDS, value_at
from iPodDB.library._identities import IdentityAllocator
from iPodDB.library._playlist_writing import position_item
from iPodDB.library.models import LibrarySnapshot
from iPodDB.library.writing import IssueSeverity, WriteIssue
from iPodDB.shared.chunk import (
    ChunkHeader,
    ChunkSelection,
    DatabaseDocument,
    ParsedChunk,
    chunk_as,
)


def playlist_rows(
    document: DatabaseDocument[MhbdHeader], kinds: tuple[int, ...] = (2, 3)
) -> tuple[tuple[int, ChunkSelection[MhbdHeader, MhypHeader]], ...]:
    return tuple(
        (dataset.chunk.header.dataset_type, row)
        for dataset in document.find_chunks(MhsdHeader)
        if dataset.chunk.header.dataset_type in kinds
        for row in dataset.find_chunks(MhypHeader)
    )


def is_master(kind: int, header: MhypHeader) -> bool:
    return kind in (2, 3) and bool(header.master_flag & 1) and not header.mhsd_5_type


def is_visible(kind: int, header: MhypHeader) -> bool:
    return kind in (2, 3) and not header.master_flag & 1 and not header.mhsd_5_type


def is_podcasts(kind: int, header: MhypHeader) -> bool:
    return (
        kind == 3
        and is_visible(kind, header)
        and bool(header.playlist_kind_flags & 1)
        and not header.playlist_kind_flags & 0x100
    )


def affected_datasets(
    before: LibrarySnapshot, desired: LibrarySnapshot
) -> frozenset[int]:
    def browse(snapshot: LibrarySnapshot) -> tuple[tuple[object, ...], ...]:
        return tuple(
            (t.track_id, *(value_at(t, name) for name in sorted(BROWSE_FIELDS)))
            for t in snapshot.tracks
        )

    affected: set[int] = set()
    if (
        before.playlists != desired.playlists
        or before.device_name != desired.device_name
        or browse(before) != browse(desired)
    ):
        affected.update((2, 3))
    if {t.track_id for t in before.tracks} - {t.track_id for t in desired.tracks}:
        affected.add(5)
    return frozenset(affected)


def structure_issues(
    document: DatabaseDocument[MhbdHeader],
    *,
    affected: bool = False,
    affected_kinds: frozenset[int] = frozenset((2, 3, 5)),
    phase: str = "source",
) -> tuple[WriteIssue, ...]:
    """Untouched structural anomalies warn; dependent edits must fail closed."""
    issues: list[WriteIssue] = []
    datasets = [
        s
        for s in document.find_chunks(MhsdHeader)
        if s.chunk.header.dataset_type in (2, 3, 5)
    ]
    counts = Counter(s.chunk.header.dataset_type for s in datasets)
    for dataset in datasets:
        kind = dataset.chunk.header.dataset_type
        rows = dataset.find_chunks(MhypHeader)
        severity = (
            IssueSeverity.ERROR
            if affected and kind in affected_kinds
            else IssueSeverity.WARNING
        )

        def issue(
            code: str,
            message: str,
            row: ParsedChunk[MhypHeader] | None = None,
            *,
            dataset_kind: int = kind,
            dataset_offset: int = dataset.chunk.offset,
            level: IssueSeverity = severity,
        ) -> None:
            issues.append(
                WriteIssue(
                    code,
                    message,
                    level,
                    phase,
                    "playlist" if row else "library",
                    row.header.playlist_id if row else None,
                    detail=f"Dataset {dataset_kind}. Inspect the retained source before changing its playlist structure.",
                    offset=row.offset if row else dataset_offset,
                )
            )

        if counts[kind] > 1:
            issue(
                "playlist.duplicate_dataset",
                "Multiple playlist datasets have the same type; their ownership is ambiguous.",
            )
        ids = [s.chunk.header.playlist_id for s in rows]
        if len(set(ids)) != len(ids):
            issue(
                "playlist.duplicate_native_id",
                "A playlist dataset contains repeated native identities.",
            )
        if kind == 5:
            continue
        masters = [s for s in rows if is_master(kind, s.chunk.header)]
        if len(masters) != 1:
            issue(
                "playlist.master_count",
                "This playlist dataset must have exactly one Master Playlist.",
            )
        elif rows[0].path != masters[0].path:
            issue(
                "playlist.master_position",
                "The Master Playlist is not first in its dataset.",
                masters[0].chunk,
            )
        for master in masters:
            members = [s.chunk.header.track_id for s in master.find_chunks(MhipHeader)]
            expected_members = {
                s.chunk.header.track_id for s in document.find_chunks(MhitHeader)
            }
            if set(members) != expected_members or len(members) != len(set(members)):
                issue(
                    "source.master_membership",
                    "The retained Master Playlist has incomplete or ambiguous membership. Unrelated edits preserve it.",
                    master.chunk,
                    level=IssueSeverity.WARNING,
                )
        podcasts = [
            s
            for s in rows
            if is_visible(kind, s.chunk.header)
            and s.chunk.header.playlist_kind_flags & 1
        ]
        if len(podcasts) > 1:
            issue(
                "playlist.multiple_podcasts",
                "More than one Playlist carries the special Podcasts marker.",
            )
        for row in podcasts:
            if row.chunk.header.playlist_kind_flags & 0x100:
                issue(
                    "playlist.podcast_folder",
                    "A Playlist cannot be both the special Podcasts playlist and a folder.",
                    row.chunk,
                )
    return tuple(issues)


def ensure_companion(
    document: DatabaseDocument[MhbdHeader],
    allocator: IdentityAllocator,
) -> DatabaseDocument[MhbdHeader]:
    """Original iOpenPod supplies a standard companion for a type-3-only source.

    Copy retained metadata, but flatten podcast MHIPs for the newly created type 2.
    Existing type 2 rows are never overwritten or inferred from type 3.
    """
    datasets = document.find_chunks(MhsdHeader)
    if any(s.chunk.header.dataset_type == 2 for s in datasets):
        children = list(document.children)
        slots = [
            i
            for i, c in enumerate(children)
            if isinstance(c.header, MhsdHeader) and c.header.dataset_type in (2, 3)
        ]
        ordered = sorted(
            (children[i] for i in slots),
            key=lambda c: -chunk_as(c, MhsdHeader).header.dataset_type,
        )
        for i, child in zip(slots, ordered, strict=True):
            children[i] = child
        return replace(document, children=tuple(children))
    source = next((s for s in datasets if s.chunk.header.dataset_type == 3), None)
    if source is None:
        return document
    rows: list[ParsedChunk[ChunkHeader]] = []
    for child in source.chunk.children[0].children:
        if not isinstance(child.header, MhypHeader):
            rows.append(child)
            continue
        if not is_visible(3, child.header) and not is_master(3, child.header):
            continue
        items = [
            item for item in child.children if not isinstance(item.header, MhipHeader)
        ]
        members = [
            chunk_as(c, MhipHeader)
            for c in child.children
            if isinstance(c.header, MhipHeader)
            and not c.header.podcast_group_flag & 0x100
        ]
        if is_master(3, child.header):
            by_track = {c.header.track_id: c for c in members}
            if len(by_track) != len(members) or any(
                isinstance(c.header, MhipHeader) and c.header.podcast_group_flag & 0x100
                for c in child.children
            ):
                raise ValueError(
                    "Cannot create a standard companion from an ambiguous Master Playlist."
                )
            members = [
                by_track.get(s.chunk.header.track_id)
                or new_itunes_chunk(
                    MHIP,
                    MhipHeader(
                        track_id=s.chunk.header.track_id,
                        track_persistent_id=s.chunk.header.db_track_id,
                    ),
                )
                for s in document.find_chunks(MhitHeader)
            ]
        for position, typed in enumerate(members):
            typed = replace(
                typed,
                header=replace(
                    typed.header,
                    group_id=0,
                    group_id_ref=0,
                    mhip_persistent_id=allocator.take(),
                ),
            )
            items.append(position_item(typed, position))
        rows.append(replace(child, children=tuple(items)))
    companion = new_itunes_chunk(
        MHSD,
        MhsdHeader(dataset_type=2),
        children=(replace(source.chunk.children[0], children=tuple(rows)),),
    )
    children = list(document.children)
    children.insert(source.path.child_indexes[0] + 1, companion)
    return replace(document, children=tuple(children))
