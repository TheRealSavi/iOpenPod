"""Classic Mix publication uses binary Library data and its Genius companion."""

import plistlib
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from tests.iOpenPod.app.services.test_library_resources import Device, build_device

from device_registry import DeviceProfile
from iOpenPod.app import genius_mixes
from iOpenPod.app.library_write import LibraryPreparationRequest
from iPodDB.ArtworkDB.parser.parse_ArtworkDB import parse_ArtworkDB
from iPodDB.ArtworkDB.shared.artwork_index import build_artwork_index
from iPodDB.library.genius import GeniusCollectionKind
from storage import HardwareProbeObservation, HardwareProbeResult


def classic_device(tmp_path: Path) -> Device:
    device = build_device(tmp_path, model="MB565")
    device.platform.add_volume(
        device.root,
        probe_result=HardwareProbeResult(
            observations=(
                HardwareProbeObservation(
                    source="classic-mix-test",
                    vendor="Apple",
                    product="iPod",
                    vendor_payload=plistlib.dumps(
                        {
                            "ModelNumStr": "MB565",
                            "VisibleBuildID": "2.0.5",
                            "UpdaterFamilyID": 38,
                        }
                    ),
                ),
            )
        ),
    )
    candidate = device.coordinator.discover_devices().candidates[0]
    device.coordinator.select_device(candidate.id, reconcile_metadata=False)
    return device


def test_classic_manual_mix_is_published_browsable_and_recoverable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(genius_mixes, "MIN_MIX_TRACKS", 1)
    device = classic_device(tmp_path)
    try:
        active = device.active
        assert active.firmware_version == "2.0.5"
        assert active.profile.generation == "6.5th Gen"
        assert genius_mixes.supports_mix_creation(active.profile)
        desired = replace(
            active.library,
            tracks=tuple(replace(t, genre="Rock") for t in active.library.tracks),
        )
        review = device.coordinator.prepare_library(
            LibraryPreparationRequest(
                desired,
                active,
                1,
                1,
                regenerate_genius=True,
                add_genius_mixes=("rock",),
            ),
            lambda _: None,
            Event(),
        )
        assert review.result.prepared is not None, review.result.issues
        assert review.result.prepared.sqlite is None
        assert review.result.prepared.artwork is not None
        assert any(
            f.relative_path.startswith("iPod_Control/Artwork/F1069_")
            for f in review.result.prepared.artwork_files
        )
        paths = {c.path for c in review.file_changes}
        assert "iPod_Control/iTunes/iTunesDB" in paths
        assert "iPod_Control/iTunes/Extras.itdb" in paths
        assert not any("iTunes Library.itlp" in p for p in paths)
        saved = device.save(review)
        assert saved.active is not None, saved.issues
        mixes = [
            c
            for c in saved.active.genius.collections
            if c.kind is GeniusCollectionKind.MIX
        ]
        assert len(mixes) == 1 and mixes[0].name == "Rock Mix"
        artwork = (device.root / "iPod_Control/Artwork/ArtworkDB").read_bytes()
        index = build_artwork_index(parse_ArtworkDB(artwork))
        assert mixes[0].native_playlist_id is not None
        cover = index.item_for_db_track_id(mixes[0].native_playlist_id)
        assert cover is not None and cover.locations[0].format_id == 1069
        assert mixes[0].track_ids == tuple(
            t.track_id for t in saved.active.library.tracks
        )
        assert not any(
            p.playlist_id == mixes[0].native_playlist_id
            for p in saved.active.library.playlists
        )
        assert (
            saved.active.genius_mix_state.entries[0].container_id
            == mixes[0].native_playlist_id
        )
        device.restore(saved.recovery_path)
    finally:
        device.coordinator.close()


def test_existing_owned_mix_receives_cover_on_next_save_then_reuses_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from iOpenPod.app.services import device_coordinator

    def no_mix_artwork(_profile: DeviceProfile) -> None:
        return None

    monkeypatch.setattr(genius_mixes, "MIN_MIX_TRACKS", 1)
    device = classic_device(tmp_path)
    try:
        active = device.active
        desired = replace(
            active.library,
            tracks=tuple(replace(t, genre="Rock") for t in active.library.tracks),
        )
        # Simulate the previous producer, which saved Mixes without covers.
        with monkeypatch.context() as prior:
            prior.setattr(device_coordinator, "mix_artwork_format", no_mix_artwork)
            review = device.coordinator.prepare_library(
                LibraryPreparationRequest(
                    desired,
                    active,
                    1,
                    1,
                    regenerate_genius=True,
                    add_genius_mixes=("rock",),
                ),
                lambda _: None,
                Event(),
            )
            saved = device.save(review)
            assert saved.active is not None, saved.issues
        initial = (device.root / "iPod_Control/Artwork/ArtworkDB").read_bytes()
        review = device.prepare(device.active.library)
        assert review.result.prepared is not None, review.result.issues
        assert len(review.result.prepared.artwork_files) == 1
        assert (device.root / "iPod_Control/Artwork/ArtworkDB").read_bytes() == initial
        saved = device.save(review)
        assert saved.active is not None, saved.issues
        repeated = device.prepare(device.active.library)
        assert repeated.result.prepared is not None, repeated.result.issues
        assert repeated.result.prepared.artwork_files == ()
        assert not any("Artwork" in f.path for f in repeated.file_changes)
    finally:
        device.coordinator.close()
