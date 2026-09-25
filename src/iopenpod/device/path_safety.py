"""Contain untrusted persisted paths to an explicitly approved subtree."""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path


class UnsafeDevicePathError(ValueError):
    """Raised when an untrusted device path could address an unsafe location."""


class UnsafeHostPathError(ValueError):
    """Raised when an untrusted host path could address an unsafe location."""


def resolve_device_path(
    ipod_root: str | Path,
    device_relative_path: str | Path,
    *,
    allowed_subtree: str | Path,
) -> Path:
    """Resolve an untrusted iPod-relative path within ``allowed_subtree``.

    Device database strings must be relative. Foreign absolute paths, parent
    traversal, NULs, and paths whose resolved target escapes through a symlink
    or reparse point are rejected.
    """

    relative_parts = _validated_relative_parts(device_relative_path, "device path")
    allowed_parts = _validated_relative_parts(allowed_subtree, "allowed subtree")

    root = Path(ipod_root).resolve(strict=False)
    allowed_lexical = root.joinpath(*allowed_parts)
    candidate_lexical = root.joinpath(*relative_parts)
    if not allowed_lexical.is_relative_to(root):
        raise UnsafeDevicePathError("Allowed iPod subtree resolves outside the device root")
    if not candidate_lexical.is_relative_to(allowed_lexical):
        raise UnsafeDevicePathError(
            f"Device path is outside the allowed iPod subtree: {device_relative_path!s}",
        )

    _reject_link_or_reparse_components(root, relative_parts)

    allowed = allowed_lexical.resolve(strict=False)
    if not allowed.is_relative_to(root):
        raise UnsafeDevicePathError("Allowed iPod subtree resolves outside the device root")
    candidate = candidate_lexical.resolve(strict=False)
    if not candidate.is_relative_to(allowed):
        raise UnsafeDevicePathError(
            f"Device path is outside the allowed iPod subtree: {device_relative_path!s}",
        )
    return candidate


def resolve_host_path(
    allowed_root: str | Path,
    persisted_path: str | Path,
) -> Path:
    """Resolve an absolute persisted host path beneath ``allowed_root``.

    The configured root is the trust anchor. The persisted path itself may
    not be relative, escape lexically or after resolution, or traverse a
    symbolic link/reparse point.
    """
    raw = os.fspath(persisted_path)
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise UnsafeHostPathError("Invalid persisted host path")
    if not os.path.isabs(raw):
        raise UnsafeHostPathError("Persisted host path must be absolute")

    root = Path(os.path.abspath(os.fspath(allowed_root)))
    candidate_lexical = Path(os.path.abspath(raw))
    try:
        relative = candidate_lexical.relative_to(root)
    except ValueError as exc:
        raise UnsafeHostPathError(
            f"Persisted host path is outside the allowed root: {raw}"
        ) from exc
    if not relative.parts:
        raise UnsafeHostPathError("Persisted host path must name a file below the root")

    _reject_link_or_reparse_components(
        root,
        relative.parts,
        error_type=UnsafeHostPathError,
        path_label="Host path",
    )

    resolved_root = root.resolve(strict=False)
    candidate = candidate_lexical.resolve(strict=False)
    if not candidate.is_relative_to(resolved_root):
        raise UnsafeHostPathError(
            f"Persisted host path escapes the allowed root: {raw}"
        )
    return candidate


def _validated_relative_parts(value: str | Path, label: str) -> tuple[str, ...]:
    raw = os.fspath(value)
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise UnsafeDevicePathError(f"Invalid {label}")

    unified = raw.replace("\\", "/")
    if unified.startswith("/") or re.match(r"^[A-Za-z]:", unified):
        raise UnsafeDevicePathError(f"{label.capitalize()} must be relative")

    parts = tuple(unified.split("/"))
    if any(not part or part in {".", ".."} or ":" in part for part in parts):
        raise UnsafeDevicePathError(f"Invalid component in {label}: {raw}")
    return parts


def _reject_link_or_reparse_components(
    root: Path,
    parts: tuple[str, ...],
    *,
    error_type: type[ValueError] = UnsafeDevicePathError,
    path_label: str = "Device path",
) -> None:
    """Reject aliases that could redirect a mutation to another device file."""
    current = root
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    for part in parts:
        current = current / part
        try:
            metadata = os.lstat(current)
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise error_type(
                f"Could not safely inspect {path_label.lower()} component {current}: {exc}"
            ) from exc
        file_attributes = int(getattr(metadata, "st_file_attributes", 0) or 0)
        if stat.S_ISLNK(metadata.st_mode) or file_attributes & reparse_flag:
            raise error_type(
                f"{path_label} contains a symbolic link or reparse point: {current}"
            )
