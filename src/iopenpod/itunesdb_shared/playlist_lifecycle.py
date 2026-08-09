"""Playlist row lifecycle helpers.

Playlist rows are not just user-visible names and track membership. Their MHSD
dataset, result bucket, header flags, opaque MHOD children, and duplicated rows
across datasets are part of the iPod's format. Editing one field must therefore
start from the parsed row and overlay the deliberate UI changes, not rebuild a
playlist from a narrow schema.
"""

from __future__ import annotations

from typing import Any

from .playlist_kinds import (
    is_playlist_folder,
    is_podcast_playlist,
    playlist_kind_flags,
)
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
    normalize_playlist_description(row)

    kind_flags = playlist_kind_flags(row)
    row["playlist_kind_flags"] = kind_flags
    row["podcast_flag"] = kind_flags
    row["is_folder"] = is_playlist_folder(kind_flags)
    row["is_podcast"] = is_podcast_playlist(kind_flags)

    raw_parent_id = row.get(
        "parent_folder_playlist_id",
        row.get("unk0x30_playlist_ref", 0),
    )
    try:
        parent_id = int(raw_parent_id or 0)
    except (TypeError, ValueError, OverflowError):
        parent_id = 0
    row["parent_folder_playlist_id"] = parent_id
    row["unk0x30_playlist_ref"] = parent_id
    return row
