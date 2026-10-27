"""Firmware overlays are idempotent and become durable only in verified output."""

import plistlib
import struct
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from tests.iPodDB.library.test_writing import library
from tests.iPodDB.sidecars.test_sidecar_readers import counts, otg, stats

from iPodDB.device_time import DeviceTimeContext, DeviceTimeSource, mac_to_unix
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import IPodLibrary, WriteResources
from iPodDB.sidecars import PlaybackSidecar


@pytest.mark.parametrize("offset", [-14400, 0, 19800])
def test_play_counts_reference_epoch_does_not_create_playback_dates(
    offset: int,
) -> None:
    # Finder's Nano 5 capture: a summer device offset encodes the missing Core
    # Data date; interpreting it with January DST rules would create 01:00 UTC.
    context = DeviceTimeContext(
        ZoneInfo("America/New_York"),
        DeviceTimeSource.PREFERENCES_CITY,
        database_offset_seconds=offset,
    )
    source = library()
    document = parse_iTunesDB(source.serialize().itunes)
    document = replace(
        document, header=replace(document.header, timezone_offset=offset)
    )
    selected = document.find_chunks(MhitHeader)[0]
    document = document.replace_chunk(
        selected,
        replace(selected.chunk, header=replace(selected.chunk.header, length=20000)),
    )
    source = IPodLibrary(write_iTunesDB(document)).with_device_time(context)
    sentinel = 3061152000 + offset
    sidecar = counts(((0, sentinel, 12005, 0, 512, 0, sentinel),))
    loaded = source.with_sidecars((PlaybackSidecar("Play Counts", sidecar),))
    track = loaded.snapshot.tracks[0]
    assert track.metadata.last_played == 0
    assert track.metadata.last_skipped == 0
    assert track.metadata.bookmark_time_ms == 12005
    prepared = loaded.prepare(
        loaded.analyze(loaded.begin_draft()),
        WriteResources(pending_playback_sidecars=False),
    )
    assert prepared.prepared is not None, prepared.issues
    reread = IPodLibrary(prepared.prepared.itunes).snapshot.tracks[0]
    assert reread.metadata.last_played == reread.metadata.last_skipped == 0


def test_real_play_counts_date_survives_with_zero_completed_plays() -> None:
    source = library()
    sidecar = counts(((0, 3875145178, 500, 0, 512, 0, 0),))
    loaded = source.with_sidecars((PlaybackSidecar("Play Counts", sidecar),))
    track = loaded.snapshot.tracks[0]
    assert track.play_count == 0
    assert track.metadata.last_played == mac_to_unix(3875145178, loaded.device_time)
    assert track.metadata.bookmark_time_ms == 500


def test_reference_epoch_does_not_erase_previous_playback_history() -> None:
    source = library()
    track = source.snapshot.tracks[0]
    desired = replace(
        source.snapshot,
        tracks=(
            replace(
                track,
                metadata=replace(
                    track.metadata,
                    last_played=1_700_000_000,
                    last_skipped=1_700_000_100,
                ),
            ),
            *source.snapshot.tracks[1:],
        ),
    )
    saved = source.prepare(source.analyze(source.begin_draft(desired)))
    assert saved.prepared is not None, saved.issues
    source = IPodLibrary(saved.prepared.itunes)
    sentinel = 3061152000 + source.device_time.database_offset_seconds
    loaded = source.with_sidecars(
        (
            PlaybackSidecar(
                "Play Counts", counts(((0, sentinel, 0, 0, 512, 0, sentinel),))
            ),
        )
    )
    assert loaded.snapshot.tracks[0].metadata.last_played == 1_700_000_000
    assert loaded.snapshot.tracks[0].metadata.last_skipped == 1_700_000_100


def _library_with_playback_history() -> IPodLibrary:
    document = parse_iTunesDB(library().serialize().itunes)
    selected = document.find_chunks(MhitHeader)[0]
    document = document.replace_chunk(
        selected,
        replace(
            selected.chunk,
            header=replace(
                selected.chunk.header,
                play_count_1=7,
                play_count_2=5,
                skip_count=11,
                secondary_skip_count=17,
                last_played=3_800_000_000,
                last_skipped=3_800_000_100,
            ),
        ),
    )
    return IPodLibrary(write_iTunesDB(document))


