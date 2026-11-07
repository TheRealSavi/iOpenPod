"""Rebuild undersized Phase indexes through ordinary Classic Library saves."""

import plistlib
from dataclasses import replace
from pathlib import Path

import pytest
from tests.iOpenPod.app.services.test_library_resources import build_device

from iOpenPod.app.services.phase import INDEX_PATH, MANIFEST_PATH
from iPodDB.games import parse_phase_library
from iPodDB.library import Playlist


@pytest.mark.parametrize(
    "original", [b"", b"mhfd" + bytes(303)], ids=["empty", "short"]
)
@pytest.mark.parametrize("create", [True, False], ids=["create", "convert"])
@pytest.mark.parametrize("change_after_review", [False, True], ids=["save", "conflict"])
def test_rebuild_short_index_on_classic_save(
    tmp_path: Path, original: bytes, create: bool, change_after_review: bool
) -> None:
    device = build_device(tmp_path, model="MC293")
    try:
        manifest = device.root / str(MANIFEST_PATH)
        manifest.parent.mkdir(parents=True)
        manifest.write_bytes(
            plistlib.dumps({"Name": "Phase", "Version": "1.0", "GUID": "phase"})
        )
        index = device.root / str(INDEX_PATH)
        index.parent.mkdir(parents=True)
        index.write_bytes(original)
        active = device.coordinator.select_device(device.active.candidate.id)
        before = active.library
        playlists = (
            (*before.playlists, Playlist(-2, "Phase Songs", is_phase=True))
            if create
            else tuple(
                replace(p, is_phase=True, entries=()) if i == 0 else p
                for i, p in enumerate(before.playlists)
            )
        )
        review = device.prepare(replace(before, playlists=playlists))
        assert review.result.prepared is not None, review.result.issues
        assert index.read_bytes() == original
        if change_after_review:
            index.write_bytes(b"changed after review")
        saved = device.save(review)
        if change_after_review:
            assert saved.active is None
            assert saved.issues[0].code in ("save.source_unavailable", "save.failed")
            assert index.read_bytes() == b"changed after review"
            device.assert_original()
            return
        assert saved.active is not None, saved.issues
        selected = next(p for p in saved.active.library.playlists if p.is_phase)
        rebuilt = parse_phase_library(index.read_bytes())
        assert rebuilt.playlist_id == selected.playlist_id
        assert rebuilt.playlist_id > 0
        assert not rebuilt.tracks
        device.restore(saved.recovery_path)
        assert index.read_bytes() == original
    finally:
        device.coordinator.close()
