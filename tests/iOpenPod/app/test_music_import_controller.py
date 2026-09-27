"""Inspection is asynchronous, atomic for a batch, and bound to its draft."""

from collections.abc import Callable, Iterator
from pathlib import Path
from threading import Event

import pytest
from PySide6.QtCore import QThreadPool
from PySide6.QtTest import QSignalSpy
from tests.iOpenPod.app.services.test_library_resources import Device, build_device
from tests.iOpenPod.app.test_library_write_controller import wait_for
from tests.iOpenPod.app.test_music_import import song_file
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context

from device_registry import DeviceProfile
from iOpenPod.app.core.settings.definitions import DRAFT_ALL_CHANGES
from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.core.settings.stores import DeviceSettingsStore, GlobalSettingsStore
from iOpenPod.app.device_controller import DeviceController
from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.library_write_controller import PreparationState
from iOpenPod.app.media import music_paths
from iOpenPod.app.media.importing import ImportedSong, MusicImporter, relocate_song
from iOpenPod.app.models.track_table_model import TrackTableModel
from iOpenPod.app.music_import_controller import MusicImportController
from iPodDB.library import IPodLibrary
from storage import HostPath

type ImportSession = tuple[Device, DeviceController, LibraryWorkspace, HostPath]


class WaitingImporter(MusicImporter):
    def __init__(self, song: ImportedSong) -> None:
        self.song = song
        self.entered, self.release = Event(), Event()

    def inspect(
        self,
        source: HostPath,
        profile: DeviceProfile,
        *,
        checkpoint: Callable[[], None],
    ) -> ImportedSong:
        self.entered.set()
        assert self.release.wait(5)
        checkpoint()
        return self.song


@pytest.fixture
def setup(
    tmp_path: Path,
) -> Iterator[tuple[Device, DeviceController, LibraryWorkspace, HostPath]]:
    device = build_device(tmp_path)
    devices = DeviceController(
        device.coordinator,
        TrackTableModel(),
        SettingsService(GlobalSettingsStore(), DeviceSettingsStore()),
    )
    workspace = LibraryWorkspace()
    workspace.load(device.active.library)
    try:
        yield device, devices, workspace, song_file(tmp_path)
    finally:
        devices.shutdown()


def test_completed_inspection_adds_draft_resources_without_device_write(
    setup: ImportSession,
) -> None:
    device, devices, workspace, path = setup
    controller = MusicImportController(workspace, devices)
    done, failed = QSignalSpy(controller.finished), QSignalSpy(controller.failed)
    try:
        controller.start((path,))
        wait_for(lambda: not controller.busy)
        assert done.count() == 1 and failed.count() == 0
        assert workspace.dirty and workspace.media_sources and workspace.artwork_assets
        assert len(workspace.tracks) == len(device.active.library.tracks) + 1
        device.assert_original()
        assert not (device.root / workspace.tracks[-1].metadata.location).exists()
    finally:
        controller.shutdown()


@pytest.mark.parametrize(
    "occupied",
    ("ipod_control/music/f00/aaaa.M4A", ":ipod_control:music:f00:aaaa.M4A"),
)
def test_repeated_import_reserves_pending_paths_case_insensitively(
    setup: ImportSession, monkeypatch: pytest.MonkeyPatch, occupied: str
) -> None:
    device, devices, workspace, path = setup
    inspected = MusicImporter().inspect(
        path, device.active.profile, checkpoint=lambda: None
    )
    workspace.add_songs((relocate_song(inspected, occupied),), workspace.edit_revision)

    def first_slot(_limit: int) -> int:
        return 0

    monkeypatch.setattr(music_paths, "randbelow", first_slot)
    controller = MusicImportController(workspace, devices)
    done, failed = QSignalSpy(controller.finished), QSignalSpy(controller.failed)
    try:
        controller.start((path, path))
        wait_for(lambda: not controller.busy)
        assert done.count() == 1 and failed.count() == 0
        controller.start((path,))
        wait_for(lambda: not controller.busy)
        assert done.count() == 2 and failed.count() == 0
        locations = tuple(
            track.metadata.location for track in workspace.tracks if track.track_id < 0
        )
        canonical = {
            location.replace(":", "/").lstrip("/").casefold() for location in locations
        }
        assert len(locations) == len(canonical) == 4
        assert canonical == {
            f"ipod_control/music/f{index:02d}/aaaa.m4a" for index in range(4)
        }
        resources = {
            source.media.track_id: source for source in workspace.media_sources
        }
        for track in workspace.tracks:
            if track.track_id < 0:
                resource = resources[track.track_id]
                assert resource.media.file.relative_path == track.metadata.location
                assert resource.fingerprint == inspected.source.fingerprint
                assert resource.media.file.sha256 == inspected.source.media.file.sha256
        device.assert_original()
    finally:
        controller.shutdown()


