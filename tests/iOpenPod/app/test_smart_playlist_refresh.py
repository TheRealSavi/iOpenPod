"""Refresh saved Smart Playlist membership at the shared publication boundary."""

from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from tests.iOpenPod.app.services.test_library_resources import Device, build_device
from tests.iOpenPod.app.test_sync_execution import (
    _AvailableTools,  # pyright: ignore[reportPrivateUsage]
    _Executor,  # pyright: ignore[reportPrivateUsage]
    _host,  # pyright: ignore[reportPrivateUsage]
    _request,  # pyright: ignore[reportPrivateUsage]
)
from tests.iPodDB.library.test_writing import library

from iOpenPod.app.library_write import PreparationCancelledError
from iOpenPod.app.smart_playlist_preview import refresh_smart_playlists
from iOpenPod.app.sync_execution import SyncExecutionStatus
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.smart_rules_mhod import (
    MhodSmartNumericRuleData,
    MhodSmartRawRuleData,
    MhodSmartRulesPayload,
)
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
    SmartOperator,
    SmartPlaylist,
    SmartPlaylistLimit,
    SmartPlaylistReference,
    SmartRule,
    SmartRuleGroup,
    Track,
    TrackMetadata,
    UnsupportedSmartRule,
    playlist_entries,
)
from iPodDB.library._smart_writing import smart_chunks
from iPodDB.shared.chunk import ParsedChunk


def _smart(identity: int, rule: SmartRule, *members: int) -> Playlist:
    return Playlist(
        identity,
        f"Smart {identity}",
        PlaylistKind.SMART,
        entries=playlist_entries(members),
        smart=SmartPlaylist(rules=SmartRuleGroup(rules=(rule,))),
    )


def test_refresh_uses_final_tracks_preserves_occurrences_and_applies_limit_and_sort() -> (
    None
):
    tracks = (
        Track(1, "Zebra", "Artist", "Album", 1000, rating=100),
        Track(2, "Alpha", "Artist", "Album", 1000, rating=80),
        Track(3, "Dropped", "Artist", "Album", 1000, rating=20),
    )
    playlist = _smart(
        10, SmartRule(SmartField.RATING, SmartOperator.GREATER_THAN, 60), 1, 3
    )
    assert playlist.smart is not None
    playlist = replace(
        playlist,
        sort_order=PlaylistSortOrder.TITLE,
        smart=replace(
            playlist.smart,
            limit=SmartPlaylistLimit(
                2, SmartLimitUnit.TRACKS, SmartLimitSort.RATING, descending=True
            ),
        ),
    )
    snapshot = LibrarySnapshot(tracks=tracks, playlists=(playlist,))

    updated = refresh_smart_playlists(snapshot)

    assert updated.playlists[0].track_ids == (2, 1)
    assert updated.playlists[0].entries[1].entry_id == playlist.entries[0].entry_id
    assert tuple(e.position for e in updated.playlists[0].entries) == (0, 1)
    assert updated.playlists[0].smart == playlist.smart
    assert snapshot.playlists[0].track_ids == (1, 3)
    assert refresh_smart_playlists(updated) == updated


def test_refresh_preserves_unknown_rules_and_firmware_managed_membership() -> None:
    unknown = replace(
        _smart(10, SmartRule(SmartField.YEAR, SmartOperator.IS, 2000), 1),
        smart=SmartPlaylist(
            rules=SmartRuleGroup(rules=(UnsupportedSmartRule(),)), editable=False
        ),
    )
    managed = replace(
        _smart(11, SmartRule(SmartField.YEAR, SmartOperator.IS, 2000), 1),
        system_managed=True,
    )
    regular = Playlist(12, "Regular", entries=playlist_entries((1, 1)))
    snapshot = LibrarySnapshot(
        tracks=(Track(1, "Song", "Artist", "Album", 1000),),
        playlists=(unknown, managed, regular),
    )

    assert refresh_smart_playlists(snapshot) == snapshot


