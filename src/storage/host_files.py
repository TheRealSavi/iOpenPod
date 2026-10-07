"""Platform-native locations and safe writes for ordinary Host files."""

from __future__ import annotations

import os
import shutil
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from storage.errors import (
    FilePreconditionError,
    StorageOperationError,
    UnsupportedStorageOperationError,
)

_COPY_CHUNK_SIZE = 1024 * 1024

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True, slots=True)
class AtomicHostFile:
    """Read and atomically replace one ordinary application-owned Host file."""

    path: Path

    def read_bytes(self, *, max_bytes: int | None = None) -> bytes | None:
        """Read an optional file, with a caller-selected allocation bound."""

        if max_bytes is not None and max_bytes < 0:
            raise ValueError("Host file read limit must be non-negative")
        try:
            with self.path.open("rb") as stream:
                data = (
                    stream.read() if max_bytes is None else stream.read(max_bytes + 1)
                )
        except FileNotFoundError:
            return None
        if max_bytes is not None and len(data) > max_bytes:
            raise StorageOperationError("The Host file exceeds its read size limit")
        return data

    def revision(self) -> tuple[int, int, int, int] | None:
        """Return device, inode, size and mtime as a cheap cache freshness hint.

        This notices ordinary replacement and edits; it is not a content digest
        or authorization for a write. A missing file has no revision.
        """

        try:
            metadata = self.path.stat()
        except FileNotFoundError:
            return None
        return (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_size,
            metadata.st_mtime_ns,
        )

    def exists(self) -> bool:
        return os.path.lexists(self.path)

    def create_bytes(self, data: bytes) -> None:
        """Atomically create a complete file without replacing any existing path."""

        parent = self.path.parent
        if not parent.is_dir():
            raise StorageOperationError(
                f"The Host destination directory does not exist: {parent}"
            )
        descriptor, temporary_name = tempfile.mkstemp(
            dir=parent,
            prefix=f".{self.path.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            if os.name != "nt":
                temporary_path.chmod(0o600)
            _publish_new_file(temporary_path, self.path)
        finally:
            temporary_path.unlink(missing_ok=True)

    def replace_bytes(self, data: bytes) -> None:
        parent = self.path.parent
        parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=parent,
            prefix=f".{self.path.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            if os.name != "nt":
                temporary_path.chmod(0o600)
            os.replace(temporary_path, self.path)
            _flush_directory(parent)
        finally:
            temporary_path.unlink(missing_ok=True)


def application_config_file(
    application_name: str,
    filename: str,
    *,
    platform_name: str,
    environment: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """Return a settings-style file in the Host's conventional config location."""

    _require_path_component(application_name, "application name")
    _require_path_component(filename, "filename")
    resolved_environment = os.environ if environment is None else environment
    resolved_home = Path.home() if home is None else home

    if platform_name == "windows":
        base = _absolute_environment_path(resolved_environment, "APPDATA")
        if base is None:
            base = resolved_home / "AppData" / "Roaming"
        return base / application_name / filename
    if platform_name == "macos":
        return (
            resolved_home
            / "Library"
            / "Application Support"
            / application_name
            / filename
        )
    if platform_name == "linux":
        base = _absolute_environment_path(resolved_environment, "XDG_CONFIG_HOME")
        if base is None:
            base = resolved_home / ".config"
        return base / application_name.casefold() / filename
    raise UnsupportedStorageOperationError(
        f"Storage does not support Host configuration files on {platform_name!r}"
    )


def application_cache_file(
    application_name: str,
    filename: str,
    *,
    platform_name: str,
    environment: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """Return a file in the Host's conventional application cache location."""

    _require_path_component(application_name, "application name")
    _require_path_component(filename, "filename")
    resolved_environment = os.environ if environment is None else environment
    resolved_home = Path.home() if home is None else home

    if platform_name == "windows":
        base = _absolute_environment_path(resolved_environment, "LOCALAPPDATA")
        if base is None:
            base = resolved_home / "AppData" / "Local"
        return base / application_name / "cache" / filename
    if platform_name == "macos":
        return resolved_home / "Library" / "Caches" / application_name / filename
    if platform_name == "linux":
        base = _absolute_environment_path(resolved_environment, "XDG_CACHE_HOME")
        if base is None:
            base = resolved_home / ".cache"
        return base / application_name.casefold() / filename
    raise UnsupportedStorageOperationError(
        f"Storage does not support Host cache files on {platform_name!r}"
    )


def _require_path_component(value: str, label: str) -> None:
    if not value or value in {".", ".."} or Path(value).name != value:
        raise ValueError(f"Invalid {label}: {value!r}")


def _absolute_environment_path(
    environment: Mapping[str, str],
    key: str,
) -> Path | None:
    value = environment.get(key)
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else None


def _flush_directory(directory: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _publish_new_file(source: Path, destination: Path) -> None:
    """Publish a staged Host file with create-only semantics on every platform."""

    try:
        os.link(source, destination)
        _flush_directory(destination.parent)
        source.unlink()
        return
    except FileExistsError as error:
        raise FilePreconditionError(
            f"Host destination already exists: {destination}"
        ) from error
    except OSError:
        pass

    descriptor = -1
    try:
        descriptor = os.open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
            0o600,
        )
        with source.open("rb") as staged, os.fdopen(descriptor, "wb") as published:
            descriptor = -1
            shutil.copyfileobj(staged, published, _COPY_CHUNK_SIZE)
            published.flush()
            os.fsync(published.fileno())
        _flush_directory(destination.parent)
        source.unlink()
    except FileExistsError as error:
        raise FilePreconditionError(
            f"Host destination already exists: {destination}"
        ) from error
    except OSError:
        if descriptor >= 0:
            os.close(descriptor)
        with suppress(OSError):
            destination.unlink(missing_ok=True)
        raise
