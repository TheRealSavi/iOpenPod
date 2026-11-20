"""SCSI lifecycle, exclusivity, and failure behavior at the Storage boundary."""

from collections.abc import Callable
from pathlib import Path

import pytest

from storage import (
    DeviceBusyError,
    MountedVolume,
    ScsiCommand,
    ScsiCommandError,
    ScsiIdentity,
    ScsiResponse,
    ScsiSessionError,
    Storage,
    UnsupportedStorageOperationError,
    VolumeIdentityChangedError,
)
from storage.models import VolumeObservation
from storage.testing import VirtualStoragePlatform

IDENTITY = ScsiIdentity("Vendor", "Disk", "serial-1")
WRITE = ScsiCommand(bytes.fromhex("c6910001000000000000"), data_out=b"x" * 4096)


class _Channel:
    def __init__(self) -> None:
        self.commands: list[ScsiCommand] = []
        self.close_count = 0
        self.result: ScsiResponse | Exception | None = None

    def execute(self, command: ScsiCommand) -> ScsiResponse:
        self.commands.append(command)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result or ScsiResponse(
            b"r" * command.data_in_length, command.transfer_length
        )

    def close(self) -> None:
        self.close_count += 1


class _Platform(VirtualStoragePlatform):
    def __init__(self) -> None:
        super().__init__()
        self.channel = _Channel()
        self.on_open: Callable[[], None] = lambda: None
        self.opens = 0

    def open_scsi_channel(
        self, observation: VolumeObservation, expected_identity: ScsiIdentity
    ) -> _Channel:
        assert observation.physical_device.id.value == "virtual-device-1"
        assert expected_identity == IDENTITY
        self.opens += 1
        self.on_open()
        return self.channel


def _setup(tmp_path: Path) -> tuple[_Platform, Storage, MountedVolume]:
    root = tmp_path / "volume"
    root.mkdir()
    platform = _Platform()
    platform.add_volume(root)
    portal = Storage(platform, writer_lock_directory=tmp_path / "locks")
    return platform, portal, portal.inspect(root)


def test_exclusive_session_closes_without_extra_commands_and_allows_reopening(
    tmp_path: Path,
) -> None:
    platform, portal, mounted = _setup(tmp_path)
    with portal.open_scsi_session(mounted, expected_identity=IDENTITY) as session:
        result = session.execute(WRITE)
        assert result.transferred == 4096
        with pytest.raises(DeviceBusyError):
            portal.open_session(mounted)
        with pytest.raises(DeviceBusyError):
            portal.open_scsi_session(mounted, expected_identity=IDENTITY)
        with pytest.raises(DeviceBusyError):
            portal.eject(mounted)
        with pytest.raises(DeviceBusyError):
            portal.probe_hardware(mounted)
    session.close()
    assert platform.channel.commands == [WRITE]
    assert platform.channel.close_count == 1
    with pytest.raises(ScsiSessionError):
        session.execute(WRITE)
    with portal.open_session(mounted) as ordinary:
        assert ordinary.is_active


def test_existing_filesystem_access_must_be_closed_first(tmp_path: Path) -> None:
    platform, portal, mounted = _setup(tmp_path)
    with portal.open_session(mounted), pytest.raises(DeviceBusyError):
        portal.open_scsi_session(mounted, expected_identity=IDENTITY)
    assert platform.opens == 0
    with portal.open_scsi_session(mounted, expected_identity=IDENTITY):
        assert platform.opens == 1


@pytest.mark.parametrize(
    "failure",
    [
        ScsiResponse(b"", 2048),
        ScsiResponse(b"", 4096, status=2, sense=b"\x70\0\x03"),
        OSError("device disconnected"),
        TimeoutError("uncertain timeout"),
    ],
)
def test_failed_command_invalidates_generation_and_never_retries_or_finalizes(
    tmp_path: Path, failure: ScsiResponse | Exception
) -> None:
    platform, portal, mounted = _setup(tmp_path)
    platform.channel.result = failure
    with portal.open_scsi_session(mounted, expected_identity=IDENTITY) as session:
        with pytest.raises((ScsiCommandError, OSError)):
            session.execute(WRITE)
        with pytest.raises(ScsiSessionError):
            session.execute(WRITE)
        assert not session.is_active
    assert platform.channel.commands == [WRITE]
    assert platform.channel.close_count == 1
    with pytest.raises(VolumeIdentityChangedError):
        portal.open_session(mounted)
    refreshed = portal.inspect(mounted.mount_point.path)
    assert refreshed.connection_generation != mounted.connection_generation
    with portal.open_session(refreshed):
        pass


