# pyright: strict, reportPrivateUsage=false
"""Native safe-eject policy tests independent of the current Host OS."""

import pytest

from storage import EjectError, UnsupportedStorageOperationError
from storage.platform.linux_eject import (
    LinuxDeviceEjector,
    UDisksError,
    UDisksTarget,
    _first_argument,
    _has_mount_points,
    _object_paths,
    _variant_map,
)
from storage.platform.macos_eject import MacOSDeviceEjector, _CommandResult
from storage.platform.windows_eject import (
    WindowsDeviceEjector,
    _EjectReply,
)


class _WindowsApi:
    def __init__(self, reply: _EjectReply, *, device_instance: int | None = 41) -> None:
        self.reply = reply
        self.device_instance = device_instance
        self.parents: list[int] = []
        self.requested: list[int] = []

    def device_instance_for_disk(self, disk_number: int) -> int | None:
        assert disk_number == 7
        return self.device_instance

    def parent_device_instance(self, device_instance: int) -> int:
        self.parents.append(device_instance)
        return 42

    def request_eject(self, device_instance: int) -> _EjectReply:
        self.requested.append(device_instance)
        return self.reply


class _UDisksClient:
    def __init__(self) -> None:
        self.target = UDisksTarget(
            drive="/drives/ipod",
            mounted_filesystems=("/blocks/ipod1", "/blocks/ipod2"),
        )
        self.unmounted: list[str] = []
        self.powered_off: list[str] = []
        self.unmount_error_at: str | None = None
        self.power_error: UDisksError | None = None

    def target_for_device(self, device_path: str) -> UDisksTarget:
        assert device_path == "/dev/sdb1"
        return self.target

    def unmount(self, filesystem: str) -> None:
        if filesystem == self.unmount_error_at:
            raise UDisksError(
                "org.freedesktop.UDisks2.Error.DeviceBusy",
                "device busy",
            )
        self.unmounted.append(filesystem)

    def power_off(self, drive: str) -> None:
        if self.power_error is not None:
            raise self.power_error
        self.powered_off.append(drive)


class _MalformedUDisksReply:
    def arguments(self) -> str:
        return "not an argument list"


class _ReadOnlyArrayArgument:
    def __init__(self, items: tuple[object, ...]) -> None:
        self._items = iter(items)
        self._current: object | None = None

    def beginArray(self) -> None:
        self._advance()

    def atEnd(self) -> bool:
        return self._current is None

    def asVariant(self) -> object:
        current = self._current
        assert current is not None
        self._advance()
        return current

    def _advance(self) -> None:
        self._current = next(self._items, None)


def test_windows_uses_configuration_manager_and_preserves_app_veto() -> None:
    api = _WindowsApi(_EjectReply(0x17, 3, "MusicApp.exe"))

    with pytest.raises(EjectError, match=r"MusicApp\.exe") as raised:
        WindowsDeviceEjector(api).eject(7)

    assert raised.value.volume_unmounted is False
    assert api.parents == [41]
    assert api.requested == [42]
    assert "not ejected" in str(raised.value)


def test_windows_fails_closed_without_exact_plug_and_play_match() -> None:
    api = _WindowsApi(_EjectReply(0, 0, ""), device_instance=None)

    with pytest.raises(UnsupportedStorageOperationError, match="taskbar"):
        WindowsDeviceEjector(api).eject(7)

    assert api.parents == []
    assert api.requested == []


def test_macos_unmounts_whole_disk_without_force_before_eject() -> None:
    commands: list[tuple[str, ...]] = []

    def run(command: tuple[str, ...], _timeout: int) -> _CommandResult:
        commands.append(command)
        return _CommandResult(0)

    result = MacOSDeviceEjector(run).eject("disk4")

    assert commands == [
        ("diskutil", "unmountDisk", "disk4"),
        ("diskutil", "eject", "disk4"),
    ]
    assert "safe to remove" in result.detail


def test_macos_reports_unmounted_partial_state_when_eject_fails() -> None:
    responses = iter((_CommandResult(0), _CommandResult(1, stderr="denied")))

    with pytest.raises(EjectError, match="Every iPod Volume") as raised:
        MacOSDeviceEjector(lambda _command, _timeout: next(responses)).eject("disk4")

    assert raised.value.volume_unmounted is True
    assert "Finder" in str(raised.value)


def test_linux_unmounts_all_drive_filesystems_then_powers_off() -> None:
    client = _UDisksClient()

    result = LinuxDeviceEjector(client).eject("/dev/sdb1")

    assert client.unmounted == ["/blocks/ipod1", "/blocks/ipod2"]
    assert client.powered_off == ["/drives/ipod"]
    assert "powered off" in result.detail


def test_linux_busy_before_first_unmount_is_retryable() -> None:
    client = _UDisksClient()
    client.unmount_error_at = "/blocks/ipod1"

    with pytest.raises(EjectError, match="files are still open") as raised:
        LinuxDeviceEjector(client).eject("/dev/sdb1")

    assert raised.value.volume_unmounted is False
    assert client.powered_off == []


def test_linux_poweroff_failure_reports_unmounted_partial_state() -> None:
    client = _UDisksClient()
    client.power_error = UDisksError(
        "org.freedesktop.UDisks2.Error.Failed",
        "USB deconfiguration failed",
    )

    with pytest.raises(EjectError, match="power-off") as raised:
        LinuxDeviceEjector(client).eject("/dev/sdb1")

    assert raised.value.volume_unmounted is True
    assert client.unmounted == ["/blocks/ipod1", "/blocks/ipod2"]


def test_linux_translates_malformed_dbus_replies() -> None:
    with pytest.raises(UDisksError, match="invalid response"):
        _first_argument(object())
    with pytest.raises(UDisksError, match="invalid response arguments"):
        _first_argument(_MalformedUDisksReply())


def test_linux_uses_qvariant_maps_for_udisks_arguments() -> None:
    values: dict[str, object] = {"path": "/dev/sdb1"}

    encoded = _variant_map(values)

    assert isinstance(encoded, dict)
    assert encoded == values
    assert encoded is not values


def test_linux_reads_compound_dbus_arrays_without_recursive_unwrapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from PySide6 import QtDBus

    monkeypatch.setattr(QtDBus, "QDBusArgument", _ReadOnlyArrayArgument)

    assert _object_paths(
        _ReadOnlyArrayArgument(("/blocks/ipod1", "/blocks/ipod2"))
    ) == ("/blocks/ipod1", "/blocks/ipod2")
    assert _has_mount_points(_ReadOnlyArrayArgument((b"/media/iPod\0",)))
    assert not _has_mount_points(_ReadOnlyArrayArgument(()))
