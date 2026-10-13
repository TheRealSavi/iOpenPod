"""Mounted-volume discovery and Filesystem Session lifecycle tests."""

from pathlib import Path

import pytest

from storage import (
    AccessMode,
    DevicePath,
    DiscoveryIssue,
    EjectError,
    HostPath,
    HostPathOnPhysicalDeviceError,
    MountInspectionError,
    NotVolumeRootError,
    PhysicalDeviceId,
    ReadOnlyFilesystemError,
    SessionInvalidatedError,
    Storage,
    VolumeDisconnectedError,
    VolumeIdentityChangedError,
)
from storage.platform.base import ObservationDiscoveryResult
from storage.testing import VirtualStoragePlatform


class _IndeterminateHostPlatform(VirtualStoragePlatform):
    def physical_device_id_for_path(self, path: Path) -> None:
        del path


class _ReplacingHostCheckPlatform(VirtualStoragePlatform):
    def __init__(self, root: Path) -> None:
        super().__init__()
        self._root = root

    def physical_device_id_for_path(self, path: Path) -> PhysicalDeviceId | None:
        result = super().physical_device_id_for_path(path)
        self.replace_identity(
            self._root,
            device_id="replacement-device",
            volume_id="replacement-volume",
        )
        return result


def _portal(
    tmp_path: Path,
    *,
    writable: bool = True,
) -> tuple[Path, VirtualStoragePlatform, Storage]:
    root = tmp_path / "volume"
    root.mkdir()
    platform = VirtualStoragePlatform()
    platform.add_volume(root, writable=writable)
    storage = Storage(platform, writer_lock_directory=tmp_path / "locks")
    return root, platform, storage


def test_discovery_distinguishes_identity_mount_and_connection_generation(
    tmp_path: Path,
) -> None:
    root, platform, storage = _portal(tmp_path)

    first = storage.discover().volumes[0]
    repeated = storage.discover().volumes[0]

    assert first.physical_device.id.value == "virtual-device-1"
    assert first.volume.id.value == "virtual-volume-1"
    assert first.mount_point.path == root
    assert first.connection_generation == repeated.connection_generation

    platform.disconnect(root)
    assert storage.discover().volumes == ()
    platform.reconnect(root)
    reconnected = storage.discover().volumes[0]

    assert reconnected.volume.id == first.volume.id
    assert reconnected.connection_generation != first.connection_generation
    with pytest.raises(VolumeIdentityChangedError):
        storage.open_session(first)


def test_inspection_accepts_only_the_actual_volume_root(tmp_path: Path) -> None:
    root, _, storage = _portal(tmp_path)
    child = root / "iPod_Control"
    child.mkdir()

    assert storage.inspect(root).mount_point.path == root
    with pytest.raises(NotVolumeRootError):
        storage.inspect(child)


@pytest.mark.parametrize("partial", (False, True))
def test_incomplete_discovery_reinspects_omitted_connections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, partial: bool
) -> None:
    root, platform, storage = _portal(tmp_path)
    mounted = storage.discover().volumes[0]
    issue = DiscoveryIssue("volumes", "temporary enumeration failure")
    if partial:
        other = tmp_path / "other-volume"
        other.mkdir()
        platform.add_volume(other, device_id="other-device", volume_id="other-volume")
    observed = platform.discover().observations[1:]

    def incomplete() -> ObservationDiscoveryResult:
        return ObservationDiscoveryResult(observed, (issue,))

    with (
        storage.open_session(mounted) as first,
        storage.open_session(mounted) as second,
    ):
        monkeypatch.setattr(platform, "discover", incomplete)
        result = storage.discover()
        assert result.issues == (issue,)
        assert len(result.volumes) == 1 + int(partial)
        retained = next(v for v in result.volumes if v.volume.id == mounted.volume.id)
        assert retained.connection_generation == mounted.connection_generation
        assert first.is_active and second.is_active
        assert not first.exists(DevicePath("absent"))
        # A later complete observation still uses the same live connection.
        monkeypatch.undo()
        assert storage.discover().volumes[0].connection_generation == (
            mounted.connection_generation
        )
        assert (
            storage.inspect(root).connection_generation == mounted.connection_generation
        )