def _with_native_dates(
    source: IPodLibrary, index: int, played_raw: int, skipped_raw: int
) -> IPodLibrary:
    document = parse_iTunesDB(source.serialize().itunes)
    selected = document.find_chunks(MhitHeader)[index]
    document = document.replace_chunk(
        selected,
        replace(
            selected.chunk,
            header=replace(
                selected.chunk.header,
                last_played=played_raw,
                last_skipped=skipped_raw,
            ),
        ),
    )
    return IPodLibrary(write_iTunesDB(document), device_time=source.device_time)


@pytest.mark.parametrize(
    "played_raw,skipped_raw", [(3_799_998_200, 3_799_998_300), (0, 0)]
)
@pytest.mark.parametrize("play_delta,skip_delta", [(0, 0), (2, 3)])
def test_binary_dates_replace_older_history_or_clear_without_a_count_gate(
    played_raw: int, skipped_raw: int, play_delta: int, skip_delta: int
) -> None:
    source = _library_with_playback_history()
    original = source.serialize()
    sidecars = (
        PlaybackSidecar(
            "Play Counts",
            counts(
                ((play_delta, played_raw, 0, 0xFFFFFFFF, 0, skip_delta, skipped_raw),)
            ),
        ),
    )
    loaded = source.with_sidecars(sidecars)
    track = loaded.snapshot.tracks[0]
    assert not loaded.sidecar_issues
    assert loaded.consumed_sidecars == sidecars
    assert track.play_count == 7 + play_delta
    assert track.metadata.skip_count == 11 + skip_delta
    assert track.metadata.unscrobbled_play_count == 5 + play_delta
    assert track.metadata.last_played == (
        played_raw - 2_082_844_800 if played_raw else 0
    )
    assert track.metadata.last_skipped == (
        skipped_raw - 2_082_844_800 if skipped_raw else 0
    )
    assert loaded.with_sidecars(sidecars).snapshot == loaded.snapshot
    assert loaded.with_device_time(loaded.device_time).snapshot == loaded.snapshot
    assert loaded.serialize() == original

    prepared = loaded.prepare(
        loaded.analyze(loaded.begin_draft()),
        WriteResources(pending_playback_sidecars=False),
    )
    assert prepared.prepared is not None, prepared.issues
    native = parse_iTunesDB(prepared.prepared.itunes).find_chunks(MhitHeader)[0].chunk
    # Check literal serialized coordinates independently of the field definitions.
    assert struct.unpack_from("<I", native.raw_header, 0x58)[0] == played_raw
    assert struct.unpack_from("<I", native.raw_header, 0xA0)[0] == skipped_raw
    assert struct.unpack_from("<I", native.raw_header, 0x50)[0] == 7 + play_delta
    assert struct.unpack_from("<I", native.raw_header, 0x98)[0] == 11 + skip_delta
    assert struct.unpack_from("<I", native.raw_header, 0x9C)[0] == 17
    assert IPodLibrary(prepared.prepared.itunes).snapshot.tracks[0] == track
    assert loaded.serialize() == original


@pytest.mark.parametrize("width", [12, 16, 20, 24, 25, 27])
def test_binary_absent_skip_date_preserves_history_while_zero_play_date_clears(
    width: int,
) -> None:
    source = _library_with_playback_history()
    loaded = source.with_sidecars(
        (
            PlaybackSidecar(
                "Play Counts",
                counts(((2, 0, 0, 0xFFFFFFFF, 0, 0, 0),), width=width),
            ),
        )
    )
    track = loaded.snapshot.tracks[0]
    assert not loaded.sidecar_issues
    assert track.play_count == 9
    assert track.metadata.last_played == 0
    assert track.metadata.skip_count == 11
    assert (
        track.metadata.last_skipped == source.snapshot.tracks[0].metadata.last_skipped
    )
    prepared = loaded.prepare(
        loaded.analyze(loaded.begin_draft()),
        WriteResources(pending_playback_sidecars=False),
    )
    assert prepared.prepared is not None, prepared.issues
    native = parse_iTunesDB(prepared.prepared.itunes).find_chunks(MhitHeader)[0].chunk
    assert struct.unpack_from("<I", native.raw_header, 0x58)[0] == 0
    assert struct.unpack_from("<I", native.raw_header, 0xA0)[0] == 3_800_000_100
    assert IPodLibrary(prepared.prepared.itunes).snapshot.tracks[0] == track
    assert loaded.serialize() == source.serialize()