def test_disconnection_invalidates_native_handle(tmp_path: Path) -> None:
    platform, portal, mounted = _setup(tmp_path)
    with portal.open_scsi_session(mounted, expected_identity=IDENTITY) as session:
        platform.disconnect(mounted.mount_point.path)
        portal.discover()
        with pytest.raises(ScsiSessionError):
            session.execute(WRITE)
    assert platform.channel.commands == []
    assert platform.channel.close_count == 1


def test_connection_expiring_during_open_closes_and_releases_reservation(
    tmp_path: Path,
) -> None:
    platform, portal, mounted = _setup(tmp_path)

    def disconnect() -> None:
        platform.disconnect(mounted.mount_point.path)
        portal.discover()

    platform.on_open = disconnect
    with pytest.raises(VolumeIdentityChangedError):
        portal.open_scsi_session(mounted, expected_identity=IDENTITY)
    assert platform.channel.close_count == 1
    platform.reconnect(mounted.mount_point.path)
    with portal.open_session(portal.inspect(mounted.mount_point.path)):
        pass


def test_native_lock_denial_releases_host_lease_and_portal_reservation(
    tmp_path: Path,
) -> None:
    platform, portal, mounted = _setup(tmp_path)

    def busy() -> None:
        raise DeviceBusyError("other application has an open file")

    platform.on_open = busy
    with pytest.raises(DeviceBusyError):
        portal.open_scsi_session(mounted, expected_identity=IDENTITY)
    platform.on_open = lambda: None
    with portal.open_scsi_session(mounted, expected_identity=IDENTITY):
        pass


def test_native_identity_mismatch_expires_the_old_filesystem_authority(
    tmp_path: Path,
) -> None:
    platform, portal, mounted = _setup(tmp_path)

    def changed_serial() -> None:
        raise VolumeIdentityChangedError("The native serial changed")

    platform.on_open = changed_serial
    with pytest.raises(VolumeIdentityChangedError):
        portal.open_scsi_session(mounted, expected_identity=IDENTITY)
    with pytest.raises(VolumeIdentityChangedError):
        portal.open_session(mounted)
    assert portal.inspect(mounted.mount_point.path).connection_generation != (
        mounted.connection_generation
    )


def test_reservation_blocks_filesystem_open_even_before_native_channel_returns(
    tmp_path: Path,
) -> None:
    platform, portal, mounted = _setup(tmp_path)

    def competing_open() -> None:
        with pytest.raises(DeviceBusyError):
            portal.open_session(mounted)

    platform.on_open = competing_open
    with portal.open_scsi_session(mounted, expected_identity=IDENTITY):
        pass


def test_shared_host_writer_lease_blocks_another_storage_portal(tmp_path: Path) -> None:
    platform, portal, mounted = _setup(tmp_path)
    other = Storage(platform, writer_lock_directory=tmp_path / "locks")
    other_mount = other.inspect(mounted.mount_point.path)
    with (
        portal.open_scsi_session(mounted, expected_identity=IDENTITY),
        pytest.raises(DeviceBusyError),
    ):
        other.open_scsi_session(other_mount, expected_identity=IDENTITY)
    assert platform.opens == 1


def test_unsupported_platform_fails_before_device_access(tmp_path: Path) -> None:
    platform = VirtualStoragePlatform()
    platform.add_volume(tmp_path)
    portal = Storage(platform)
    with pytest.raises(UnsupportedStorageOperationError):
        portal.open_scsi_session(portal.inspect(tmp_path), expected_identity=IDENTITY)


def test_short_response_requires_explicit_read_permission(tmp_path: Path) -> None:
    platform, portal, mounted = _setup(tmp_path)
    platform.channel.result = ScsiResponse(b"serial", 6)
    command = ScsiCommand(b"\x12\x01\x80\0\xff\0", data_in_length=255)
    with portal.open_scsi_session(mounted, expected_identity=IDENTITY) as session:
        permitted = ScsiCommand(command.cdb, data_in_length=255, allow_short_read=True)
        assert session.execute(permitted).data == b"serial"
        with pytest.raises(ScsiCommandError):
            session.execute(command)


@pytest.mark.parametrize(
    "command",
    [
        lambda: ScsiCommand(b"\0" * 17),
        lambda: ScsiCommand(b"\0" * 6, data_in_length=-1),
        lambda: ScsiCommand(b"\0" * 6, data_in_length=1024 * 1024 + 1),
        lambda: ScsiCommand(b"\0" * 6, data_out=b"a", data_in_length=1),
        lambda: ScsiCommand(b"\0" * 6, data_out=b"a", allow_short_read=True),
        lambda: ScsiCommand(b"\0" * 6, timeout_seconds=0),
        lambda: ScsiCommand(b"\0" * 6, timeout_seconds=61),
    ],
)
def test_invalid_command_never_reaches_a_device(
    command: Callable[[], ScsiCommand],
) -> None:
    with pytest.raises(ValueError):
        command()
