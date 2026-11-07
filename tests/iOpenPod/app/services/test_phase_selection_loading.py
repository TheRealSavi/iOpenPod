"""Selection-time history commits must not enter expensive Phase analysis."""

from dataclasses import replace
from pathlib import Path

import pytest
from tests.iOpenPod.app.services.test_library_resources import build_device
from tests.iPodDB.sidecars.test_sidecar_readers import counts

from iOpenPod.app.services import device_coordinator
from iOpenPod.app.services.phase import INDEX_PATH, PhasePublication
from iPodDB.games import PhaseLibrary, build_phase_library
from iPodDB.library import Playlist


@pytest.mark.parametrize("change", ["device_name", "other_playlist", "track_metadata"])
def test_selection_commits_history_without_entering_phase_preparation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    device = build_device(tmp_path, model="MA450")
    index = device.root / str(INDEX_PATH)
    index.parent.mkdir(parents=True, exist_ok=True)
    original = build_phase_library(
        PhaseLibrary(device.active.library.playlists[0].playlist_id)
    )
    index.write_bytes(original)
    sidecar = device.root / "iPod_Control/iTunes/Play Counts"
    sidecar.write_bytes(counts())
    calls: list[bool] = []

    def phase(*args: object, **kwargs: object) -> PhasePublication:
        calls.append(True)
        return PhasePublication()

    monkeypatch.setattr(device_coordinator, "prepare_phase", phase)
    try:
        selected = device.coordinator.select_device(device.active.candidate.id)
        assert selected.library.tracks[0].play_count == 3
        assert any(p.is_phase for p in selected.library.playlists)
        assert not sidecar.exists()
        assert index.read_bytes() == original
        assert not calls, (
            "Loading the iPod entered Phase preparation (model/network work)"
        )
        if change == "device_name":
            unrelated = replace(selected.library, device_name="Explicit save")
        elif change == "other_playlist":
            unrelated = replace(
                selected.library,
                playlists=(*selected.library.playlists, Playlist(-1, "Other")),
            )
        else:
            unrelated = replace(
                selected.library,
                tracks=tuple(
                    replace(t, title="Updated title") for t in selected.library.tracks
                ),
            )
        review = device.prepare(unrelated)
        assert review.result.prepared is not None, review.result.issues
        assert not calls, "An unrelated Library save evaluated Phase"
        changed = replace(
            selected.library,
            playlists=tuple(
                replace(p, name="Changed Phase") if p.is_phase else p
                for p in selected.library.playlists
            ),
        )
        review = device.prepare(changed)
        assert review.result.prepared is not None, review.result.issues
        assert calls == [True]
    finally:
        device.coordinator.close()
