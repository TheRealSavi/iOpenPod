"""Installer recovery and adversarial archives, using real Host file operations."""

import hashlib
import io
import json
import sys
import tarfile
import zipfile
from collections.abc import Callable
from pathlib import Path
from threading import Event

import pytest
from tests.iOpenPod.app.test_release_metadata import signed_release

from iOpenPod.app.updates import helper
from iOpenPod.app.updates.installation import Installation
from iOpenPod.app.updates.portable import (
    Operation,
    PortableInstaller,
    unpack_linux,
    unpack_windows,
)
from iOpenPod.app.updates.processes import CandidateProcess
from iOpenPod.app.updates.releases import ReleaseAsset, verify_release
from iOpenPod.app.updates.transport import DownloadAsset, UpdateTransport, validate_url
from storage.host_installation import file_identity, move_owned_file
from storage.host_usage import HostInstallationLease


def asset(payload: bytes = b"new", target: str = "windows-x86_64") -> ReleaseAsset:
    return ReleaseAsset(
        target,
        "windows-onefile-v1" if target.startswith("windows") else "linux-managed-v1",
        "2.0.2",
        10,
        "a" * 64,
        hashlib.sha256(payload).hexdigest(),
        "10.0",
    )


def operation(root: Path) -> Operation:
    target = root / "iOpenPod.exe"
    target.write_bytes(b"old")
    directory = root / ".iopenpod-update-test"
    directory.mkdir()
    candidate = directory / "incoming.exe"
    candidate.write_bytes(b"new")
    for path in (
        root / "documents.txt",
        root / "previous.exe",
        root / "_internal" / "user.txt",
    ):
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"user-owned")
    return Operation(
        directory,
        root,
        target,
        "f" * 32,
        asset(),
        file_identity(target),
        file_identity(candidate),
        (1,),
    )


def assert_sentinels(root: Path) -> None:
    for path in (
        root / "documents.txt",
        root / "previous.exe",
        root / "_internal" / "user.txt",
    ):
        assert path.read_bytes() == b"user-owned"


@pytest.mark.skipif(sys.platform != "win32", reason="Native Windows helper transaction")
@pytest.mark.parametrize("healthy", [True, False])
def test_helper_commits_only_a_healthy_launch_and_rolls_back_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, healthy: bool
) -> None:
    op = operation(tmp_path)
    op.write("authorized", op.nonce)

    def read_operation(_directory: Path, _keys: tuple[str, ...]) -> Operation:
        return op

    monkeypatch.setattr(helper, "read_operation", read_operation)

    class Parent:
        def __init__(self, pid: int, executable: Path) -> None:
            pass

        def exited(self) -> bool:
            return True

        def close(self) -> None:
            pass

    class Child:
        stopped = False

        def __init__(self, probe: bool) -> None:
            self.probe = probe

        def poll(self) -> int | None:
            return 0 if self.probe else None if healthy else 1

        def wait(self, timeout: float | None = None) -> int:
            return 0

        def stop(self) -> None:
            self.stopped = True

        def release(self) -> None:
            pass

    children: list[Child] = []

    def launch(arguments: list[str]) -> CandidateProcess:
        child = Child("--smoke-test" in arguments)
        children.append(child)
        if not child.probe and healthy:
            assert file_identity(op.target) == op.incoming
            op.write("healthy", op.nonce)
        return child

    monkeypatch.setattr(helper, "ParentProcess", Parent)
    monkeypatch.setattr(helper, "candidate_process", launch)
    if healthy:
        helper.install(op.directory, ())
        assert op.matches("committed", op.nonce)
        assert op.target.read_bytes() == b"new"
        assert (op.directory / "previous.exe").read_bytes() == b"old"
        assert not children[-1].stopped
    else:
        with pytest.raises(RuntimeError, match="healthy"):
            helper.install(op.directory, ())
        assert not op.matches("committed", op.nonce)
        assert op.target.read_bytes() == b"old"
        assert children[-1].stopped
    assert_sentinels(tmp_path)


