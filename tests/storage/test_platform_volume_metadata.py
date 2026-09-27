# pyright: strict, reportPrivateUsage=false
"""Native label and Finder flag contracts without writing physical devices."""

import os
import struct
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from storage.errors import StorageOperationError
from storage.models import VolumeObservation
from storage.platform import linux_eject
from storage.platform.linux_eject import UDisksError, _QtUDisksClient
from storage.platform.macos_volume_metadata import _AttrList, _VolumeAttributes
from storage.platform.windows import WindowsPlatformAdapter
from storage.testing import VirtualStoragePlatform


class _Reply:
    def __init__(self, value: object) -> None:
        self.value = value

    def arguments(self) -> list[object]:
        return [self.value]


class _LabelClient(_QtUDisksClient):
    def __init__(self, blocks: tuple[str, ...] = ("/blocks/selected",)) -> None:
        self.blocks = blocks
        self.label = "Old"
        self.calls: list[tuple[str, str, tuple[object, ...]]] = []

    def _property(self, path: str, interface: str, name: str) -> object:
        assert path == "/blocks/selected" and name == "IdLabel"
        return self.label

    def _call(
        self,
        path: str,
        interface: str,
        method: str,
        *arguments: object,
        timeout_ms: int = 30_000,
    ) -> object:
        self.calls.append((path, method, arguments))
        if method == "ResolveDevice":
            assert arguments == ({"path": "/dev/sdb1"}, {})
            return _Reply(list(self.blocks))
        assert method == "SetLabel" and path == "/blocks/selected"
        assert arguments == ("Name", {"auth.no_user_interaction": True})
        self.label = "Name"
        return _Reply(None)


def test_linux_resolves_one_block_and_never_unmounts_or_requests_authentication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _LabelClient()
    monkeypatch.setattr(linux_eject, "_QtUDisksClient", lambda: client)
    assert linux_eject.set_volume_label("/dev/sdb1", "Name") == "Name"
    assert linux_eject.set_volume_label("/dev/sdb1", "Name") == "Name"
    assert [method for _, method, _ in client.calls] == [
        "ResolveDevice",
        "SetLabel",
        "ResolveDevice",
    ]


@pytest.mark.parametrize("blocks", [(), ("/blocks/a", "/blocks/b")])
def test_linux_rejects_ambiguous_native_targets(
    blocks: tuple[str, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _LabelClient(blocks)
    monkeypatch.setattr(linux_eject, "_QtUDisksClient", lambda: client)
    with pytest.raises(StorageOperationError, match="one exact block device") as raised:
        linux_eject.set_volume_label("/dev/sdb1", "Name")
    assert isinstance(raised.value.__cause__, UDisksError)
    assert all(method != "SetLabel" for _, method, _ in client.calls)


class _Attributes(_VolumeAttributes):
    def __init__(self, root: Path) -> None:
        self._root = root
        self.label = "Old"
        self.finder = bytes(range(32))
        self.writes: list[bytes] = []

    def read(self, fd: int, attributes: _AttrList) -> bytes:
        assert fd == 123
        if attributes.volattr:
            assert attributes.volattr == 0x80002000
            encoded = self.label.encode() + b"\0"
            return struct.pack("=iI", 8, len(encoded)) + encoded
        assert attributes.commonattr == 0x4000
        return self.finder

    def write(self, fd: int, attributes: _AttrList, data: bytes) -> None:
        assert fd == 123
        self.writes.append(data)
        if attributes.volattr:
            assert struct.unpack_from("=iI", data) == (8, len(data) - 8)
            self.label = data[8:-1].decode()
        else:
            self.finder = data


def test_macos_preserves_finder_flags_and_sets_unicode_label_idempotently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attributes = _Attributes(tmp_path)
    original = attributes.finder
    opened: list[int] = []
    closed: list[int] = []

    def open_root(path: Path, flags: int) -> int:
        assert path == tmp_path
        opened.append(flags)
        return 123

    monkeypatch.setattr(os, "open", open_root)
    monkeypatch.setattr(os, "close", closed.append)
    attributes.enable_icon()
    attributes.enable_icon()
    assert attributes.finder[:8] == original[:8]
    assert attributes.finder[8] == original[8] | 4
    assert attributes.finder[9:] == original[9:]
    assert attributes.set_label("Zoë's iPod") == "Zoë's iPod"
    assert attributes.set_label("Zoë's iPod") == "Zoë's iPod"
    assert len(attributes.writes) == 2
    assert len(opened) == len(closed) == 4
    assert all(flags & getattr(os, "O_NOFOLLOW", 0x100) for flags in opened)


class _SetLabel:
    def __init__(self) -> None:
        self.argtypes: list[object] = []
        self.restype: object = None
        self.calls: list[tuple[str, str]] = []

    def __call__(self, root: str, label: str) -> bool:
        self.calls.append((root, label))
        return True


def test_windows_targets_retained_volume_guid_and_verifies_label(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    platform = VirtualStoragePlatform()
    observed = platform.add_volume(tmp_path)
    root = "\\\\?\\Volume{12345678-1234-1234-1234-123456789abc}\\"
    observed = replace(observed, mount_instance="windows-volume:" + root)
    native = WindowsPlatformAdapter.__new__(WindowsPlatformAdapter)
    function = _SetLabel()
    native._kernel32 = SimpleNamespace(SetVolumeLabelW=function)

    def inspect(_path: Path) -> VolumeObservation:
        return replace(observed, volume=replace(observed.volume, label="Name"))

    monkeypatch.setattr(native, "inspect", inspect)
    assert native.set_volume_label(observed, "Name") == "Name"
    assert function.calls == [(root, "Name")]
