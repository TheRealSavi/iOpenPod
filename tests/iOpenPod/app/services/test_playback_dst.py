"""Uncertain firmware dates never prevent loading or replay history twice."""

import struct
from pathlib import Path

import pytest
from tests.iOpenPod.app.services.test_library_resources import build_device
from tests.iPodDB.sidecars.test_sidecar_readers import counts
from whenever import PlainDateTime

from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader


@pytest.mark.parametrize("wall", ["2026-11-01T01:30:00", "2026-03-08T02:30:00"])
@pytest.mark.parametrize("field", ["played", "skipped"])
def test_selection_commits_uncertain_dates_without_changing_native_words(
    tmp_path: Path, wall: str, field: str
) -> None:
    device = build_device(tmp_path, model="MB145")
    try:
        candidate = device.active.candidate.id
        preferences = bytearray(2956)
        struct.pack_into("<H", preferences, 0xB70, 0x29)  # New York
        preferences_path = device.root / "iPod_Control/Device/Preferences"
        preferences_path.write_bytes(preferences)
        native = PlainDateTime(wall).assume_utc().timestamp() + 2_082_844_800
        played, skipped = (native, 0) if field == "played" else (0, native)
        sidecar = counts(((2, played, 0, 0xFFFFFFFF, 0, 3, skipped),))
        directory = device.root / "iPod_Control/iTunes"
        path = directory / "Play Counts"
        path.write_bytes(sidecar)

        active = device.coordinator.select_device(candidate, reconcile_metadata=False)
        assert active.library.tracks[0].play_count == 2
        assert active.library.tracks[0].metadata.skip_count == 3
        assert preferences_path.read_bytes() == preferences
        assert not path.exists()
        assert path.with_name("Play Counts.bak").read_bytes() == sidecar
        committed = (directory / "iTunesDB").read_bytes()
        header = parse_iTunesDB(committed).find_chunks(MhitHeader)[0].chunk.header
        assert (header.last_played, header.last_skipped) == (played, skipped)

        again = device.coordinator.select_device(candidate, reconcile_metadata=False)
        assert again.library.tracks[0] == active.library.tracks[0]
        assert (directory / "iTunesDB").read_bytes() == committed
    finally:
        device.coordinator.close()
