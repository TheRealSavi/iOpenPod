"""
playlist_parser.py — Parse M3U/M3U8/PLS/XSPF playlist files into PC file paths.

Public API:
    parse_playlist(filepath) -> (list[str], playlist_name)

Relative paths in playlist files are resolved against the directory containing
the playlist file. HTTP/HTTPS URLs are silently skipped.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import unquote, urlparse


def parse_playlist(filepath: str | Path) -> tuple[list[str], str]:
    """Parse a playlist file and return (absolute_paths, playlist_name).

    Args:
        filepath: Path to a .m3u, .m3u8, .pls, or .xspf file.

    Returns:
        A tuple of (list of absolute path strings, human-readable name).
        Paths point to audio files on the local filesystem. Files that are
        referenced via HTTP/HTTPS URLs are omitted.

    Raises:
        ValueError: Unsupported file extension.
        OSError:    File cannot be opened or read.
    """
    filepath = Path(filepath)
    ext = filepath.suffix.lower()
    base_dir = filepath.parent

    if ext in (".m3u", ".m3u8"):
        paths = _parse_m3u(filepath, base_dir)
    elif ext == ".pls":
        paths = _parse_pls(filepath, base_dir)
    elif ext == ".xspf":
        paths = _parse_xspf(filepath, base_dir)
    else:
        raise ValueError(f"Unsupported playlist format: '{ext}'")

    return paths, _derive_name(filepath)


def resolve_existing_playlist_path(raw_path: str | Path) -> str | None:
    """Return an existing filesystem path for a playlist entry if one exists.

    Playlist files created by media players may encode the same file in a few
    different ways: file URIs, percent-escaped paths, UNC-like network paths,
    or Windows-style backslash separators on POSIX systems. This helper tries a
    few safe variants and returns the first real file it finds.
    """
    for candidate in _path_candidates(raw_path):
        if candidate.is_file():
            return str(candidate)
    return None


class PlaylistPathResolver:
    """Cached resolver for many playlist entries in one scan.

    ``resolve_existing_playlist_path`` is intentionally stateless and simple,
    but sync scans often resolve thousands of entries across several playlist
    files. This resolver caches duplicate entries, candidate file checks, and
    missing parent directories so unavailable paths do not get probed over and
    over.
    """

    def __init__(self) -> None:
        self._resolved: dict[str, str | None] = {}
        self._is_file: dict[str, bool] = {}
        self._is_dir: dict[str, bool] = {}
        self._missing_dirs: set[str] = set()

    def resolve_existing_path(self, raw_path: str | Path) -> str | None:
        key = str(raw_path)
        if key in self._resolved:
            return self._resolved[key]

        resolved: str | None = None
        for candidate in _path_candidates(raw_path):
            if self._candidate_is_file(candidate):
                resolved = str(candidate)
                break

        self._resolved[key] = resolved
        return resolved

    def _candidate_is_file(self, candidate: Path) -> bool:
        key = os.fspath(candidate)
        cached = self._is_file.get(key)
        if cached is not None:
            return cached

        parent = os.path.dirname(key)
        if parent in self._missing_dirs:
            self._is_file[key] = False
            return False

        try:
            is_file = os.path.isfile(key)
        except OSError:
            is_file = False

        self._is_file[key] = is_file
        if is_file or not parent:
            return is_file

        parent_cached = self._is_dir.get(parent)
        if parent_cached is None:
            try:
                parent_cached = os.path.isdir(parent)
            except OSError:
                parent_cached = False
            self._is_dir[parent] = parent_cached
        if not parent_cached:
            self._missing_dirs.add(parent)
        return False


# ---------------------------------------------------------------------------
# Name derivation
# ---------------------------------------------------------------------------

def _derive_name(filepath: Path) -> str:
    """Derive a human-readable playlist name from the file stem."""
    stem = filepath.stem.replace("_", " ").replace("-", " ").strip()
    return stem.title() if stem else "Imported Playlist"


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def _resolve_path(raw: str, base_dir: Path) -> str:
    """Resolve a raw path string from a playlist entry to an absolute path.

    Handles:
    - file:// URIs (percent-decoded; leading slash stripped on Windows drives)
    - Absolute paths (Unix / or Windows drive letter)
    - Relative paths (resolved against base_dir)
    """
    raw = raw.strip().strip("\"'")
    if not raw:
        return ""

    # Skip streaming URLs
    lower = raw.lower()
    if lower.startswith("http://") or lower.startswith("https://"):
        return ""

    raw = unquote(raw)

    # file:// URI
    if lower.startswith("file://"):
        try:
            parsed = urlparse(raw)
            path_part = unquote(parsed.path)
            # On Windows: /C:/path → C:/path
            if (
                os.name == "nt"
                and path_part.startswith("/")
                and len(path_part) > 2
                and path_part[2] == ":"
            ):
                path_part = path_part[1:]
            return str(Path(path_part))
        except Exception:
            return ""

    if os.name != "nt" and "\\" in raw:
        raw = raw.replace("\\", "/")

    p = Path(raw)
    if p.is_absolute():
        return str(p)

    # Relative — make absolute without touching the filesystem. Existence and
    # canonical resolution are handled later by the scan resolver.
    return os.path.abspath(os.path.join(os.fspath(base_dir), raw))


def _path_candidates(raw_path: str | Path) -> list[Path]:
    raw = str(raw_path).strip().strip("\"'")
    if not raw:
        return []

    candidates: list[Path] = []
    seen: set[str] = set()

    def _add(candidate: str) -> None:
        text = candidate.strip()
        if not text or text in seen:
            return
        seen.add(text)
        candidates.append(Path(text).expanduser())

    _add(raw)

    decoded = unquote(raw)
    if decoded != raw:
        _add(decoded)

    if os.name != "nt" and "\\" in decoded:
        _add(decoded.replace("\\", "/"))

    if "://" not in raw:
        return candidates

    parsed = urlparse(raw)
    if parsed.scheme in {"http", "https"}:
        return []

    decoded_path = unquote(parsed.path or "")

    if parsed.scheme == "file":
        if decoded_path:
            if (
                os.name == "nt"
                and decoded_path.startswith("/")
                and len(decoded_path) > 2
                and decoded_path[2] == ":"
            ):
                decoded_path = decoded_path[1:]
            _add(decoded_path)
        if parsed.netloc and parsed.netloc.lower() != "localhost" and decoded_path:
            if os.name == "nt":
                _add(
                    "\\\\"
                    + parsed.netloc
                    + decoded_path.replace("/", "\\")
                )
            else:
                _add("//" + parsed.netloc + decoded_path)
        return candidates

    if parsed.netloc and decoded_path:
        if os.name == "nt":
            _add("\\\\" + parsed.netloc + decoded_path.replace("/", "\\"))
        else:
            _add("//" + parsed.netloc + decoded_path)

    return candidates


# ---------------------------------------------------------------------------
# Format parsers
# ---------------------------------------------------------------------------

def _read_text(filepath: Path) -> str:
    """Read a file trying UTF-8 with BOM first, then latin-1 as fallback."""
    try:
        return filepath.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return filepath.read_text(encoding="latin-1")


def _parse_m3u(filepath: Path, base_dir: Path) -> list[str]:
    """Parse M3U / M3U8 playlist.

    Lines beginning with '#' are metadata/comments and are skipped.
    Blank lines are skipped. Every other line is treated as a path entry.
    """
    paths: list[str] = []
    for line in _read_text(filepath).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        resolved = _resolve_path(line, base_dir)
        if resolved:
            paths.append(resolved)
    return paths


def _parse_pls(filepath: Path, base_dir: Path) -> list[str]:
    """Parse PLS (INI-style) playlist.

    Reads File1=, File2=, … entries (case-insensitive). Returns paths in
    ascending entry-number order.
    """
    entries: dict[int, str] = {}
    for line in _read_text(filepath).splitlines():
        m = re.match(r"(?i)^File(\d+)\s*=\s*(.+)$", line.strip())
        if m:
            n = int(m.group(1))
            resolved = _resolve_path(m.group(2), base_dir)
            if resolved:
                entries[n] = resolved
    return [entries[k] for k in sorted(entries)]


def _parse_xspf(filepath: Path, base_dir: Path) -> list[str]:
    """Parse XSPF (XML Shareable Playlist Format) playlist.

    Reads <location> elements inside <trackList><track>. Only file://
    locations are returned; http(s):// URLs are skipped.
    """
    import xml.etree.ElementTree as ET

    try:
        tree = ET.parse(str(filepath))
    except ET.ParseError as exc:
        raise ValueError(f"XSPF parse error: {exc}") from exc

    def _local_tag(elem) -> str:
        """Strip XML namespace prefix: {ns}tag → tag."""
        t = elem.tag
        return t.split("}", 1)[1] if "}" in t else t

    paths: list[str] = []
    for child in tree.getroot():
        if _local_tag(child) == "trackList":
            for track in child:
                if _local_tag(track) == "track":
                    for item in track:
                        if _local_tag(item) == "location":
                            loc = (item.text or "").strip()
                            resolved = _resolve_path(loc, base_dir)
                            if resolved:
                                paths.append(resolved)
    return paths
