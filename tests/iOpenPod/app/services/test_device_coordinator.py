"""End-to-end tests for Application Layer device coordination."""

import base64
import os
import plistlib
import sqlite3
import struct
from dataclasses import replace
from pathlib import Path
from threading import Event, Thread

import pytest
from PIL import Image

from iOpenPod.app.backups import BackupIdentityClaimKind
from iOpenPod.app.library_write import LibraryPreparationRequest
from iOpenPod.app.models.artwork import ArtworkRequest
from iOpenPod.app.models.device import DeviceCandidateIssueCode, DeviceReadiness
from iOpenPod.app.models.photos import FULL_RESOLUTION_REQUEST_ID, PhotoRequest
from iOpenPod.app.playback.backend import PlaybackSourceError
from iOpenPod.app.services.device_coordinator import (
    DeviceAccessError,
    DeviceChangedError,
    DeviceCoordinator,
    DevicePhotoExportError,
)
from iPodDB.ArtworkDB.builder.build_ArtworkDB import (
    new_artwork_chunk,
    new_ArtworkDB,
    new_container_mhod,
)
from iPodDB.ArtworkDB.builder.build_ArtworkDB import (
    new_string_mhod as new_artwork_string_mhod,
)
from iPodDB.ArtworkDB.shared.chunk_defs.mhii import DEFINITION as MHII_DEFINITION
from iPodDB.ArtworkDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhni import DEFINITION as MHNI_DEFINITION
from iPodDB.ArtworkDB.shared.chunk_defs.mhni import MhniHeader
from iPodDB.ArtworkDB.shared.constants import ArtworkMhodType
from iPodDB.ArtworkDB.writer.write_ArtworkDB import write_ArtworkDB
from iPodDB.iTunesDB.cdb import compress_iTunesCDB
from iPodDB.iTunesDB.writer.signature import verify_hashab
from iPodDB.library import IPodLibrary, SQLiteDatabaseSet
from iPodDB.library.writing import WriteChecksum
from iPodDB.PhotosDB.builder.build_PhotosDB import (
    new_container_mhod as new_photo_container_mhod,
)
from iPodDB.PhotosDB.builder.build_PhotosDB import (
    new_photos_chunk,
    new_PhotosDB,
)
from iPodDB.PhotosDB.builder.build_PhotosDB import (
    new_string_mhod as new_photo_string_mhod,
)
from iPodDB.PhotosDB.shared.chunk_defs.mhii import DEFINITION as PHOTO_MHII_DEFINITION
from iPodDB.PhotosDB.shared.chunk_defs.mhii import MhiiHeader as PhotoMhiiHeader
from iPodDB.PhotosDB.shared.chunk_defs.mhni import DEFINITION as PHOTO_MHNI_DEFINITION
from iPodDB.PhotosDB.shared.chunk_defs.mhni import MhniHeader as PhotoMhniHeader
from iPodDB.PhotosDB.shared.constants import PhotosMhodType
from iPodDB.PhotosDB.writer.write_PhotosDB import write_PhotosDB
from iPodDB.SQLiteDB.checksum import verify_locations_cbk
from storage import (
    AccessMode,
    DevicePath,
    FileRangeSnapshot,
    FileSnapshot,
    HardwareIdentifiers,
    HardwareProbeObservation,
    HardwareProbeResult,
    HardwareProperty,
    HostPath,
    MountedVolume,
    ScsiVpdPagePlan,
    Storage,
    StorageOperationError,
    VolumeDisconnectedError,
)
from storage.models import VolumeObservation
from storage.session import FilesystemSession
from storage.testing import VirtualStoragePlatform


class _RecordingStorage(Storage):
    def __init__(self, platform: VirtualStoragePlatform) -> None:
        super().__init__(platform)
        self.access_modes: list[AccessMode] = []
        self.host_path_checks: list[tuple[HostPath, MountedVolume]] = []

    def open_session(
        self,
        mounted_volume: MountedVolume,
        *,
        access: AccessMode = AccessMode.READ_ONLY,
    ) -> FilesystemSession:
        self.access_modes.append(access)
        return super().open_session(mounted_volume, access=access)

    def require_host_path_off_physical_device(
        self,
        path: HostPath,
        device: MountedVolume,
    ) -> None:
        self.host_path_checks.append((path, device))
        super().require_host_path_off_physical_device(path, device)


class _LinuxVirtualStoragePlatform(VirtualStoragePlatform):
    @property
    def name(self) -> str:
        return "linux"


class _MacOSVirtualStoragePlatform(VirtualStoragePlatform):
    @property
    def name(self) -> str:
        return "macos"


class _ProbeCountingPlatform(VirtualStoragePlatform):
    def __init__(self) -> None:
        super().__init__()
        self.probe_count = 0

    def probe(
        self,
        observation: VolumeObservation,
        page_plan: ScsiVpdPagePlan | None = None,
    ) -> HardwareProbeResult:
        self.probe_count += 1
        return super().probe(observation, page_plan)


class _MutatingLibraryLoader:
    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path

    def __call__(self, data: bytes) -> IPodLibrary:
        library = IPodLibrary.parse(data)
        self._database_path.write_bytes(data + b"changed")
        return library


def test_discovery_identifies_candidate_and_selection_loads_its_library(
    tmp_path: Path,
) -> None:
    platform = VirtualStoragePlatform()
    root = _ipod_volume(tmp_path / "classic", model_number="MB565")
    platform.add_volume(
        root,
        label="John's iPod",
        identifiers=HardwareIdentifiers(
            usb_vendor_id=0x05AC,
            usb_product_id=0x1261,
            transport_serial="000A270012345678",
        ),
    )
    storage = _RecordingStorage(platform)
    coordinator = DeviceCoordinator(storage)

    discovery = coordinator.discover_devices()

    assert len(discovery.candidates) == 1
    candidate = discovery.candidates[0]
    assert candidate.display_name == "John's iPod"
    assert candidate.model_number == "MB565"
    assert candidate.readiness is DeviceReadiness.READY
    assert candidate.selectable

    active = coordinator.select_device(candidate.id)

    assert active.candidate.id == candidate.id
    assert active.profile.model_number == "MB565"
    assert active.database_name == "iTunesDB"
    assert len(active.library.tracks) == 1
    assert active.library.tracks[0].title == "Blue Train"
    assert active.library.tracks[0].artist == "John Coltrane"
    assert coordinator.active_ipod == active
    assert discovery.candidates[0].id.value
    assert storage.access_modes
    assert set(storage.access_modes) == {
        AccessMode.READ_ONLY,
        AccessMode.READ_WRITE,
    }

    coordinator.close()


def test_poll_reuses_ready_candidates_but_manual_refresh_reinspects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    platform = VirtualStoragePlatform()
    root = _ipod_volume(tmp_path / "classic", model_number="MB565")
    platform.add_volume(root)
    inspect = platform.inspect

    def inspect_with_new_capacity(path: Path) -> VolumeObservation:
        observation = inspect(path)
        return replace(
            observation, volume=replace(observation.volume, available_bytes=0)
        )

    monkeypatch.setattr(platform, "inspect", inspect_with_new_capacity)
    storage = _RecordingStorage(platform)
    coordinator = DeviceCoordinator(storage)
    try:
        candidate = coordinator.discover_devices(refresh_known=False).candidates[0]
        assert candidate.available_bytes == 0
        access_count = len(storage.access_modes)

        def forbidden_reinspection(*_args: object, **_kwargs: object) -> None:
            pytest.fail(
                "Cached polling must not reread the device databases or metadata"
            )

        with monkeypatch.context() as cached_poll:
            cached_poll.setattr(
                FilesystemSession, "read_snapshot", forbidden_reinspection
            )
            cached_poll.setattr(
                FilesystemSession, "fingerprint", forbidden_reinspection
            )
            assert (
                coordinator.discover_devices(refresh_known=False).candidates[0]
                is candidate
            )
        assert storage.access_modes[access_count:] == [AccessMode.READ_ONLY]
        access_count = len(storage.access_modes)
        coordinator.discover_devices()
        assert len(storage.access_modes) > access_count
        access_count = len(storage.access_modes)
        platform.set_writable(root, False)
        coordinator.discover_devices(refresh_known=False)
        assert len(storage.access_modes) > access_count
        platform.disconnect(root)
        assert coordinator.discover_devices(refresh_known=False).candidates == ()
        platform.reconnect(root)
        assert (
            coordinator.discover_devices(refresh_known=False).candidates[0].id
            != candidate.id
        )
    finally:
        coordinator.close()


def test_poll_retries_a_candidate_whose_database_is_not_ready(tmp_path: Path) -> None:
    platform = VirtualStoragePlatform()
    root = _ipod_volume(tmp_path / "classic", model_number="MB565")
    database = root / "iPod_Control" / "iTunes" / "iTunesDB"
    original = database.read_bytes()
    database.unlink()
    platform.add_volume(root)
    coordinator = DeviceCoordinator(Storage(platform))
    try:
        candidate = coordinator.discover_devices(refresh_known=False).candidates[0]
        assert candidate.readiness is DeviceReadiness.DATABASE_MISSING
        database.write_bytes(original)
        ready = coordinator.discover_devices(refresh_known=False).candidates[0]
        assert ready.id == candidate.id
        assert ready.selectable
    finally:
        coordinator.close()


