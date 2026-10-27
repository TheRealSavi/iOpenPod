"""Clock setbacks survive selection-time publication without replaying counts."""

from dataclasses import replace
from pathlib import Path

import pytest
from tests.iOpenPod.app.services.test_library_resources import build_device
from tests.iPodDB.sidecars.test_sidecar_readers import counts

from iPodDB.device_time import MAC_EPOCH_UNIX_OFFSET
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.library import IPodLibrary


@pytest.mark.parametrize("clear_dates", [False, True])
def test_binary_dates_replace_history_and_commit_counts_once(
    tmp_path: Path, clear_dates: bool
) -> None:
    device = build_device(tmp_path)
    directory = device.root / "iPod_Control/iTunes"
    try:
        baseline = device.active.library
        first = baseline.tracks[0]
        prior_played, prior_skipped = 1_700_100_000, 1_700_100_100
        seeded = replace(
            baseline,
            tracks=(
                replace(
                    first,
                    play_count=7,
                    metadata=replace(
                        first.metadata,
                        skip_count=5,
                        last_played=prior_played,
                        last_skipped=prior_skipped,
                    ),
                ),
                *baseline.tracks[1:],
            ),
        )
        review = device.prepare(seeded)
        assert review.result.prepared is not None, review.result.issues
        saved = device.save(review)
        assert saved.active is not None, saved.issues
        pending_before = saved.active.library.tracks[0].metadata.unscrobbled_play_count

        # This virtual device has no Preferences: its diagnosed fixed-offset
        # context makes these synthetic raw words unambiguous.
        offset = parse_iTunesDB(
            (directory / "iTunesDB").read_bytes()
        ).header.timezone_offset
        played = 0 if clear_dates else prior_played - 3600
        skipped = 0 if clear_dates else prior_skipped - 3600
        raw_played = played + MAC_EPOCH_UNIX_OFFSET + offset if played else 0
        raw_skipped = skipped + MAC_EPOCH_UNIX_OFFSET + offset if skipped else 0
        sidecar = counts(((2, raw_played, 0, 0xFFFFFFFF, 0x100, 3, raw_skipped),))
        (directory / "Play Counts").write_bytes(sidecar)

        selected = device.coordinator.select_device(device.active.candidate.id)
        track = selected.library.tracks[0]
        assert track.play_count == 9
        assert track.metadata.skip_count == 8
        assert track.metadata.unscrobbled_play_count == pending_before + 2
        assert (track.metadata.last_played, track.metadata.last_skipped) == (
            played,
            skipped,
        )
        assert selected.library.tracks[1:] == seeded.tracks[1:]
        assert not (directory / "Play Counts").exists()
        assert (directory / "Play Counts.bak").read_bytes() == sidecar

        committed = (directory / "iTunesDB").read_bytes()
        native = parse_iTunesDB(committed).find_chunks(MhitHeader)[0].chunk.header
        assert (native.last_played, native.last_skipped) == (raw_played, raw_skipped)
        assert IPodLibrary(committed).snapshot.tracks[0].metadata.last_played == played
        reselected = device.coordinator.select_device(selected.candidate.id)
        assert reselected.library.tracks[0] == track
        assert (directory / "iTunesDB").read_bytes() == committed
        assert (directory / "Play Counts.bak").read_bytes() == sidecar
    finally:
        device.coordinator.close()