@pytest.mark.parametrize(
    "change", ("disconnect", "remount", "replacement", "uninspectable")
)
def test_incomplete_discovery_never_preserves_an_unverified_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    root, platform, storage = _portal(tmp_path)
    mounted = storage.discover().volumes[0]

    def incomplete() -> ObservationDiscoveryResult:
        return ObservationDiscoveryResult(
            (), (DiscoveryIssue("volumes", "temporary enumeration failure"),)
        )

    def fail_reinspection(_retained: object) -> None:
        raise MountInspectionError("Cannot verify retained connection")

    with (
        storage.open_session(mounted) as first,
        storage.open_session(mounted) as second,
    ):
        if change == "disconnect":
            platform.disconnect(root)
        elif change == "remount":
            platform.reconnect(root)
        elif change == "replacement":
            platform.replace_identity(root, device_id="replacement", volume_id="new")
        else:
            monkeypatch.setattr(platform, "reinspect", fail_reinspection)
        monkeypatch.setattr(platform, "discover", incomplete)
        result = storage.discover()
        assert not first.is_active and not second.is_active
        with pytest.raises(VolumeIdentityChangedError):
            storage.open_session(mounted)
        if change in ("disconnect", "uninspectable"):
            assert result.volumes == ()
            assert len(result.issues) == 2
        else:
            assert len(result.volumes) == 1
            assert (
                result.volumes[0].connection_generation != mounted.connection_generation
            )