def test_backup_session_delegates_host_placement_to_storage(tmp_path: Path) -> None:
    platform = VirtualStoragePlatform()
    root = _ipod_volume(tmp_path / "classic", model_number="MB565")
    platform.add_volume(root, label="Classic")
    storage = _RecordingStorage(platform)
    coordinator = DeviceCoordinator(storage)
    candidate = coordinator.discover_devices().candidates[0]
    active = coordinator.select_device(candidate.id)
    backup_root = tmp_path / "host-backups" / "not-created"

    with coordinator.backup_session(
        active,
        backup_root,
        access=AccessMode.READ_ONLY,
    ):
        pass

    assert len(storage.host_path_checks) == 1
    checked_path, checked_volume = storage.host_path_checks[0]
    assert checked_path == HostPath(backup_root)
    assert checked_volume.physical_device.id.value == "virtual-device-1"
    assert not backup_root.exists()


def test_read_only_backup_session_does_not_block_playback_reads(
    tmp_path: Path,
) -> None:
    platform = VirtualStoragePlatform()
    root = _ipod_volume(tmp_path / "classic", model_number="MB565")
    platform.add_volume(root, label="Classic")
    coordinator = DeviceCoordinator(Storage(platform))
    candidate = coordinator.discover_devices().candidates[0]
    active = coordinator.select_device(candidate.id)
    source = coordinator.open_playback_source(active.library.tracks[0])
    backup_root = tmp_path / "host-backups" / "not-created"
    backup_started = Event()
    release_backup = Event()
    read_finished = Event()
    payloads: list[bytes] = []

    def hold_backup_session() -> None:
        with coordinator.backup_session(
            active,
            backup_root,
            access=AccessMode.READ_ONLY,
        ):
            backup_started.set()
            release_backup.wait(2)

    def read_playback() -> None:
        payloads.append(source.read_at(0, 5))
        read_finished.set()

    backup_thread = Thread(target=hold_backup_session)
    playback_thread = Thread(target=read_playback)
    try:
        backup_thread.start()
        assert backup_started.wait(1)
        playback_thread.start()

        assert read_finished.wait(0.5), "Playback read was blocked by Backup capture"
        assert payloads == [b"audio"]
    finally:
        release_backup.set()
        backup_thread.join(2)
        playback_thread.join(2)
        coordinator.close()


def test_backup_identifier_uses_volume_fallback_when_serial_is_unknown(
    tmp_path: Path,
) -> None:
    platform = VirtualStoragePlatform()
    root = _ipod_volume(tmp_path / "classic", model_number="MB565")
    platform.add_volume(root, label="Classic")
    coordinator = DeviceCoordinator(Storage(platform))
    candidate = coordinator.discover_devices().candidates[0]
    coordinator.select_device(candidate.id)

    context = coordinator.backup_device_context()

    assert context is not None
    assert not context.identity.uses_serial_number
    assert {claim.kind for claim in context.identity.claims} == {
        BackupIdentityClaimKind.VOLUME_ID
    }
    assert context.archive_key is None
    coordinator.close()


def test_backup_identifier_uses_known_metadata_serial_before_volume_fallback(
    tmp_path: Path,
) -> None:
    platform = VirtualStoragePlatform()
    root = _ipod_volume(tmp_path / "classic", model_number="MB565")
    sysinfo = root / "iPod_Control" / "Device" / "SysInfo"
    sysinfo.write_text(
        "ModelNumStr: MB565\npszSerialNumber: 8P840FN62C7\n",
        encoding="utf-8",
    )
    platform.add_volume(root, label="Classic")
    coordinator = DeviceCoordinator(Storage(platform))
    candidate = coordinator.discover_devices().candidates[0]
    coordinator.select_device(candidate.id)

    context = coordinator.backup_device_context()

    assert context is not None
    assert context.identity.uses_serial_number
    assert {claim.kind for claim in context.identity.claims} == {
        BackupIdentityClaimKind.PRODUCT_SERIAL,
        BackupIdentityClaimKind.VOLUME_ID,
    }
    coordinator.close()


def test_backup_host_paths_all_delegate_to_the_active_physical_device(
    tmp_path: Path,
) -> None:
    platform = VirtualStoragePlatform()
    root = _ipod_volume(tmp_path / "classic", model_number="MB565")
    platform.add_volume(root, label="Classic")
    storage = _RecordingStorage(platform)
    coordinator = DeviceCoordinator(storage)
    candidate = coordinator.discover_devices().candidates[0]
    coordinator.select_device(candidate.id)
    archive = tmp_path / "host-backups" / "not-created"
    export = tmp_path / "host-export" / "not-created"

    coordinator.require_backup_host_paths(archive, export)

    assert [path for path, _ in storage.host_path_checks] == [
        HostPath(archive),
        HostPath(export),
    ]
    assert all(
        mounted.physical_device.id.value == "virtual-device-1"
        for _, mounted in storage.host_path_checks
    )
    assert not archive.exists()
    assert not export.exists()


def test_backup_session_rejects_sibling_volume_on_same_physical_device(
    tmp_path: Path,
) -> None:
    platform = VirtualStoragePlatform()
    root = _ipod_volume(tmp_path / "classic", model_number="MB565")
    sibling = tmp_path / "sibling-volume"
    sibling.mkdir()
    platform.add_volume(
        root,
        label="Classic",
        device_id="shared-device",
        volume_id="ipod-volume",
    )
    platform.add_volume(
        sibling,
        label="Other partition",
        device_id="shared-device",
        volume_id="other-volume",
    )
    coordinator = DeviceCoordinator(Storage(platform))
    candidate = coordinator.discover_devices().candidates[0]
    active = coordinator.select_device(candidate.id)

    with (
        pytest.raises(DeviceAccessError, match="another Physical Device"),
        coordinator.backup_session(
            active,
            sibling / "backups",
            access=AccessMode.READ_ONLY,
        ),
    ):
        pass


def test_backup_host_path_rejects_the_active_physical_device(
    tmp_path: Path,
) -> None:
    platform = VirtualStoragePlatform()
    root = _ipod_volume(tmp_path / "classic", model_number="MB565")
    platform.add_volume(root, label="Classic")
    coordinator = DeviceCoordinator(Storage(platform))
    candidate = coordinator.discover_devices().candidates[0]
    coordinator.select_device(candidate.id)

    with pytest.raises(DeviceAccessError, match="another Physical Device"):
        coordinator.require_backup_host_paths(root / "Backups")


def test_photo_export_folder_must_be_off_the_active_physical_device(
    tmp_path: Path,
) -> None:
    platform = VirtualStoragePlatform()
    root = _ipod_volume(tmp_path / "classic", model_number="MB565")
    platform.add_volume(root, label="Classic")
    storage = _RecordingStorage(platform)
    coordinator = DeviceCoordinator(storage)
    coordinator.select_device(coordinator.discover_devices().candidates[0].id)
    host_exports = tmp_path / "host-exports"
    host_exports.mkdir()

    coordinator.require_photo_export_directory(HostPath(host_exports))

    assert [path for path, _mounted in storage.host_path_checks] == [
        HostPath(host_exports)
    ]
    with pytest.raises(DevicePhotoExportError, match="another Physical Device"):
        coordinator.require_photo_export_directory(HostPath(root / "Photos"))


def test_discovery_ignores_removable_volume_without_ipod_control(
    tmp_path: Path,
) -> None:
    platform = VirtualStoragePlatform()
    ipod_root = _ipod_volume(tmp_path / "classic", model_number="MB565")
    flash_drive_root = tmp_path / "flash-drive"
    flash_drive_root.mkdir()
    platform.add_volume(
        flash_drive_root,
        device_id="generic-usb-device",
        volume_id="generic-usb-volume",
        label="USB Flash Drive",
        identifiers=HardwareIdentifiers(
            usb_vendor_id=0x0781,
            usb_product_id=0x5581,
        ),
    )
    platform.add_volume(
        ipod_root,
        device_id="ipod-device",
        volume_id="ipod-volume",
        label="Classic",
    )
    coordinator = DeviceCoordinator(Storage(platform))

    discovery = coordinator.discover_devices()

    assert tuple(candidate.display_name for candidate in discovery.candidates) == (
        "Classic",
    )


def test_selection_repairs_missing_device_metadata_and_records_authority(
    tmp_path: Path,
) -> None:
    platform = VirtualStoragePlatform()
    root = _ipod_volume(tmp_path / "classic", model_number="MB565")
    device_directory = root / "iPod_Control" / "Device"
    (device_directory / "SysInfo").unlink()
    platform.add_volume(
        root,
        label="Classic",
        identifiers=HardwareIdentifiers(
            usb_vendor_id=0x05AC,
            usb_product_id=0x1261,
            product_serial="8P840FN62C7",
            transport_serial="000A270012345678",
        ),
    )
    storage = _RecordingStorage(platform)
    coordinator = DeviceCoordinator(storage)

    candidate = coordinator.discover_devices().candidates[0]
    active = coordinator.select_device(candidate.id)

    assert active.profile.model_number == "MB565"
    assert "ModelNumStr: xB565" in (device_directory / "SysInfo").read_text()
    assert (device_directory / "SysInfoExtended").is_file()
    assert (device_directory / "iOpenPodSysInfoAuthority").is_file()
    assert AccessMode.READ_WRITE in storage.access_modes
    coordinator.close()