@pytest.mark.skipif(
    sys.platform != "win32", reason="Native Windows executable replacement"
)
@pytest.mark.parametrize("phase", ["before", "between", "after"])
def test_recovery_at_every_publication_boundary_retains_user_files(
    tmp_path: Path, phase: str
) -> None:
    op = operation(tmp_path)
    if phase in ("between", "after"):
        move_owned_file(op.target, op.directory / "previous.exe", op.previous)
    if phase == "after":
        move_owned_file(op.candidate, op.target, op.incoming)
    helper.restore_previous(op)
    helper.restore_previous(op)
    assert op.target.read_bytes() == b"old"
    assert_sentinels(tmp_path)


@pytest.mark.skipif(
    sys.platform != "win32", reason="Native Windows executable replacement"
)
def test_recovery_refuses_to_replace_a_user_file_created_in_the_gap(
    tmp_path: Path,
) -> None:
    op = operation(tmp_path)
    move_owned_file(op.target, op.directory / "previous.exe", op.previous)
    op.target.write_bytes(b"user-created replacement")
    with pytest.raises(ValueError, match="unrelated"):
        helper.restore_previous(op)
    assert op.target.read_bytes() == b"user-created replacement"
    assert (op.directory / "previous.exe").read_bytes() == b"old"
    assert_sentinels(tmp_path)


@pytest.mark.parametrize("changed_pointer", [False, True])
def test_linux_pointer_publication_and_recovery_preserve_every_version(
    tmp_path: Path, changed_pointer: bool
) -> None:
    old = tmp_path / "versions/2.0.1/iOpenPod"
    incoming = tmp_path / "versions/2.0.2/iOpenPod"
    for path, data in ((old, b"old"), (incoming, b"new")):
        path.parent.mkdir(parents=True)
        path.write_bytes(data)
        (path.parent / "user.txt").write_bytes(b"user-owned")
    directory = tmp_path / ".iopenpod-update-linux"
    directory.mkdir()
    pointer = tmp_path / "current.json"
    pointer.write_text(json.dumps({"version": "2.0.1"}))
    op = Operation(
        directory,
        tmp_path,
        old,
        "e" * 32,
        asset(target="linux-x86_64"),
        file_identity(old),
        file_identity(incoming),
        (1,),
    )
    # Stop at the publication boundary so recovery can exercise an interrupted
    # transaction; the public installer would continue through the health commit.
    helper._linux_install(op)  # pyright: ignore[reportPrivateUsage]
    assert json.loads(pointer.read_bytes()) == {"version": "2.0.2"}
    if changed_pointer:
        pointer.write_text(json.dumps({"version": "2.0.3"}))
        with pytest.raises(ValueError, match="changed installation state"):
            helper.restore_previous(op)
        assert json.loads(pointer.read_bytes()) == {"version": "2.0.3"}
    else:
        helper.restore_previous(op)
        helper.restore_previous(op)
        assert json.loads(pointer.read_bytes()) == {"version": "2.0.1"}
    assert old.read_bytes() == b"old" and incoming.read_bytes() == b"new"
    assert all(
        (path.parent / "user.txt").read_bytes() == b"user-owned"
        for path in (old, incoming)
    )


@pytest.mark.parametrize(
    "entries",
    [
        {"../iOpenPod.exe": b"new"},
        {"iOpenPod.exe": b"new", "notes.txt": b"user"},
        {"_internal/a.dll": b"new"},
        {"iOpenPod.exe/": b""},
    ],
)
def test_windows_archive_cannot_claim_anything_but_one_executable(
    tmp_path: Path, entries: dict[str, bytes]
) -> None:
    package = tmp_path / "update.zip"
    with zipfile.ZipFile(package, "w") as zipped:
        for name, data in entries.items():
            zipped.writestr(name, data)
    with pytest.raises(ValueError):
        unpack_windows(
            package, tmp_path / "incoming", hashlib.sha256(b"new").hexdigest()
        )
    assert not (tmp_path / "incoming").exists()


def test_zip_link_and_payload_hash_mismatch_are_rejected(tmp_path: Path) -> None:
    package = tmp_path / "update.zip"
    with zipfile.ZipFile(package, "w") as zipped:
        entry = zipfile.ZipInfo("iOpenPod.exe")
        entry.external_attr = 0o120777 << 16
        zipped.writestr(entry, "elsewhere")
    with pytest.raises(ValueError, match="unsafe"):
        unpack_windows(package, tmp_path / "linked", "b" * 64)
    with zipfile.ZipFile(package, "w") as zipped:
        zipped.writestr("iOpenPod.exe", b"wrong")
    with pytest.raises(ValueError, match="differs"):
        unpack_windows(package, tmp_path / "wrong", "b" * 64)