def test_binary_finder_sentinels_preserve_history_while_counts_increase() -> None:
    source = _library_with_playback_history()
    sentinel = 3_061_152_000 + source.device_time.database_offset_seconds
    loaded = source.with_sidecars(
        (
            PlaybackSidecar(
                "Play Counts", counts(((2, sentinel, 0, 0xFFFFFFFF, 0, 3, sentinel),))
            ),
        )
    )
    track = loaded.snapshot.tracks[0]
    assert not loaded.sidecar_issues
    assert track.play_count == 9
    assert track.metadata.skip_count == 14
    assert track.metadata.last_played == source.snapshot.tracks[0].metadata.last_played
    assert (
        track.metadata.last_skipped == source.snapshot.tracks[0].metadata.last_skipped
    )
    prepared = loaded.prepare(
        loaded.analyze(loaded.begin_draft()),
        WriteResources(pending_playback_sidecars=False),
    )
    assert prepared.prepared is not None, prepared.issues
    assert IPodLibrary(prepared.prepared.itunes).snapshot.tracks[0] == track


@pytest.mark.parametrize("field", ["played", "skipped"])
@pytest.mark.parametrize(
    "collision", ["incoming_epoch", "retained_fold", "retained_gap", "retained_epoch"]
)
def test_binary_unrepresentable_date_in_later_row_preserves_all_pending_evidence(
    field: str, collision: str
) -> None:
    source = _library_with_playback_history()
    previous = 0
    if collision in ("retained_fold", "retained_gap"):
        source = source.with_device_time(
            DeviceTimeContext(
                ZoneInfo("America/New_York"), DeviceTimeSource.PREFERENCES_CITY
            )
        )
        label = (
            "2026-11-01T01:30:00"
            if collision == "retained_fold"
            else "2026-03-08T02:30:00"
        )
        previous = int(
            (datetime.fromisoformat(label) - datetime(1904, 1, 1)).total_seconds()
        )
    elif collision == "retained_epoch":
        previous = 2_082_844_800
    source = _with_native_dates(
        source,
        1,
        previous if field == "played" else 0,
        previous if field == "skipped" else 0,
    )
    assert source.snapshot.tracks[1].metadata.last_played == 0
    assert source.snapshot.tracks[1].metadata.last_skipped == 0
    incoming = 2_082_844_800 if collision == "incoming_epoch" else 0
    sidecar = PlaybackSidecar(
        "Play Counts",
        counts(
            (
                (2, 3_800_001_800, 5000, 80, 0x100, 3, 3_800_001_800),
                (
                    1,
                    incoming if field == "played" else 0,
                    0,
                    0xFFFFFFFF,
                    0,
                    1,
                    incoming if field == "skipped" else 0,
                ),
            )
        ),
    )
    loaded = source.with_sidecars((sidecar,))
    assert loaded.snapshot == source.snapshot
    assert not loaded.consumed_sidecars
    assert len(loaded.sidecar_issues) == 1
    issue = loaded.sidecar_issues[0]
    assert issue.code == "source.playback_sidecar"
    assert f"Track 2 last-{field} date" in issue.message
    assert (
        "Unix zero" if collision == "incoming_epoch" else "cannot be cleared"
    ) in issue.message
    result = loaded.prepare(
        loaded.analyze(loaded.begin_draft()),
        WriteResources(pending_playback_sidecars=False),
    )
    assert result.prepared is None
    assert loaded.serialize() == source.serialize()


