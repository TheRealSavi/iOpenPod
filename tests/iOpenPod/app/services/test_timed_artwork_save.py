"""Timed frame drafts publish through the ordinary verified Storage transaction."""

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from tests.iOpenPod.app.services.test_library_resources import Device, build_device

import iPodDB.library as library_api
from iOpenPod.app.artwork_policy import application_cover_formats
from iOpenPod.app.library_workspace import (
    LibraryWorkspace,
    TrackArtworkEdit,
    TrackUpdate,
)
from iOpenPod.app.library_write import LibraryPreparationRequest, LibraryReview
from iPodDB.library import (
    ArtworkGroupReference,
    ArtworkPixels,
    IPodLibrary,
    TimedArtworkFrame,
    WriteTarget,
)
from storage import (
    DevicePath,
    FileFingerprint,
    FilesystemSession,
    StorageOperationError,
)
from storage.content_workspace import ContentWorkspace, StagedContent

BLUE = ArtworkPixels(1, 1, b"\0\0\xff")


@pytest.mark.parametrize("chapter_formats", [True, False])
def test_completion_captures_referenced_full_shard_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, chapter_formats: bool
) -> None:
    device = build_device(tmp_path)
    try:

        def bounded_target[**P](
            factory: Callable[P, WriteTarget],
        ) -> Callable[P, WriteTarget]:
            def build(*args: P.args, **kwargs: P.kwargs) -> WriteTarget:
                target = factory(*args, **kwargs)
                return replace(
                    target,
                    max_artwork_file_bytes=204800,
                    chapter_formats=target.chapter_formats if chapter_formats else (),
                )

            return build

        monkeypatch.setattr(library_api, "WriteTarget", bounded_target(WriteTarget))
        directory = device.root / "iPod_Control/Artwork"
        source_file = directory / "F1055_1.ithmb"
        source_file.write_bytes(source_file.read_bytes().ljust(229376, b"\0"))
        unrelated = directory / "F1055_99.ithmb"
        unrelated.write_bytes(bytes(229376))
        captured: list[str] = []
        original_capture = ContentWorkspace.capture_device_snapshot

        def observe(
            self: ContentWorkspace, session: FilesystemSession, path: DevicePath
        ) -> tuple[bytes | StagedContent, FileFingerprint]:
            captured.append(path.name)
            return original_capture(self, session, path)

        monkeypatch.setattr(ContentWorkspace, "capture_device_snapshot", observe)
        workspace = LibraryWorkspace()
        workspace.load(device.active.library)
        first = workspace.tracks[0]
        workspace.apply_track_edits(
            (TrackUpdate(first.track_id, ()),),
            workspace.edit_revision,
            artwork=TrackArtworkEdit(
                None,
                frames=(
                    TimedArtworkFrame(0, ArtworkGroupReference(first.artwork_id, 0)),
                    TimedArtworkFrame(
                        15000, ArtworkGroupReference(first.artwork_id, 0)
                    ),
                ),
            ),
        )
        review = prepare(device, workspace)
        assert review.result.prepared is not None, review.result.issues
        assert "F1055_1.ithmb" in captured
        assert "F1055_99.ithmb" not in captured
        assert review.result.prepared.snapshot.tracks[0].metadata.artwork_count == 2
        assert source_file.stat().st_size == 229376
        assert unrelated.stat().st_size == 229376
    finally:
        device.coordinator.close()


def prepare(device: Device, workspace: LibraryWorkspace) -> LibraryReview:
    return device.coordinator.prepare_library(
        LibraryPreparationRequest(
            workspace.desired_snapshot(),
            device.active,
            workspace.generation,
            workspace.revision,
            artwork=workspace.artwork_assets,
        ),
        lambda _: None,
        Event(),
    )


def reread(device: Device) -> IPodLibrary:
    return IPodLibrary(
        (device.root / "iPod_Control/iTunes/iTunesDB").read_bytes()
    ).with_artwork((device.root / "iPod_Control/Artwork/ArtworkDB").read_bytes())


