"""ITHMB filename helpers shared by ArtworkDB readers and writers."""

from __future__ import annotations

import os


def ithmb_filename(format_id: int, index: int = 1) -> str:
    return f"F{int(format_id)}_{int(index)}.ithmb"


def normalize_ithmb_filename(format_id: int, filename: str | None, default_index: int = 1) -> str:
    name = (filename or "").strip().replace("\\", "/")
    if ":" in name:
        name = name.split(":")[-1]
    if "/" in name:
        name = name.rsplit("/", 1)[-1]
    return name or ithmb_filename(format_id, default_index)


def ithmb_filename_from_path(path: str, format_id: int, default_index: int = 1) -> str:
    return normalize_ithmb_filename(format_id, path, default_index)


def ithmb_path_for_filename(artwork_dir: str, format_id: int, filename: str | None) -> str:
    return os.path.join(artwork_dir, normalize_ithmb_filename(format_id, filename))