@pytest.mark.parametrize("instant", [-1, 1])
def test_binary_dates_on_either_side_of_unix_zero_remain_representable(
    instant: int,
) -> None:
    source = _library_with_playback_history()
    raw = 2_082_844_800 + instant
    loaded = source.with_sidecars(
        (PlaybackSidecar("Play Counts", counts(((0, raw, 0, 0xFFFFFFFF, 0, 0, raw),))),)
    )
    track = loaded.snapshot.tracks[0]
    assert not loaded.sidecar_issues
    assert track.metadata.last_played == track.metadata.last_skipped == instant
    result = loaded.prepare(
        loaded.analyze(loaded.begin_draft()),
        WriteResources(pending_playback_sidecars=False),
    )
    assert result.prepared is not None, result.issues
    native = parse_iTunesDB(result.prepared.itunes).find_chunks(MhitHeader)[0].chunk
    assert struct.unpack_from("<I", native.raw_header, 0x58)[0] == raw
    assert struct.unpack_from("<I", native.raw_header, 0xA0)[0] == raw
    assert IPodLibrary(result.prepared.itunes).snapshot.tracks[0] == track


@pytest.mark.parametrize("incoming", ["valid", "sentinel", "absent_skip"])
def test_binary_dates_can_replace_unavailable_history_or_preserve_it_explicitly(
    incoming: str,
) -> None:
    source = _library_with_playback_history().with_device_time(
        DeviceTimeContext(
            ZoneInfo("America/New_York"), DeviceTimeSource.PREFERENCES_CITY
        )
    )
    ambiguous = int(
        (datetime(2026, 11, 1, 1, 30) - datetime(1904, 1, 1)).total_seconds()
    )
    source = _with_native_dates(
        source, 0, 0 if incoming == "absent_skip" else ambiguous, ambiguous
    )
    raw = 3_800_000_000 if incoming == "valid" else 3_061_152_000
    if incoming == "absent_skip":
        data = counts(((2, 0, 0),), width=12)
    else:
        data = counts(((2, raw, 0, 0xFFFFFFFF, 0, 0, raw),))
    loaded = source.with_sidecars((PlaybackSidecar("Play Counts", data),))
    assert not loaded.sidecar_issues
    assert len(loaded.consumed_sidecars) == 1
    assert loaded.snapshot.tracks[0].play_count == 9
    result = loaded.prepare(
        loaded.analyze(loaded.begin_draft()),
        WriteResources(pending_playback_sidecars=False),
    )
    assert result.prepared is not None, result.issues
    native = parse_iTunesDB(result.prepared.itunes).find_chunks(MhitHeader)[0].chunk
    assert struct.unpack_from("<I", native.raw_header, 0x58)[0] == (
        raw if incoming == "valid" else 0 if incoming == "absent_skip" else ambiguous
    )
    assert struct.unpack_from("<I", native.raw_header, 0xA0)[0] == (
        raw if incoming == "valid" else ambiguous
    )
    assert (
        IPodLibrary(
            result.prepared.itunes, device_time=source.device_time
        ).snapshot.tracks[0]
        == loaded.snapshot.tracks[0]
    )
    assert loaded.serialize() == source.serialize()


@pytest.mark.parametrize(
    "kind,dates",
    [
        ("stats24", "absent"),
        ("stats32", "older"),
        ("stats32", "zero"),
        ("plist", "older"),
        ("plist", "zero"),
        ("plist", "absent"),
    ],
)
def test_other_formats_keep_the_newest_nonzero_date_policy(
    kind: str, dates: str
) -> None:
    source = _library_with_playback_history()
    if kind == "plist":
        row = {"persistentID": 101, "playCount": 2, "skipCount": 3}
        if dates != "absent":
            row.update(
                playMacOSDate=3_799_998_200 if dates == "older" else 0,
                skipMacOSDate=3_799_998_300 if dates == "older" else 0,
            )
        sidecar = PlaybackSidecar("PlayCounts.plist", plistlib.dumps({"tracks": [row]}))
    else:
        # Stats24 has no date fields; Stats32 has mandatory Unix date words.
        data = bytearray(stats(3 if kind == "stats24" else 4, (2,)))
        if kind == "stats32" and dates != "older":
            struct.pack_into("<I", data, 8 + 3 * 4, 0)
            struct.pack_into("<I", data, 8 + 5 * 4, 0)
        sidecar = PlaybackSidecar("iTunesStats", bytes(data))
    loaded = source.with_sidecars((sidecar,))
    track = loaded.snapshot.tracks[0]
    assert not loaded.sidecar_issues
    assert loaded.consumed_sidecars == (sidecar,)
    assert track.play_count == 9
    assert track.metadata.last_played == source.snapshot.tracks[0].metadata.last_played
    assert (
        track.metadata.last_skipped == source.snapshot.tracks[0].metadata.last_skipped
    )
    prepared = loaded.prepare(
        loaded.analyze(loaded.begin_draft()),
        WriteResources(pending_playback_sidecars=False),
    )
    assert prepared.prepared is not None, prepared.issues
    assert IPodLibrary(prepared.prepared.itunes).snapshot.tracks[0] == track


