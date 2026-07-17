"""iPod track location path helpers.

iTunesDB stores track files as device location strings such as
``:iPod_Control:Music:F00:Track.mp3``.  Other paths can appear in imported or
legacy databases, including Windows absolute paths and POSIX paths containing
``iPod_Control``.  Keep those rules in one place so sync planning, integrity
checks, exports, and execution resolve the same device file.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from iopenpod.device.path_safety import UnsafeDevicePathError, resolve_device_path

_TRACKS_SUBTREE = Path("iPod_Control") / "Music"


def expected_ipod_track_file_path(
    ipod_root: str | Path,
    track_or_location: Mapping[str, Any] | str | Path | None,
) -> Path | None:
    """Return the expected on-device path for a track location.

    The returned path may not exist.  Use this for integrity checks, removals,
    and orphan comparison where a missing file is still meaningful.
    """

    root = Path(ipod_root) if ipod_root else None
    location = _coerce_location(track_or_location)
    if root is None or not location:
        return None

    loc = _strip_file_uri(location)
    if not loc:
        return None

    relative_location = _device_relative_track_location(loc)
    if relative_location is None:
        return None

    try:
        return resolve_device_path(
            root,
            relative_location,
            allowed_subtree=_TRACKS_SUBTREE,
        )
    except UnsafeDevicePathError:
        return None


def existing_ipod_track_file_path(
    ipod_root: str | Path,
    track_or_location: Mapping[str, Any] | str | Path | None,
    *,
    allow_music_filename_fallback: bool = False,
) -> Path | None:
    """Return an existing on-device path for a track location, if one exists."""

    if not ipod_root:
        return None

    expected = expected_ipod_track_file_path(ipod_root, track_or_location)
    if expected is not None and expected.is_file():
        return expected

    if not allow_music_filename_fallback:
        return None

    filename = _location_filename(track_or_location, expected)
    if not filename:
        return None

    match = _find_music_file_by_name(Path(ipod_root), filename)
    if match is not None and match.is_file():
        return match
    return None


def ipod_location_from_file_path(ipod_root: str | Path, file_path: str | Path) -> str:
    """Return an iTunesDB colon location for a path on the iPod."""

    root = Path(ipod_root).resolve(strict=False)
    path = Path(file_path)
    if not path.is_absolute():
        path = root / path
    try:
        relative = path.resolve(strict=False).relative_to(root)
        safe_path = resolve_device_path(
            root,
            relative,
            allowed_subtree=_TRACKS_SUBTREE,
        )
        relative = safe_path.relative_to(root)
    except ValueError as exc:
        raise UnsafeDevicePathError(
            f"Track path is outside the iPod music directory: {file_path!s}",
        ) from exc
    return ":" + ":".join(relative.parts)


def _coerce_location(
    track_or_location: Mapping[str, Any] | str | Path | None,
) -> str:
    if track_or_location is None:
        return ""
    if isinstance(track_or_location, Mapping):
        raw = track_or_location.get("Location") or track_or_location.get("location")
    else:
        raw = track_or_location
    return str(raw or "").strip()


def _strip_file_uri(location: str) -> str:
    if not location.lower().startswith("file://"):
        return location

    from urllib.parse import unquote, urlparse

    parsed = urlparse(location)
    return unquote(parsed.path or "").strip()


def _is_windows_absolute_path(location: str) -> bool:
    return (
        len(location) >= 3
        and location[0].isalpha()
        and location[1] == ":"
        and location[2] in ("\\", "/")
    )


def _device_relative_track_location(location: str) -> str | None:
    if not location or "\x00" in location:
        return None

    unified = location.replace("\\", "/")
    if unified.startswith("//"):
        return None

    is_windows_drive_path = (
        len(unified) >= 2
        and unified[0].isalpha()
        and unified[1] == ":"
    )
    if ":" in unified and not is_windows_drive_path:
        unified = unified.replace(":", "/")

    parts = unified.split("/")
    marker_index = next(
        (index for index, part in enumerate(parts) if part.lower() == "ipod_control"),
        None,
    )
    if marker_index is None:
        if unified.startswith("/") or is_windows_drive_path:
            return None
        candidate_parts = parts
    else:
        candidate_parts = parts[marker_index:]

    if len(candidate_parts) < 2 or [part.lower() for part in candidate_parts[:2]] != [
        "ipod_control",
        "music",
    ]:
        return None

    return "/".join(("iPod_Control", "Music", *candidate_parts[2:]))


def _location_filename(
    track_or_location: Mapping[str, Any] | str | Path | None,
    expected_path: Path | None,
) -> str:
    if expected_path is not None:
        return expected_path.name
    location = _strip_file_uri(_coerce_location(track_or_location))
    rel = _device_relative_track_location(location)
    return Path(rel).name if rel else ""


def _find_music_file_by_name(ipod_root: Path, filename: str) -> Path | None:
    try:
        music_root = resolve_device_path(
            ipod_root,
            _TRACKS_SUBTREE,
            allowed_subtree=_TRACKS_SUBTREE,
        )
    except UnsafeDevicePathError:
        return None
    if not music_root.is_dir():
        return None

    root = ipod_root.resolve(strict=False)
    target_name = filename.lower()
    target_stem = Path(filename).stem.lower()
    stem_match: Path | None = None
    for item in music_root.rglob("*"):
        try:
            relative = item.relative_to(root)
            safe_item = resolve_device_path(
                root,
                relative,
                allowed_subtree=_TRACKS_SUBTREE,
            )
        except (UnsafeDevicePathError, ValueError):
            continue
        if not safe_item.is_file():
            continue
        if safe_item.name.lower() == target_name:
            return safe_item
        if stem_match is None and target_stem and safe_item.stem.lower() == target_stem:
            stem_match = safe_item
    return stem_match
