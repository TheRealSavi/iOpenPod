"""Native presentation retains generic Storage identity and write safeguards."""

from pathlib import Path

import pytest

from storage import (
    AccessMode,
    ReadOnlyFilesystemError,
    Storage,
    StorageOperationError,
    VolumeDisconnectedError,
)
from storage.models import VolumeObservation
from storage.testing import VirtualStoragePlatform
from storage.volume_metadata import volume_label


@pytest.mark.parametrize(
    ("name", "filesystem", "expected"),
    [
        ("John's long iPod name", "fat32", "JOHN'S LONG"),
        ("Zoë / iPod", "vfat", "ZOE  IPOD"),
        ("音乐", "msdos", "VOLUME"),
        ("音" * 8, "ext4", "音" * 5),
        ("🎵" * 10, "exfat", "🎵" * 7),
        ("Zoë's iPod", "hfs", "Zoë's iPod"),
    ],
)
def test_labels_respect_filesystem_encoding_limits(
    name: str, filesystem: str, expected: str
) -> None:
    assert volume_label(name, filesystem) == expected


def test_native_metadata_requires_writable_current_connection(tmp_path: Path) -> None:
    platform = VirtualStoragePlatform()
    platform.add_volume(tmp_path)
    storage = Storage(platform)
    volume = storage.discover().volumes[0]
    with storage.open_session(volume) as session:
        with pytest.raises(ReadOnlyFilesystemError):
            session.set_volume_label("Changed")
        with pytest.raises(ReadOnlyFilesystemError):
            session.enable_volume_icon()
    with storage.open_session(volume, access=AccessMode.READ_WRITE) as session:
        platform.disconnect(tmp_path)
        with pytest.raises(VolumeDisconnectedError):
            session.set_volume_label("Changed")


def test_native_label_must_verify(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    platform = VirtualStoragePlatform()
    platform.add_volume(tmp_path)
    storage = Storage(platform)

    def wrong(_observation: VolumeObservation, _label: str) -> str:
        return "Wrong"

    monkeypatch.setattr(platform, "set_volume_label", wrong)
    with (
        storage.open_session(
            storage.discover().volumes[0], access=AccessMode.READ_WRITE
        ) as session,
        pytest.raises(StorageOperationError, match="did not verify"),
    ):
        session.set_volume_label("Correct")
