"""Bound device reads for ordinary Library preparation, independently of USB speed."""

from collections import Counter
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from tests.iOpenPod.app.services.test_library_resources import (
    build_device,
    cover_snapshot,
    without_first,
)
from tests.iOpenPod.app.test_media_lyrics import fixture

from iOpenPod.app.library_write import LibraryPreparationRequest, WriteProgress
from storage import DevicePath, FileFingerprint, FilesystemSession


@pytest.mark.parametrize("change", ["rename", "rockbox", "lyrics", "cover", "remove"])
def test_preparation_validates_each_resource_once_at_review_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    device = build_device(tmp_path, media_payload=fixture("tone.m4a"))
    hashes: Counter[str] = Counter()
    fingerprint = FilesystemSession.fingerprint

    def count(session: FilesystemSession, path: DevicePath) -> FileFingerprint:
        hashes[str(path)] += 1
        return fingerprint(session, path)

    try:
        first, second = device.active.library.tracks
        desired = replace(
            device.active.library,
            tracks=(
                replace(
                    first,
                    title="Renamed video",
                    metadata=replace(first.metadata, lyrics="New lyrics")
                    if change == "lyrics"
                    else first.metadata,
                ),
                second,
            ),
        )
        monkeypatch.setattr(FilesystemSession, "fingerprint", count)
        if change == "cover":
            review = device.prepare(cover_snapshot(device), cover=True)
        elif change == "remove":
            review = device.prepare(without_first(device), delete=True)
        else:
            review = device.coordinator.prepare_library(
                LibraryPreparationRequest(
                    desired, device.active, 1, 1, rockbox_metadata=change == "rockbox"
                ),
                lambda _: None,
                Event(),
            )
        assert review.result.prepared is not None, review.result.issues
        # Early source rejection and final validation suffice. Rechecking the same
        # database through both explicit and captured dependency lists adds I/O.
        assert hashes["iPod_Control/iTunes/iTunesDB"] == 2, hashes
        assert hashes["iPod_Control/Artwork/ArtworkDB"] == 2, hashes
        media_reads = (
            2 if change == "remove" else 1 if change in ("rockbox", "lyrics") else 0
        )
        assert hashes[first.metadata.location] == media_reads, hashes
        assert hashes[second.metadata.location] == 0, hashes
        thumbnails = [path for path in device.original if path.endswith(".ithmb")]
        assert all(
            hashes[path] == (1 if change == "cover" else 0) for path in thumbnails
        ), hashes
        device.assert_original()
        saved = device.save(review)
        assert saved.active is not None, saved.issues
    finally:
        device.coordinator.close()


@pytest.mark.parametrize(
    "phase", ["source.recheck", "save.source_check", "save.storage.prepared"]
)
@pytest.mark.parametrize(
    "artifact", ["iPod_Control/iTunes/iTunesDB", "iPod_Control/Artwork/ArtworkDB"]
)
def test_source_changes_still_block_each_publication_boundary(
    tmp_path: Path, phase: str, artifact: str
) -> None:
    device = build_device(tmp_path)
    try:
        first, second = device.active.library.tracks
        desired = replace(
            device.active.library, tracks=(replace(first, title="Renamed"), second)
        )
        changed = False

        def mutate(event: WriteProgress) -> None:
            nonlocal changed
            if event.phase == phase and not changed:
                changed = True
                path = device.root / artifact
                path.write_bytes(path.read_bytes() + b"external edit")

        review = device.coordinator.prepare_library(
            LibraryPreparationRequest(desired, device.active, 1, 1), mutate, Event()
        )
        if phase == "source.recheck":
            assert review.result.prepared is None
            assert not review.file_changes
        else:
            assert review.result.prepared is not None, review.result.issues
            saved = device.coordinator.save_library(
                review, device.active, mutate, Event()
            )
            assert saved.active is None
        assert changed
        for relative, data in device.original.items():
            expected = data + b"external edit" if relative == artifact else data
            assert (device.root / relative).read_bytes() == expected
    finally:
        device.coordinator.close()