@pytest.mark.parametrize(
    "name,kind",
    [
        ("iOpenPod/versions/2.0.2/../../escape", tarfile.REGTYPE),
        ("iOpenPod/versions/2.0.2/linked", tarfile.SYMTYPE),
        ("iOpenPod/versions/2.0.2/linked", tarfile.LNKTYPE),
        ("iOpenPod/versions/2.0.2/device", tarfile.CHRTYPE),
        ("iOpenPod/versions/2.0.3/iOpenPod", tarfile.REGTYPE),
    ],
)
def test_linux_archives_cannot_escape_or_create_links(
    tmp_path: Path, name: str, kind: bytes
) -> None:
    package = tmp_path / "update.tar.gz"
    destination = tmp_path / "version"
    destination.mkdir()
    with tarfile.open(package, "w:gz") as tar:
        entry = tarfile.TarInfo(name)
        entry.type = kind
        entry.linkname = "../../user"
        tar.addfile(entry, io.BytesIO())
    with pytest.raises(ValueError):
        unpack_linux(package, destination, asset(target="linux-x86_64"))
    assert not (tmp_path / "escape").exists()


def test_shared_application_leases_exclude_installer_and_new_launches(
    tmp_path: Path,
) -> None:
    target = tmp_path / "application"
    with (
        HostInstallationLease(target),
        HostInstallationLease(target),
        pytest.raises(OSError),
        HostInstallationLease(target, exclusive=True),
    ):
        pytest.fail("Maintenance acquired a live installation")
    with (
        HostInstallationLease(target, exclusive=True),
        pytest.raises(OSError),
        HostInstallationLease(target),
    ):
        pytest.fail("A launch raced maintenance")
    with HostInstallationLease(target):
        pass


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/file",
        "https://github.com@evil.example/file",
        "https://evil.example/file",
        "https://github.com:8443/file",
        "file:///tmp/update",
    ],
)
def test_untrusted_transport_origins_are_rejected(url: str) -> None:
    with pytest.raises(ValueError):
        validate_url(url)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows portable staging contract")
def test_authenticated_stage_does_not_modify_the_running_application(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "iOpenPod.exe"
    executable.write_bytes(b"old")
    resources = tmp_path / "runtime"
    (resources / "updates").mkdir(parents=True)
    (resources / "updates/iOpenPod-update.exe").write_bytes(b"independent helper")
    package = io.BytesIO()
    with zipfile.ZipFile(package, "w") as zipped:
        zipped.writestr("iOpenPod.exe", b"new")
    payload = package.getvalue()
    data, keys = signed_release(
        assets=[
            {
                "target": "windows-x86_64",
                "layout": "windows-onefile-v1",
                "updater_protocol": 1,
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "executable_sha256": hashlib.sha256(b"new").hexdigest(),
                "minimum_os": "10.0",
            }
        ]
    )

    class Transport(UpdateTransport):
        def download(
            self,
            asset: DownloadAsset,
            path: Path,
            cancel: Event,
            progress: Callable[[float], None],
        ) -> None:
            path.write_bytes(payload)
            progress(1.0)

    installer = PortableInstaller(
        Installation(
            "2.0.1", "windows-x86_64", "windows-onefile-v1", keys, executable, resources
        )
    )
    installer.stage(
        verify_release(data, keys).asset("windows-x86_64"),
        data,
        Transport(),
        Event(),
        lambda _p: None,
    )
    assert executable.read_bytes() == b"old"
    directories = list(tmp_path.glob(".iopenpod-update-*"))
    assert len(directories) == 1
    assert (directories[0] / "incoming.exe").read_bytes() == b"new"
    assert not (directories[0] / "authorized").exists()
    record = json.loads((directories[0] / "operation.json").read_bytes())
    installer.close()
    assert (directories[0] / "canceled").read_text() == record["nonce"]
    assert executable.read_bytes() == b"old"
