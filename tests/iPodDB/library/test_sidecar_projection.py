"""Firmware overlays are idempotent and become durable only in verified output."""

import plistlib
from dataclasses import replace
from zoneinfo import ZoneInfo

import pytest
from tests.iPodDB.library.test_writing import library
from tests.iPodDB.sidecars.test_sidecar_readers import counts, otg, stats

from iPodDB.device_time import DeviceTimeContext, DeviceTimeSource, mac_to_unix
from iPodDB.library import IPodLibrary, WriteResources
from iPodDB.sidecars import PlaybackSidecar


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


def test_ambiguous_device_date_preserves_pending_history_without_guessing() -> None:
    from datetime import datetime

    ambiguous = int(
        (datetime(2026, 11, 1, 1, 30) - datetime(1904, 1, 1)).total_seconds()
    )
    context = DeviceTimeContext(
        ZoneInfo("America/New_York"), DeviceTimeSource.PREFERENCES_CITY
    )
    source = library().with_device_time(context)
    loaded = source.with_sidecars(
        (PlaybackSidecar("Play Counts", counts(((1, ambiguous, 0),), width=12)),)
    )
    assert loaded.sidecar_issues
    assert loaded.snapshot == source.snapshot


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
