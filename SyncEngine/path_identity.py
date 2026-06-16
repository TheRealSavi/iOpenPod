"""Shared identity helpers for sync planning.

The sync engine compares paths that may come from scan results, playlist files,
mapping hints, GUI selections, and parsed iTunesDB rows. Keep the normalization
rules in one place so those systems agree on what "the same source path" means.
"""

from __future__ import annotations

import os
from pathlib import Path


def stable_path_key(path: str | os.PathLike[str]) -> str:
    """Return the canonical case-normalized absolute key for a local path."""

    expanded = Path(path).expanduser()
    try:
        return os.path.normcase(str(expanded.resolve()))
    except OSError:
        return os.path.normcase(os.path.abspath(os.fspath(expanded)))


def coerce_int(value: object, default: int = 0) -> int:
    """Convert common scalar values to ``int`` without accepting arbitrary objects."""

    if value is None:
        return default
    if not isinstance(value, (str, bytes, bytearray, int, float)):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