@pytest.mark.parametrize(
    "invalidate", ["cancel", "edit", "disconnect", "lock", "shutdown"]
)
def test_late_result_cannot_apply_to_invalidated_draft(
    setup: ImportSession, invalidate: str
) -> None:
    device, devices, workspace, path = setup
    importer = WaitingImporter(
        MusicImporter().inspect(path, device.active.profile, checkpoint=lambda: None)
    )
    controller = MusicImportController(workspace, devices, importer=importer)
    done, failed = QSignalSpy(controller.finished), QSignalSpy(controller.failed)
    try:
        controller.start((path,))
        wait_for(importer.entered.is_set)
        if invalidate == "cancel":
            controller.cancel()
        elif invalidate == "edit":
            workspace.rename(
                workspace.playlists[0].playlist_id, "Changed during inspection"
            )
        elif invalidate == "lock":
            workspace.set_locked(True)
        elif invalidate == "shutdown":
            importer.release.set()
            controller.shutdown()
        else:
            device.platform.disconnect(device.root)
            devices.refresh_devices()
            wait_for(lambda: not devices.busy and devices.active_ipod is None)
        importer.release.set()
        pool = controller.findChild(QThreadPool)
        assert pool is not None and pool.waitForDone(5000)
        APPLICATION.processEvents()
        assert not controller.busy
        assert not workspace.media_sources and not workspace.artwork_assets
        assert done.count() == 0 and failed.count() == 0
        device.assert_original()
    finally:
        importer.release.set()
        controller.shutdown()


def test_batch_failure_never_adds_a_partial_selection(
    setup: ImportSession, tmp_path: Path
) -> None:
    device, devices, workspace, path = setup
    controller = MusicImportController(workspace, devices)
    failed = QSignalSpy(controller.failed)
    try:
        controller.start((path, HostPath(tmp_path / "missing.mp3")))
        wait_for(lambda: not controller.busy)
        assert failed.count() == 1
        assert not workspace.dirty and not workspace.media_sources
        device.assert_original()
    finally:
        controller.shutdown()


@pytest.mark.parametrize("draft_all_changes", (False, True))
def test_import_draft_uses_the_selected_save_policy(
    tmp_path: Path,
    draft_all_changes: bool,
) -> None:
    device = build_device(tmp_path)
    path = song_file(tmp_path)
    context = build_context(device_coordinator=device.coordinator)
    context.settings.set_global(DRAFT_ALL_CHANGES, draft_all_changes)
    context.library_workspace.load(device.active.library)
    context.track_model.replace_tracks(device.active.library.tracks)
    controller = MusicImportController(
        context.library_workspace, context.device_controller
    )
    try:
        controller.start((path,))
        wait_for(lambda: not controller.busy)
        writer = context.library_write_controller
        if draft_all_changes:
            assert context.library_workspace.dirty
            assert (
                len(context.library_workspace.tracks)
                == len(device.active.library.tracks) + 1
            )
            device.assert_original()
            assert writer.review is None
            writer.prepare()
            wait_for(lambda: writer.state is PreparationState.READY)
            device.assert_original()
            assert writer.review is not None and len(writer.review.file_changes) == 7
            assert writer.can_save
            writer.save()
        wait_for(lambda: writer.state is PreparationState.SAVED)
        assert writer.save_result is not None and writer.save_result.active is not None
        added = writer.save_result.active.library.tracks[-1]
        assert added.title == "Chapter test" and added.artwork_id > 0
        assert (device.root / added.metadata.location).read_bytes() == Path(
            path.path
        ).read_bytes()
        parsed = IPodLibrary(
            (device.root / "iPod_Control/iTunes/iTunesDB").read_bytes()
        ).with_artwork((device.root / "iPod_Control/Artwork/ArtworkDB").read_bytes())
        assert parsed.snapshot == writer.save_result.active.library
        assert not context.library_workspace.dirty
        assert not writer.save_result.recovery_path
        assert not tuple(device.root.glob(".iopenpod-recovery/*/transaction.json"))
    finally:
        controller.shutdown()
        context.shutdown()
