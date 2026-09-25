"""Windows Physical Device correlation through resolved Volume handles."""

from pathlib import Path

from storage.platform.windows import (
    _FILE_DEVICE_DISK,  # pyright: ignore[reportPrivateUsage]
    _StorageDeviceIdentity,  # pyright: ignore[reportPrivateUsage]
    _WindowsPhysicalDeviceLookup,  # pyright: ignore[reportPrivateUsage]
)


class _FakeWindowsVolumeApi:
    def __init__(
        self,
        *,
        path: Path,
        final_path: str | None,
        volume_guid_path: str,
        device: _StorageDeviceIdentity | None,
    ) -> None:
        self._path = path
        self._final_path = final_path
        self._volume_guid_path = volume_guid_path
        self._device = device
        self.open_handles: set[int] = set()

    def open_path(self, path: Path) -> int | None:
        if path != self._path:
            return None
        self.open_handles.add(11)
        return 11

    def final_volume_guid_path(self, handle: int) -> str | None:
        assert handle == 11
        return self._final_path

    def open_volume(self, volume_guid_path: str) -> int | None:
        if volume_guid_path != self._volume_guid_path:
            return None
        self.open_handles.add(22)
        return 22

    def storage_device(self, handle: int) -> _StorageDeviceIdentity | None:
        assert handle == 22
        return self._device

    def close(self, handle: int) -> None:
        self.open_handles.remove(handle)


def test_windows_drive_path_uses_its_resolved_volume_handle() -> None:
    path = Path("E:\\")
    volume = "\\\\?\\Volume{12345678-1234-1234-1234-123456789abc}"
    api = _FakeWindowsVolumeApi(
        path=path,
        final_path=f"{volume}\\",
        volume_guid_path=volume,
        device=_StorageDeviceIdentity(_FILE_DEVICE_DISK, 7),
    )

    identity = _WindowsPhysicalDeviceLookup(api).for_path(path)

    assert identity is not None
    assert identity.value == "windows:disk-7"
    assert api.open_handles == set()


def test_windows_directory_mount_uses_the_containing_volume() -> None:
    path = Path("C:\\Mounted\\iPod backups")
    volume = "\\\\?\\Volume{12345678-1234-1234-1234-123456789abc}"
    api = _FakeWindowsVolumeApi(
        path=path,
        final_path=f"{volume}\\Archives",
        volume_guid_path=volume,
        device=_StorageDeviceIdentity(_FILE_DEVICE_DISK, 4),
    )

    identity = _WindowsPhysicalDeviceLookup(api).for_path(path)

    assert identity is not None
    assert identity.value == "windows:disk-4"
    assert api.open_handles == set()


def test_windows_lookup_rejects_a_non_volume_final_path() -> None:
    path = Path("E:\\")
    api = _FakeWindowsVolumeApi(
        path=path,
        final_path="E:\\",
        volume_guid_path="unused",
        device=None,
    )

    assert _WindowsPhysicalDeviceLookup(api).for_path(path) is None
    assert api.open_handles == set()


def test_windows_lookup_rejects_a_non_disk_volume() -> None:
    path = Path("E:\\")
    volume = "\\\\?\\Volume{12345678-1234-1234-1234-123456789abc}"
    api = _FakeWindowsVolumeApi(
        path=path,
        final_path=f"{volume}\\",
        volume_guid_path=volume,
        device=_StorageDeviceIdentity(0x12, 7),
    )

    assert _WindowsPhysicalDeviceLookup(api).for_path(path) is None
    assert api.open_handles == set()


def test_windows_lookup_closes_the_path_handle_when_resolution_fails() -> None:
    path = Path("E:\\")
    api = _FakeWindowsVolumeApi(
        path=path,
        final_path=None,
        volume_guid_path="unused",
        device=None,
    )

    assert _WindowsPhysicalDeviceLookup(api).for_path(path) is None
    assert api.open_handles == set()