def test_playback_overlay_is_visible_lossless_and_idempotent() -> None:
    source = library()
    original = source.serialize()
    sidecars = (PlaybackSidecar("Play Counts", counts()),)
    loaded = source.with_sidecars(sidecars)
    track = loaded.snapshot.tracks[0]
    assert track.play_count == 3 and track.rating == 80
    assert track.metadata.skip_count == 2
    assert track.metadata.unscrobbled_play_count == 3
    assert track.metadata.last_played == mac_to_unix(3_800_000_000, loaded.device_time)
    assert track.metadata.bookmark_time_ms == 500
    assert track.metadata.played
    assert loaded.serialize() == original
    assert loaded.with_sidecars(sidecars).snapshot == loaded.snapshot
    assert loaded.with_device_time(loaded.device_time).snapshot == loaded.snapshot
    assert source.snapshot.tracks[0].play_count == 0
    plan = loaded.analyze(loaded.begin_draft())
    assert plan.changes_itunes and plan.requires_sidecar_inventory
    blocked = loaded.prepare(plan)
    assert blocked.prepared is None
    result = loaded.prepare(plan, WriteResources(pending_playback_sidecars=False))
    assert result.prepared is not None, result.issues
    reloaded = IPodLibrary(result.prepared.itunes)
    assert reloaded.snapshot.tracks[0] == track
    assert loaded.serialize() == original


@pytest.mark.parametrize("marker,expected", [(1, True), (2, False)])
@pytest.mark.parametrize("plays", [0, 7])
def test_play_counts_explicit_played_marker_survives_preparation(
    marker: int, expected: bool, plays: int
) -> None:
    source = library()
    document = parse_iTunesDB(source.serialize().itunes)
    selected = document.find_chunks(MhitHeader)[0]
    document = document.replace_chunk(
        selected,
        replace(
            selected.chunk,
            header=replace(
                selected.chunk.header,
                play_count_1=plays,
                not_played_flag=2 if expected else 1,
            ),
        ),
    )
    source = IPodLibrary(write_iTunesDB(document))
    data = bytearray(counts(((0, 0, 0, 0xFFFFFFFF, 0, 0, 0),)))
    data[96 + 0x11] = marker
    loaded = source.with_sidecars((PlaybackSidecar("Play Counts", bytes(data)),))
    assert loaded.snapshot.tracks[0].metadata.played is expected
    assert loaded.snapshot.tracks[0].play_count == plays
    prepared = loaded.prepare(
        loaded.analyze(loaded.begin_draft()),
        WriteResources(pending_playback_sidecars=False),
    )
    assert prepared.prepared is not None, prepared.issues
    reread = IPodLibrary(prepared.prepared.itunes).snapshot.tracks[0]
    assert reread.metadata.played is expected
    assert reread.play_count == plays
    assert loaded.serialize() == source.serialize()


