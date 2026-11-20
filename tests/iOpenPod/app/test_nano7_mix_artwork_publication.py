"""Qualified Nano 7 covers share album formats without sharing image ownership."""

import plistlib
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from tests.iOpenPod.app.services.test_library_resources import Device, build_device
from tests.iPodDB.library.test_write_artwork import BLUE

from iOpenPod.app import genius_mixes
from iOpenPod.app.library_write import LibraryPreparationRequest
from iPodDB.ArtworkDB.parser.parse_ArtworkDB import parse_ArtworkDB
from iPodDB.ArtworkDB.shared.artwork_index import build_artwork_index
from iPodDB.library import CoverFormat, CoverPixelFormat
from storage import HardwareProbeObservation, HardwareProbeResult


def nano7_device(tmp_path: Path, *, version: str = "1.0.4", family: int = 37) -> Device:
    device = build_device(
        tmp_path,
        model="MD479",
        compressed_database=True,
        artwork_format=CoverFormat(1010, 240, 240, 480, CoverPixelFormat.RGB565_LE),
    )
    device.platform.add_volume(
        device.root,
        probe_result=HardwareProbeResult(
            observations=(
                HardwareProbeObservation(
                    source="nano-mix-test",
                    vendor="Apple",
                    product="iPod",
                    vendor_payload=plistlib.dumps(
                        {
                            "ModelNumStr": "MD479",
                            "VisibleBuildID": version,
                            "UpdaterFamilyID": family,
                        }
                    ),
                ),
            )
        ),
    )
    candidate = device.coordinator.discover_devices().candidates[0]
    device.coordinator.select_device(candidate.id, reconcile_metadata=False)
    return device


@pytest.mark.parametrize(("version", "family"), [("1.0.4", 37), ("1.1.2", 39)])
def test_nano7_mix_cover_is_published_and_preserves_album_art(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, version: str, family: int
) -> None:
    monkeypatch.setattr(genius_mixes, "MIN_MIX_TRACKS", 1)
    device = nano7_device(tmp_path, version=version, family=family)
    try:
        original = (device.root / "iPod_Control/Artwork/ArtworkDB").read_bytes()
        before = build_artwork_index(parse_ArtworkDB(original))
        active = device.active
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
        prepared = review.result.prepared
        assert prepared is not None, review.result.issues
        assert prepared.sqlite is not None and prepared.artwork is not None
        assert len(prepared.artwork_files) == 1
        assert prepared.artwork_files[0].relative_path.startswith(
            "iPod_Control/Artwork/F1010_"
        )
        assert len(prepared.artwork_files[0].data) == 115200
        saved = device.save(review)
        assert saved.active is not None, saved.issues
        mix_id = saved.active.genius_mix_state.entries[0].container_id
        after = build_artwork_index(
            parse_ArtworkDB(
                (device.root / "iPod_Control/Artwork/ArtworkDB").read_bytes()
            )
        )
        image = after.item_for_db_track_id(mix_id)
        assert image is not None
        assert (
            image.locations[0].format_id,
            image.locations[0].width,
            image.locations[0].height,
        ) == (1010, 240, 240)
        assert all(
            after.item_for_image_id(item.image_id) == item for item in before.items
        )
        repeated = device.prepare(device.active.library)
        assert repeated.result.prepared is not None, repeated.result.issues
        assert repeated.result.prepared.artwork_files == ()
        assert not any("Artwork" in f.path for f in repeated.file_changes)
        device.restore(saved.recovery_path)
    finally:
        device.coordinator.close()


def test_mix_and_album_cover_changes_can_share_f1010_without_overwriting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(genius_mixes, "MIN_MIX_TRACKS", 1)
    device = nano7_device(tmp_path)
    try:
        existing = {
            p.name: p.read_bytes()
            for p in (device.root / "iPod_Control/Artwork").glob("F1010_*.ithmb")
        }
        assert existing
        active = device.active
        first, second = active.library.tracks
        review = device.coordinator.prepare_library(
            LibraryPreparationRequest(
                replace(
                    active.library,
                    tracks=(
                        replace(first, genre="Rock"),
                        replace(second, genre="Rock", artwork_id=BLUE.artwork_id),
                    ),
                ),
                active,
                2,
                2,
                artwork=(BLUE,),
                regenerate_genius=True,
                add_genius_mixes=("rock",),
            ),
            lambda _: None,
            Event(),
        )
        prepared = review.result.prepared
        assert prepared is not None, review.result.issues
        saved = device.save(review)
        assert saved.active is not None, saved.issues
        index = build_artwork_index(
            parse_ArtworkDB(
                (device.root / "iPod_Control/Artwork/ArtworkDB").read_bytes()
            )
        )
        mix = index.item_for_db_track_id(
            saved.active.genius_mix_state.entries[0].container_id
        )
        assert mix is not None
        assert mix.image_id not in {t.artwork_id for t in saved.active.library.tracks}
        assert mix.locations[0].format_id == 1010
        for name, data in existing.items():
            assert (
                (device.root / "iPod_Control/Artwork" / name)
                .read_bytes()
                .startswith(data)
            )
        repeated = device.prepare(device.active.library)
        assert repeated.result.prepared is not None, repeated.result.issues
        assert repeated.result.prepared.artwork_files == ()
    finally:
        device.coordinator.close()
