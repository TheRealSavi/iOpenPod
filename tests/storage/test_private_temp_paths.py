"""Private Storage files remain readable when the system temp root is an alias."""

import os
import subprocess
import tempfile
from contextlib import ExitStack
from pathlib import Path

import pytest

from storage import DevicePath, HostPath, Storage, capture_host_file
from storage.device_capture import capture_device_file
from storage.host_input import LocalHostFile
from storage.media_processing import media_workspace
from storage.testing import VirtualStoragePlatform


def _directory_alias(alias: Path, destination: Path) -> None:
    try:
        alias.symlink_to(destination, target_is_directory=True)
    except OSError as error:
        if os.name != "nt":
            pytest.skip(f"Host cannot create a directory alias: {error}")
        # Junctions do not require the Windows symlink privilege and reproduce the
        # same reparse-parent restriction used by LocalHostFile.
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(alias), str(destination)],
            capture_output=True,
            check=False,
        )
        if result.returncode:
            pytest.skip("Host cannot create a temporary-directory junction")


@pytest.mark.parametrize("kind", ["capture", "local", "workspace", "device"])
def test_private_paths_are_canonical_under_aliased_temp_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    real_root = tmp_path / "real-temporary"
    real_root.mkdir()
    alias = tmp_path / "temporary-alias"
    _directory_alias(alias, real_root)
    monkeypatch.setattr(tempfile, "tempdir", str(alias))
    source = tmp_path / "source.bin"
    source.write_bytes(b"captured source")
    with ExitStack() as lifetime:
        if kind == "capture":
            path = lifetime.enter_context(
                capture_host_file(HostPath(source), checkpoint=lambda: None)
            ).snapshot
        elif kind == "local":
            path = lifetime.enter_context(
                LocalHostFile.observe(HostPath(source)).capture(checkpoint=lambda: None)
            )
        elif kind == "workspace":
            workspace = lifetime.enter_context(media_workspace(checkpoint=lambda: None))
            captured = workspace.capture(HostPath(source))
            with LocalHostFile.observe(captured.snapshot).open_read() as stream:
                assert stream.read() == b"captured source"
            path = workspace.transform_bytes(
                captured.snapshot, ".bin", lambda data: data
            ).snapshot
        else:
            device_root = tmp_path / "device"
            device_root.mkdir()
            (device_root / "source.bin").write_bytes(b"captured source")
            platform = VirtualStoragePlatform()
            platform.add_volume(device_root)
            storage = Storage(platform)
            session = lifetime.enter_context(
                storage.open_session(storage.discover().volumes[0])
            )
            path = lifetime.enter_context(
                capture_device_file(
                    session,
                    DevicePath("source.bin"),
                    checkpoint=lambda: None,
                    temporary_directory=HostPath(alias),
                )
            )
        with LocalHostFile.observe(path).open_read() as stream:
            assert stream.read() == b"captured source"
        assert Path(path).is_relative_to(real_root.resolve())
    assert not tuple(real_root.iterdir())
