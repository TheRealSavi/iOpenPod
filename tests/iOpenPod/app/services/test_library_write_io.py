"""Bound device reads for ordinary Library preparation, independently of USB speed."""

import shutil
from collections import Counter
from dataclasses import replace
from os import PathLike
from pathlib import Path
from threading import Event

import pytest
from tests.iOpenPod.app.services.test_library_resources import (
    build_device,
    cover_snapshot,
    without_first,
)
from tests.iOpenPod.app.test_media_lyrics import fixture, media_payload

from iOpenPod.app.library_write import LibraryPreparationRequest, WriteProgress
from iOpenPod.app.podcasts.store import HISTORY_PATH
from iOpenPod.app.tag_normalizer import TagProfile, normalize_tags
from iPodDB.library import edit_track_metadata
from storage import DevicePath, FileFingerprint, FilesystemSession


@pytest.mark.parametrize("library_changed", [False, True])
def test_podcast_state_is_included_before_the_single_review_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, library_changed: bool
) -> None:
    device = build_device(tmp_path, host_recovery=True)
    try:
        state = device.coordinator.load_podcast_state(device.active)
        desired = device.active.library
        if library_changed:
            desired = replace(
                desired,
                tracks=(
                    replace(desired.tracks[0], title="Renamed"),
                    *desired.tracks[1:],
                ),
            )
        hashes: Counter[str] = Counter()
        original = FilesystemSession.fingerprint

        def fingerprint(
            session: FilesystemSession, path: DevicePath
        ) -> FileFingerprint:
            hashes[str(path)] += 1
            return original(session, path)

        monkeypatch.setattr(FilesystemSession, "fingerprint", fingerprint)
        review = device.coordinator.prepare_library(
            LibraryPreparationRequest(desired, device.active, 1, 1),
            lambda _: None,
            Event(),
            podcast_state=state,
            allow_unchanged=True,
        )
        assert review.result.prepared is not None, review.result.issues
        assert hashes["iPod_Control/iTunes/iTunesDB"] == 2, hashes
        assert hashes["iPod_Control/Artwork/ArtworkDB"] == 2, hashes
        saved = device.save(review)
        assert saved.active is not None, saved.issues
        assert (device.root / str(HISTORY_PATH)).is_file()
    finally:
        device.coordinator.close()


def test_combined_review_still_rejects_changed_podcast_state(tmp_path: Path) -> None:
    device = build_device(tmp_path, host_recovery=True)
    try:
        state = device.coordinator.load_podcast_state(device.active)
        history = device.root / str(HISTORY_PATH)

        def progress(event: WriteProgress) -> None:
            if event.phase == "source.recheck":
                history.parent.mkdir(parents=True, exist_ok=True)
                history.write_bytes(b"external change")

        review = device.coordinator.prepare_library(
            LibraryPreparationRequest(device.active.library, device.active, 1, 1),
            progress,
            Event(),
            podcast_state=state,
            allow_unchanged=True,
        )
        assert review.result.prepared is None
        assert history.read_bytes() == b"external change"
        device.assert_original()
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("rockbox", [False, True])
@pytest.mark.parametrize("host_recovery", [False, True])
def test_normalize_tags_saves_with_space_for_one_media_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rockbox: bool, host_recovery: bool
) -> None:
    # A retained MP4 free atom supplies realistic file size without a large fixture.
    padding = 1024 * 1024
    media = (
        fixture("tone.m4a") + padding.to_bytes(4, "big") + b"free" + bytes(padding - 8)
    )
    device = build_device(tmp_path, media_payload=media, host_recovery=host_recovery)
    try:
        source = device.active
        draft = replace(
            source.library,
            tracks=tuple(
                replace(t, artist="The Artist", album="The Album")
                for t in source.library.tracks
            ),
        )
        suggestion = normalize_tags(draft.tracks, TagProfile("test", True, True))
        assert suggestion.field_count
        edits = {u.track_id: u.edits for u in suggestion.updates}
        desired = replace(
            draft,
            tracks=tuple(
                edit_track_metadata(t, edits.get(t.track_id, ())) for t in draft.tracks
            ),
        )
        unit = 4096

        def allocated() -> int:
            return sum(
                ((p.stat().st_size + unit - 1) // unit) * unit
                for p in device.root.rglob("*")
                if p.is_file()
            )

        baseline = allocated()
        usage = shutil.disk_usage(device.root)
        actual_usage = shutil.disk_usage
        # Two roughly 1 MiB replacements need over 5 MiB when staged together.
        # Originals + one stage + restoration reserve fit within 4.5 MiB.
        budget = 256 * 1024 if host_recovery else 9 * 512 * 1024

        def limited_disk_usage(path: str | PathLike[str]) -> tuple[int, int, int]:
            if Path(path).resolve() == device.root:
                return usage._replace(free=budget - (allocated() - baseline))
            return actual_usage(path)

        monkeypatch.setattr(shutil, "disk_usage", limited_disk_usage)
        review = device.coordinator.prepare_library(
            LibraryPreparationRequest(desired, source, 1, 1, rockbox_metadata=rockbox),
            lambda _: None,
            Event(),
        )
        assert review.result.prepared is not None, review.result.issues
        media_writes = [
            f for f in review.file_changes if f.path.startswith("iPod_Control/Music/")
        ]
        assert len(media_writes) == (2 if rockbox else 0)
        device.assert_original()
        saved = device.save(review)
        assert saved.active is not None, saved.issues
        assert (
            normalize_tags(
                saved.active.library.tracks, TagProfile("test", True, True)
            ).field_count
            == 0
        )
        for track in saved.active.library.tracks:
            data = (device.root / track.metadata.location).read_bytes()
            assert media_payload(data, ".m4a") == media_payload(media, ".m4a")
            if rockbox:
                assert data != media
            else:
                assert data == media
    finally:
        device.coordinator.close()


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