@pytest.mark.parametrize("upper_displacement", (-1, 1))
def test_displaced_relative_upper_bound_retains_bytes_and_saved_occurrences(
    upper_displacement: int,
) -> None:
    smart = SmartPlaylist(
        rules=SmartRuleGroup(
            rules=(SmartRule(SmartField.DATE_ADDED, SmartOperator.IN_LAST, 86400),)
        )
    )
    prefs, row = smart_chunks(smart, ())
    payload = row.payload
    assert isinstance(payload, MhodSmartRulesPayload)
    rule = payload.rules[0]
    assert isinstance(rule.data, MhodSmartNumericRuleData)
    native = replace(
        row,
        payload=replace(
            payload,
            rules=(replace(rule, data=replace(rule.data, to_date=upper_displacement)),),
        ),
    )
    _assert_unsupported_definition_preserves_bytes_and_membership(prefs, native)


@pytest.mark.parametrize("upper", (False, True))
def test_signed_native_numeric_bound_retains_bytes_and_saved_occurrences(
    upper: bool,
) -> None:
    semantic = (
        SmartRule(SmartField.PLAY_COUNT, SmartOperator.BETWEEN, 0, 10)
        if upper
        else SmartRule(SmartField.PLAY_COUNT, SmartOperator.LESS_THAN, 10)
    )
    prefs, row = smart_chunks(
        SmartPlaylist(rules=SmartRuleGroup(rules=(semantic,))), ()
    )
    payload = row.payload
    assert isinstance(payload, MhodSmartRulesPayload)
    rule = payload.rules[0]
    assert isinstance(rule.data, MhodSmartNumericRuleData)
    data = (
        replace(rule.data, to_value=1 << 63)
        if upper
        else replace(rule.data, from_value=1 << 63)
    )
    native = replace(row, payload=replace(payload, rules=(replace(rule, data=data),)))
    _assert_unsupported_definition_preserves_bytes_and_membership(prefs, native)


@pytest.mark.parametrize("raw_text", (b"\x00A\xff", b"\xd8\x00", b"\xdc\x00"))
def test_malformed_utf16_operand_retains_bytes_and_saved_occurrences(
    raw_text: bytes,
) -> None:
    smart = SmartPlaylist(
        rules=SmartRuleGroup(
            rules=(SmartRule(SmartField.TITLE, SmartOperator.IS, "A"),)
        )
    )
    prefs, row = smart_chunks(smart, ())
    payload = row.payload
    assert isinstance(payload, MhodSmartRulesPayload)
    rule = replace(payload.rules[0], data=MhodSmartRawRuleData(raw_text))
    native = replace(row, payload=replace(payload, rules=(rule,)))
    _assert_unsupported_definition_preserves_bytes_and_membership(prefs, native)


