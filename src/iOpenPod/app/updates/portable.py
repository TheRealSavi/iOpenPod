"""Staging and handoff; this process never replaces a running application."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import stat
import sys
import tarfile
import time
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, cast

from storage.host_installation import (
    HostFileIdentity,
    durable_write,
    file_identity,
    pin_installation,
    private_directory,
    require_plain_path,
)

from .backend import UpdateOutcome, UpdateResult
from .processes import independent_process
from .releases import (
    MAX_ARCHIVE,
    ReleaseAsset,
    integer_field,
    read_json,
    text_field,
    verify_release,
    version_tuple,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from subprocess import Popen
    from threading import Event

    from .installation import Installation
    from .transport import UpdateTransport


def installation_root(installation: Installation) -> Path:
    executable = require_plain_path(installation.executable)
    if installation.layout == "windows-onefile-v1":
        if executable.name != "iOpenPod.exe":
            raise ValueError(
                "Restore the filename iOpenPod.exe before using automatic updates"
            )
        return executable.parent
    if installation.layout != "linux-managed-v1":
        raise ValueError("Unsupported portable installation layout")
    root = executable.parent.parent.parent
    if executable != root / "versions" / installation.version / "iOpenPod":
        raise ValueError(
            "Download and extract the new managed Linux package to enable updates"
        )
    marker = read_json((root / "installation.json").read_bytes())
    if marker != {"product": "iOpenPod", "layout": "linux-managed-v1"}:
        raise ValueError("This directory is not an iOpenPod managed installation")
    return require_plain_path(root)


def lease_target(installation: Installation) -> Path:
    return (
        installation.executable
        if installation.target.startswith("windows")
        else installation_root(installation)
    )


def _copy(source: Path, target: Path) -> None:
    with source.open("rb") as reader, target.open("xb") as writer:
        shutil.copyfileobj(reader, writer, 256 * 1024)
        writer.flush()
        os.fsync(writer.fileno())


def unpack_windows(archive: Path, destination: Path, expected: str) -> None:
    with zipfile.ZipFile(archive) as package:
        entries = package.infolist()
        if len(entries) != 1 or entries[0].filename != "iOpenPod.exe":
            raise ValueError("Windows update must contain exactly iOpenPod.exe")
        entry = entries[0]
        mode = entry.external_attr >> 16
        if (
            entry.is_dir()
            or entry.flag_bits & 1
            or stat.S_IFMT(mode) not in (0, stat.S_IFREG)
            or not 0 < entry.file_size <= MAX_ARCHIVE
        ):
            raise ValueError("Windows update contains an unsafe executable entry")
        with package.open(entry) as reader, destination.open("xb") as writer:
            shutil.copyfileobj(reader, writer, 256 * 1024)
            writer.flush()
            os.fsync(writer.fileno())
    if file_identity(destination).sha256 != expected:
        raise ValueError("Extracted executable differs from the signed release")


def unpack_linux(archive: Path, destination: Path, asset: ReleaseAsset) -> None:
    """Extract only an immutable version into a new, private directory.

    Release packaging dereferences library symlinks. Updates reject all links,
    special files, duplicate names, traversal and writes to the stable launcher.
    """
    prefix = f"iOpenPod/versions/{asset.version}"
    seen: set[str] = set()
    total = 0
    with tarfile.open(archive, "r:gz") as package:
        for entry in package:
            name = entry.name.rstrip("/")
            parts = PurePosixPath(name).parts
            if (
                name in seen
                or "\\" in name
                or name.startswith("/")
                or any(part in (".", "..") for part in parts)
            ):
                raise ValueError("Unsafe or duplicate Linux archive path")
            seen.add(name)
            if (
                len(seen) > 30_000
                or not (entry.isdir() or entry.isfile())
                or entry.mode & 0o7000
            ):
                raise ValueError("Unsupported Linux archive entry")
            total += entry.size
            if total > 8 * 1024**3:
                raise ValueError("Linux update exceeds its extracted size limit")
            if name in ("iOpenPod", "iOpenPod/versions", prefix):
                if not entry.isdir():
                    raise ValueError("Linux archive parent must be a directory")
                continue
            if name in (
                "iOpenPod/iOpenPod",
                "iOpenPod/current.json",
                "iOpenPod/installation.json",
            ):
                if not entry.isfile():
                    raise ValueError("Invalid stable Linux launcher entry")
                continue
            if not name.startswith(prefix + "/"):
                raise ValueError("Linux archive contains an unexpected layout")
            relative = PurePosixPath(name[len(prefix) + 1 :])
            target = destination.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            if entry.isdir():
                target.mkdir(exist_ok=True)
                continue
            reader = package.extractfile(entry)
            if reader is None:
                raise ValueError("Missing Linux archive contents")
            with reader, target.open("xb") as writer:
                shutil.copyfileobj(reader, writer, 256 * 1024)
                writer.flush()
                os.fsync(writer.fileno())
            target.chmod(0o755 if entry.mode & 0o111 else 0o644)
    if file_identity(destination / "iOpenPod").sha256 != asset.executable_sha256:
        raise ValueError("Linux executable differs from the signed release")


def verify_linux_runtime(archive: Path, destination: Path, asset: ReleaseAsset) -> None:
    """Recheck every staged dependency against the signed archive before execution."""
    identity = file_identity(archive)
    if identity.size != asset.size or identity.sha256 != asset.sha256:
        raise ValueError("Retained Linux archive differs from the signed release")
    expected: set[Path] = set()
    prefix = f"iOpenPod/versions/{asset.version}/"
    with tarfile.open(archive, "r:gz") as package:
        for entry in package:
            if not entry.name.startswith(prefix) or not entry.isfile():
                continue
            relative = PurePosixPath(entry.name[len(prefix) :])
            if (
                any(part in (".", "..") for part in relative.parts)
                or "\\" in entry.name
            ):
                raise ValueError("Unsafe Linux runtime path")
            path = require_plain_path(destination.joinpath(*relative.parts))
            content = package.extractfile(entry)
            if content is None:
                raise ValueError("Missing Linux runtime content")
            with content:
                digest = hashlib.sha256()
                while chunk := content.read(256 * 1024):
                    digest.update(chunk)
            actual = file_identity(path)
            if actual.size != entry.size or actual.sha256 != digest.hexdigest():
                raise ValueError("A staged Linux dependency changed after verification")
            expected.add(path)
    actual_paths: set[Path] = set()
    for parent, directories, files in os.walk(destination, followlinks=False):
        for name in directories:
            require_plain_path(Path(parent) / name)
        actual_paths.update(require_plain_path(Path(parent) / name) for name in files)
    if actual_paths != expected or destination / "iOpenPod" not in expected:
        raise ValueError("The staged Linux runtime contains unexpected files")


@dataclass(frozen=True, slots=True)
class Operation:
    directory: Path
    root: Path
    target: Path
    nonce: str
    asset: ReleaseAsset
    previous: HostFileIdentity
    incoming: HostFileIdentity
    parents: tuple[int, ...]

    @property
    def candidate(self) -> Path:
        return (
            self.directory / "incoming.exe"
            if self.asset.target.startswith("windows")
            else self.root / "versions" / self.asset.version / "iOpenPod"
        )

    def write(self, name: str, value: str) -> None:
        durable_write(self.directory / name, value.encode())

    def matches(self, name: str, value: str) -> bool:
        path = require_plain_path(self.directory / name)
        return (
            path.is_file() and path.stat().st_size < 1024 and path.read_text() == value
        )


def read_operation(
    directory: Path, public_keys: tuple[str, ...], *, recovery: bool = False
) -> Operation:
    require_plain_path(directory)
    value = read_json(require_plain_path(directory / "operation.json").read_bytes())
    nonce = text_field(value, "nonce")
    if (
        len(nonce) != 32
        or any(char not in "0123456789abcdef" for char in nonce)
        or not directory.name.startswith(".iopenpod-update-")
    ):
        raise ValueError("Invalid update operation identity")
    root = directory.parent
    root_stat = root.stat()
    if (
        value.get("root_device") != root_stat.st_dev
        or value.get("root_inode") != root_stat.st_ino
    ):
        raise ValueError("Installation directory was replaced")
    directory_stat = directory.stat()
    if value.get("directory_inode") != directory_stat.st_ino:
        raise ValueError("Update operation directory was replaced")
    metadata = require_plain_path(directory / "release.json").read_bytes()
    timestamp = None
    if recovery:
        # Recovery restores only the recorded previous file. Historical signatures
        # remain usable offline; this never authorizes a new installation.
        envelope = read_json(metadata)
        payload = read_json(base64.b64decode(str(envelope["payload"]), validate=True))
        timestamp = datetime.fromisoformat(text_field(payload, "issued"))
    release = verify_release(metadata, public_keys, now=timestamp)
    asset = release.asset(text_field(value, "target"))
    if asset.target.startswith("windows") != (sys.platform == "win32"):
        raise ValueError("Update operation targets a different operating system")
    old_version = text_field(value, "previous_version")
    if version_tuple(asset.version) <= version_tuple(old_version):
        raise ValueError("An application update must advance the installed version")
    target = (
        root / "iOpenPod.exe"
        if asset.target.startswith("windows")
        else root / "versions" / old_version / "iOpenPod"
    )
    raw_parents = value.get("parents")
    if not isinstance(raw_parents, list):
        raise ValueError("Invalid update process ownership")
    parents = cast("list[object]", raw_parents)
    if not 1 <= len(parents) <= 2:
        raise ValueError("Invalid update process ownership")
    pids = tuple(integer_field({"pid": pid}, "pid", 2**32 - 1) for pid in parents)
    return Operation(
        directory,
        root,
        target,
        nonce,
        asset,
        HostFileIdentity.from_json(value.get("previous")),
        HostFileIdentity.from_json(value.get("incoming")),
        pids,
    )


class PortableInstaller:
    def __init__(self, installation: Installation) -> None:
        self.installation = installation
        self.root = installation_root(installation)
        self._operation: Operation | None = None
        self._helper_identity: HostFileIdentity | None = None
        self._helper: Popen[bytes] | None = None
        self._started = 0.0
        self._transferred = False
        self._ready_reported = False

    def stage(
        self,
        asset: ReleaseAsset,
        metadata: bytes,
        transport: UpdateTransport,
        cancel: Event,
        progress: Callable[[float], None],
    ) -> None:
        if sys.platform == "win32":
            from storage.platform.host_install_windows import require_fixed_ntfs

            require_fixed_ntfs(self.root)
        if shutil.disk_usage(self.root).free < asset.size * 4 + 128 * 1024**2:
            raise OSError(
                "Not enough free disk space to stage an update and retain recovery files"
            )
        with pin_installation(self.root):
            previous = file_identity(self.installation.executable)
            directory = private_directory(self.root, ".iopenpod-update-")
            archive = directory / "download"
            transport.download(asset, archive, cancel, progress)
            if cancel.is_set():
                raise InterruptedError("Update canceled")
            if asset.target.startswith("windows"):
                candidate = directory / "incoming.exe"
                unpack_windows(archive, candidate, asset.executable_sha256)
                helper_name = "iOpenPod-update.exe"
            else:
                versions = require_plain_path(self.root / "versions")
                destination = versions / asset.version
                try:
                    destination.mkdir(exist_ok=False)
                except FileExistsError:
                    # A canceled attempt may have finished staging. Reuse only
                    # the complete authenticated runtime; never repair or delete
                    # an existing directory based on its version-like name.
                    verify_linux_runtime(archive, destination, asset)
                else:
                    unpack_linux(archive, destination, asset)
                candidate = destination / "iOpenPod"
                helper_name = "iOpenPod-update"
            incoming = file_identity(candidate)
            helper = directory / helper_name
            _copy(self.installation.resources / "updates" / helper_name, helper)
            self._helper_identity = file_identity(helper)
            if sys.platform != "win32":
                helper.chmod(0o700)
            nonce = uuid.uuid4().hex
            parents = [os.getpid()]
            if sys.platform == "win32" and getattr(sys, "frozen", False):
                parents.append(os.getppid())
            durable_write(directory / "release.json", metadata)
            durable_write(
                directory / "operation.json",
                json.dumps(
                    {
                        "nonce": nonce,
                        "target": asset.target,
                        "previous_version": self.installation.version,
                        "root_device": self.root.stat().st_dev,
                        "root_inode": self.root.stat().st_ino,
                        "directory_inode": directory.stat().st_ino,
                        "parents": parents,
                        "previous": previous.to_json(),
                        "incoming": incoming.to_json(),
                    }
                ).encode(),
            )
            self._operation = read_operation(directory, self.installation.public_keys)

    def install(self, asset: ReleaseAsset) -> None:
        operation = self._operation
        if operation is None or operation.asset != asset:
            raise RuntimeError("Download this update before installing it")
        if self._helper is not None:
            raise RuntimeError("The update helper has already started")
        name = (
            "iOpenPod-update.exe"
            if asset.target.startswith("windows")
            else "iOpenPod-update"
        )
        if file_identity(operation.directory / name) != self._helper_identity:
            raise ValueError("The independent helper changed after staging")
        self._helper = independent_process(
            [str(operation.directory / name), "--install", str(operation.directory)]
        )
        self._started = time.monotonic()

    def poll(self) -> UpdateResult | None:
        if self._helper is None or self._operation is None or self._transferred:
            return None
        if self._helper.poll() is not None:
            error = self._operation.directory / "error.txt"
            detail = (
                error.read_text()[:2048]
                if error.is_file()
                else "The independent update helper stopped before handoff"
            )
            self._helper = None
            return UpdateResult(UpdateOutcome.FAILED, detail)
        if not self._ready_reported and self._operation.matches(
            "ready", self._operation.nonce
        ):
            self._ready_reported = True
            return UpdateResult(UpdateOutcome.HANDOFF)
        if time.monotonic() - self._started > 180:
            self.close()
            return UpdateResult(
                UpdateOutcome.FAILED, "The update helper did not acknowledge handoff"
            )
        return None

    def complete_handoff(self) -> None:
        if self._operation is None or not self._ready_reported:
            raise RuntimeError("The update helper has not acknowledged ownership")
        self._operation.write("authorized", self._operation.nonce)
        self._transferred = True

    def close(self) -> None:
        if self._operation and not self._transferred:
            self._operation.write("canceled", self._operation.nonce)
