"""Qt-thread adapter tests for device discovery and library publication."""

from collections.abc import Callable
from pathlib import Path
from threading import Event, get_ident
from time import monotonic, sleep

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from iOpenPod.app.core.settings.definitions import LAST_SELECTED_IPOD_VOLUME_ID
from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.core.settings.stores import DeviceSettingsStore, GlobalSettingsStore
from iOpenPod.app.device_controller import (
    DeviceController,
    DeviceEjectCompletion,
    DeviceOperation,
    DeviceOperationFailure,
)
from iOpenPod.app.models.track_table_model import TrackTableModel
from iOpenPod.app.services.device_coordinator import DeviceCoordinator
from iPodDB.iTunesDB.builder.build_iTunesDB import (
    new_itunes_chunk,
    new_iTunesDB,
    new_string_mhod,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhit import DEFINITION as MHIT_DEFINITION
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhlt import DEFINITION as MHLT_DEFINITION
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import DEFINITION as MHSD_DEFINITION
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.shared.chunk import EmptyChunkHeader
from storage import Storage
from storage.platform.base import ObservationDiscoveryResult
from storage.testing import VirtualStoragePlatform


def _application() -> QApplication:
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    return QApplication([])


APPLICATION = _application()


class _ObservedPlatform(VirtualStoragePlatform):
    def __init__(self, name: str = "virtual") -> None:
        super().__init__()
        self._name = name
        self.scans = 0
        self.scan_threads: list[int] = []
        self.release: Event | None = None
        self.fail = False

    @property
    def name(self) -> str:
        return self._name

    def discover(self) -> ObservationDiscoveryResult:
        self.scans += 1
        self.scan_threads.append(get_ident())
        if self.release is not None:
            assert self.release.wait(3), "Test did not release discovery"
        if self.fail:
            raise OSError("Temporary discovery failure")
        return super().discover()


@pytest.fixture
def fast_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("iOpenPod.app.device_controller._AUTO_REFRESH_INTERVAL_MS", 30)


@pytest.mark.usefixtures("fast_refresh")
@pytest.mark.parametrize("platform_name", ["windows", "macos", "linux"])
def test_auto_refresh_finds_connections_and_expires_disconnections(
    tmp_path: Path, platform_name: str
) -> None:
    platform = _ObservedPlatform(platform_name)
    tracks = TrackTableModel()
    controller = DeviceController(
        DeviceCoordinator(Storage(platform)),
        tracks,
        SettingsService(GlobalSettingsStore(), DeviceSettingsStore()),
    )
    changes: list[object] = []
    controller.activeIPodChanged.connect(changes.append)
    try:
        controller.start_auto_refresh()
        controller.start_auto_refresh()
        _wait_until(lambda: platform.scans > 0 and not controller.busy)
        root = _device_root(tmp_path / "device")
        platform.add_volume(root, label="Connected iPod")
        _wait_until(
            lambda: bool(controller.discovery.candidates) and not controller.busy
        )
        candidate = controller.discovery.candidates[0]
        assert controller.active_ipod is None
        controller.select_device(candidate.id.value)
        _wait_until(lambda: controller.active_ipod is not None and not controller.busy)
        active = controller.active_ipod
        scan_count = platform.scans
        _wait_until(lambda: platform.scans >= scan_count + 2 and not controller.busy)
        assert controller.active_ipod is active
        assert changes == [None, active]
        assert tracks.rowCount() == 1

        platform.disconnect(root)
        _wait_until(lambda: not controller.discovery.candidates and not controller.busy)
        assert controller.active_ipod is None
        assert tracks.rowCount() == 0

        platform.reconnect(root)
        _wait_until(lambda: controller.active_ipod is not None and not controller.busy)
        assert controller.active_ipod is not None
        assert controller.active_ipod.candidate.id != candidate.id
        assert all(thread != get_ident() for thread in platform.scan_threads)
    finally:
        controller.shutdown()
    scan_count = platform.scans
    QTest.qWait(100)
    assert platform.scans == scan_count


@pytest.mark.usefixtures("fast_refresh")
@pytest.mark.parametrize("read_only", [False, True])
def test_auto_refresh_waits_for_device_reservations(
    tmp_path: Path, read_only: bool
) -> None:
    platform = _ObservedPlatform()
    platform.add_volume(_device_root(tmp_path / "device"))
    controller = DeviceController(
        DeviceCoordinator(Storage(platform)),
        TrackTableModel(),
        SettingsService(GlobalSettingsStore(), DeviceSettingsStore()),
    )
    try:
        controller.refresh_devices()
        _wait_until(lambda: not controller.busy)
        controller.select_device(controller.discovery.candidates[0].id.value)
        _wait_until(lambda: not controller.busy)
        reserve = (
            controller.begin_read_only_operation
            if read_only
            else controller.begin_exclusive_operation
        )
        assert reserve()
        scan_count = platform.scans
        controller.start_auto_refresh()
        QTest.qWait(120)
        assert platform.scans == scan_count
        assert not controller.searching
        if read_only:
            controller.finish_read_only_operation()
        else:
            controller.finish_exclusive_operation()
        _wait_until(lambda: platform.scans > scan_count and not controller.busy)
    finally:
        controller.shutdown()


@pytest.mark.usefixtures("fast_refresh")
def test_slow_auto_scan_does_not_overlap_or_queue_refreshes() -> None:
    platform = _ObservedPlatform()
    release = Event()
    platform.release = release
    controller = DeviceController(
        DeviceCoordinator(Storage(platform)),
        TrackTableModel(),
        SettingsService(GlobalSettingsStore(), DeviceSettingsStore()),
    )
    searching: list[bool] = []
    controller.searchingChanged.connect(searching.append)
    try:
        controller.start_auto_refresh()
        _wait_until(lambda: platform.scans == 1)
        controller.refresh_devices()
        QTest.qWait(120)
        assert controller.searching
        assert platform.scans == 1
        assert searching == [True]
        release.set()
        _wait_until(lambda: not controller.busy)
        assert searching == [True, False]
        _wait_until(lambda: platform.scans >= 2 and not controller.busy)
    finally:
        release.set()
        controller.shutdown()


@pytest.mark.usefixtures("fast_refresh")
def test_closing_picker_during_scan_stops_polling_and_remembered_selection(
    tmp_path: Path,
) -> None:
    platform = _ObservedPlatform()
    platform.add_volume(_device_root(tmp_path / "device"), volume_id="remembered")
    release = Event()
    platform.release = release
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    settings.set_global(LAST_SELECTED_IPOD_VOLUME_ID, "remembered")
    controller = DeviceController(
        DeviceCoordinator(Storage(platform)), TrackTableModel(), settings
    )
    try:
        controller.start_auto_refresh()
        _wait_until(lambda: platform.scans == 1)
        controller.stop_auto_refresh()
        release.set()
        _wait_until(lambda: not controller.busy)
        QTest.qWait(100)
        assert platform.scans == 1
        assert controller.active_ipod is None
        controller.start_auto_refresh()
        _wait_until(lambda: controller.active_ipod is not None and not controller.busy)
    finally:
        release.set()
        controller.shutdown()


def test_closing_picker_does_not_cancel_startup_restoration(tmp_path: Path) -> None:
    platform = _ObservedPlatform()
    platform.add_volume(_device_root(tmp_path / "device"), volume_id="remembered")
    release = Event()
    platform.release = release
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    settings.set_global(LAST_SELECTED_IPOD_VOLUME_ID, "remembered")
    controller = DeviceController(
        DeviceCoordinator(Storage(platform)), TrackTableModel(), settings
    )
    try:
        controller.restore_previous_device()
        _wait_until(lambda: platform.scans == 1)
        controller.start_auto_refresh()
        controller.stop_auto_refresh()
        release.set()
        _wait_until(lambda: controller.active_ipod is not None and not controller.busy)
        assert platform.scans == 1
    finally:
        release.set()
        controller.shutdown()


@pytest.mark.usefixtures("fast_refresh")
def test_auto_scan_recovers_from_errors_without_modal_failures() -> None:
    platform = _ObservedPlatform()
    platform.fail = True
    controller = DeviceController(
        DeviceCoordinator(Storage(platform)),
        TrackTableModel(),
        SettingsService(GlobalSettingsStore(), DeviceSettingsStore()),
    )
    failures: list[object] = []
    controller.operationFailed.connect(failures.append)
    try:
        controller.start_auto_refresh()
        _wait_until(lambda: platform.scans >= 2 and not controller.busy)
        assert controller.discovery_error == "Temporary discovery failure"
        assert failures == []
        platform.fail = False
        _wait_until(lambda: not controller.discovery_error and not controller.busy)
        platform.fail = True
        controller.refresh_devices()
        _wait_until(lambda: not controller.busy)
        assert len(failures) == 1
    finally:
        controller.shutdown()


@pytest.mark.usefixtures("fast_refresh")
def test_failed_remembered_selection_is_not_retried_every_poll(tmp_path: Path) -> None:
    platform = _ObservedPlatform()
    root = _device_root(tmp_path / "device")
    platform.add_volume(root, volume_id="remembered")
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    settings.set_global(LAST_SELECTED_IPOD_VOLUME_ID, "remembered")
    controller = DeviceController(
        DeviceCoordinator(Storage(platform)), TrackTableModel(), settings
    )
    # Discovery needs only the header; loading must reject the damaged body.
    database = root / "iPod_Control" / "iTunes" / "iTunesDB"
    database.write_bytes(database.read_bytes()[:256])
    failures: list[object] = []
    controller.operationFailed.connect(failures.append)
    try:
        controller.start_auto_refresh()
        _wait_until(lambda: bool(failures) and not controller.busy)
        scan_count = platform.scans
        _wait_until(lambda: platform.scans >= scan_count + 2 and not controller.busy)
        assert controller.active_ipod is None
        assert len(failures) == 1
        database.write_bytes(_itunesdb())
        controller.refresh_devices()
        _wait_until(lambda: controller.active_ipod is not None and not controller.busy)
    finally:
        controller.shutdown()


def test_controller_loads_device_library_into_qt_model_off_thread(
    tmp_path: Path,
) -> None:
    platform = VirtualStoragePlatform()
    root = _device_root(tmp_path / "device")
    platform.add_volume(root, label="Test iPod")
    tracks = TrackTableModel()
    controller = DeviceController(
        DeviceCoordinator(Storage(platform)),
        tracks,
        SettingsService(GlobalSettingsStore(), DeviceSettingsStore()),
    )
    failures: list[object] = []
    controller.operationFailed.connect(failures.append)

    try:
        controller.refresh_devices()
        _wait_until(lambda: not controller.busy)
        assert len(controller.discovery.candidates) == 1

        controller.select_device(controller.discovery.candidates[0].id.value)
        _wait_until(lambda: not controller.busy)

        assert failures == []
        assert controller.active_ipod is not None
        assert controller.active_ipod.display_name == "Test iPod"
        assert tracks.rowCount() == 1
        first_track = tracks.track_at(0)
        assert first_track is not None
        assert first_track.title == "So What"
    finally:
        controller.shutdown()


def test_read_only_reservation_keeps_reads_available_and_blocks_mutations(
    tmp_path: Path,
) -> None:
    platform = VirtualStoragePlatform()
    root = _device_root(tmp_path / "device")
    platform.add_volume(root, label="Test iPod")
    controller = DeviceController(
        DeviceCoordinator(Storage(platform)),
        TrackTableModel(),
        SettingsService(GlobalSettingsStore(), DeviceSettingsStore()),
    )
    write_availability: list[bool] = []
    controller.deviceWritesAllowedChanged.connect(write_availability.append)

    try:
        controller.refresh_devices()
        _wait_until(lambda: not controller.busy)
        controller.select_device(controller.discovery.candidates[0].id.value)
        _wait_until(lambda: not controller.busy)
        active = controller.active_ipod

        assert controller.device_writes_allowed is True
        assert controller.begin_read_only_operation() is True
        assert controller.busy is False
        assert controller.device_writes_allowed is False
        assert controller.begin_exclusive_operation() is False

        controller.refresh_devices()
        controller.select_device(controller.discovery.candidates[0].id.value)
        APPLICATION.processEvents()
        assert controller.busy is False
        assert controller.active_ipod is active

        controller.finish_read_only_operation()
        assert controller.device_writes_allowed is True
        assert write_availability[-2:] == [False, True]
    finally:
        controller.shutdown()


def test_controller_safely_ejects_active_ipod_and_clears_models(
    tmp_path: Path,
) -> None:
    platform = VirtualStoragePlatform()
    root = _device_root(tmp_path / "device")
    platform.add_volume(root, label="Test iPod")
    tracks = TrackTableModel()
    controller = DeviceController(
        DeviceCoordinator(Storage(platform)),
        tracks,
        SettingsService(GlobalSettingsStore(), DeviceSettingsStore()),
    )
    started: list[bool] = []
    completed: list[object] = []
    controller.ejectStarted.connect(lambda: started.append(True))
    controller.ejectCompleted.connect(completed.append)

    try:
        controller.refresh_devices()
        _wait_until(lambda: not controller.busy)
        controller.select_device(controller.discovery.candidates[0].id.value)
        _wait_until(lambda: not controller.busy)

        assert controller.eject_active_ipod() is True
        _wait_until(lambda: not controller.busy)

        assert started == [True]
        assert platform.eject_count(root) == 1
        assert controller.active_ipod is None
        assert controller.discovery.candidates == ()
        assert tracks.rowCount() == 0
        assert len(completed) == 1
        assert isinstance(completed[0], DeviceEjectCompletion)
        assert completed[0].display_name == "Test iPod"
    finally:
        controller.shutdown()


def test_controller_restores_active_session_after_retryable_eject_refusal(
    tmp_path: Path,
) -> None:
    platform = VirtualStoragePlatform()
    root = _device_root(tmp_path / "device")
    platform.add_volume(root, label="Test iPod")
    controller = DeviceController(
        DeviceCoordinator(Storage(platform)),
        TrackTableModel(),
        SettingsService(GlobalSettingsStore(), DeviceSettingsStore()),
    )
    failures: list[object] = []
    controller.operationFailed.connect(failures.append)

    try:
        controller.refresh_devices()
        _wait_until(lambda: not controller.busy)
        controller.select_device(controller.discovery.candidates[0].id.value)
        _wait_until(lambda: not controller.busy)
        active = controller.active_ipod
        platform.fail_eject(root, "Another app is using the iPod")

        assert controller.eject_active_ipod() is True
        _wait_until(lambda: not controller.busy)

        assert controller.active_ipod is active
        assert controller.device_writes_allowed is True
        assert len(failures) == 1
        assert isinstance(failures[0], DeviceOperationFailure)
        assert failures[0].operation is DeviceOperation.EJECT
        assert "Another app" in failures[0].message
    finally:
        controller.shutdown()


def test_controller_clears_active_state_after_partial_eject_failure(
    tmp_path: Path,
) -> None:
    platform = VirtualStoragePlatform()
    root = _device_root(tmp_path / "device")
    platform.add_volume(root, label="Test iPod")
    tracks = TrackTableModel()
    controller = DeviceController(
        DeviceCoordinator(Storage(platform)),
        tracks,
        SettingsService(GlobalSettingsStore(), DeviceSettingsStore()),
    )
    failures: list[object] = []
    controller.operationFailed.connect(failures.append)

    try:
        controller.refresh_devices()
        _wait_until(lambda: not controller.busy)
        controller.select_device(controller.discovery.candidates[0].id.value)
        _wait_until(lambda: not controller.busy)
        platform.fail_eject(
            root,
            "Volumes unmounted but power-off failed",
            volume_unmounted=True,
        )

        assert controller.eject_active_ipod() is True
        _wait_until(lambda: not controller.busy)

        assert controller.active_ipod is None
        assert controller.discovery.candidates == ()
        assert tracks.rowCount() == 0
        assert len(failures) == 1
        assert isinstance(failures[0], DeviceOperationFailure)
        assert "can no longer verify" in failures[0].message
    finally:
        controller.shutdown()


def test_controller_remembers_and_automatically_reselects_the_last_ipod(
    tmp_path: Path,
) -> None:
    platform = VirtualStoragePlatform()
    root = _device_root(tmp_path / "device")
    platform.add_volume(
        root,
        device_id="remembered-ipod",
        volume_id="remembered-ipod-volume",
        label="Remembered iPod",
    )
    global_store = GlobalSettingsStore()
    settings = SettingsService(global_store, DeviceSettingsStore())
    first = DeviceController(
        DeviceCoordinator(Storage(platform)),
        TrackTableModel(),
        settings,
    )

    first.refresh_devices()
    _wait_until(lambda: not first.busy)
    first.select_device(first.discovery.candidates[0].id.value)
    _wait_until(lambda: not first.busy)

    assert settings.get(LAST_SELECTED_IPOD_VOLUME_ID) == "remembered-ipod-volume"
    first.shutdown()

    restored_tracks = TrackTableModel()
    restored = DeviceController(
        DeviceCoordinator(Storage(platform)),
        restored_tracks,
        settings,
    )
    try:
        restored.refresh_devices()
        _wait_until(lambda: not restored.busy)

        assert restored.active_ipod is not None
        assert restored.active_ipod.display_name == "Remembered iPod"
        assert restored_tracks.rowCount() == 1
    finally:
        restored.shutdown()


def test_controller_does_not_auto_select_a_different_connected_ipod(
    tmp_path: Path,
) -> None:
    platform = VirtualStoragePlatform()
    root = _device_root(tmp_path / "other-device")
    platform.add_volume(
        root,
        device_id="other-ipod",
        volume_id="other-ipod-volume",
        label="Other iPod",
    )
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    settings.set_global(LAST_SELECTED_IPOD_VOLUME_ID, "missing-ipod-volume")
    controller = DeviceController(
        DeviceCoordinator(Storage(platform)),
        TrackTableModel(),
        settings,
    )

    try:
        controller.refresh_devices()
        _wait_until(lambda: not controller.busy)

        assert len(controller.discovery.candidates) == 1
        assert controller.active_ipod is None
    finally:
        controller.shutdown()


def _wait_until(predicate: Callable[[], bool], timeout_ms: int = 3000) -> None:
    deadline = monotonic() + timeout_ms / 1000
    while monotonic() < deadline:
        APPLICATION.processEvents()
        if predicate():
            return
        QTest.qWait(10)
        sleep(0.005)
    assert predicate(), "Timed out waiting for asynchronous device work"


def _device_root(root: Path) -> Path:
    device_directory = root / "iPod_Control" / "Device"
    database_directory = root / "iPod_Control" / "iTunes"
    device_directory.mkdir(parents=True)
    database_directory.mkdir(parents=True)
    (device_directory / "SysInfo").write_text(
        "ModelNumStr: MB565\n",
        encoding="utf-8",
    )
    (database_directory / "iTunesDB").write_bytes(_itunesdb())
    return root


def _itunesdb() -> bytes:
    metadata = (
        new_string_mhod(1, "So What"),
        new_string_mhod(4, "Miles Davis"),
        new_string_mhod(3, "Kind of Blue"),
        new_string_mhod(5, "Jazz"),
    )
    track = new_itunes_chunk(
        MHIT_DEFINITION,
        MhitHeader(
            track_id=1,
            size=5_000_000,
            length=545_000,
            track_number=1,
            year=1959,
            bitrate=256,
        ),
        children=metadata,
    )
    track_list = new_itunes_chunk(
        MHLT_DEFINITION,
        EmptyChunkHeader(),
        children=(track,),
    )
    dataset = new_itunes_chunk(
        MHSD_DEFINITION,
        MhsdHeader(dataset_type=1),
        children=(track_list,),
    )
    return write_iTunesDB(new_iTunesDB(MhbdHeader(), datasets=(dataset,)))