def test_partial_discovery_does_not_duplicate_a_replacement_at_the_same_mount(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, platform, storage = _portal(tmp_path)
    mounted = storage.discover().volumes[0]
    with storage.open_session(mounted) as session:
        platform.replace_identity(root, device_id="replacement", volume_id="new")
        observed = platform.discover().observations

        def partial() -> ObservationDiscoveryResult:
            return ObservationDiscoveryResult(
                observed, (DiscoveryIssue("other-volume", "unavailable"),)
            )

        monkeypatch.setattr(platform, "discover", partial)
        result = storage.discover()
        assert len(result.volumes) == 1
        assert result.volumes[0].volume.id.value == "new"
        assert result.volumes[0].connection_generation != mounted.connection_generation
        assert not session.is_active


def test_host_path_on_sibling_volume_of_same_physical_device_is_rejected(
    tmp_path: Path,
) -> None:
    device_root = tmp_path / "device-volume"
    sibling_root = tmp_path / "sibling-volume"
    device_root.mkdir()
    sibling_root.mkdir()
    platform = VirtualStoragePlatform()
    platform.add_volume(
        device_root,
        device_id="shared-physical-device",
        volume_id="device-volume",
    )
    platform.add_volume(
        sibling_root,
        device_id="shared-physical-device",
        volume_id="sibling-volume",
    )
    storage = Storage(platform)
    mounted = next(
        volume
        for volume in storage.discover().volumes
        if volume.volume.id.value == "device-volume"
    )
    backup_root = sibling_root / "not-created" / "backups"

    with pytest.raises(HostPathOnPhysicalDeviceError):
        storage.require_host_path_off_physical_device(
            HostPath(backup_root),
            mounted,
        )

    assert not backup_root.exists()


def test_host_path_on_another_physical_device_is_accepted_without_creation(
    tmp_path: Path,
) -> None:
    root, _, storage = _portal(tmp_path)
    mounted = storage.discover().volumes[0]
    backup_root = tmp_path / "host-backups" / "not-created"

    storage.require_host_path_off_physical_device(
        HostPath(backup_root),
        mounted,
    )

    assert root.exists()
    assert not backup_root.exists()


def test_host_path_alias_to_device_volume_is_rejected(tmp_path: Path) -> None:
    root, _, storage = _portal(tmp_path)
    mounted = storage.discover().volumes[0]
    alias = tmp_path / "device-alias"
    try:
        alias.symlink_to(root, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"directory links unavailable: {error}")

    with pytest.raises(HostPathOnPhysicalDeviceError):
        storage.require_host_path_off_physical_device(
            HostPath(alias / "not-created" / "backups"),
            mounted,
        )


def test_indeterminate_host_physical_device_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "volume"
    root.mkdir()
    platform = _IndeterminateHostPlatform()
    platform.add_volume(root)
    storage = Storage(platform)
    mounted = storage.discover().volumes[0]

    with pytest.raises(MountInspectionError, match="could not identify"):
        storage.require_host_path_off_physical_device(
            HostPath(tmp_path / "backups"),
            mounted,
        )


def test_connection_replacement_during_host_path_check_fails_closed(
    tmp_path: Path,
) -> None:
    root = tmp_path / "volume"
    root.mkdir()
    platform = _ReplacingHostCheckPlatform(root)
    platform.add_volume(root)
    storage = Storage(platform)
    mounted = storage.discover().volumes[0]

    with pytest.raises(VolumeIdentityChangedError, match="during Host path"):
        storage.require_host_path_off_physical_device(
            HostPath(tmp_path / "backups"),
            mounted,
        )


def test_read_write_authority_is_fixed_when_the_session_opens(tmp_path: Path) -> None:
    root, platform, storage = _portal(tmp_path, writable=False)
    mounted = storage.discover().volumes[0]

    read_only = storage.open_session(mounted)
    assert read_only.access is AccessMode.READ_ONLY
    with pytest.raises(ReadOnlyFilesystemError):
        storage.open_session(mounted, access=AccessMode.READ_WRITE)

    platform.set_writable(root, True)
    refreshed = storage.discover().volumes[0]
    read_write = storage.open_session(refreshed, access=AccessMode.READ_WRITE)
    assert read_write.access is AccessMode.READ_WRITE


def test_disconnect_invalidates_every_session_from_that_connection(
    tmp_path: Path,
) -> None:
    root, platform, storage = _portal(tmp_path)
    mounted = storage.discover().volumes[0]
    first = storage.open_session(mounted)
    second = storage.open_session(mounted)

    platform.disconnect(root)
    with pytest.raises(VolumeDisconnectedError):
        first.exists(DevicePath("iPod_Control"))
    with pytest.raises(SessionInvalidatedError):
        second.exists(DevicePath("iPod_Control"))

    assert not first.is_active
    assert not second.is_active


def test_identity_replacement_permanently_invalidates_the_session(
    tmp_path: Path,
) -> None:
    root, platform, storage = _portal(tmp_path)
    session = storage.open_session(storage.discover().volumes[0])

    platform.replace_identity(
        root,
        device_id="replacement-device",
        volume_id="replacement-volume",
    )

    with pytest.raises(VolumeIdentityChangedError):
        session.exists(DevicePath("iPod_Control"))
    with pytest.raises(SessionInvalidatedError):
        session.exists(DevicePath("iPod_Control"))


def test_remount_invalidates_sibling_sessions_without_further_inspection(
    tmp_path: Path,
) -> None:
    root, platform, storage = _portal(tmp_path)
    mounted = storage.discover().volumes[0]
    first = storage.open_session(mounted)
    second = storage.open_session(mounted)

    platform.reconnect(root)
    with pytest.raises(VolumeIdentityChangedError):
        first.exists(DevicePath("iPod_Control"))
    with pytest.raises(SessionInvalidatedError):
        second.exists(DevicePath("iPod_Control"))


def test_close_all_sessions_ends_access_without_changing_the_volume(
    tmp_path: Path,
) -> None:
    _, _, storage = _portal(tmp_path)
    mounted = storage.discover().volumes[0]
    first = storage.open_session(mounted)
    second = storage.open_session(mounted)

    storage.close_all_sessions()

    assert not first.is_active
    assert not second.is_active


def test_safe_eject_expires_generation_and_invalidates_all_sessions(
    tmp_path: Path,
) -> None:
    root, platform, storage = _portal(tmp_path)
    mounted = storage.discover().volumes[0]
    first = storage.open_session(mounted)
    second = storage.open_session(mounted)

    result = storage.eject(mounted)

    assert "safely ejected" in result.detail
    assert platform.eject_count(root) == 1
    assert storage.discover().volumes == ()
    assert not first.is_active
    assert not second.is_active
    with pytest.raises(VolumeIdentityChangedError):
        storage.open_session(mounted)


def test_refused_eject_retains_connection_for_graceful_recovery(
    tmp_path: Path,
) -> None:
    root, platform, storage = _portal(tmp_path)
    mounted = storage.discover().volumes[0]
    session = storage.open_session(mounted)
    platform.fail_eject(root, "another app has a file open")

    with pytest.raises(EjectError, match="another app") as raised:
        storage.eject(mounted)

    assert raised.value.volume_unmounted is False
    assert session.is_active
    replacement = storage.open_session(mounted)
    assert replacement.is_active


def test_partial_eject_expires_connection_after_unmount(tmp_path: Path) -> None:
    root, platform, storage = _portal(tmp_path)
    mounted = storage.discover().volumes[0]
    session = storage.open_session(mounted)
    platform.fail_eject(
        root,
        "unmounted but power-off was not confirmed",
        volume_unmounted=True,
    )

    with pytest.raises(EjectError) as raised:
        storage.eject(mounted)

    assert raised.value.volume_unmounted is True
    assert not session.is_active
    with pytest.raises(VolumeIdentityChangedError):
        storage.open_session(mounted)
