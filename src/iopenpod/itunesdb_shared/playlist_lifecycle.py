"""Playlist row lifecycle helpers.

Playlist rows are not just user-visible names and track membership. Their MHSD
dataset, result bucket, header flags, opaque MHOD children, and duplicated rows
across datasets are part of the iPod's format. Editing one field must therefore
start from the parsed row and overlay the deliberate UI changes, not rebuild a
playlist from a narrow schema.
"""

from __future__ import annotations

from typing import Any

from .playlist_properties import normalize_playlist_description


def playlist_edit_payload(
    existing_row: dict[str, Any] | None,
    changes: dict[str, Any],
) -> dict[str, Any]:
    """Return the complete row to save for a playlist edit.

    ``existing_row`` carries the playlist's iPod law: which MHSD it came from,
    which result bucket it belongs to, its flags, opaque plist/MHOD fields, and
    membership. ``changes`` is only the UI delta. Starting from the existing row
    keeps unknown fields whole and prevents an edit from accidentally becoming a
    new playlist in another dataset.
    """

    row: dict[str, Any] = dict(existing_row or {})
    row.update(changes)
    return normalize_playlist_description(row)