def test_save_reload_then_retime_retains_source_pixels_and_other_track(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path)
    try:
        workspace = LibraryWorkspace()
        workspace.load(device.active.library)
        first, second = workspace.tracks
        frames = (
            TimedArtworkFrame(0, ArtworkGroupReference(first.artwork_id, 0)),
            TimedArtworkFrame(10_000, BLUE),
        )
        workspace.apply_track_edits(
            (TrackUpdate(first.track_id, ()),),
            workspace.edit_revision,
            artwork=TrackArtworkEdit(None, frames=frames),
        )
        review = prepare(device, workspace)
        assert review.result.prepared is not None, review.result.issues
        device.assert_original()
        saved = device.save(review)
        assert saved.active is not None, saved.issues
        assert saved.active.library.tracks[1] == second
        source = reread(device)
        identity = source.snapshot.tracks[0].artwork_id
        assert source.artwork_display_times(identity) == (0, 10_000)
        formats = application_cover_formats(device.active.profile)
        for time, expected in ((0, bytes((255, 0, 0))), (10_000, bytes((0, 0, 255)))):
            read = source.artwork_read(identity, formats, 120, display_time_ms=time)
            assert read is not None
            payload = (device.root / read.relative_path).read_bytes()
            pixels = read.decode(payload[read.offset : read.offset + read.length])
            assert pixels.rgb888 == expected * (pixels.width * pixels.height)

        before = {
            p.name: p.read_bytes()
            for p in (device.root / "iPod_Control/Artwork").glob("*.ithmb")
        }
        workspace.load(device.active.library)
        workspace.apply_track_edits(
            (TrackUpdate(first.track_id, ()),),
            workspace.edit_revision,
            artwork=TrackArtworkEdit(
                None,
                frames=(
                    TimedArtworkFrame(0, ArtworkGroupReference(identity, 0)),
                    TimedArtworkFrame(20_000, ArtworkGroupReference(identity, 10_000)),
                ),
            ),
        )
        retime = prepare(device, workspace)
        assert retime.result.prepared is not None, retime.result.issues
        assert not retime.result.prepared.artwork_files
        resaved = device.save(retime)
        assert resaved.active is not None, resaved.issues
        source = reread(device)
        assert source.artwork_display_times(source.snapshot.tracks[0].artwork_id) == (
            0,
            20_000,
        )
        assert source.snapshot.tracks[1] == second
        assert before == {
            p.name: p.read_bytes()
            for p in (device.root / "iPod_Control/Artwork").glob("*.ithmb")
        }
    finally:
        device.coordinator.close()


def test_retained_timed_source_cannot_be_treated_as_full_regeneration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device = build_device(tmp_path)
    try:
        workspace = LibraryWorkspace()
        workspace.load(device.active.library)
        first = workspace.tracks[0]
        workspace.apply_track_edits(
            tuple(TrackUpdate(track.track_id, ()) for track in workspace.tracks),
            workspace.edit_revision,
            artwork=TrackArtworkEdit(
                None,
                frames=(
                    TimedArtworkFrame(0, ArtworkGroupReference(first.artwork_id, 0)),
                    TimedArtworkFrame(10_000, BLUE),
                ),
            ),
        )
        original_capture = ContentWorkspace.capture_device_snapshot

        def fail_source(
            self: ContentWorkspace,
            session: FilesystemSession,
            path: DevicePath,
        ) -> tuple[bytes | StagedContent, FileFingerprint]:
            if path.name.endswith(".ithmb"):
                raise StorageOperationError("Retained frame unavailable")
            return original_capture(self, session, path)

        monkeypatch.setattr(ContentWorkspace, "capture_device_snapshot", fail_source)
        review = prepare(device, workspace)
        assert review.result.prepared is None
        assert any(
            "Retained frame unavailable" in issue.detail
            for issue in review.result.issues
        )
        device.assert_original()
    finally:
        device.coordinator.close()


def test_ordinary_cover_refresh_cannot_discard_unreadable_later_groups(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device = build_device(tmp_path)
    try:
        workspace = LibraryWorkspace()
        workspace.load(device.active.library)
        first = workspace.tracks[0]
        workspace.apply_track_edits(
            (TrackUpdate(first.track_id, ()),),
            workspace.edit_revision,
            artwork=TrackArtworkEdit(
                None,
                frames=(
                    TimedArtworkFrame(0, ArtworkGroupReference(first.artwork_id, 0)),
                    TimedArtworkFrame(10_000, BLUE),
                ),
            ),
        )
        initial = prepare(device, workspace)
        assert initial.result.prepared is not None, initial.result.issues
        assert device.save(initial).active is not None
        before = {
            path: path.read_bytes()
            for path in (device.root / "iPod_Control/Artwork").iterdir()
        }
        workspace.load(device.active.library)
        workspace.set_artwork(
            tuple(track.track_id for track in workspace.tracks),
            BLUE,
            workspace.edit_revision,
        )
        original_capture = ContentWorkspace.capture_device_snapshot

        def fail_source(
            self: ContentWorkspace,
            session: FilesystemSession,
            path: DevicePath,
        ) -> tuple[bytes | StagedContent, FileFingerprint]:
            if path.name.endswith(".ithmb"):
                raise StorageOperationError("Later frame unavailable")
            return original_capture(self, session, path)

        monkeypatch.setattr(ContentWorkspace, "capture_device_snapshot", fail_source)
        review = prepare(device, workspace)
        assert review.result.prepared is None
        assert any(
            "Later frame unavailable" in issue.detail for issue in review.result.issues
        )
        assert all(path.read_bytes() == data for path, data in before.items())
    finally:
        device.coordinator.close()
