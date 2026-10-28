"""Retained frame capture follows explicit locations instead of shard-name guesses."""

from dataclasses import replace
from pathlib import Path

import pytest
from tests.iOpenPod.app.services.test_library_resources import Device, build_device
from tests.iOpenPod.app.services.test_timed_artwork_save import BLUE, prepare, reread

from iOpenPod.app.artwork_policy import application_cover_formats
from iOpenPod.app.library_workspace import (
    LibraryWorkspace,
    TrackArtworkEdit,
    TrackUpdate,
)
from iPodDB.ArtworkDB.builder.build_ArtworkDB import new_string_mhod
from iPodDB.ArtworkDB.parser.parse_ArtworkDB import parse_ArtworkDB
from iPodDB.ArtworkDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhod_payloads.container_mhod import (
    MhodContainerPayload,
)
from iPodDB.ArtworkDB.shared.constants import ArtworkMhodType
from iPodDB.ArtworkDB.writer.write_ArtworkDB import write_ArtworkDB
from iPodDB.library import ArtworkGroupReference, TimedArtworkFrame
from storage import DeviceEntry, DevicePath, FileFingerprint, FilesystemSession
from storage.content_workspace import ContentWorkspace, StagedContent


def _device_with_named_source(tmp_path: Path, name: str) -> Device:
    device = build_device(tmp_path)
    device.coordinator.close()
    database_path = "iPod_Control/Artwork/ArtworkDB"
    document = parse_ArtworkDB(device.original[database_path])
    token = ":" + name.replace("/", ":")
    for selection in document.find_chunks(MhiiHeader):
        children = list(selection.chunk.children)
        for index, child in enumerate(children):
            if isinstance(child.payload, MhodContainerPayload):
                location = replace(
                    child.payload.child,
                    children=(new_string_mhod(ArtworkMhodType.FILE_NAME, token),),
                )
                child = replace(child, payload=replace(child.payload, child=location))
            children[index] = child
        document = document.replace_chunk(
            selection, replace(selection.chunk, children=tuple(children))
        )
    original = "iPod_Control/Artwork/F1055_1.ithmb"
    renamed = "iPod_Control/Artwork/" + name
    target = device.root / renamed
    target.parent.mkdir(parents=True, exist_ok=True)
    (device.root / original).rename(target)
    device.original[renamed] = device.original.pop(original)
    device.original[database_path] = write_ArtworkDB(document)
    (device.root / database_path).write_bytes(device.original[database_path])
    device.coordinator.select_device(
        device.coordinator.discover_devices().candidates[0].id
    )
    return device


def _referenced_frames(device: Device) -> LibraryWorkspace:
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
                TimedArtworkFrame(15000, ArtworkGroupReference(first.artwork_id, 0)),
            ),
        ),
    )
    return workspace


@pytest.mark.parametrize("name", ["Résumé-F9999_7.ithmb", "chapters/表紙.ithmb"])
def test_required_source_is_captured_once_independent_of_name_or_subdirectory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    device = _device_with_named_source(tmp_path, name)
    try:
        required = "iPod_Control/Artwork/" + name
        unrelated = device.root / "iPod_Control/Artwork/chapters/unrelated.ithmb"
        unrelated.parent.mkdir(parents=True, exist_ok=True)
        unrelated.write_bytes(b"unrelated pixels")
        captured: list[str] = []
        listed: list[str] = []
        original_capture = ContentWorkspace.capture_device_snapshot
        original_list = FilesystemSession.list_directory

        def observe_capture(
            self: ContentWorkspace, session: FilesystemSession, path: DevicePath
        ) -> tuple[bytes | StagedContent, FileFingerprint]:
            captured.append(str(path))
            return original_capture(self, session, path)

        def observe_listing(
            self: FilesystemSession, path: DevicePath
        ) -> tuple[DeviceEntry, ...]:
            listed.append(str(path))
            return original_list(self, path)

        monkeypatch.setattr(
            ContentWorkspace, "capture_device_snapshot", observe_capture
        )
        monkeypatch.setattr(FilesystemSession, "list_directory", observe_listing)
        review = prepare(device, _referenced_frames(device))

        assert review.result.prepared is not None, review.result.issues
        assert (
            review.result.prepared.artwork_files
        )  # Missing representations were filled.
        assert review.resources is not None
        assert any(
            source.dependency.relative_path == required
            for source in review.resources.files
        )
        assert captured.count(required) == 1
        assert (
            str(unrelated.relative_to(device.root)).replace("\\", "/") not in captured
        )
        assert "iPod_Control/Artwork/chapters" not in listed
        assert review.result.prepared.snapshot.tracks[0].metadata.artwork_count == 2
        device.assert_original()
        saved = device.save(review)
        assert saved.active is not None, saved.issues
        assert (device.root / required).read_bytes() == device.original[required]
        assert unrelated.read_bytes() == b"unrelated pixels"
        source = reread(device)
        read = source.artwork_read(
            source.snapshot.tracks[0].artwork_id,
            tuple(
                layout
                for layout in application_cover_formats(device.active.profile)
                if layout.format_id == 1055
            ),
            128,
            display_time_ms=15000,
        )
        assert read is not None
        assert read.relative_path == required
        payload = (device.root / required).read_bytes()[
            read.offset : read.offset + read.length
        ]
        assert read.decode(payload).rgb888 == b"\xff\0\0" * (128 * 128)
    finally:
        device.coordinator.close()


