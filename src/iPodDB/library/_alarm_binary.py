"""Classic and Nano 3/4 native imported Playlist array for explicit Alarm edits."""

from dataclasses import dataclass
from functools import cmp_to_key

from iPodDB.iTunesDB.shared.chunk_defs.mhip import MhipHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.smart_prefs_mhod import (
    MhodSmartPrefsPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.smart_rules_mhod import (
    MhodSmartRulesPayload,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.string_mhod import (
    MhodStringPayload,
    MhodStringPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import MhypHeader
from iPodDB.iTunesDB.shared.constants import MhodType
from iPodDB.library._alarm_chunks import dataset_rows, has_captured_fields
from iPodDB.library._alarm_collation import compare_alarm_names
from iPodDB.library._alarm_names import native_alarm_name
from iPodDB.library.alarm_playlists import (
    AlarmPlaylist,
    AlarmPlaylistCatalog,
    AlarmPlaylistLayout,
)
from iPodDB.shared.binary_struct import binary_struct_extent
from iPodDB.shared.chunk import ParsedChunk, chunk_as


@dataclass(frozen=True, slots=True)
class _Imported:
    row: ParsedChunk[MhypHeader]
    name: str
    sort_name: str
    smart: bool
    audio: bool


def _import(
    row: ParsedChunk[MhypHeader], tracks: dict[int, int], mask: int, issues: list[str]
) -> _Imported:
    name = sort_name = ""
    attached = False
    inhibited = 0
    audio = False
    groups: set[int] = set()
    if (
        not has_captured_fields(
            row, "playlist_id", "master_flag", "playlist_kind_flags"
        )
        or row.raw_trailing_data
    ):
        issues.append("A native Playlist has incomplete identity or trailing records.")
    for child in row.children:
        header = child.header
        if isinstance(header, MhodHeader):
            if header.mhod_type == MhodType.TITLE:
                if not isinstance(child.payload, MhodStringPayload) or not isinstance(
                    child.prefix, MhodStringPrefix
                ):
                    issues.append("A Playlist name has an unsupported native encoding.")
                    continue
                if child.prefix.encoding_indicator != 1:
                    # Original encoding-2 title import feeds uninitialized stack
                    # bytes into its counted-name cache. No stable order exists.
                    issues.append(
                        "A Playlist uses an unsupported native Alarm name encoding."
                    )
                    continue
                name = child.payload.value
                if not name and child.prefix.bypass_pair_composition == 0:
                    issues.append(
                        "An empty Playlist title reuses undefined native Alarm name state."
                    )
                    continue
                native_name = name
                if (
                    child.raw_body
                    and child.original_payload == child.payload
                    and child.original_prefix == child.prefix
                ):
                    start = (
                        binary_struct_extent(MhodStringPrefix)
                        - child.generic_header.header_length
                    )
                    native_name = child.raw_body[
                        start : start + child.prefix.string_length
                    ].decode("utf-16-le", errors="surrogatepass")
                sort_name = native_alarm_name(
                    native_name, compose=child.prefix.bypass_pair_composition == 0
                )
            elif header.mhod_type == MhodType.SMART_PLAYLIST_PREFERENCES:
                if not isinstance(child.prefix, MhodSmartPrefsPrefix):
                    issues.append("A Smart Playlist has incomplete native preferences.")
                    continue
                inhibited = child.prefix.attachment_inhibit
                attached = attached or not inhibited
            elif header.mhod_type == MhodType.SMART_PLAYLIST_RULES:
                if not isinstance(child.payload, MhodSmartRulesPayload):
                    issues.append("A Smart Playlist has incomplete native rules.")
                    continue
                attached = attached or not inhibited
        elif isinstance(header, MhipHeader):
            if not has_captured_fields(
                child, "group_marker", "group_id", "group_id_ref", "track_id"
            ):
                issues.append("A Playlist member has incomplete native fields.")
                continue
            if header.group_id_ref and header.group_id_ref not in groups:
                continue
            if header.is_group:
                if not header.group_id or header.group_id in groups:
                    issues.append("Playlist group identities are ambiguous.")
                groups.add(header.group_id)
            elif header.track_id and tracks.get(header.track_id, 0) & mask:
                audio = True
        else:
            issues.append("A Playlist contains unrecognized native records.")
    return _Imported(row, name, sort_name, attached, audio)


def project_binary_alarm_playlists(
    dataset: ParsedChunk[MhsdHeader],
    tracks: dict[int, int],
    issues: list[str],
    layout: AlarmPlaylistLayout,
) -> AlarmPlaylistCatalog:
    mask = 0x20012D if layout is AlarmPlaylistLayout.CLASSIC_LATE else 0x12D
    imported: list[_Imported] = []
    child_counts: dict[int, int] = {}
    for row in dataset_rows(dataset, b"mhlp", issues):
        if not isinstance(row.header, MhypHeader):
            issues.append(
                "An unrecognized Playlist makes native sound indices ambiguous."
            )
            continue
        native = _import(chunk_as(row, MhypHeader), tracks, mask, issues)
        identity = row.header.playlist_id
        if not identity or identity in child_counts:
            issues.append("Native Playlist identities must be nonzero and unique.")
        # Native lookup links parents already imported; later/missing parents
        # attach to the root and do not retroactively acquire children.
        parent = (
            row.header.parent_folder_playlist_id
            if has_captured_fields(row, "parent_folder_playlist_id")
            else 0
        )
        if parent in child_counts:
            child_counts[parent] += 1
        child_counts[identity] = 0
        imported.append(native)
    masters = [row for row in imported if row.row.header.master_flag]
    if len(masters) != 1:
        issues.append(
            "The native Playlist array needs one unambiguous Master Playlist."
        )
    selected = [
        row
        for row in imported
        if not row.row.header.playlist_kind_flags & 1
        and not (
            layout is AlarmPlaylistLayout.CLASSIC_LATE
            and row.row.header.phase_game_flag & 0xFF in (32, 34)
        )
        and (
            row.row.header.master_flag
            or row.audio
            or (row.smart and child_counts[row.row.header.playlist_id] == 0)
        )
    ]

    def compare(left: _Imported, right: _Imported) -> int:
        lm, rm = bool(left.row.header.master_flag), bool(right.row.header.master_flag)
        return (
            (rm - lm)
            if lm != rm
            else compare_alarm_names(left.sort_name, right.sort_name)
        )

    # Python's stable sort reproduces increasing allocation IDs for name ties.
    selected.sort(key=cmp_to_key(compare))
    result = tuple(
        AlarmPlaylist(
            index,
            row.row.header.playlist_id,
            row.name,
            bool(row.row.header.master_flag),
        )
        for index, row in enumerate(selected)
    )
    if not result or not result[0].is_master:
        issues.append("The native Master Playlist is absent from the sound array.")
    return AlarmPlaylistCatalog(result, tuple(dict.fromkeys(issues)))