def test_macos_discovery_identifies_ipod_without_sysinfo(
    tmp_path: Path,
) -> None:
    platform = _MacOSVirtualStoragePlatform()
    root = _ipod_volume(tmp_path / "classic", model_number="MB565")
    (root / "iPod_Control" / "Device" / "SysInfo").unlink()
    platform.add_volume(
        root,
        label="Classic",
        identifiers=HardwareIdentifiers(
            usb_vendor_id=0x05AC,
            usb_product_id=0x1261,
            transport_serial="000A270018A1F847",
        ),
        probe_result=HardwareProbeResult(
            observations=(
                HardwareProbeObservation(
                    source="iokit",
                    vendor="Apple",
                    product="iPod",
                    unit_serial="8P840FN62C7",
                    transport_serial="000A270018A1F847",
                ),
            )
        ),
    )
    coordinator = DeviceCoordinator(Storage(platform))

    candidate = coordinator.discover_devices().candidates[0]

    assert candidate.model_number == "MB565"
    assert candidate.readiness is DeviceReadiness.READY


def test_valid_authority_avoids_repeating_a_live_hardware_probe(
    tmp_path: Path,
) -> None:
    platform = _ProbeCountingPlatform()
    root = _ipod_volume(tmp_path / "classic", model_number="MB565")
    platform.add_volume(
        root,
        identifiers=HardwareIdentifiers(
            product_serial="8P840FN62C7",
            transport_serial="000A270012345678",
        ),
    )
    coordinator = DeviceCoordinator(Storage(platform))

    candidate = coordinator.discover_devices().candidates[0]
    coordinator.select_device(candidate.id)
    coordinator.discover_devices()

    assert platform.probe_count == 1
    coordinator.close()


def test_live_identity_repairs_stale_sysinfo_model_on_selection(
    tmp_path: Path,
) -> None:
    platform = VirtualStoragePlatform()
    root = _ipod_volume(tmp_path / "classic", model_number="M9160")
    platform.add_volume(
        root,
        identifiers=HardwareIdentifiers(product_serial="8P840FN62C7"),
    )
    coordinator = DeviceCoordinator(Storage(platform))

    candidate = coordinator.discover_devices().candidates[0]
    active = coordinator.select_device(candidate.id)

    assert candidate.model_number == "MB565"
    assert active.profile.model_number == "MB565"
    sysinfo = root / "iPod_Control" / "Device" / "SysInfo"
    assert "ModelNumStr: xB565" in sysinfo.read_text(encoding="utf-8")
    coordinator.close()


def test_read_only_selection_reports_metadata_repair_without_writing(
    tmp_path: Path,
) -> None:
    platform = VirtualStoragePlatform()
    root = _ipod_volume(tmp_path / "classic", model_number="MB565")
    device_directory = root / "iPod_Control" / "Device"
    (device_directory / "SysInfo").unlink()
    platform.add_volume(
        root,
        writable=False,
        identifiers=HardwareIdentifiers(product_serial="8P840FN62C7"),
    )
    storage = _RecordingStorage(platform)
    coordinator = DeviceCoordinator(storage)

    candidate = coordinator.discover_devices().candidates[0]
    active = coordinator.select_device(candidate.id)

    assert active.profile.model_number == "MB565"
    assert not (device_directory / "SysInfo").exists()
    assert not (device_directory / "SysInfoExtended").exists()
    assert not (device_directory / "iOpenPodSysInfoAuthority").exists()
    assert AccessMode.READ_WRITE not in storage.access_modes
    assert any(
        issue.code is DeviceCandidateIssueCode.METADATA_RECONCILIATION_SKIPPED
        for issue in active.candidate.issues
    )
    coordinator.close()