def test_binary_zero_bookmark_clears_the_previous_position() -> None:
    source = library()
    document = parse_iTunesDB(source.serialize().itunes)
    selected = document.find_chunks(MhitHeader)[0]
    document = document.replace_chunk(
        selected,
        replace(
            selected.chunk, header=replace(selected.chunk.header, bookmark_time=7500)
        ),
    )
    source = IPodLibrary(write_iTunesDB(document))
    loaded = source.with_sidecars(
        (PlaybackSidecar("Play Counts", counts(((0, 0, 0),), width=12)),)
    )
    assert loaded.snapshot.tracks[0].metadata.bookmark_time_ms == 0
    prepared = loaded.prepare(
        loaded.analyze(loaded.begin_draft()),
        WriteResources(pending_playback_sidecars=False),
    )
    assert prepared.prepared is not None, prepared.issues
    assert (
        IPodLibrary(prepared.prepared.itunes)
        .snapshot.tracks[0]
        .metadata.bookmark_time_ms
        == 0
    )
    plist = plistlib.dumps({"tracks": [{"persistentID": 101, "playCount": 0}]})
    assert (
        source.with_sidecars((PlaybackSidecar("PlayCounts.plist", plist),))
        .snapshot.tracks[0]
        .metadata.bookmark_time_ms
        == 7500
    )


def test_empty_otg_base_activates_numbered_playlists_without_an_empty_playlist() -> (
    None
):
    source = library()
    sidecars = (
        PlaybackSidecar("OTGPlaylistInfo_10", otg((1, 0, 1))),
        PlaybackSidecar("OTGPlaylistInfo", b""),
        PlaybackSidecar("OTGPlaylistInfo_2", otg((0,))),
    )
    loaded = source.with_sidecars(sidecars)
    assert not loaded.sidecar_issues
    imported = loaded.snapshot.playlists[len(source.snapshot.playlists) :]
    assert [(p.name, p.track_ids) for p in imported] == [
        ("On-The-Go 3", (1,)),
        ("On-The-Go 11", (2, 1, 2)),
    ]
    assert loaded.consumed_sidecars == (sidecars[1], sidecars[2], sidecars[0])
    assert loaded.serialize() == source.serialize()
    assert loaded.with_sidecars(sidecars).snapshot == loaded.snapshot


@pytest.mark.parametrize(
    "sidecars",
    [
        (PlaybackSidecar("OTGPlaylistInfo", b"bad"),),
        (
            PlaybackSidecar("OTGPlaylistInfo", b""),
            PlaybackSidecar("OTGPlaylistInfo_1", b""),
        ),
    ],
)
def test_otg_empty_marker_exception_does_not_accept_malformed_documents(
    sidecars: tuple[PlaybackSidecar, ...],
) -> None:
    source = library()
    loaded = source.with_sidecars(sidecars)
    assert loaded.sidecar_issues
    assert loaded.snapshot == source.snapshot
    prepared = loaded.prepare(
        loaded.analyze(loaded.begin_draft()),
        WriteResources(pending_playback_sidecars=False),
    )
    assert prepared.prepared is None
    assert loaded.serialize() == source.serialize()


def test_otg_imports_numbered_files_in_numeric_order_and_keeps_duplicates() -> None:
    source = library()
    sidecars = tuple(
        PlaybackSidecar(name, otg((1, 0, 1)))
        for name in ("OTGPlaylistInfo_10", "OTGPlaylistInfo_2", "OTGPlaylistInfo")
    )
    loaded = source.with_sidecars(sidecars)
    imported = loaded.snapshot.playlists[len(source.snapshot.playlists) :]
    assert [p.name for p in imported] == ["On-The-Go 1", "On-The-Go 3", "On-The-Go 11"]
    assert imported[0].track_ids == (2, 1, 2)
    assert len({p.playlist_id for p in loaded.snapshot.playlists}) == len(
        loaded.snapshot.playlists
    )
    assert loaded.with_sidecars(sidecars).snapshot == loaded.snapshot
    result = loaded.prepare(
        loaded.analyze(loaded.begin_draft()),
        WriteResources(pending_playback_sidecars=False),
    )
    assert result.prepared is not None, result.issues
    assert (
        tuple(p.track_ids for p in result.prepared.snapshot.playlists[-3:])
        == ((2, 1, 2),) * 3
    )


def test_orphan_numbered_otg_is_not_imported_again() -> None:
    source = library()
    loaded = source.with_sidecars((PlaybackSidecar("OTGPlaylistInfo_1", otg((0,))),))
    assert loaded.snapshot == source.snapshot
    assert not loaded.consumed_sidecars


