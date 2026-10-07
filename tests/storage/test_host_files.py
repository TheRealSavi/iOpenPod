"""Behavioral tests for ordinary Host application-file storage."""

from pathlib import Path

import pytest

from storage import FilePreconditionError, Storage, StorageOperationError
from storage.host_files import (
    AtomicHostFile,
    application_cache_file,
    application_config_file,
)
from storage.testing import VirtualStoragePlatform


class _LinuxHostPlatform(VirtualStoragePlatform):
    @property
    def name(self) -> str:
        return "linux"


def test_application_settings_file_uses_each_host_platform_convention(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    roaming = tmp_path / "roaming"
    xdg_config = tmp_path / "xdg-config"

    assert (
        application_config_file(
            "iOpenPod",
            "settings-v2.json",
            platform_name="windows",
            environment={"APPDATA": str(roaming)},
            home=home,
        )
        == roaming / "iOpenPod" / "settings-v2.json"
    )
    assert (
        application_config_file(
            "iOpenPod",
            "settings-v2.json",
            platform_name="macos",
            environment={},
            home=home,
        )
        == home / "Library" / "Application Support" / "iOpenPod" / "settings-v2.json"
    )
    assert (
        application_config_file(
            "iOpenPod",
            "settings-v2.json",
            platform_name="linux",
            environment={"XDG_CONFIG_HOME": str(xdg_config)},
            home=home,
        )
        == xdg_config / "iopenpod" / "settings-v2.json"
    )
    assert (
        application_config_file(
            "iOpenPod",
            "settings-v2.json",
            platform_name="linux",
            environment={},
            home=home,
        )
        == home / ".config" / "iopenpod" / "settings-v2.json"
    )
    assert (
        application_config_file(
            "iOpenPod",
            "settings-v2.json",
            platform_name="linux",
            environment={"XDG_CONFIG_HOME": "relative-config"},
            home=home,
        )
        == home / ".config" / "iopenpod" / "settings-v2.json"
    )


def test_application_cache_file_has_one_application_directory(
    tmp_path: Path,
) -> None:
    local = tmp_path / "local"
    xdg_cache = tmp_path / "xdg-cache"
    home = tmp_path / "home"

    assert (
        application_cache_file(
            "iOpenPod",
            "host-media-library-v1.json",
            platform_name="windows",
            environment={"LOCALAPPDATA": str(local)},
            home=home,
        )
        == local / "iOpenPod" / "cache" / "host-media-library-v1.json"
    )
    assert (
        application_cache_file(
            "iOpenPod",
            "host-media-library-v1.json",
            platform_name="macos",
            environment={},
            home=home,
        )
        == home / "Library" / "Caches" / "iOpenPod" / "host-media-library-v1.json"
    )
    assert (
        application_cache_file(
            "iOpenPod",
            "host-media-library-v1.json",
            platform_name="linux",
            environment={"XDG_CACHE_HOME": str(xdg_cache)},
            home=home,
        )
        == xdg_cache / "iopenpod" / "host-media-library-v1.json"
    )


def test_atomic_host_file_replaces_complete_bytes_and_creates_parent(
    tmp_path: Path,
) -> None:
    path = tmp_path / "configuration" / "settings-v2.json"
    host_file = AtomicHostFile(path)

    assert host_file.read_bytes() is None

    host_file.replace_bytes(b'{"generation":1}')
    host_file.replace_bytes(b'{"generation":2}')

    assert host_file.read_bytes() == b'{"generation":2}'
    assert tuple(path.parent.iterdir()) == (path,)


def test_host_file_revision_observes_replace_change_and_removal(tmp_path: Path) -> None:
    host_file = AtomicHostFile(tmp_path / "cache.json")
    assert host_file.revision() is None
    host_file.replace_bytes(b"first")
    original = host_file.revision()
    assert original is not None and original[2] == 5
    assert host_file.revision() == original
    host_file.replace_bytes(b"other")
    assert host_file.revision() != original
    host_file.path.unlink()
    assert host_file.revision() is None


def test_host_file_bounded_read_rejects_oversized_cache(tmp_path: Path) -> None:
    host_file = AtomicHostFile(tmp_path / "cache.json")
    assert host_file.read_bytes(max_bytes=4) is None
    host_file.replace_bytes(b"1234")
    assert host_file.read_bytes(max_bytes=4) == b"1234"
    with pytest.raises(StorageOperationError, match="limit"):
        host_file.read_bytes(max_bytes=3)
    with pytest.raises(ValueError, match="non-negative"):
        host_file.read_bytes(max_bytes=-1)


def test_atomic_host_file_can_create_without_replacing_existing_output(
    tmp_path: Path,
) -> None:
    path = tmp_path / "Road trip.m3u8"
    host_file = AtomicHostFile(path)

    assert not host_file.exists()
    host_file.create_bytes(b"#EXTM3U\n")

    assert host_file.exists()
    assert path.read_bytes() == b"#EXTM3U\n"
    with pytest.raises(FilePreconditionError):
        host_file.create_bytes(b"replacement")
    assert path.read_bytes() == b"#EXTM3U\n"
    assert not tuple(tmp_path.glob(".Road trip.m3u8.*.tmp"))


def test_storage_opens_application_config_files_without_exposing_host_branches(
    tmp_path: Path,
) -> None:
    storage = Storage(_LinuxHostPlatform())

    host_file = storage.host_config_file(
        "iOpenPod",
        "settings-v2.json",
        environment={},
        home=tmp_path,
    )

    assert host_file.path == tmp_path / ".config" / "iopenpod" / "settings-v2.json"


def test_storage_opens_application_cache_files_without_exposing_host_branches(
    tmp_path: Path,
) -> None:
    storage = Storage(_LinuxHostPlatform())

    host_file = storage.host_cache_file(
        "iOpenPod",
        "host-media-library-v1.json",
        environment={},
        home=tmp_path,
    )

    assert (
        host_file.path
        == tmp_path / ".cache" / "iopenpod" / "host-media-library-v1.json"
    )