def test_changed_nested_source_blocks_publication_after_capture(tmp_path: Path) -> None:
    device = _device_with_named_source(tmp_path, "chapters/cover.ithmb")
    try:
        review = prepare(device, _referenced_frames(device))
        assert review.result.prepared is not None, review.result.issues
        source = device.root / "iPod_Control/Artwork/chapters/cover.ithmb"
        original = source.read_bytes()
        source.write_bytes(bytes((original[0] ^ 0xFF,)) + original[1:])

        saved = device.save(review)

        assert saved.active is None
        for relative in (
            "iPod_Control/iTunes/iTunesDB",
            "iPod_Control/Artwork/ArtworkDB",
        ):
            assert (device.root / relative).read_bytes() == device.original[relative]
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("kind", ["missing", "directory"])
def test_unavailable_required_nested_source_blocks_preparation(
    tmp_path: Path, kind: str
) -> None:
    device = _device_with_named_source(tmp_path, "chapters/cover.ithmb")
    try:
        source = device.root / "iPod_Control/Artwork/chapters/cover.ithmb"
        source.unlink()
        if kind == "directory":
            source.mkdir()

        review = prepare(device, _referenced_frames(device))

        assert review.result.prepared is None
        assert any("cover.ithmb" in issue.detail for issue in review.result.issues)
        for relative in (
            "iPod_Control/iTunes/iTunesDB",
            "iPod_Control/Artwork/ArtworkDB",
        ):
            assert (device.root / relative).read_bytes() == device.original[relative]
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("later_group", [False, True])
def test_ordinary_cover_refresh_preserves_nested_retained_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, later_group: bool
) -> None:
    device = _device_with_named_source(tmp_path, "chapters/episode.ithmb")
    try:
        if later_group:
            initial = prepare(device, _referenced_frames(device))
            assert initial.result.prepared is not None, initial.result.issues
            assert device.save(initial).active is not None
        required = "iPod_Control/Artwork/chapters/episode.ithmb"
        original = (device.root / required).read_bytes()
        unrelated = device.root / "iPod_Control/Artwork/chapters/unrelated.ithmb"
        unrelated.write_bytes(b"unrelated pixels")
        captured: list[str] = []
        original_capture = ContentWorkspace.capture_device_snapshot

        def observe_capture(
            self: ContentWorkspace, session: FilesystemSession, path: DevicePath
        ) -> tuple[bytes | StagedContent, FileFingerprint]:
            captured.append(str(path))
            return original_capture(self, session, path)

        monkeypatch.setattr(
            ContentWorkspace, "capture_device_snapshot", observe_capture
        )
        workspace = LibraryWorkspace()
        workspace.load(device.active.library)
        first, second = workspace.tracks
        workspace.set_artwork((first.track_id,), BLUE, workspace.edit_revision)

        review = prepare(device, workspace)

        assert review.result.prepared is not None, review.result.issues
        assert review.resources is not None
        assert any(
            dependency.relative_path == required
            for dependency in review.resources.file_inventory or ()
        )
        assert captured.count(required) == int(later_group)
        assert "iPod_Control/Artwork/chapters/unrelated.ithmb" not in captured
        saved = device.save(review)
        assert saved.active is not None, saved.issues
        assert saved.active.library.tracks[1] == second
        assert (device.root / required).read_bytes() == original
        assert unrelated.read_bytes() == b"unrelated pixels"
        source = reread(device)
        identity = (
            source.snapshot.tracks[0].artwork_id if later_group else second.artwork_id
        )
        read = source.artwork_read(
            identity,
            tuple(
                layout
                for layout in application_cover_formats(device.active.profile)
                if layout.format_id == 1055
            ),
            128,
            display_time_ms=15000 if later_group else 0,
        )
        assert read is not None
        assert read.relative_path == required
        assert read.decode(
            original[read.offset : read.offset + read.length]
        ).rgb888 == (b"\xff\0\0" * (128 * 128))
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("name", ["chapters/missing.ithmb", "._F1055_1.ithmb"])
def test_full_regeneration_keeps_unavailable_source_policy(
    tmp_path: Path, name: str
) -> None:
    device = _device_with_named_source(tmp_path, name)
    try:
        path = device.root / "iPod_Control/Artwork" / name
        original = path.read_bytes()
        if name.startswith("chapters/"):
            path.unlink()
        workspace = LibraryWorkspace()
        workspace.load(device.active.library)
        workspace.set_artwork(
            tuple(track.track_id for track in workspace.tracks),
            BLUE,
            workspace.edit_revision,
        )

        review = prepare(device, workspace)

        assert review.result.prepared is not None, review.result.issues
        saved = device.save(review)
        assert saved.active is not None, saved.issues
        assert all(track.artwork_id for track in saved.active.library.tracks)
        if name.startswith("chapters/"):
            assert not path.exists()
        else:
            assert path.read_bytes() == original
    finally:
        device.coordinator.close()
