"""Root-independent Device Path values."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import PurePath, PurePosixPath

from storage.errors import InvalidDevicePathError, InvalidHostPathError

_WINDOWS_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")


@dataclass(frozen=True, slots=True, init=False)
class DevicePath:
    """A normalized, non-empty relative path inside a device root."""

    _parts: tuple[str, ...]

    def __init__(self, value: str | PurePath) -> None:
        raw = os.fspath(value)
        if not raw or "\x00" in raw:
            raise InvalidDevicePathError("A Device Path must be non-empty text")

        unified = raw.replace("\\", "/")
        if unified.startswith("/") or _WINDOWS_DRIVE_PREFIX.match(unified):
            raise InvalidDevicePathError("A Device Path must be relative")

        parts = tuple(unified.split("/"))
        if any(not part or part in {".", ".."} or ":" in part for part in parts):
            raise InvalidDevicePathError(
                f"A Device Path contains an invalid component: {raw!r}"
            )
        object.__setattr__(self, "_parts", parts)

    @classmethod
    def from_parts(cls, parts: tuple[str, ...]) -> DevicePath:
        """Construct from canonical path components without rewriting characters."""

        if not parts or any(
            not part
            or "\x00" in part
            or "/" in part
            or part in {".", ".."}
            or ":" in part
            for part in parts
        ):
            raise InvalidDevicePathError(
                f"A Device Path contains an invalid component: {parts!r}"
            )
        result = object.__new__(cls)
        object.__setattr__(result, "_parts", parts)
        return result

    @property
    def parts(self) -> tuple[str, ...]:
        return self._parts

    @property
    def name(self) -> str:
        return self._parts[-1]

    @property
    def parent(self) -> DevicePath | None:
        if len(self._parts) == 1:
            return None
        return DevicePath.from_parts(self._parts[:-1])

    def joinpath(self, *parts: str) -> DevicePath:
        return DevicePath.from_parts((*self._parts, *parts))

    def is_relative_to(self, other: DevicePath) -> bool:
        return self._parts[: len(other.parts)] == other.parts

    def __str__(self) -> str:
        return PurePosixPath(*self._parts).as_posix()


@dataclass(frozen=True, slots=True)
class HostPath:
    """An explicit absolute Host path authorized for one copy operation."""

    path: PurePath

    def __init__(self, value: str | PurePath) -> None:
        path = PurePath(value)
        raw = os.fspath(path)
        if not raw or "\x00" in raw or not path.is_absolute():
            raise InvalidHostPathError("A Host Path must be absolute")
        object.__setattr__(self, "path", path)

    def __fspath__(self) -> str:
        return os.fspath(self.path)

    def __str__(self) -> str:
        return os.fspath(self.path)
