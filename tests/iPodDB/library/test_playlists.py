"""Playlist browsing semantics exercised through complete lossless source adapters."""

from dataclasses import replace

import pytest

from iPodDB.ArtworkDB.builder.build_ArtworkDB import new_ArtworkDB
from iPodDB.ArtworkDB.writer.write_ArtworkDB import write_ArtworkDB
from iPodDB.iTunesDB.builder.build_iTunesDB import (
    new_itunes_chunk,
    new_iTunesDB,
    new_string_mhod,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhip import DEFINITION as MHIP
from iPodDB.iTunesDB.shared.chunk_defs.mhip import MhipHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhit import DEFINITION as MHIT
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhlp import DEFINITION as MHLP
from iPodDB.iTunesDB.shared.chunk_defs.mhlt import DEFINITION as MHLT
from iPodDB.iTunesDB.shared.chunk_defs.mhod import DEFINITION as MHOD
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.contextual_100_mhod import (
    MhodPlaylistPositionPayload,
    MhodPlaylistPositionPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.plist_mhod import MhodPlistPayload
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.smart_prefs_mhod import (
    MhodSmartPrefsPayload,
    MhodSmartPrefsPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.smart_rules_mhod import (
    MhodSmartNumericRuleData,
    MhodSmartRawRuleData,
    MhodSmartRule,
    MhodSmartRuleGroupData,
    MhodSmartRulesPayload,
    MhodSmartRulesPrefix,
    MhodSmartStringRuleData,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import DEFINITION as MHSD
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import DEFINITION as MHYP
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import MhypHeader
from iPodDB.iTunesDB.shared.constants import MhodType
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import (
    IPodLibrary,
    LibrarySnapshot,
    Playlist,
    PlaylistKind,
    PlaylistSortOrder,
    SmartField,
    SmartLimitSort,
    SmartLimitUnit,
    SmartMatch,
    SmartOperator,
    SmartPlaylist,
    SmartPlaylistLimit,
    SmartRule,
    SmartRuleGroup,
    UnsupportedPlaylistSortOrder,
    UnsupportedSmartRule,
)
from iPodDB.shared.chunk import EmptyChunkHeader, ParsedChunk


def _playlist(
    playlist_id: int,
    name: str,
    *,
    parent: int = 0,
    folder: bool = False,
    master: bool = False,
    category: int = 0,
    items: tuple[MhipHeader, ...] = (),
    metadata: tuple[ParsedChunk[MhodHeader], ...] = (),
) -> ParsedChunk[MhypHeader]:
    return new_itunes_chunk(
        MHYP,
        MhypHeader(
            playlist_id=playlist_id,
            parent_folder_playlist_id=parent,
            playlist_kind_flags=0x0100 if folder else 0,
            master_flag=int(master),
            mhsd_5_type=category,
        ),
        children=(
            new_string_mhod(MhodType.TITLE, name),
            *metadata,
            *(new_itunes_chunk(MHIP, item) for item in items),
        ),
    )


def _dataset(kind: int, *playlists: ParsedChunk[MhypHeader]) -> ParsedChunk[MhsdHeader]:
    return new_itunes_chunk(
        MHSD,
        MhsdHeader(dataset_type=kind),
        children=(new_itunes_chunk(MHLP, EmptyChunkHeader(), children=playlists),),
    )


def _database(*datasets: ParsedChunk[MhsdHeader]) -> bytes:
    tracks = new_itunes_chunk(
        MHLT,
        EmptyChunkHeader(),
        children=tuple(
            new_itunes_chunk(MHIT, MhitHeader(track_id=track_id))
            for track_id in (0, 1, 2)
        ),
    )
    track_dataset = new_itunes_chunk(
        MHSD, MhsdHeader(dataset_type=1), children=(tracks,)
    )
    return write_iTunesDB(
        new_iTunesDB(MhbdHeader(), datasets=(track_dataset, *datasets))
    )


def _smart(
    *rules: MhodSmartRule,
    conjunction: int = 0,
    prefs: MhodSmartPrefsPrefix | None = None,
) -> tuple[ParsedChunk[MhodHeader], ParsedChunk[MhodHeader]]:
    return (
        new_itunes_chunk(
            MHOD,
            MhodHeader(mhod_type=MhodType.SMART_PLAYLIST_PREFERENCES),
            prefix=prefs or MhodSmartPrefsPrefix(live_update=1, check_rules=1),
            payload=MhodSmartPrefsPayload(),
        ),
        new_itunes_chunk(
            MHOD,
            MhodHeader(mhod_type=MhodType.SMART_PLAYLIST_RULES),
            prefix=MhodSmartRulesPrefix(
                magic=b"SLst", unk_0x1C=0x00010001, conjunction=conjunction
            ),
            payload=MhodSmartRulesPayload(rules=rules, trailing_data=b""),
        ),
    )


def _string_rule(
    field: int = 0x04, action: int = 0x01000002, value: str = "Miles"
) -> MhodSmartRule:
    return MhodSmartRule(
        field, action, 0, bytes(40), MhodSmartStringRuleData(value, b"")
    )


def _numeric_rule(
    field: int = 0x19, action: int = 0x00000100, lower: int = 60, upper: int = 100
) -> MhodSmartRule:
    return MhodSmartRule(
        field,
        action,
        0,
        bytes(40),
        MhodSmartNumericRuleData(lower, 0, 1, upper, 0, 1, 0, 0, 0, 0, 0, b""),
    )


def test_prefers_dataset_three_without_duplicating_mirrors_or_exposing_categories() -> (
    None
):
    data = (
        _database(
            _dataset(5, _playlist(90, "Rentals", master=True, category=7)),
            _dataset(
                2, _playlist(10, "Older name", master=True), _playlist(11, "Mirror")
            ),
            _dataset(
                3,
                _playlist(10, "John's iPod", master=True),
                _playlist(11, "Road trips"),
            ),
        )
        + b"untouched suffix"
    )
    source = IPodLibrary.parse(data)
    assert source.snapshot.device_name == "John's iPod"
    assert source.snapshot.playlists == (Playlist(11, "Road trips"),)
    assert source.serialize().itunes == data


def test_dataset_two_fallback_and_empty_authoritative_dataset() -> None:
    fallback = _dataset(2, _playlist(10, "My iPod", master=True), _playlist(11, "Mix"))
    assert IPodLibrary(_database(fallback)).snapshot.device_name == "My iPod"
    assert IPodLibrary(_database(fallback, _dataset(3))).snapshot.playlists == ()
    assert (
        IPodLibrary(
            _database(_dataset(5, _playlist(1, "Music", master=True, category=4)))
        ).snapshot.device_name
        == ""
    )


def test_ambiguous_masters_do_not_invent_a_device_name() -> None:
    snapshot = IPodLibrary(
        _database(
            _dataset(
                2, _playlist(1, "One", master=True), _playlist(2, "Two", master=True)
            )
        )
    ).snapshot
    assert snapshot.device_name == ""
    assert snapshot.playlists == ()


def test_membership_preserves_valid_occurrences_and_skips_missing_tracks_and_group_headers() -> (
    None
):
    data = _database(
        _dataset(
            3,
            _playlist(
                11,
                "Episodes",
                items=(
                    MhipHeader(track_id=0, podcast_group_flag=0x0100),
                    MhipHeader(track_id=2),
                    MhipHeader(track_id=1),
                    MhipHeader(track_id=2),
                    MhipHeader(track_id=99),
                    MhipHeader(track_id=0),
                ),
            ),
        )
    )
    source = IPodLibrary(data)
    assert source.snapshot.playlists[0].track_ids == (2, 1, 2, 0)
    assert source.serialize().itunes == data


def test_playlist_sort_order_and_occurrence_positions_are_projected_losslessly() -> (
    None
):
    def item(track_id: int, position: int) -> ParsedChunk[MhipHeader]:
        return new_itunes_chunk(
            MHIP,
            MhipHeader(track_id=track_id),
            children=(
                new_itunes_chunk(
                    MHOD,
                    MhodHeader(mhod_type=100),
                    prefix=MhodPlaylistPositionPrefix(position=position),
                    payload=MhodPlaylistPositionPayload(),
                ),
            ),
        )

    playlist = _playlist(11, "Positioned")
    playlist = replace(
        playlist,
        header=replace(playlist.header, sort_order=PlaylistSortOrder.TITLE),
        children=(*playlist.children, item(2, 7), item(1, 2)),
    )
    data = _database(_dataset(3, playlist))

    source = IPodLibrary(data)
    projected = source.snapshot.playlists[0]

    assert projected.sort_order is PlaylistSortOrder.TITLE
    assert tuple(entry.position for entry in projected.entries) == (7, 2)
    assert source.serialize().itunes == data


def test_unknown_playlist_sort_order_is_explicit_and_losslessly_retained() -> None:
    playlist = _playlist(11, "Future order")
    playlist = replace(playlist, header=replace(playlist.header, sort_order=0xFEDC))
    data = _database(_dataset(3, playlist))

    source = IPodLibrary(data)

    assert source.snapshot.playlists[0].sort_order == UnsupportedPlaylistSortOrder(
        0xFEDC
    )
    assert source.serialize().itunes == data


def test_playlist_title_does_not_come_from_a_podcast_group_title() -> None:
    group = new_itunes_chunk(
        MHIP,
        MhipHeader(podcast_group_flag=0x0100),
        children=(new_string_mhod(MhodType.TITLE, "Show name"),),
    )
    playlist = _playlist(1, "Podcasts")
    playlist = replace(playlist, children=(*playlist.children, group))
    assert (
        IPodLibrary(_database(_dataset(3, playlist))).snapshot.playlists[0].name
        == "Podcasts"
    )


def test_folders_remain_folders_when_they_carry_smart_aggregate_rules() -> None:
    snapshot = IPodLibrary(
        _database(
            _dataset(
                3,
                _playlist(10, "Outer", folder=True, metadata=_smart()),
                _playlist(11, "Inner", parent=10, folder=True, metadata=_smart()),
                _playlist(12, "Smart mix", parent=11, metadata=_smart(_string_rule())),
            )
        )
    ).snapshot
    outer, inner, smart = snapshot.playlists
    assert outer.kind is inner.kind is PlaylistKind.FOLDER
    assert outer.smart is inner.smart is None
    assert inner.parent_id == 10
    assert smart.parent_id == 11
    assert smart.kind is PlaylistKind.SMART


def test_hierarchy_repairs_only_projection_and_keeps_children_of_detached_cycles() -> (
    None
):
    data = _database(
        _dataset(
            2,
            _playlist(10, "A", folder=True, parent=20),
            _playlist(20, "B", folder=True, parent=10),
            _playlist(30, "Self", folder=True, parent=30),
            _playlist(40, "Missing", parent=99),
            _playlist(50, "Not a folder", parent=40),
            _playlist(60, "Child", parent=10),
        )
    )
    source = IPodLibrary(data)
    assert tuple(item.parent_id for item in source.snapshot.playlists) == (
        None,
        None,
        None,
        None,
        None,
        10,
    )
    assert source.serialize().itunes == data


def test_folder_projection_has_no_fixed_nesting_depth() -> None:
    source = IPodLibrary(
        _database(
            _dataset(
                2,
                *(
                    _playlist(index, str(index), folder=True, parent=index - 1)
                    for index in range(1, 1_101)
                ),
            )
        )
    )
    assert len(source.snapshot.playlists) == 1_100
    assert source.snapshot.playlists[-1].parent_id == 1_099


def test_snapshot_and_source_reject_duplicate_playlist_identities() -> None:
    with pytest.raises(ValueError, match="Duplicate Playlist ID"):
        LibrarySnapshot(playlists=(Playlist(0, "One"), Playlist(0, "Two")))
    with pytest.raises(ValueError, match="Duplicate Playlist ID"):
        IPodLibrary(_database(_dataset(2, _playlist(1, "One"), _playlist(1, "Two"))))
    assert (
        LibrarySnapshot(playlists=(Playlist(0, "Zero"),)).playlists[0].playlist_id == 0
    )


def test_nested_smart_rules_translate_without_flattening_and_retain_stored_membership() -> (
    None
):
    group = MhodSmartRule(
        0,
        1,
        0x01000000,
        bytes(40),
        MhodSmartRuleGroupData(
            b"SLst",
            0x00010001,
            0,
            1,
            bytes(120),
            (_string_rule(), _numeric_rule()),
            b"",
        ),
    )
    prefs = MhodSmartPrefsPrefix(
        live_update=1,
        check_rules=1,
        check_limits=1,
        limit_type=3,
        limit_sort=23,
        limit_value=25,
        match_checked_only=1,
    )
    data = _database(
        _dataset(
            3,
            _playlist(
                1,
                "Favorites",
                metadata=_smart(group, prefs=prefs),
                items=(MhipHeader(track_id=2),),
            ),
        )
    )
    source = IPodLibrary(data)
    playlist = source.snapshot.playlists[0]
    assert playlist.smart == SmartPlaylist(
        rules=SmartRuleGroup(
            rules=(
                SmartRuleGroup(
                    SmartMatch.ANY,
                    (
                        SmartRule(SmartField.ARTIST, SmartOperator.CONTAINS, "Miles"),
                        SmartRule(SmartField.RATING, SmartOperator.BETWEEN, 60, 100),
                    ),
                ),
            )
        ),
        checked_only=True,
        limit=SmartPlaylistLimit(
            25, SmartLimitUnit.TRACKS, SmartLimitSort.RATING, True
        ),
    )
    assert playlist.track_ids == (2,)
    assert source.serialize().itunes == data


@pytest.mark.parametrize(
    "rule",
    (
        _string_rule(field=0x9F),
        _string_rule(action=0x03000008),
        MhodSmartRule(0xFFFF, 1, 0, bytes(40), MhodSmartRawRuleData(b"future rule")),
    ),
)
def test_unknown_smart_conditions_are_uneditable_and_losslessly_retained(
    rule: MhodSmartRule,
) -> None:
    data = _database(_dataset(2, _playlist(1, "Future mix", metadata=_smart(rule))))
    source = IPodLibrary(data)
    smart = source.snapshot.playlists[0].smart
    assert smart is not None and not smart.editable
    assert isinstance(smart.rules.rules[0], UnsupportedSmartRule)
    assert source.serialize().itunes == data


@pytest.mark.parametrize(
    ("conjunction", "nested", "field"),
    (
        (99, _string_rule(), 0),
        (1, _string_rule(field=0x9F), 0),
        (1, _string_rule(), 7),
    ),
)
def test_unknown_nested_smart_conditions_and_wrappers_remain_uneditable(
    conjunction: int, nested: MhodSmartRule, field: int
) -> None:
    group_data: MhodSmartRuleGroupData | MhodSmartRawRuleData
    if field == 0:
        group_data = MhodSmartRuleGroupData(
            b"SLst", 0x00010001, 0, conjunction, bytes(120), (nested,), b""
        )
    else:
        # An unknown wrapper is opaque, even when its body begins with SLst.
        group_data = MhodSmartRawRuleData(b"SLst" + bytes(8))
    group = MhodSmartRule(
        field,
        1,
        0x01000000,
        bytes(40),
        group_data,
    )
    data = _database(_dataset(2, _playlist(1, "Nested mix", metadata=_smart(group))))
    source = IPodLibrary(data)
    smart = source.snapshot.playlists[0].smart
    assert smart is not None and not smart.editable
    assert source.serialize().itunes == data


def test_structurally_truncated_nested_smart_rules_fail_at_the_lossless_parser() -> (
    None
):
    truncated = MhodSmartRule(
        0, 1, 0x01000000, bytes(40), MhodSmartRawRuleData(b"SLst" + bytes(8))
    )
    data = _database(_dataset(2, _playlist(1, "Truncated", metadata=_smart(truncated))))
    with pytest.raises(ValueError, match=r"nested SLst.*too short"):
        IPodLibrary(data)


@pytest.mark.parametrize(
    "prefs",
    (
        MhodSmartPrefsPrefix(
            check_rules=1, check_limits=1, limit_type=99, limit_sort=2, limit_value=25
        ),
        MhodSmartPrefsPrefix(
            check_rules=1, check_limits=1, limit_type=3, limit_sort=99, limit_value=25
        ),
        MhodSmartPrefsPrefix(check_rules=1, live_update=2),
    ),
)
def test_unrecognized_smart_preferences_are_explicitly_uneditable(
    prefs: MhodSmartPrefsPrefix,
) -> None:
    smart = (
        IPodLibrary(
            _database(
                _dataset(
                    2, _playlist(1, "Mix", metadata=_smart(_string_rule(), prefs=prefs))
                )
            )
        )
        .snapshot.playlists[0]
        .smart
    )
    assert smart is not None and not smart.editable


def test_description_prefers_playlist_properties_then_contextual_string() -> None:
    properties = new_itunes_chunk(
        MHOD,
        MhodHeader(mhod_type=MhodType.PLAYLIST_PROPERTY_PLIST),
        payload=MhodPlistPayload(
            b"", {"description": "A weekend soundtrack", "future": 7}
        ),
    )
    fallback = new_string_mhod(MhodType.ALBUM, "Earlier description")
    data = _database(
        _dataset(
            2,
            _playlist(1, "Mix", metadata=(properties, fallback)),
            _playlist(2, "Second", metadata=(fallback,)),
        )
    )
    source = IPodLibrary(data)
    assert tuple(item.description for item in source.snapshot.playlists) == (
        "A weekend soundtrack",
        "Earlier description",
    )
    assert source.serialize().itunes == data


def test_artwork_replacement_retains_playlists_and_name_without_touching_source() -> (
    None
):
    data = _database(
        _dataset(2, _playlist(10, "My iPod", master=True), _playlist(11, "Mix"))
    )
    source = IPodLibrary(data)
    artwork = write_ArtworkDB(new_ArtworkDB(next_mhii_id=1, unk_mhfd_0x10=2))
    updated = source.with_artwork(artwork)
    assert updated.snapshot.playlists == source.snapshot.playlists
    assert updated.snapshot.device_name == "My iPod"
    assert updated.serialize().itunes == data
