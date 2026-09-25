"""Device-file inspection copies have a Storage-owned, per-file lifetime."""

from pathlib import Path

import pytest

from storage import DevicePath, HostPath, Storage
from storage.device_capture import capture_device_file
from storage.testing import VirtualStoragePlatform


@pytest.mark.parametrize("failure", ("", "copy-cancelled", "consumer-failed"))
def test_device_capture_cleans_up_and_preserves_source(
    tmp_path: Path, failure: str
) -> None:
    root, staging = tmp_path / "device", tmp_path / "captures"
    root.mkdir()
    staging.mkdir()
    original = root / "SONG.MP3"
    original.write_bytes(b"audio source")
    platform = VirtualStoragePlatform()
    platform.add_volume(root)
    storage = Storage(platform)
    calls = 0

    def checkpoint() -> None:
        nonlocal calls
        calls += 1
        if failure == "copy-cancelled" and calls > 1:
            raise RuntimeError(failure)

    def consume() -> None:
        with (
            storage.open_session(storage.discover().volumes[0]) as session,
            capture_device_file(
                session,
                DevicePath("SONG.MP3"),
                checkpoint=checkpoint,
                temporary_directory=HostPath(staging),
            ) as captured,
        ):
            assert Path(captured).read_bytes() == b"audio source"
            assert captured.path.suffix == ".MP3"
            if failure == "consumer-failed":
                raise RuntimeError(failure)

    if failure:
        with pytest.raises(RuntimeError, match=failure):
            consume()
    else:
        consume()
    assert not tuple(staging.iterdir())
    assert original.read_bytes() == b"audio source"
