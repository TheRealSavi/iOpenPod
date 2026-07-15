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

    direct = Path(loc).expanduser()
    if direct.is_file():
        return direct

    unified = loc.replace("\\", "/")
    is_windows_abs = _is_windows_absolute_path(loc)

    # iTunesDB colon paths need to win before the marker branch so
    # :iPod_Control:Music:F00:Track.mp3 becomes slash-delimited.
    if not is_windows_abs and ":" in loc:
        return root / loc.replace(":", "/").lstrip("/")

    marker_index = unified.lower().find("ipod_control")
    if marker_index >= 0:
        return root / unified[marker_index:].lstrip("/")

    if not direct.is_absolute() and not is_windows_abs:
        return root / unified.lstrip("/")

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

    root = Path(ipod_root)
    path = Path(file_path)
    try:
        relative = path.relative_to(root)
    except ValueError:
        relative = path
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
    return str(raw or "").split("\x00", 1)[0].strip()


def _strip_file_uri(location: str) -> str:
    if not location.lower().startswith("file://"):
        return location

    from urllib.parse import unquote, urlparse

    parsed = urlparse(location)
    return unquote(parsed.path or "").split("\x00", 1)[0].strip()


def _is_windows_absolute_path(location: str) -> bool:
    return (
        len(location) >= 3
        and location[0].isalpha()
        and location[1] == ":"
        and location[2] in ("\\", "/")
    )


def _location_filename(
    track_or_location: Mapping[str, Any] | str | Path | None,
    expected_path: Path | None,
) -> str:
    if expected_path is not None:
        return expected_path.name
    location = _strip_file_uri(_coerce_location(track_or_location))
    rel = location.replace("\\", "/").replace(":", "/").lstrip("/")
    return Path(rel).name if rel else ""


def _find_music_file_by_name(ipod_root: Path, filename: str) -> Path | None:
    music_root = ipod_root / "iPod_Control" / "Music"
    if not music_root.is_dir():
        return None

    target_name = filename.lower()
    target_stem = Path(filename).stem.lower()
    stem_match: Path | None = None
    for item in music_root.rglob("*"):
        if not item.is_file():
            continue
        if item.name.lower() == target_name:
            return item
        if stem_match is None and target_stem and item.stem.lower() == target_stem:
            stem_match = item
    return stem_match