def test_omitting_imported_otg_requires_explicit_deletion_intent() -> None:
    source = library()
    loaded = source.with_sidecars((PlaybackSidecar("OTGPlaylistInfo", otg((0,))),))
    desired = replace(loaded.snapshot, playlists=source.snapshot.playlists)
    plan = loaded.analyze(loaded.begin_draft(desired))
    assert any(i.code == "draft.deletion_not_enabled" for i in plan.issues)
    result = loaded.prepare(
        loaded.analyze(loaded.begin_draft(desired, delete_omissions=True)),
        WriteResources(pending_playback_sidecars=False),
    )
    assert result.prepared is not None, result.issues
    assert result.prepared.itunes == source.serialize().itunes


def test_plist_matches_persistent_ids_instead_of_track_order() -> None:
    source = library()
    data = plistlib.dumps({"tracks": [{"persistentID": 102, "playCount": 4}]})
    loaded = source.with_sidecars((PlaybackSidecar("PlayCounts.plist", data),))
    assert [t.play_count for t in loaded.snapshot.tracks] == [0, 4]


@pytest.mark.parametrize("word", [3, 4])
def test_stats_projects_supported_fields_without_inventing_skip_count(
    word: int,
) -> None:
    loaded = library().with_sidecars((PlaybackSidecar("iTunesStats", stats(word)),))
    assert [t.play_count for t in loaded.snapshot.tracks] == [3, 5]
    assert loaded.snapshot.tracks[0].metadata.skip_count == 0
    assert loaded.snapshot.tracks[0].metadata.last_played == (
        1_700_000_000 if word == 4 else 0
    )


@pytest.mark.parametrize(
    "sidecars",
    [
        (PlaybackSidecar("Play Counts", counts(((1, 0, 0),) * 3, width=12)),),
        (PlaybackSidecar("Play Counts", b"broken"),),
        (PlaybackSidecar("OTGPlaylistInfo", otg((0, 999))),),
        (
            PlaybackSidecar("Play Counts", counts()),
            PlaybackSidecar("iTunesStats", stats(3)),
        ),
        (
            PlaybackSidecar(
                "PlayCounts.plist",
                plistlib.dumps({"tracks": [{"persistentID": 999, "playCount": 1}]}),
            ),
        ),
    ],
)
def test_invalid_evidence_is_not_partially_applied_and_blocks_save(
    sidecars: tuple[PlaybackSidecar, ...],
) -> None:
    source = library()
    loaded = source.with_sidecars(sidecars)
    assert loaded.snapshot == source.snapshot
    assert loaded.sidecar_issues
    result = loaded.prepare(
        loaded.analyze(loaded.begin_draft()),
        WriteResources(pending_playback_sidecars=False),
    )
    assert result.prepared is None
    assert loaded.serialize() == source.serialize()


@pytest.mark.parametrize("wall", ["2026-11-01T01:30:00", "2026-03-08T02:30:00"])
@pytest.mark.parametrize("field", ["played", "skipped"])
def test_later_gap_or_fold_row_rejects_all_pending_history_without_guessing(
    wall: str, field: str
) -> None:
    ambiguous = int(
        (datetime.fromisoformat(wall) - datetime(1904, 1, 1)).total_seconds()
    )
    valid = int((datetime(2026, 10, 26, 12) - datetime(1904, 1, 1)).total_seconds())
    context = DeviceTimeContext(
        ZoneInfo("America/New_York"), DeviceTimeSource.PREFERENCES_CITY
    )
    source = _library_with_playback_history().with_device_time(context)
    sidecar = PlaybackSidecar(
        "Play Counts",
        counts(
            (
                (2, valid, 5000, 80, 0x100, 3, valid),
                (
                    1,
                    ambiguous if field == "played" else valid,
                    1000,
                    0xFFFFFFFF,
                    0,
                    1,
                    ambiguous if field == "skipped" else valid,
                ),
            )
        ),
    )
    loaded = source.with_sidecars((sidecar,))
    assert len(loaded.sidecar_issues) == 1
    assert loaded.sidecar_issues[0].code == "source.playback_sidecar"
    assert "ambiguous or nonexistent" in loaded.sidecar_issues[0].message
    assert not loaded.consumed_sidecars
    assert loaded.snapshot == source.snapshot
    assert loaded.serialize() == source.serialize()
    assert loaded.with_sidecars((sidecar,)).snapshot == source.snapshot
    result = loaded.prepare(
        loaded.analyze(loaded.begin_draft()),
        WriteResources(pending_playback_sidecars=False),
    )
    assert result.prepared is None


