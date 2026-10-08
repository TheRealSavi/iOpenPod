"""Embedded lyrics and iTunesDB publish and recover as one reviewed transaction."""

import io
import struct
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from threading import Event
from typing import Any, BinaryIO

import pytest
from mutagen.mp4 import MP4
from tests.iOpenPod.app.services.test_library_resources import Device, build_device
from tests.iOpenPod.app.test_media_lyrics import WORDS, fixture, media_payload
from tests.iOpenPod.app.test_music_import import song_file
from tests.iPodDB.library.test_write_artwork import BLUE

from iOpenPod.app.library_workspace import LibraryWorkspace, TrackUpdate
from iOpenPod.app.library_write import (
    LibraryPreparationRequest,
    PreparationCancelledError,
)
from iOpenPod.app.media.importing import MusicImporter
from iOpenPod.app.media.lyrics import embedded_lyrics, rewrite_lyrics
from iOpenPod.app.services import library_resources
from iPodDB.library import LibrarySnapshot, TrackChapter, TrackFieldEdit
from storage import CapturedHostFile, HostPath
from storage.media_processing import MediaWorkspace


def desired_lyrics(device: Device, text: str) -> LibrarySnapshot:
    first, *others = device.active.library.tracks
    return replace(
        device.active.library,
        tracks=(
            replace(
                first,
                title="Library title",
                metadata=replace(first.metadata, lyrics=text),
            ),
            *others,
        ),
    )


def read_lyrics(data: bytes) -> str:
    reader: Any = MP4
    return embedded_lyrics(reader(io.BytesIO(data)))