def test_linux_candidate_asks_for_identity_rule_when_product_serial_is_hidden(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(
        "INFO",
        logger="iOpenPod.app.services.device_coordinator",
    )
    platform = _LinuxVirtualStoragePlatform()
    root = _ipod_volume(tmp_path / "classic", model_number="MB565")
    platform.add_volume(
        root,
        identifiers=HardwareIdentifiers(
            usb_vendor_id=0x05AC,
            usb_product_id=0x1261,
            transport_serial="000A270012345678",
        ),
        probe_result=HardwareProbeResult(
            observations=(
                HardwareProbeObservation(
                    source="udev",
                    transport_serial="000A270012345678",
                    host_properties=(
                        HardwareProperty("ID_VENDOR_ID", "05ac"),
                        HardwareProperty("ID_MODEL_ID", "1261"),
                    ),
                ),
            )
        ),
    )
    coordinator = DeviceCoordinator(Storage(platform))

    candidate = coordinator.discover_devices().candidates[0]

    assert any(
        issue.code is DeviceCandidateIssueCode.HARDWARE_PROBE_SETUP_REQUIRED
        for issue in candidate.issues
    )
    assert any(
        message.startswith(
            "Linux iPod udev runtime properties: identity-rule marker not observed"
        )
        for message in caplog.messages
    )


def test_linux_candidate_logs_installed_rule_that_did_not_publish_serial(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(
        "INFO",
        logger="iOpenPod.app.services.device_coordinator",
    )
    platform = _LinuxVirtualStoragePlatform()
    root = _ipod_volume(tmp_path / "classic", model_number="MB565")
    platform.add_volume(
        root,
        identifiers=HardwareIdentifiers(
            usb_vendor_id=0x05AC,
            usb_product_id=0x1261,
            transport_serial="000A270012345678",
        ),
        probe_result=HardwareProbeResult(
            observations=(
                HardwareProbeObservation(
                    source="udev",
                    transport_serial="000A270012345678",
                    host_properties=(
                        HardwareProperty("ID_IOPENPOD_RULE_VERSION", "2"),
                    ),
                ),
            )
        ),
    )
    coordinator = DeviceCoordinator(Storage(platform))

    candidate = coordinator.discover_devices().candidates[0]

    assert any(
        issue.code is DeviceCandidateIssueCode.HARDWARE_PROBE_FAILED
        for issue in candidate.issues
    )
    assert (
        "Linux iPod udev runtime properties: expected rule version 2 observed for "
        "the current connection"
    ) in caplog.messages
    assert (
        "Linux iPod identity rule ran but did not publish a valid product serial"
        in caplog.messages
    )


def test_linux_candidate_logs_when_rule_supplies_product_serial(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(
        "INFO",
        logger="iOpenPod.app.services.device_coordinator",
    )
    platform = _LinuxVirtualStoragePlatform()
    root = _ipod_volume(tmp_path / "classic", model_number="MB565")
    platform.add_volume(
        root,
        identifiers=HardwareIdentifiers(
            usb_vendor_id=0x05AC,
            usb_product_id=0x1261,
            transport_serial="000A270012345678",
        ),
        probe_result=HardwareProbeResult(
            observations=(
                HardwareProbeObservation(
                    source="udev",
                    transport_serial="000A270012345678",
                    host_properties=(
                        HardwareProperty("ID_IOPENPOD_RULE_VERSION", "2"),
                        HardwareProperty(
                            "ID_IOPENPOD_PRODUCT_SERIAL",
                            "8P840FN62C7",
                        ),
                    ),
                ),
            )
        ),
    )
    coordinator = DeviceCoordinator(Storage(platform))

    candidate = coordinator.discover_devices().candidates[0]

    assert not any(
        issue.code is DeviceCandidateIssueCode.HARDWARE_PROBE_SETUP_REQUIRED
        for issue in candidate.issues
    )
    assert (
        "Linux iPod udev runtime properties: expected rule version 2 observed for "
        "the current connection"
    ) in caplog.messages
    assert (
        "Linux iPod udev runtime property supplied the product serial for the "
        "current connection; this does not prove the rule file is still installed"
    ) in caplog.messages
    assert "8P840FN62C7" not in caplog.text


def test_short_scsi_unit_serial_is_not_promoted_to_apple_product_identity(
    tmp_path: Path,
) -> None:
    platform = VirtualStoragePlatform()
    root = _ipod_volume(tmp_path / "classic", model_number="MB565")
    platform.add_volume(
        root,
        identifiers=HardwareIdentifiers(
            usb_vendor_id=0x05AC,
            usb_product_id=0x1261,
        ),
        probe_result=HardwareProbeResult(
            observations=(
                HardwareProbeObservation(
                    source="windows_scsi",
                    vendor="Apple",
                    product="iPod",
                    unit_serial="4",
                ),
            )
        ),
    )
    coordinator = DeviceCoordinator(Storage(platform))

    candidate = coordinator.discover_devices().candidates[0]
    coordinator.select_device(candidate.id)

    assert candidate.model_number == "MB565"
    assert candidate.profile is not None
    sysinfo = root / "iPod_Control" / "Device" / "SysInfo"
    assert "pszSerialNumber: 4" not in sysinfo.read_text(encoding="utf-8")
    coordinator.close()


def test_discovery_only_requires_itunescdb_for_sqlite_device(
    tmp_path: Path,
) -> None:
    platform = VirtualStoragePlatform()
    root = _ipod_volume(
        tmp_path / "nano",
        model_number="MC027",
        database_name="iTunesCDB",
    )
    platform.add_volume(root, label="Nano")
    coordinator = DeviceCoordinator(Storage(platform))

    candidate = coordinator.discover_devices().candidates[0]
    active = coordinator.select_device(candidate.id)

    assert candidate.model_number == "MC027"
    assert candidate.readiness is DeviceReadiness.READY
    assert candidate.selectable
    assert active.database_name == "iTunesCDB"
    assert active.library.tracks[0].title == "Blue Train"


def test_selection_reads_itunescdb_without_sqlite_companions(tmp_path: Path) -> None:
    platform = VirtualStoragePlatform()
    root = _ipod_volume(
        tmp_path / "nano",
        model_number="MC027",
        database_name="iTunesCDB",
    )
    raw = _database_with_track()
    (root / "iPod_Control" / "iTunes" / "iTunesCDB").write_bytes(
        compress_iTunesCDB(raw)
    )
    platform.add_volume(root, label="Nano")
    coordinator = DeviceCoordinator(Storage(platform))

    candidate = coordinator.discover_devices().candidates[0]
    active = coordinator.select_device(candidate.id)

    assert candidate.readiness is DeviceReadiness.READY
    assert active.database_name == "iTunesCDB"
    assert active.library.tracks[0].title == "Blue Train"


def test_selection_ignores_damaged_sqlite_projection(tmp_path: Path) -> None:
    platform = VirtualStoragePlatform()
    root = _ipod_volume(
        tmp_path / "nano",
        model_number="MC027",
        database_name="iTunesCDB",
    )
    raw = _database_with_track()
    (root / "iPod_Control" / "iTunes" / "iTunesCDB").write_bytes(
        compress_iTunesCDB(raw)
    )
    sqlite_directory = root / "iPod_Control" / "iTunes" / "iTunes Library.itlp"
    sqlite_directory.mkdir(parents=True)
    for name in (
        "Library.itdb",
        "Locations.itdb",
        "Dynamic.itdb",
        "Extras.itdb",
        "Genius.itdb",
        "Locations.itdb.cbk",
    ):
        (sqlite_directory / name).write_bytes(b"damaged projection")
    platform.add_volume(root, label="Nano")
    coordinator = DeviceCoordinator(Storage(platform))

    candidate = coordinator.discover_devices().candidates[0]
    active = coordinator.select_device(candidate.id)

    assert active.library.tracks[0].title == "Blue Train"


def test_nano_library_save_publishes_cdb_and_sqlite_as_one_generation(
    tmp_path: Path,
) -> None:
    platform = VirtualStoragePlatform()
    root = _ipod_volume(
        tmp_path / "nano",
        model_number="MC027",
        database_name="iTunesCDB",
    )
    raw = _database_with_track()
    cdb = root / "iPod_Control" / "iTunes" / "iTunesCDB"
    cdb.write_bytes(compress_iTunesCDB(raw))
    guid = bytes.fromhex("000A270012345678")
    _install_nano5_hash72_metadata(root, guid)
    _install_sqlite_postprocess_metadata(
        root,
        ("PRAGMA main.user_version = 41; PRAGMA main.user_version = 42;",),
    )
    platform.add_volume(root, label="Nano")
    coordinator = DeviceCoordinator(Storage(platform))
    active = coordinator.select_device(coordinator.discover_devices().candidates[0].id)
    edited = replace(
        active.library,
        tracks=(replace(active.library.tracks[0], title="Late Nano"),),
    )

    review = coordinator.prepare_library(
        LibraryPreparationRequest(edited, active, 1, 1),
        lambda _progress: None,
        Event(),
    )
    saved = coordinator.save_library(
        review,
        active,
        lambda _progress: None,
        Event(),
    )

    assert review.result.prepared is not None, review.result.issues
    assert saved.active is not None, saved.issues
    assert IPodLibrary.parse(cdb.read_bytes()).snapshot.tracks[0].title == "Late Nano"
    assert (root / "iPod_Control" / "iTunes" / "iTunesDB").read_bytes() == b""
    assert review.result.prepared.sqlite is not None
    library_database = sqlite3.connect(":memory:")
    library_database.deserialize(review.result.prepared.sqlite.library)
    assert library_database.execute("PRAGMA user_version").fetchone() == (42,)
    library_database.close()
    sqlite_directory = root / "iPod_Control" / "iTunes" / "iTunes Library.itlp"
    assert all(
        sqlite_directory.joinpath(name).read_bytes() == data
        for name, data in review.result.prepared.sqlite.artifacts()
    )
    assert saved.active.library.tracks[0].title == "Late Nano"


def test_nano5_applies_observed_sqlite_postprocess_commands(tmp_path: Path) -> None:
    platform = VirtualStoragePlatform()
    root = _ipod_volume(
        tmp_path / "nano",
        model_number="MC027",
        database_name="iTunesCDB",
    )
    cdb = root / "iPod_Control" / "iTunes" / "iTunesCDB"
    cdb.write_bytes(compress_iTunesCDB(_database_with_track()))
    _install_nano5_hash72_metadata(root, bytes.fromhex("000A270012345678"))
    fixture = (
        Path(__file__).parents[3]
        / "fixtures"
        / "SQLiteDB"
        / "observed-postprocess-commands.plist"
    )
    (root / "iPod_Control" / "Device" / "SysInfoExtended").write_bytes(
        fixture.read_bytes()
    )
    platform.add_volume(root, label="Nano")
    coordinator = DeviceCoordinator(Storage(platform))
    active = coordinator.select_device(coordinator.discover_devices().candidates[0].id)
    edited = replace(
        active.library,
        tracks=(replace(active.library.tracks[0], title="Observed commands"),),
    )

    review = coordinator.prepare_library(
        LibraryPreparationRequest(edited, active, 1, 1),
        lambda _progress: None,
        Event(),
    )

    assert review.result.prepared is not None, review.result.issues
    assert review.result.prepared.sqlite is not None
    library_database = sqlite3.connect(":memory:")
    try:
        library_database.deserialize(review.result.prepared.sqlite.library)
        index = library_database.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND name = ?",
            ("item_idx_artist",),
        ).fetchone()
    finally:
        library_database.close()
    assert index == ("item_idx_artist",)


@pytest.mark.parametrize(
    "hash_uuid",
    (
        pytest.param(bytes.fromhex("FFFFFFFFFFFFFFFF") + bytes(12), id="other-guid"),
        pytest.param(
            bytes.fromhex("000A270012345678") + bytes(11) + b"\x01",
            id="nonzero-padding",
        ),
    ),
)
def test_nano5_preparation_rejects_hashinfo_for_another_device(
    tmp_path: Path,
    hash_uuid: bytes,
) -> None:
    platform = VirtualStoragePlatform()
    root = _ipod_volume(
        tmp_path / "nano",
        model_number="MC027",
        database_name="iTunesCDB",
    )
    cdb = root / "iPod_Control" / "iTunes" / "iTunesCDB"
    original_cdb = compress_iTunesCDB(_database_with_track())
    cdb.write_bytes(original_cdb)
    guid = bytes.fromhex("000A270012345678")
    _install_nano5_hash72_metadata(root, guid, hash_uuid=hash_uuid)
    _install_sqlite_postprocess_metadata(root, ("PRAGMA main.user_version = 42",))
    platform.add_volume(root, label="Nano")
    coordinator = DeviceCoordinator(Storage(platform))
    active = coordinator.select_device(coordinator.discover_devices().candidates[0].id)
    edited = replace(
        active.library,
        tracks=(replace(active.library.tracks[0], title="Rejected edit"),),
    )

    review = coordinator.prepare_library(
        LibraryPreparationRequest(edited, active, 1, 1),
        lambda _progress: None,
        Event(),
    )

    assert review.result.prepared is None
    assert any(
        "HashInfo UUID does not match" in issue.detail for issue in review.result.issues
    )
    assert cdb.read_bytes() == original_cdb


@pytest.mark.parametrize(
    "metadata",
    ("missing", "unrelated", "empty-commands"),
)
def test_nano5_preparation_requires_sqlite_postprocess_commands(
    tmp_path: Path,
    metadata: str,
) -> None:
    platform = VirtualStoragePlatform()
    root = _ipod_volume(
        tmp_path / "nano",
        model_number="MC027",
        database_name="iTunesCDB",
    )
    cdb = root / "iPod_Control" / "iTunes" / "iTunesCDB"
    original_cdb = compress_iTunesCDB(_database_with_track())
    cdb.write_bytes(original_cdb)
    _install_nano5_hash72_metadata(root, bytes.fromhex("000A270012345678"))
    if metadata == "unrelated":
        (root / "iPod_Control" / "Device" / "SysInfoExtended").write_bytes(
            plistlib.dumps({"SerialNumber": "unrelated"})
        )
    elif metadata == "empty-commands":
        _install_sqlite_postprocess_metadata(root, ())
    platform.add_volume(root, label="Nano")
    coordinator = DeviceCoordinator(Storage(platform))
    active = coordinator.select_device(coordinator.discover_devices().candidates[0].id)
    edited = replace(
        active.library,
        tracks=(replace(active.library.tracks[0], title="Rejected edit"),),
    )

    review = coordinator.prepare_library(
        LibraryPreparationRequest(edited, active, 1, 1),
        lambda _progress: None,
        Event(),
    )

    assert review.result.prepared is None
    assert any("SQLite postprocess" in issue.detail for issue in review.result.issues)
    assert cdb.read_bytes() == original_cdb


def test_nano5_save_rejects_hashinfo_replaced_after_review(tmp_path: Path) -> None:
    platform = VirtualStoragePlatform()
    root = _ipod_volume(
        tmp_path / "nano",
        model_number="MC027",
        database_name="iTunesCDB",
    )
    cdb = root / "iPod_Control" / "iTunes" / "iTunesCDB"
    original_cdb = compress_iTunesCDB(_database_with_track())
    cdb.write_bytes(original_cdb)
    guid = bytes.fromhex("000A270012345678")
    _install_nano5_hash72_metadata(root, guid)
    _install_sqlite_postprocess_metadata(root, ("PRAGMA main.user_version = 42",))
    platform.add_volume(root, label="Nano")
    coordinator = DeviceCoordinator(Storage(platform))
    active = coordinator.select_device(coordinator.discover_devices().candidates[0].id)
    edited = replace(
        active.library,
        tracks=(replace(active.library.tracks[0], title="Reviewed edit"),),
    )
    review = coordinator.prepare_library(
        LibraryPreparationRequest(edited, active, 1, 1),
        lambda _progress: None,
        Event(),
    )
    hash_info = root / "iPod_Control" / "Device" / "HashInfo"
    replacement = bytearray(hash_info.read_bytes())
    replacement[6] ^= 0x01
    hash_info.write_bytes(replacement)

    saved = coordinator.save_library(
        review,
        active,
        lambda _progress: None,
        Event(),
    )

    assert review.result.prepared is not None, review.result.issues
    assert saved.active is None
    assert {issue.code for issue in saved.issues} == {"save.source_unavailable"}
    assert cdb.read_bytes() == original_cdb


def test_nano5_save_rejects_sysinfoextended_replaced_after_review(
    tmp_path: Path,
) -> None:
    platform = VirtualStoragePlatform()
    root = _ipod_volume(
        tmp_path / "nano",
        model_number="MC027",
        database_name="iTunesCDB",
    )
    cdb = root / "iPod_Control" / "iTunes" / "iTunesCDB"
    original_cdb = compress_iTunesCDB(_database_with_track())
    cdb.write_bytes(original_cdb)
    guid = bytes.fromhex("000A270012345678")
    _install_nano5_hash72_metadata(root, guid)
    _install_sqlite_postprocess_metadata(root, ("PRAGMA main.user_version = 42",))
    platform.add_volume(root, label="Nano")
    coordinator = DeviceCoordinator(Storage(platform))
    active = coordinator.select_device(coordinator.discover_devices().candidates[0].id)
    edited = replace(
        active.library,
        tracks=(replace(active.library.tracks[0], title="Reviewed edit"),),
    )
    review = coordinator.prepare_library(
        LibraryPreparationRequest(edited, active, 1, 1),
        lambda _progress: None,
        Event(),
    )
    _install_sqlite_postprocess_metadata(
        root,
        ("PRAGMA main.user_version = 43",),
    )

    saved = coordinator.save_library(
        review,
        active,
        lambda _progress: None,
        Event(),
    )

    assert review.result.prepared is not None, review.result.issues
    assert saved.active is None
    assert {issue.code for issue in saved.issues} & {
        "save.failed",
        "save.source_unavailable",
    }
    assert cdb.read_bytes() == original_cdb


def test_nano6_sqlite_postprocess_commands_are_optional(tmp_path: Path) -> None:
    platform = VirtualStoragePlatform()
    root = _ipod_volume(
        tmp_path / "nano6",
        model_number="MC525",
        database_name="iTunesCDB",
    )
    cdb = root / "iPod_Control" / "iTunes" / "iTunesCDB"
    cdb.write_bytes(compress_iTunesCDB(_database_with_track()))
    guid = bytes.fromhex("000A270012345678")
    (root / "iPod_Control" / "Device" / "SysInfo").write_text(
        f"ModelNumStr: MC525\nFirewireGuid: {guid.hex().upper()}\n",
        encoding="utf-8",
    )
    platform.add_volume(root, label="Nano 6")
    coordinator = DeviceCoordinator(Storage(platform))
    active = coordinator.select_device(coordinator.discover_devices().candidates[0].id)
    edited = replace(
        active.library,
        tracks=(replace(active.library.tracks[0], title="Optional commands"),),
    )

    review = coordinator.prepare_library(
        LibraryPreparationRequest(edited, active, 1, 1),
        lambda _progress: None,
        Event(),
    )

    assert review.result.prepared is not None, review.result.issues


def test_nano_save_rejects_sqlite_path_changed_after_review(tmp_path: Path) -> None:
    platform = VirtualStoragePlatform()
    root = _ipod_volume(
        tmp_path / "nano6",
        model_number="MC525",
        database_name="iTunesCDB",
    )
    raw = _database_with_track()
    cdb = root / "iPod_Control" / "iTunes" / "iTunesCDB"
    original_cdb = compress_iTunesCDB(raw)
    cdb.write_bytes(original_cdb)
    guid = bytes.fromhex("000A270012345678")
    (root / "iPod_Control" / "Device" / "SysInfo").write_text(
        f"ModelNumStr: MC525\nFirewireGuid: {guid.hex().upper()}\n",
        encoding="utf-8",
    )
    platform.add_volume(root, label="Nano 6")
    coordinator = DeviceCoordinator(Storage(platform))
    active = coordinator.select_device(coordinator.discover_devices().candidates[0].id)
    edited = replace(
        active.library,
        tracks=(replace(active.library.tracks[0], title="Reviewed title"),),
    )
    review = coordinator.prepare_library(
        LibraryPreparationRequest(edited, active, 1, 1),
        lambda _progress: None,
        Event(),
    )
    changed = root / "iPod_Control" / "iTunes" / "iTunes Library.itlp" / "Library.itdb"
    changed.parent.mkdir(parents=True)
    changed.write_bytes(b"external change")

    saved = coordinator.save_library(
        review,
        active,
        lambda _progress: None,
        Event(),
    )

    assert saved.active is None
    assert {issue.code for issue in saved.issues} & {
        "save.failed",
        "save.source_unavailable",
    }
    assert cdb.read_bytes() == original_cdb
    assert changed.read_bytes() == b"external change"


def test_nano6_save_uses_hashab_for_cdb_and_sqlite_generation(
    tmp_path: Path,
) -> None:
    platform = VirtualStoragePlatform()
    root = _ipod_volume(
        tmp_path / "nano6",
        model_number="MC525",
        database_name="iTunesCDB",
    )
    raw = _database_with_track()
    cdb = root / "iPod_Control" / "iTunes" / "iTunesCDB"
    cdb.write_bytes(compress_iTunesCDB(raw))
    guid = bytes.fromhex("000A270012345678")
    (root / "iPod_Control" / "Device" / "SysInfo").write_text(
        f"ModelNumStr: MC525\nFirewireGuid: {guid.hex().upper()}\n",
        encoding="utf-8",
    )
    (root / "iPod_Control" / "Device" / "SysInfoExtended").write_bytes(
        plistlib.dumps(
            {
                "com.apple.mobile.iTunes.SQLMusicLibraryPostProcessCommands": {
                    "SQLCommands": {
                        "SetLibraryVersion": "PRAGMA main.user_version = 42"
                    },
                    "UserVersionCommandSets": {
                        "1": {"Commands": ["SetLibraryVersion"]}
                    },
                }
            }
        )
    )
    platform.add_volume(root, label="Nano 6")
    coordinator = DeviceCoordinator(Storage(platform))
    active = coordinator.select_device(coordinator.discover_devices().candidates[0].id)
    edited = replace(
        active.library,
        tracks=(replace(active.library.tracks[0], title="HASHAB Nano"),),
    )

    review = coordinator.prepare_library(
        LibraryPreparationRequest(edited, active, 1, 1),
        lambda _progress: None,
        Event(),
    )
    saved = coordinator.save_library(
        review,
        active,
        lambda _progress: None,
        Event(),
    )

    assert review.result.prepared is not None, review.result.issues
    assert saved.active is not None, saved.issues
    assert verify_hashab(cdb.read_bytes(), guid)
    assert review.result.prepared.sqlite is not None
    library_database = sqlite3.connect(":memory:")
    library_database.deserialize(review.result.prepared.sqlite.library)
    assert library_database.execute("PRAGMA user_version").fetchone() == (42,)
    library_database.close()
    sqlite_directory = root / "iPod_Control" / "iTunes" / "iTunes Library.itlp"
    saved_sqlite = SQLiteDatabaseSet(
        *(
            sqlite_directory.joinpath(name).read_bytes()
            for name, _data in review.result.prepared.sqlite.artifacts()
        )
    )
    assert verify_locations_cbk(saved_sqlite, WriteChecksum.HASHAB, guid)
    assert saved.active.library.tracks[0].title == "HASHAB Nano"


def test_disconnect_invalidates_active_ipod_on_discovery_refresh(
    tmp_path: Path,
) -> None:
    platform = VirtualStoragePlatform()
    root = _ipod_volume(tmp_path / "classic", model_number="MB565")
    platform.add_volume(root, label="Classic")
    coordinator = DeviceCoordinator(Storage(platform))
    candidate = coordinator.discover_devices().candidates[0]
    coordinator.select_device(candidate.id)

    platform.disconnect(root)
    discovery = coordinator.discover_devices()

    assert discovery.candidates == ()
    assert discovery.active_candidate_id is None
    assert coordinator.active_ipod is None


def test_selection_rejects_a_stale_connection_generation(tmp_path: Path) -> None:
    platform = VirtualStoragePlatform()
    root = _ipod_volume(tmp_path / "classic", model_number="MB565")
    platform.add_volume(root, label="Classic")
    coordinator = DeviceCoordinator(Storage(platform))
    candidate = coordinator.discover_devices().candidates[0]

    platform.disconnect(root)

    with pytest.raises(DeviceAccessError):
        coordinator.select_device(candidate.id)
    assert coordinator.active_ipod is None


def test_selection_rejects_database_changed_during_parse(tmp_path: Path) -> None:
    platform = VirtualStoragePlatform()
    root = _ipod_volume(tmp_path / "classic", model_number="MB565")
    platform.add_volume(root, label="Classic")
    database_path = root / "iPod_Control" / "iTunes" / "iTunesDB"
    coordinator = DeviceCoordinator(
        Storage(platform),
        library_loader=_MutatingLibraryLoader(database_path),
    )
    candidate = coordinator.discover_devices().candidates[0]

    with pytest.raises(DeviceChangedError):
        coordinator.select_device(candidate.id)
    assert coordinator.active_ipod is None


def test_artworkdb_links_tracks_and_ithmb_is_decoded_only_when_requested(
    tmp_path: Path,
) -> None:
    platform = VirtualStoragePlatform()
    root = _ipod_volume(tmp_path / "classic", model_number="MB565")
    _install_artwork(root)
    platform.add_volume(root, label="Classic")
    coordinator = DeviceCoordinator(Storage(platform))
    candidate = coordinator.discover_devices().candidates[0]

    active = coordinator.select_device(candidate.id)
    track = active.library.tracks[0]

    assert track.ipod is not None
    assert track.ipod.db_track_id == 0x0102030405060708
    assert track.artwork_id == 64
    assert active.artwork_database_fingerprint is not None

    result = coordinator.load_artwork(ArtworkRequest(artwork_id=64, target_px=44))

    assert result is not None
    assert result.artwork_id == 64
    assert result.format_id == 1061
    assert (result.width, result.height) == (56, 56)
    assert result.rgb888[:3] == bytes((255, 0, 0))
    assert result.byte_count == 56 * 56 * 3

    large = coordinator.load_artwork(ArtworkRequest(artwork_id=64, target_px=512))
    assert large is not None
    assert large.format_id == 1060
    assert (large.width, large.height) == (320, 320)
    assert large.rgb888[:3] == bytes((0, 0, 255))

    coordinator.close()


def test_photosdb_is_projected_into_the_active_library(tmp_path: Path) -> None:
    platform = VirtualStoragePlatform()
    root = _ipod_volume(tmp_path / "classic", model_number="MB565")
    photo_directory = root / "Photos"
    photo_directory.mkdir()
    fixture = (
        Path(__file__).parents[3]
        / "fixtures"
        / "PhotosDB"
        / "original-photo-library.b64"
    )
    photo_directory.joinpath("Photo Database").write_bytes(
        base64.b64decode(
            fixture.read_text(encoding="ascii").strip(),
            validate=True,
        )
    )
    platform.add_volume(root, label="Classic")
    coordinator = DeviceCoordinator(Storage(platform))
    candidate = coordinator.discover_devices().candidates[0]

    active = coordinator.select_device(candidate.id)

    assert active.library.photos is not None
    assert active.photos_database_fingerprint is not None
    assert tuple(photo.photo_id for photo in active.library.photos.photos) == (100,)
    assert tuple(album.name for album in active.library.photos.albums) == (
        "Photo Library",
        "Favorites",
    )
    coordinator.close()


def test_photo_thumbnail_is_decoded_only_when_requested(tmp_path: Path) -> None:
    platform = VirtualStoragePlatform()
    root = _ipod_volume(tmp_path / "nano", model_number="MA004")
    _install_photos(root)
    platform.add_volume(root, label="Nano")
    coordinator = DeviceCoordinator(Storage(platform))
    candidate = coordinator.discover_devices().candidates[0]

    active = coordinator.select_device(candidate.id)

    assert active.library.photos is not None
    result = coordinator.load_photo(PhotoRequest(photo_id=100, target_px=32))

    assert result is not None
    assert result.photo_id == 100
    assert result.format_id == 1032
    assert (result.width, result.height) == (42, 37)
    assert result.rgb888[:3] == bytes((255, 0, 0))
    assert result.byte_count == 42 * 37 * 3
    coordinator.close()


def test_full_resolution_photo_is_read_safely_and_scaled_for_display(
    tmp_path: Path,
) -> None:
    platform = VirtualStoragePlatform()
    root = _ipod_volume(tmp_path / "classic", model_number="MB565")
    photo_directory = root / "Photos"
    full_resolution = photo_directory / "Full Resolution" / "iOpenPod" / "Sunrise.jpg"
    full_resolution.parent.mkdir(parents=True)
    image = Image.new("RGB", (80, 40), (10, 20, 30))
    try:
        image.save(full_resolution, format="PNG")
    finally:
        image.close()
    fixture = (
        Path(__file__).parents[3]
        / "fixtures"
        / "PhotosDB"
        / "original-photo-library.b64"
    )
    photo_directory.joinpath("Photo Database").write_bytes(
        base64.b64decode(
            fixture.read_text(encoding="ascii").strip(),
            validate=True,
        )
    )
    platform.add_volume(root, label="Classic")
    coordinator = DeviceCoordinator(Storage(platform))
    coordinator.select_device(coordinator.discover_devices().candidates[0].id)

    result = coordinator.load_photo(
        PhotoRequest(
            photo_id=100,
            target_px=32,
            format_id=FULL_RESOLUTION_REQUEST_ID,
        )
    )

    assert result is not None
    assert result.photo_id == 100
    assert result.format_id == FULL_RESOLUTION_REQUEST_ID
    assert (result.width, result.height) == (32, 16)
    assert result.rgb888[:3] == bytes((10, 20, 30))
    assert result.byte_count == 32 * 16 * 3
    coordinator.close()


def test_photo_export_copies_a_full_resolution_file_through_storage(
    tmp_path: Path,
) -> None:
    platform = VirtualStoragePlatform()
    root = _ipod_volume(tmp_path / "classic", model_number="MB565")
    photo_directory = root / "Photos"
    full_resolution = photo_directory / "Full Resolution" / "iOpenPod" / "Sunrise.jpg"
    full_resolution.parent.mkdir(parents=True)
    full_resolution.write_bytes(b"original jpeg bytes")
    fixture = (
        Path(__file__).parents[3]
        / "fixtures"
        / "PhotosDB"
        / "original-photo-library.b64"
    )
    photo_directory.joinpath("Photo Database").write_bytes(
        base64.b64decode(
            fixture.read_text(encoding="ascii").strip(),
            validate=True,
        )
    )
    platform.add_volume(root, label="Classic")
    coordinator = DeviceCoordinator(Storage(platform))
    active = coordinator.select_device(coordinator.discover_devices().candidates[0].id)
    assert active.library.photos is not None
    photo = active.library.photos.photos[0]
    destination = tmp_path / "exports" / "Sunrise.jpg"
    destination.parent.mkdir()

    reference = coordinator.reference_for_photo(photo)
    assert reference is not None
    assert reference == HostPath(full_resolution)
    result = coordinator.copy_photo_to_host(
        photo,
        HostPath(destination),
        source=reference,
    )

    assert result.bytes_copied == len(b"original jpeg bytes")
    assert destination.read_bytes() == b"original jpeg bytes"
    coordinator.close()


def test_photo_export_decodes_an_exact_retained_ithmb_format(
    tmp_path: Path,
) -> None:
    platform = VirtualStoragePlatform()
    root = _ipod_volume(tmp_path / "nano", model_number="MA004")
    _install_photos(root)
    platform.add_volume(root, label="Nano")
    coordinator = DeviceCoordinator(Storage(platform))
    active = coordinator.select_device(coordinator.discover_devices().candidates[0].id)
    assert active.library.photos is not None
    photo = active.library.photos.photos[0]

    assert coordinator.reference_for_photo(photo) is None
    image = coordinator.image_for_photo_export(photo, format_id=1032)

    assert image is not None
    assert image.format_id == 1032
    assert (image.width, image.height) == (42, 37)
    assert coordinator.image_for_photo_export(photo, format_id=9999) is None
    coordinator.close()


def test_photo_export_does_not_substitute_after_its_original_path_disappears(
    tmp_path: Path,
) -> None:
    platform = VirtualStoragePlatform()
    root = _ipod_volume(tmp_path / "classic", model_number="MB565")
    photo_directory = root / "Photos"
    full_resolution = photo_directory / "Full Resolution" / "iOpenPod" / "Sunrise.jpg"
    full_resolution.parent.mkdir(parents=True)
    full_resolution.write_bytes(b"original jpeg bytes")
    fixture = (
        Path(__file__).parents[3]
        / "fixtures"
        / "PhotosDB"
        / "original-photo-library.b64"
    )
    photo_directory.joinpath("Photo Database").write_bytes(
        base64.b64decode(
            fixture.read_text(encoding="ascii").strip(),
            validate=True,
        )
    )
    platform.add_volume(root, label="Classic")
    coordinator = DeviceCoordinator(Storage(platform))
    active = coordinator.select_device(coordinator.discover_devices().candidates[0].id)
    assert active.library.photos is not None
    photo = active.library.photos.photos[0]
    reference = coordinator.reference_for_photo(photo)
    assert reference is not None
    full_resolution.unlink()
    destination = tmp_path / "Sunrise.jpg"

    with pytest.raises(DevicePhotoExportError, match="no longer readable"):
        coordinator.copy_photo_to_host(
            photo,
            HostPath(destination),
            source=reference,
        )

    assert not destination.exists()
    coordinator.close()


def test_playback_source_streams_track_bytes_until_active_ipod_changes(
    tmp_path: Path,
) -> None:
    platform = VirtualStoragePlatform()
    root = _ipod_volume(tmp_path / "classic", model_number="MB565")
    platform.add_volume(root, label="Classic")
    coordinator = DeviceCoordinator(Storage(platform))
    candidate = coordinator.discover_devices().candidates[0]
    active = coordinator.select_device(candidate.id)

    source = coordinator.open_playback_source(active.library.tracks[0])

    assert source.file_name == "track.m4a"
    assert source.byte_count == len(b"audio payload")
    assert source.read_at(2, 5) == b"dio p"
    assert source.read_at(source.byte_count, 8) == b""

    coordinator.deactivate()

    with pytest.raises(PlaybackSourceError, match="Active iPod changed"):
        source.read_at(0, 1)


def test_track_export_references_and_copies_through_the_active_session(
    tmp_path: Path,
) -> None:
    platform = VirtualStoragePlatform()
    root = _ipod_volume(tmp_path / "classic", model_number="MB565")
    platform.add_volume(root, label="Classic")
    coordinator = DeviceCoordinator(Storage(platform))
    candidate = coordinator.discover_devices().candidates[0]
    track = coordinator.select_device(candidate.id).library.tracks[0]

    reference = coordinator.reference_for_track(track)
    destination = tmp_path / "exported.m4a"
    result = coordinator.copy_track_to_host(track, HostPath(destination))

    assert Path(os.fspath(reference)) == (
        root / "iPod_Control" / "Music" / "F00" / "track.m4a"
    )
    assert destination.read_bytes() == b"audio payload"
    assert result.bytes_copied == len(b"audio payload")
    coordinator.close()


def test_playback_source_rejects_media_that_changes_after_opening(
    tmp_path: Path,
) -> None:
    platform = VirtualStoragePlatform()
    root = _ipod_volume(tmp_path / "classic", model_number="MB565")
    platform.add_volume(root, label="Classic")
    coordinator = DeviceCoordinator(Storage(platform))
    candidate = coordinator.discover_devices().candidates[0]
    active = coordinator.select_device(candidate.id)
    source = coordinator.open_playback_source(active.library.tracks[0])
    media = root / "iPod_Control" / "Music" / "F00" / "track.m4a"

    media.write_bytes(b"changed audio payload")

    with pytest.raises(PlaybackSourceError, match="selected Track changed"):
        source.read_at(0, 1)
    coordinator.close()


def test_application_uses_f1060_as_a_display_only_fallback(tmp_path: Path) -> None:
    platform = VirtualStoragePlatform()
    root = _ipod_volume(tmp_path / "mini", model_number="M9160")
    _install_artwork(root)
    platform.add_volume(root, label="Mini")
    coordinator = DeviceCoordinator(Storage(platform))
    candidate = coordinator.discover_devices().candidates[0]
    coordinator.select_device(candidate.id)

    result = coordinator.load_artwork(ArtworkRequest(artwork_id=64, target_px=44))

    assert result is not None
    assert result.format_id == 1060
    coordinator.close()


def test_ithmb_payload_cache_reuses_only_unchanged_source_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    platform = VirtualStoragePlatform()
    root = _ipod_volume(tmp_path / "classic", model_number="MB565")
    _install_artwork(root)
    platform.add_volume(root, label="Classic")
    range_reads = 0
    original_read = FilesystemSession.read_range_snapshot

    def record_range_read(
        session: FilesystemSession,
        path: DevicePath,
        *,
        offset: int,
        length: int,
    ) -> FileRangeSnapshot:
        nonlocal range_reads
        range_reads += 1
        return original_read(session, path, offset=offset, length=length)

    monkeypatch.setattr(
        FilesystemSession,
        "read_range_snapshot",
        record_range_read,
    )
    coordinator = DeviceCoordinator(Storage(platform))
    candidate = coordinator.discover_devices().candidates[0]
    coordinator.select_device(candidate.id)

    first = coordinator.load_artwork(ArtworkRequest(artwork_id=64, target_px=44))
    second = coordinator.load_artwork(ArtworkRequest(artwork_id=64, target_px=44))

    assert first is not None
    assert second == first
    assert range_reads == 1
    assert coordinator.cached_ithmb_byte_count == 56 * 56 * 2

    ithmb = root / "iPod_Control" / "Artwork" / "F1061_1.ithmb"
    ithmb.write_bytes(b"prefix" + (b"\xe0\x07" * (56 * 56)) + b"suffix")
    refreshed = coordinator.load_artwork(ArtworkRequest(artwork_id=64, target_px=44))

    assert refreshed is not None
    assert refreshed.rgb888[:3] == bytes((0, 255, 0))
    assert range_reads == 2
    coordinator.close()


def test_malformed_optional_artworkdb_keeps_the_library_usable(
    tmp_path: Path,
) -> None:
    platform = VirtualStoragePlatform()
    root = _ipod_volume(tmp_path / "classic", model_number="MB565")
    artwork_directory = root / "iPod_Control" / "Artwork"
    artwork_directory.mkdir(parents=True)
    (artwork_directory / "ArtworkDB").write_bytes(b"not an ArtworkDB")
    platform.add_volume(root, label="Classic")
    coordinator = DeviceCoordinator(Storage(platform))
    candidate = coordinator.discover_devices().candidates[0]

    active = coordinator.select_device(candidate.id)

    assert len(active.library.tracks) == 1
    assert active.artwork_database_fingerprint is None
    assert any(
        issue.code is DeviceCandidateIssueCode.ARTWORK_DATABASE_UNREADABLE
        for issue in active.candidate.issues
    )
    coordinator.close()


def test_malformed_optional_photosdb_keeps_the_library_usable(
    tmp_path: Path,
) -> None:
    platform = VirtualStoragePlatform()
    root = _ipod_volume(tmp_path / "classic", model_number="MB565")
    photo_directory = root / "Photos"
    photo_directory.mkdir()
    photo_directory.joinpath("Photo Database").write_bytes(b"not a PhotosDB")
    platform.add_volume(root, label="Classic")
    coordinator = DeviceCoordinator(Storage(platform))
    candidate = coordinator.discover_devices().candidates[0]

    active = coordinator.select_device(candidate.id)

    assert len(active.library.tracks) == 1
    assert active.library.photos is None
    assert active.photos_database_fingerprint is None
    assert any(
        issue.code is DeviceCandidateIssueCode.PHOTOS_DATABASE_UNREADABLE
        for issue in active.candidate.issues
    )
    coordinator.close()


def test_oversized_optional_artworkdb_keeps_the_library_usable(
    tmp_path: Path,
) -> None:
    platform = VirtualStoragePlatform()
    root = _ipod_volume(tmp_path / "classic", model_number="MB565")
    artwork_directory = root / "iPod_Control" / "Artwork"
    artwork_directory.mkdir(parents=True)
    with (artwork_directory / "ArtworkDB").open("wb") as artwork_database:
        artwork_database.truncate((128 * 1024 * 1024) + 1)
    platform.add_volume(root, label="Classic")
    coordinator = DeviceCoordinator(Storage(platform))
    candidate = coordinator.discover_devices().candidates[0]

    active = coordinator.select_device(candidate.id)

    assert len(active.library.tracks) == 1
    assert active.artwork_database_fingerprint is None
    assert any(
        issue.code is DeviceCandidateIssueCode.ARTWORK_DATABASE_UNREADABLE
        for issue in active.candidate.issues
    )
    coordinator.close()


def test_artwork_only_storage_failure_keeps_the_library_usable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    platform = VirtualStoragePlatform()
    root = _ipod_volume(tmp_path / "classic", model_number="MB565")
    _install_artwork(root)
    platform.add_volume(root, label="Classic")
    original_read_snapshot = FilesystemSession.read_snapshot

    def fail_artwork_read(
        session: FilesystemSession,
        path: DevicePath,
        *,
        max_bytes: int | None = None,
    ) -> FileSnapshot:
        if path == DevicePath("iPod_Control/Artwork/ArtworkDB"):
            raise StorageOperationError("ArtworkDB read failed")
        return original_read_snapshot(session, path, max_bytes=max_bytes)

    monkeypatch.setattr(FilesystemSession, "read_snapshot", fail_artwork_read)
    coordinator = DeviceCoordinator(Storage(platform))
    candidate = coordinator.discover_devices().candidates[0]

    active = coordinator.select_device(candidate.id)

    assert len(active.library.tracks) == 1
    assert active.artwork_database_fingerprint is None
    assert any(
        issue.code is DeviceCandidateIssueCode.ARTWORK_DATABASE_UNREADABLE
        for issue in active.candidate.issues
    )
    coordinator.close()


def test_invalidated_session_during_artwork_read_aborts_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    platform = VirtualStoragePlatform()
    root = _ipod_volume(tmp_path / "classic", model_number="MB565")
    _install_artwork(root)
    platform.add_volume(root, label="Classic")
    original_read_snapshot = FilesystemSession.read_snapshot

    def disconnect_during_artwork_read(
        session: FilesystemSession,
        path: DevicePath,
        *,
        max_bytes: int | None = None,
    ) -> FileSnapshot:
        if path == DevicePath("iPod_Control/Artwork/ArtworkDB"):
            session.invalidate("The test Volume disconnected")
            raise VolumeDisconnectedError("The test Volume disconnected")
        return original_read_snapshot(session, path, max_bytes=max_bytes)

    monkeypatch.setattr(
        FilesystemSession,
        "read_snapshot",
        disconnect_during_artwork_read,
    )
    coordinator = DeviceCoordinator(Storage(platform))
    candidate = coordinator.discover_devices().candidates[0]

    with pytest.raises(DeviceAccessError):
        coordinator.select_device(candidate.id)

    assert coordinator.active_ipod is None


def _ipod_volume(
    root: Path,
    *,
    model_number: str,
    database_name: str = "iTunesDB",
) -> Path:
    device_directory = root / "iPod_Control" / "Device"
    database_directory = root / "iPod_Control" / "iTunes"
    music_directory = root / "iPod_Control" / "Music" / "F00"
    device_directory.mkdir(parents=True)
    database_directory.mkdir(parents=True)
    music_directory.mkdir(parents=True)
    (device_directory / "SysInfo").write_text(
        f"ModelNumStr: {model_number}\n",
        encoding="utf-8",
    )
    (database_directory / database_name).write_bytes(_database_with_track())
    (music_directory / "track.m4a").write_bytes(b"audio payload")
    return root


def _install_nano5_hash72_metadata(
    root: Path,
    guid: bytes,
    *,
    hash_uuid: bytes | None = None,
) -> None:
    device = root / "iPod_Control" / "Device"
    (device / "SysInfo").write_text(
        f"ModelNumStr: MC027\nFirewireGuid: {guid.hex().upper()}\n",
        encoding="utf-8",
    )
    uuid = guid + bytes(12) if hash_uuid is None else hash_uuid
    (device / "HashInfo").write_bytes(
        b"HASHv0" + uuid + bytes(range(20, 32)) + bytes(range(16))
    )


def _install_sqlite_postprocess_metadata(
    root: Path,
    commands: tuple[str, ...],
) -> None:
    names = tuple(f"Command{index}" for index in range(len(commands)))
    definition = {
        "SQLCommands": dict(zip(names, commands, strict=True)),
        "UserVersionCommandSets": {"9": {"Commands": list(names)}},
    }
    (root / "iPod_Control" / "Device" / "SysInfoExtended").write_bytes(
        plistlib.dumps(
            {"com.apple.mobile.iTunes.SQLMusicLibraryPostProcessCommands": definition}
        )
    )


def _database_with_track() -> bytes:
    metadata = b"".join(
        (
            _string_mhod(1, "Blue Train"),
            _string_mhod(4, "John Coltrane"),
            _string_mhod(3, "Blue Train"),
            _string_mhod(5, "Jazz"),
            _string_mhod(2, ":iPod_Control:Music:F00:track.m4a"),
        )
    )
    fields = bytearray(0x9C - 12)
    struct.pack_into("<II", fields, 0, 5, 7)
    struct.pack_into("<I", fields, 0x24 - 12, 5_000_000)
    struct.pack_into("<I", fields, 0x28 - 12, 640_000)
    struct.pack_into("<I", fields, 0x2C - 12, 1)
    struct.pack_into("<I", fields, 0x34 - 12, 1957)
    struct.pack_into("<I", fields, 0x38 - 12, 256)
    struct.pack_into("<Q", fields, 0x70 - 12, 0x0102030405060708)
    track = _length_chunk(b"mhit", 0x9C, metadata, fields=bytes(fields))
    return _database(_dataset(1, _list_chunk(b"mhlt", track)))


def _install_artwork(root: Path) -> None:
    artwork_directory = root / "iPod_Control" / "Artwork"
    artwork_directory.mkdir(parents=True)
    image_name = new_artwork_chunk(
        MHNI_DEFINITION,
        MhniHeader(
            format_id=1061,
            ithmb_offset=6,
            image_size=56 * 56 * 2,
            image_height=56,
            image_width=56,
            image_size_2=56 * 56 * 2,
        ),
        children=(
            new_artwork_string_mhod(
                ArtworkMhodType.FILE_NAME,
                ":F1061_1.ithmb",
            ),
        ),
    )
    large_image_name = new_artwork_chunk(
        MHNI_DEFINITION,
        MhniHeader(
            format_id=1060,
            ithmb_offset=4,
            image_size=320 * 320 * 2,
            image_height=320,
            image_width=320,
            image_size_2=320 * 320 * 2,
        ),
        children=(
            new_artwork_string_mhod(
                ArtworkMhodType.FILE_NAME,
                ":F1060_1.ithmb",
            ),
        ),
    )
    image_item = new_artwork_chunk(
        MHII_DEFINITION,
        MhiiHeader(
            image_id=64,
            db_track_id_ref=0x0102030405060708,
            source_image_size=1_000,
        ),
        children=(
            new_container_mhod(ArtworkMhodType.THUMBNAIL_IMAGE, image_name),
            new_container_mhod(
                ArtworkMhodType.THUMBNAIL_IMAGE,
                large_image_name,
            ),
        ),
    )
    (artwork_directory / "ArtworkDB").write_bytes(
        write_ArtworkDB(
            new_ArtworkDB(
                next_mhii_id=65,
                unk_mhfd_0x10=2,
                image_items=(image_item,),
            )
        )
    )
    red_rgb565 = b"\x00\xf8" * (56 * 56)
    (artwork_directory / "F1061_1.ithmb").write_bytes(
        b"prefix" + red_rgb565 + b"suffix"
    )
    blue_rgb565 = b"\x1f\x00" * (320 * 320)
    (artwork_directory / "F1060_1.ithmb").write_bytes(b"head" + blue_rgb565 + b"tail")


def _install_photos(root: Path) -> None:
    photo_directory = root / "Photos"
    thumbnail_directory = photo_directory / "Thumbs"
    thumbnail_directory.mkdir(parents=True)
    image_name = new_photos_chunk(
        PHOTO_MHNI_DEFINITION,
        PhotoMhniHeader(
            format_id=1032,
            ithmb_offset=6,
            image_size=42 * 37 * 2,
            image_height=37,
            image_width=42,
            image_size_2=42 * 37 * 2,
        ),
        children=(
            new_photo_string_mhod(
                PhotosMhodType.FILE_NAME,
                ":Thumbs:F1032_1.ithmb",
            ),
        ),
    )
    image_item = new_photos_chunk(
        PHOTO_MHII_DEFINITION,
        PhotoMhiiHeader(image_id=100, source_image_size=1_000),
        children=(
            new_photo_container_mhod(PhotosMhodType.THUMBNAIL_IMAGE, image_name),
        ),
    )
    photo_directory.joinpath("Photo Database").write_bytes(
        write_PhotosDB(
            new_PhotosDB(
                next_mhii_id=101,
                unk_mhfd_0x10=6,
                image_items=(image_item,),
            )
        )
    )
    red_rgb565 = b"\x00\xf8" * (42 * 37)
    thumbnail_directory.joinpath("F1032_1.ithmb").write_bytes(
        b"prefix" + red_rgb565 + b"suffix"
    )


def _length_chunk(
    marker: bytes,
    header_length: int,
    body: bytes = b"",
    *,
    fields: bytes = b"",
) -> bytes:
    header = bytearray(header_length)
    struct.pack_into(
        "<4sII",
        header,
        0,
        marker,
        header_length,
        header_length + len(body),
    )
    header[12 : 12 + len(fields)] = fields
    return bytes(header) + body


def _list_chunk(marker: bytes, *children: bytes) -> bytes:
    header = bytearray(92)
    struct.pack_into("<4sII", header, 0, marker, len(header), len(children))
    return bytes(header) + b"".join(children)


def _dataset(dataset_type: int, child: bytes) -> bytes:
    return _length_chunk(
        b"mhsd",
        96,
        child,
        fields=struct.pack("<I", dataset_type),
    )


def _database(*datasets: bytes) -> bytes:
    fields = bytearray(12)
    struct.pack_into("<III", fields, 0, 1, 0x30, len(datasets))
    return _length_chunk(b"mhbd", 244, b"".join(datasets), fields=bytes(fields))


def _string_mhod(mhod_type: int, value: str) -> bytes:
    encoded = value.encode("utf-16-le")
    body = struct.pack("<IIII", 1, len(encoded), 1, 0) + encoded
    return _length_chunk(
        b"mhod",
        24,
        body,
        fields=struct.pack("<III", mhod_type, 0, 0),
    )