def _assert_unsupported_definition_preserves_bytes_and_membership(
    prefs: ParsedChunk[MhodHeader], native: ParsedChunk[MhodHeader]
) -> None:
    document = parse_iTunesDB(library(mirrored=True).serialize().itunes)
    for path in document.find_chunks(MhypHeader):
        if path.chunk.header.playlist_id == 10:
            document = document.replace_chunk(
                path,
                replace(path.chunk, children=(prefs, native, *path.chunk.children)),
            )
    before = write_iTunesDB(document)
    source = IPodLibrary.parse(before)
    playlists = tuple(p for p in source.snapshot.playlists if p.playlist_id == 10)
    assert playlists and all(
        p.smart is not None and not p.smart.editable for p in playlists
    )
    assert playlists[0].track_ids == (1, 2, 1)

    refreshed = refresh_smart_playlists(source.snapshot, now=1_700_000_000)
    assert refreshed == source.snapshot
    desired = replace(
        refreshed,
        tracks=(
            replace(refreshed.tracks[0], title="Unrelated edit"),
            *refreshed.tracks[1:],
        ),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    adopted = IPodLibrary.parse(result.prepared.itunes)
    assert adopted.snapshot.playlists == source.snapshot.playlists
    assert adopted.snapshot.tracks[0].title == "Unrelated edit"
    native_rule_bytes: list[tuple[bytes, ...]] = []
    for data in (before, result.prepared.itunes):
        parsed = parse_iTunesDB(data)
        native_rule_bytes.append(
            tuple(
                path.chunk.raw_header + path.chunk.raw_body
                for path in parsed.find_chunks(MhodHeader)
                if path.chunk.header.mhod_type == MhodType.SMART_PLAYLIST_RULES
            )
        )
    assert len(native_rule_bytes[0]) == 2
    assert native_rule_bytes[1] == native_rule_bytes[0]


def test_refresh_uses_one_instant_and_saved_folder_memberships_without_cascading() -> (
    None
):
    tracks = (
        Track(1, "Old", "Artist", "Album", 1000),
        Track(
            2,
            "Recent",
            "Artist",
            "Album",
            1000,
            metadata=TrackMetadata(last_played=101),
        ),
    )
    recent = replace(
        _smart(10, SmartRule(SmartField.LAST_PLAYED, SmartOperator.IN_LAST, 100), 1),
        parent_id=20,
    )
    folder = Playlist(20, "Folder", PlaylistKind.FOLDER)
    reference = _smart(
        30, SmartRule(SmartField.PLAYLIST, SmartOperator.IS, SmartPlaylistReference(20))
    )
    snapshot = LibrarySnapshot(tracks=tracks, playlists=(recent, folder, reference))

    updated = refresh_smart_playlists(snapshot, now=200)
    assert updated.playlists[0].track_ids == (2,)
    assert updated.playlists[2].track_ids == (1,)
    reversed_order = refresh_smart_playlists(
        replace(snapshot, playlists=tuple(reversed(snapshot.playlists))), now=200
    )
    assert tuple(p.track_ids for p in reversed_order.playlists) == tuple(
        p.track_ids for p in reversed(updated.playlists)
    )


def test_refresh_reports_invalid_rules_and_can_be_cancelled() -> None:
    snapshot = LibrarySnapshot(
        playlists=(
            _smart(
                10,
                SmartRule(
                    SmartField.PLAYLIST, SmartOperator.IS, SmartPlaylistReference(99)
                ),
            ),
        )
    )
    with pytest.raises(
        ValueError, match=r'Smart Playlist "Smart 10".*missing Playlist 99'
    ):
        refresh_smart_playlists(snapshot)

    def cancel() -> None:
        raise PreparationCancelledError

    with pytest.raises(PreparationCancelledError):
        refresh_smart_playlists(snapshot, checkpoint=cancel)


def _seed(device: Device, playlists: tuple[Playlist, ...]) -> None:
    """Install stale saved memberships through the pure writer, then reload."""
    device.coordinator.close()
    database = device.root / "iPod_Control/iTunes/iTunesDB"
    source = IPodLibrary.parse(database.read_bytes())
    result = source.prepare(
        source.analyze(
            source.begin_draft(
                replace(
                    source.snapshot,
                    playlists=(
                        *source.snapshot.playlists,
                        *(replace(p, playlist_id=-p.playlist_id) for p in playlists),
                    ),
                )
            )
        )
    )
    assert result.prepared is not None, result.issues
    database.write_bytes(result.prepared.itunes)
    device.coordinator.select_device(
        device.coordinator.discover_devices().candidates[0].id
    )


def _saved_memberships(device: Device) -> dict[str, tuple[int, ...]]:
    source = IPodLibrary.parse(
        (device.root / "iPod_Control/iTunes/iTunesDB").read_bytes()
    )
    return {playlist.name: playlist.track_ids for playlist in source.snapshot.playlists}


def test_invalid_refresh_blocks_publication_and_retains_saved_membership(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path)
    try:
        first = device.active.library.tracks[0]
        _seed(
            device,
            (
                _smart(
                    10,
                    SmartRule(SmartField.TITLE, SmartOperator.IS, first.title),
                    first.track_id,
                ),
            ),
        )
        snapshot = device.active.library
        playlist = next(p for p in snapshot.playlists if p.name == "Smart 10")
        assert playlist.smart is not None
        invalid = replace(
            playlist,
            smart=replace(
                playlist.smart,
                rules=SmartRuleGroup(
                    rules=(
                        SmartRule(
                            SmartField.PLAYLIST,
                            SmartOperator.IS,
                            SmartPlaylistReference(-999),
                        ),
                    )
                ),
            ),
        )
        database = device.root / "iPod_Control/iTunes/iTunesDB"
        before = database.read_bytes()
        review = device.prepare(
            replace(
                snapshot,
                playlists=tuple(
                    invalid if p.playlist_id == playlist.playlist_id else p
                    for p in snapshot.playlists
                ),
            )
        )
        assert review.result.prepared is None
        assert any(
            'Smart Playlist "Smart 10"' in issue.detail
            for issue in review.result.issues
        )
        assert database.read_bytes() == before
        assert device.active.library == snapshot
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("live_update", [False, True])
def test_metadata_save_refreshes_only_live_smart_playlists_in_the_same_review(
    tmp_path: Path, live_update: bool
) -> None:
    device = build_device(tmp_path)
    try:
        first, second = device.active.library.tracks
        genre_playlist = _smart(
            10, SmartRule(SmartField.GENRE, SmartOperator.IS, "Jazz"), second.track_id
        )
        assert genre_playlist.smart is not None
        genre_playlist = replace(
            genre_playlist, smart=replace(genre_playlist.smart, live_update=live_update)
        )
        _seed(
            device,
            (
                genre_playlist,
                _smart(11, SmartRule(SmartField.TITLE, SmartOperator.IS, second.title)),
            ),
        )
        snapshot = device.active.library
        before = (device.root / "iPod_Control/iTunes/iTunesDB").read_bytes()
        review = device.prepare(
            replace(
                snapshot,
                tracks=(
                    replace(snapshot.tracks[0], genre="Jazz"),
                    snapshot.tracks[1],
                ),
            )
        )
        assert review.result.prepared is not None, review.result.issues
        assert (device.root / "iPod_Control/iTunes/iTunesDB").read_bytes() == before
        assert next(
            p for p in snapshot.playlists if p.name == "Smart 10"
        ).track_ids == (second.track_id,)

        saved = device.save(review)
        assert saved.active is not None, saved.issues
        memberships = _saved_memberships(device)
        assert memberships["Smart 10"] == (
            first.track_id if live_update else second.track_id,
        )
        assert memberships["Smart 11"] == (second.track_id,)
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("add_track", [False, True])
@pytest.mark.parametrize("live_update", [False, True])
def test_full_sync_refreshes_smart_playlists_even_without_other_changes(
    tmp_path: Path, add_track: bool, live_update: bool
) -> None:
    device = build_device(tmp_path)
    try:
        first = device.active.library.tracks[0]
        rule = SmartRule(
            SmartField.TITLE, SmartOperator.IS, "New song" if add_track else first.title
        )
        playlist = _smart(10, rule)
        assert playlist.smart is not None
        playlist = replace(
            playlist, smart=replace(playlist.smart, live_update=live_update)
        )
        _seed(device, (playlist,))
        host = _host(tmp_path, *(("New song",) if add_track else ()))
        request = replace(_request(device, host), reconcile_playlists=False)
        result = _Executor(device.coordinator, transcoder=_AvailableTools()).execute(
            request, lambda _: None, Event()
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert result.active is not None
        matched = next(t for t in result.active.library.tracks if t.title == rule.value)
        expected = (matched.track_id,) if live_update else ()
        assert _saved_memberships(device)["Smart 10"] == expected

        # An already-current Smart Playlist must allow another no-change Sync.
        repeat = _Executor(device.coordinator, transcoder=_AvailableTools()).execute(
            replace(_request(device, _host(tmp_path)), reconcile_playlists=False),
            lambda _: None,
            Event(),
        )
        assert repeat.status is SyncExecutionStatus.SUCCESS, repeat.issues
        assert _saved_memberships(device)["Smart 10"] == expected
    finally:
        device.coordinator.close()
