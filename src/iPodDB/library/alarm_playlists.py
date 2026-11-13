"""Source-qualified native Playlist indices for legacy Clock Alarm sounds.

Unlike the Library snapshot, these arrays retain the Master Playlist and use the
first type-2/3 dataset in file order. See alarm-sounds-legacy-2026-11-13.md.
"""

from dataclasses import dataclass
from enum import StrEnum

from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhip import MhipHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.smart_prefs_mhod import (
    MhodSmartPrefsPayload,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.smart_rules_mhod import (
    MhodSmartRulesPayload,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.string_mhod import (
    MhodStringPayload,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import MhypHeader
from iPodDB.iTunesDB.shared.constants import MhodType
from iPodDB.library._alarm_chunks import dataset_rows, has_captured_fields
from iPodDB.shared.chunk import (
    DatabaseDocument,
    ParsedChunk,
    chunk_as,
)


class AlarmPlaylistLayout(StrEnum):
    MINI = "mini"
    CLOCK = "clock"
    VIDEO = "video"
    CLASSIC = "classic"
    CLASSIC_LATE = "classic_late"
    NANO_4 = "nano_4"


@dataclass(frozen=True, slots=True)
class AlarmPlaylist:
    index: int
    playlist_id: int
    name: str
    is_master: bool


@dataclass(frozen=True, slots=True)
class AlarmPlaylistCatalog:
    playlists: tuple[AlarmPlaylist, ...] = ()
    issues: tuple[str, ...] = ()
    has_master: bool = True

    @property
    def complete(self) -> bool:
        """Only complete catalogs qualify sound choices or saved PID lookup."""
        return (
            (bool(self.playlists) or not self.has_master)
            and not self.issues
            and all(
                type(row.index) is int
                and row.index == index
                and row.is_master is (self.has_master and index == 0)
                and type(row.playlist_id) is int
                and 0 < row.playlist_id <= 0xFFFFFFFFFFFFFFFF
                for index, row in enumerate(self.playlists)
            )
            and len({row.playlist_id for row in self.playlists}) == len(self.playlists)
        )


def project_sqlite_alarm_playlists(
    library: bytes, dynamic: bytes
) -> AlarmPlaylistCatalog:
    """Project Nano 5's captured companions through the public Library contract."""
    from iPodDB.SQLiteDB.alarm_playlists import (
        project_sqlite_alarm_playlists as project,
    )

    return project(library, dynamic)


def _tracks(
    dataset: ParsedChunk[MhsdHeader],
    tracks: dict[int, int],
    issues: list[str],
    layout: AlarmPlaylistLayout,
) -> None:
    for row in dataset_rows(dataset, b"mhlt", issues):
        header = row.header
        if not isinstance(header, MhitHeader) or not has_captured_fields(
            row, "track_id", "record_class"
        ):
            issues.append("A Track has no qualified native import identity.")
            continue
        classes = (1,) if layout is AlarmPlaylistLayout.CLOCK else (1, 2, 3)
        if header.record_class not in classes:
            continue
        if header.track_id in tracks:
            issues.append("Repeated Track IDs make native Playlist lookup ambiguous.")
        # Native import clears fields absent from old headers; shared authoring
        # defaults are intentionally not interpreted as captured source bytes.
        media = header.media_type if has_captured_fields(row, "media_type") else 0
        tracks[header.track_id] = media & (
            0xFFFFFFFF if layout is AlarmPlaylistLayout.CLASSIC_LATE else 0xFFFF
        )


def _members(
    row: ParsedChunk[MhypHeader], tracks: dict[int, int], issues: list[str]
) -> tuple[int, int]:
    groups: set[int] = set()
    count = media = 0
    for child in row.children:
        header = child.header
        if isinstance(header, MhodHeader):
            continue
        if not isinstance(header, MhipHeader) or not has_captured_fields(
            child, "group_marker", "group_id", "track_id", "group_id_ref"
        ):
            issues.append("A Playlist member has an unsupported native layout.")
            continue
        # Native recursive group lookup sees only already inserted groups.
        if header.group_id_ref and header.group_id_ref not in groups:
            continue
        if header.is_group:
            if header.group_id == 0 or header.group_id in groups:
                issues.append(
                    "Repeated or zero group IDs make native membership ambiguous."
                )
            groups.add(header.group_id)
        elif header.track_id in tracks:
            count = (count + 1) & 0xFFFF
            media |= tracks[header.track_id]
    return count, media


def _playlist(
    row: ParsedChunk[MhypHeader],
    layout: AlarmPlaylistLayout,
    tracks: dict[int, int],
    issues: list[str],
) -> tuple[str, bool] | None:
    header = row.header
    if not has_captured_fields(
        row, "master_flag", "playlist_id", "playlist_kind_flags"
    ):
        issues.append("A Playlist has a truncated native identity header.")
        return None
    if row.raw_trailing_data or any(
        not isinstance(child.header, MhodHeader | MhipHeader) for child in row.children
    ):
        issues.append("A Playlist contains unrecognized native records.")
    if header.playlist_kind_flags & 1:
        return None
    metadata = tuple(
        child for child in row.children if isinstance(child.header, MhodHeader)
    )
    title = next(
        (
            child.payload.value
            for child in reversed(metadata)
            if isinstance(child.header, MhodHeader)
            and child.header.mhod_type == MhodType.TITLE
            and isinstance(child.payload, MhodStringPayload)
        ),
        "",
    )
    master = bool(header.master_flag)
    if layout is not AlarmPlaylistLayout.MINI and not master:
        smart = False
        for child in metadata:
            assert isinstance(child.header, MhodHeader)
            if child.header.mhod_type in (
                MhodType.SMART_PLAYLIST_PREFERENCES,
                MhodType.SMART_PLAYLIST_RULES,
            ):
                smart = True
                if not isinstance(
                    child.payload, MhodSmartPrefsPayload | MhodSmartRulesPayload
                ):
                    issues.append(
                        "A Smart Playlist has an unqualified native import payload."
                    )
        if not smart:
            count, media = _members(row, tracks, issues)
            if count == 0 or (media != 0 and not media & 0x12D):
                return None
    return title, master


def project_alarm_playlists(
    document: DatabaseDocument[MhbdHeader], layout: AlarmPlaylistLayout
) -> AlarmPlaylistCatalog:
    """Project the imported array prefix, excluding appended runtime collections.

    An absent PID is not proof that an on-device generated Playlist is absent.
    Complete catalogs qualify only their captured source rows and indices.
    """
    if type(layout) is not AlarmPlaylistLayout:
        raise TypeError("Alarm Playlists require an explicit native layout.")
    tracks: dict[int, int] = {}
    issues: list[str] = []
    if (
        document.raw_source_suffix
        or document.raw_trailing_data
        or document.header.child_count != len(document.children)
        or any(not isinstance(child.header, MhsdHeader) for child in document.children)
    ):
        issues.append(
            "The native Library root contains unqualified framing or datasets."
        )
    playlists: list[AlarmPlaylist] = []
    selected: ParsedChunk[MhsdHeader] | None = None
    for child in document.children:
        if not isinstance(child.header, MhsdHeader):
            issues.append("The Library contains an unrecognized native dataset.")
            continue
        dataset = chunk_as(child, MhsdHeader)
        if child.header.dataset_type in (2, 3):
            selected = dataset
            break
        if child.header.dataset_type == 1 and layout is not AlarmPlaylistLayout.MINI:
            _tracks(dataset, tracks, issues, layout)
    if selected is None:
        return AlarmPlaylistCatalog(issues=("No native Playlist dataset is present.",))
    if layout in (
        AlarmPlaylistLayout.CLASSIC,
        AlarmPlaylistLayout.CLASSIC_LATE,
        AlarmPlaylistLayout.NANO_4,
    ):
        from iPodDB.library._alarm_binary import project_binary_alarm_playlists

        return project_binary_alarm_playlists(selected, tracks, issues, layout)
    for child in dataset_rows(selected, b"mhlp", issues):
        if not isinstance(child.header, MhypHeader):
            issues.append(
                "An unrecognized Playlist record makes native indices ambiguous."
            )
            continue
        details = _playlist(chunk_as(child, MhypHeader), layout, tracks, issues)
        if details is not None:
            title, master = details
            playlists.append(
                AlarmPlaylist(len(playlists), child.header.playlist_id, title, master)
            )
    if (
        not playlists
        or not playlists[0].is_master
        or sum(p.is_master for p in playlists) != 1
    ):
        issues.append(
            "The native Playlist array requires one Master Playlist at index zero."
        )
    identities = [playlist.playlist_id for playlist in playlists]
    if 0 in identities or len(identities) != len(set(identities)):
        issues.append("Native Alarm Playlist IDs must be nonzero and unique.")
    return AlarmPlaylistCatalog(tuple(playlists), tuple(dict.fromkeys(issues)))