def test_existing_totals_are_added_once_and_later_user_edits_win() -> None:
    source = library()
    track = source.snapshot.tracks[0]
    before = replace(
        track,
        play_count=7,
        rating=80,
        metadata=replace(
            track.metadata, unscrobbled_play_count=5, skip_count=9, played=True
        ),
    )
    result = source.prepare(
        source.analyze(
            source.begin_draft(
                replace(source.snapshot, tracks=(before, source.snapshot.tracks[1]))
            )
        )
    )
    assert result.prepared is not None, result.issues
    loaded = IPodLibrary(result.prepared.itunes).with_sidecars(
        (PlaybackSidecar("Play Counts", counts(((3, 0, 0, 0, 0, 2, 0),))),)
    )
    merged = loaded.snapshot.tracks[0]
    assert merged.play_count == 10 and merged.rating == 0
    assert merged.metadata.unscrobbled_play_count == 8
    assert merged.metadata.skip_count == 11
    desired = replace(
        loaded.snapshot, tracks=(replace(merged, rating=60), loaded.snapshot.tracks[1])
    )
    saved = loaded.prepare(
        loaded.analyze(loaded.begin_draft(desired)),
        WriteResources(pending_playback_sidecars=False),
    )
    assert saved.prepared is not None, saved.issues
    assert saved.prepared.snapshot.tracks[0].rating == 60


def short_header_library(header_length: int = 0x9C) -> IPodLibrary:
    """Original-format MHIT ends before secondary skip, date, and played fields."""
    document = parse_iTunesDB(library().serialize().itunes)
    for selection in document.find_chunks(MhitHeader):
        chunk = selection.chunk
        document = document.replace_chunk(
            selection,
            replace(
                chunk,
                generic_header=replace(
                    chunk.generic_header, header_length=header_length
                ),
                raw_header=chunk.raw_header[:header_length],
            ),
        )
    return IPodLibrary(write_iTunesDB(document))


def test_skip_evidence_beyond_a_short_track_header_is_never_discarded() -> None:
    source = short_header_library()
    loaded = source.with_sidecars((PlaybackSidecar("Play Counts", counts()),))
    assert not loaded.sidecar_issues
    track = loaded.snapshot.tracks[0]
    assert track.play_count == 3 and track.rating == 80
    assert track.metadata.skip_count == 2
    assert track.metadata.last_skipped == mac_to_unix(3_800_000_100, loaded.device_time)
    assert track.metadata.played
    result = loaded.prepare(
        loaded.analyze(loaded.begin_draft()),
        WriteResources(pending_playback_sidecars=False),
    )
    # Without selected-device capabilities, keep the evidence pending.
    assert result.prepared is None
    assert loaded.serialize() == source.serialize()
    assert loaded.consumed_sidecars


@pytest.mark.parametrize("play_count,played", [(4, True), (0, False)])
def test_played_state_follows_play_count_in_a_short_track_header(
    play_count: int, played: bool
) -> None:
    source = short_header_library()
    track = source.snapshot.tracks[0]
    edited = replace(
        track,
        play_count=play_count,
        metadata=replace(track.metadata, played=played),
    )
    desired = replace(source.snapshot, tracks=(edited, *source.snapshot.tracks[1:]))
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    reloaded = IPodLibrary(result.prepared.itunes).snapshot.tracks[0]
    assert reloaded.play_count == play_count
    assert reloaded.metadata.played is (play_count > 0)


def test_played_without_plays_is_rejected_in_a_short_track_header() -> None:
    source = short_header_library()
    track = source.snapshot.tracks[0]
    edited = replace(track, metadata=replace(track.metadata, played=True))
    desired = replace(source.snapshot, tracks=(edited, *source.snapshot.tracks[1:]))
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is None
    assert any(i.code == "track.unstorable" for i in result.issues)