def test_invalid_chapters_do_not_report_unprepared_lyrics_as_missing(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path, media_payload=fixture("tone.m4a"))
    try:
        first, second = device.active.library.tracks
        invalid = replace(
            first,
            metadata=replace(
                first.metadata,
                chapters=(TrackChapter("Beyond duration", first.length_ms + 1),),
            ),
        )
        with_lyrics = replace(second, metadata=replace(second.metadata, lyrics=WORDS))
        review = device.prepare(
            replace(device.active.library, tracks=(invalid, with_lyrics))
        )
        assert review.result.prepared is None
        assert review.plan is not None and review.plan.required_lyrics == (
            second.track_id,
        )
        assert review.resources is not None and not review.resources.lyrics
        assert any(
            issue.code == "track.invalid_value" and issue.record_id == first.track_id
            for issue in review.result.issues
        )
        assert not any(
            issue.code == "resources.missing_lyrics" for issue in review.result.issues
        )
        device.assert_original()

        corrected = device.prepare(
            replace(device.active.library, tracks=(first, with_lyrics))
        )
        assert corrected.result.prepared is not None, corrected.result.issues
        assert corrected.resources is not None
        assert len(corrected.resources.lyrics) == 1
        assert corrected.resources.lyrics[0].lyrics == WORDS
        device.assert_original()
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("capture_limited", [False, True])
def test_add_replace_and_clear_publish_with_database_and_restore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capture_limited: bool
) -> None:
    device = build_device(tmp_path, media_payload=fixture("tone.m4a"))
    try:
        if capture_limited:
            monkeypatch.setattr(library_resources, "_MAX_CAPTURE_BYTES", 10)
        first, second = device.active.library.tracks
        path = device.root / first.metadata.location
        original_payload = media_payload(path.read_bytes(), ".m4a")
        original = dict(device.original)
        for text in (WORDS, "Replacement", ""):
            before = path.read_bytes()
            review = device.prepare(desired_lyrics(device, text))
            assert review.result.prepared is not None, review.result.issues
            assert not any(
                issue.code == "resources.lyrics_disk_staging"
                for issue in review.result.issues
            )
            assert review.plan is not None and review.plan.required_lyrics == (
                first.track_id,
            )
            assert review.file_changes[0].path == first.metadata.location
            assert review.file_changes[-1].path == "iPod_Control/iTunes/iTunesDB"
            assert path.read_bytes() == before
            saved = device.save(review)
            assert saved.active is not None, saved.issues
            data = path.read_bytes()
            assert read_lyrics(data) == text
            assert media_payload(data, ".m4a") == original_payload
            track = saved.active.library.tracks[0]
            assert track.metadata.has_lyrics == bool(text)
            assert track.metadata.lyrics == text
            assert track.size_bytes == len(data)
            assert saved.active.library.tracks[1] == second
            if text == WORDS:
                # The same recovery journal restores media and database together.
                device.restore(saved.recovery_path)
                device.coordinator.select_device(
                    device.coordinator.discover_devices().candidates[0].id
                )
            else:
                # Keep the replacement state for the following clear operation.
                assert read_lyrics(path.read_bytes()) == text
        for name, data in original.items():
            if name not in (first.metadata.location, "iPod_Control/iTunes/iTunesDB"):
                assert (device.root / name).read_bytes() == data
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("change", ["modify", "remove", "disconnect"])
@pytest.mark.parametrize("capture_limited", [False, True])
def test_stale_media_or_connection_prevents_database_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
    capture_limited: bool,
) -> None:
    device = build_device(tmp_path, media_payload=fixture("tone.m4a"))
    try:
        if capture_limited:
            monkeypatch.setattr(library_resources, "_MAX_CAPTURE_BYTES", 10)
        review = device.prepare(desired_lyrics(device, WORDS))
        assert review.result.prepared is not None, review.result.issues
        active = device.active
        path = device.root / device.active.library.tracks[0].metadata.location
        if change == "modify":
            path.write_bytes(path.read_bytes() + b"external edit")
        elif change == "remove":
            path.unlink()
        else:
            device.coordinator.close()
        saved = device.coordinator.save_library(review, active, lambda _: None, Event())
        assert saved.active is None
        assert (
            device.root / "iPod_Control/iTunes/iTunesDB"
        ).read_bytes() == device.original["iPod_Control/iTunes/iTunesDB"]
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("problem", ["invalid", "missing", "shared", "cancel"])
def test_unpreparable_lyrics_never_offer_a_database_only_save(
    tmp_path: Path, problem: str
) -> None:
    device = build_device(
        tmp_path, shared_media=problem == "shared", media_payload=fixture("tone.m4a")
    )
    try:
        path = device.root / device.active.library.tracks[0].metadata.location
        if problem == "invalid":
            path.write_bytes(b"invalid media")
        elif problem == "missing":
            path.unlink()
        elif problem == "cancel":
            cancelled = Event()
            cancelled.set()
            with pytest.raises(PreparationCancelledError):
                device.coordinator.prepare_library(
                    LibraryPreparationRequest(
                        desired_lyrics(device, WORDS), device.active, 1, 1
                    ),
                    lambda _: None,
                    cancelled,
                )
            return
        review = device.prepare(desired_lyrics(device, WORDS))
        assert review.result.prepared is None
        assert any(
            device.active.library.tracks[0].metadata.location in issue.detail
            for issue in review.result.issues
        )
        assert not review.file_changes
        assert device.save(review).active is None
        assert (
            device.root / "iPod_Control/iTunes/iTunesDB"
        ).read_bytes() == device.original["iPod_Control/iTunes/iTunesDB"]
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("output_growth", [False, True])
def test_batch_budget_spills_only_overflowing_media_and_preserves_every_track(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, output_growth: bool
) -> None:
    original = fixture("tone.m4a")
    output = rewrite_lyrics(original, "tone.m4a", WORDS)
    device = build_device(tmp_path, media_payload=original)
    try:
        budget = len(original) if output_growth else len(output)
        monkeypatch.setattr(library_resources, "_MAX_CAPTURE_BYTES", budget)
        snapshot = replace(
            device.active.library,
            tracks=tuple(
                replace(t, metadata=replace(t.metadata, lyrics=WORDS))
                for t in device.active.library.tracks
            ),
        )
        review = device.prepare(snapshot)
        assert review.result.prepared is not None, review.result.issues
        assert not any(
            issue.code == "resources.lyrics_disk_staging"
            for issue in review.result.issues
        )
        device.assert_original()
        saved = device.save(review)
        assert saved.active is not None, saved.issues
        for track in saved.active.library.tracks:
            data = (device.root / track.metadata.location).read_bytes()
            assert read_lyrics(data) == WORDS
            assert media_payload(data, ".m4a") == media_payload(original, ".m4a")
        device.restore(saved.recovery_path)
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("large_media", [False, True])
def test_disk_staged_lyrics_do_not_consume_artwork_capture_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, large_media: bool
) -> None:
    # A valid free atom makes the complete media larger than the thumbnail budget.
    original = fixture("tone.m4a")
    if large_media:
        original += struct.pack(">I4s", 32768, b"free") + bytes(32760)
    device = build_device(tmp_path, media_payload=original)
    try:
        monkeypatch.setattr(library_resources, "_MAX_CAPTURE_BYTES", 32768)
        desired = desired_lyrics(device, WORDS)
        desired = replace(
            desired,
            tracks=(
                replace(desired.tracks[0], artwork_id=BLUE.artwork_id),
                *desired.tracks[1:],
            ),
        )
        review = device.prepare(desired, cover=True)
        assert review.result.prepared is not None, review.result.issues
        saved = device.save(review)
        assert saved.active is not None, saved.issues
        track = saved.active.library.tracks[0]
        data = (device.root / track.metadata.location).read_bytes()
        assert read_lyrics(data) == WORDS
        assert media_payload(data, ".m4a") == media_payload(original, ".m4a")
        device.restore(saved.recovery_path)
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("finish", ["save", "reprepare", "close", "failure", "cancel"])
def test_disk_staging_lives_until_review_is_retired_and_cleans_partial_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, finish: str
) -> None:
    device = build_device(tmp_path, media_payload=fixture("tone.m4a"))
    paths: list[Path] = []
    transform = MediaWorkspace.transform_stream

    def record(
        workspace: MediaWorkspace, source: HostPath, action: Callable[[BinaryIO], None]
    ) -> CapturedHostFile:
        paths.append(Path(source))
        # First prepare succeeds; a second two-Track prepare fails after one spill.
        if len(paths) == 3:
            if finish == "failure":
                raise ValueError("simulated tag failure")
            if finish == "cancel":
                raise PreparationCancelledError
        return transform(workspace, source, action)

    monkeypatch.setattr(MediaWorkspace, "transform_stream", record)
    monkeypatch.setattr(library_resources, "_MAX_CAPTURE_BYTES", 10)
    try:
        review = device.prepare(desired_lyrics(device, WORDS))
        assert review.result.prepared is not None, review.result.issues
        assert len(paths) == 1 and paths[0].exists()
        if finish == "save":
            assert device.save(review).active is not None
        elif finish == "close":
            device.coordinator.close()
        elif finish == "reprepare":
            assert (
                device.prepare(desired_lyrics(device, "")).result.prepared is not None
            )
        else:
            desired = replace(
                device.active.library,
                tracks=tuple(
                    replace(t, metadata=replace(t.metadata, lyrics=WORDS))
                    for t in device.active.library.tracks
                ),
            )
            if finish == "cancel":
                with pytest.raises(PreparationCancelledError):
                    device.prepare(desired)
            else:
                failed = device.prepare(desired)
                assert failed.result.prepared is None
                assert (
                    desired.tracks[1].metadata.location
                    in failed.result.issues[-1].detail
                )
            assert len(paths) == 3
        assert all(not path.exists() for path in paths)
        if finish != "save":
            device.assert_original()
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("edited", [False, True])
@pytest.mark.parametrize("capture_limited", [False, True])
def test_import_reads_embedded_lyrics_and_writes_reviewed_text_without_changing_host(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    edited: bool,
    capture_limited: bool,
) -> None:
    device = build_device(tmp_path)
    try:
        host = song_file(tmp_path, "tone.m4a")
        original = rewrite_lyrics(Path(host).read_bytes(), "song.m4a", WORDS)
        Path(host).write_bytes(original)
        song = MusicImporter().inspect(
            host, device.active.profile, checkpoint=lambda: None
        )
        assert song.track.metadata.lyrics == WORDS
        workspace = LibraryWorkspace()
        workspace.load(device.active.library)
        workspace.add_songs((song,), workspace.edit_revision)
        expected = "Edited before import" if edited else WORDS
        if edited:
            workspace.apply_track_edits(
                (
                    TrackUpdate(
                        workspace.tracks[-1].track_id,
                        (TrackFieldEdit("metadata.lyrics", expected),),
                    ),
                ),
                workspace.edit_revision,
            )
        if capture_limited:
            monkeypatch.setattr(library_resources, "_MAX_CAPTURE_BYTES", 10)
        review = device.coordinator.prepare_library(
            LibraryPreparationRequest(
                workspace.desired_snapshot(),
                device.active,
                1,
                1,
                media=workspace.media_sources,
            ),
            lambda _: None,
            Event(),
        )
        assert review.result.prepared is not None, review.result.issues
        assert not any(
            issue.code == "resources.lyrics_disk_staging"
            for issue in review.result.issues
        )
        assert Path(host).read_bytes() == original
        saved = device.save(review)
        assert saved.active is not None, saved.issues
        track = saved.active.library.tracks[-1]
        data = (device.root / track.metadata.location).read_bytes()
        assert read_lyrics(data) == expected
        assert track.metadata.has_lyrics and track.size_bytes == len(data)
        assert media_payload(data, ".m4a") == media_payload(original, ".m4a")
        assert Path(host).read_bytes() == original
        device.restore(saved.recovery_path)
    finally:
        device.coordinator.close()
