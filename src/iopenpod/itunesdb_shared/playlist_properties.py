"""Playlist property helpers for MHYP-level metadata.

Classic iTunesDB playlist rows can carry playlist description in two places:

- MHOD type 55: an Apple binary plist. The iPod 5.5G sample only shows
  a ``description`` key, but the plist is preserved whole for future keys.
- MHOD type 3: the same text duplicated as a string child. Type 3 is "Album"
  for tracks, so this fallback is only valid while handling playlist rows.

This module is the lifecycle boundary for that data. Parser, cache, UI, and
writer code should call these helpers instead of re-decoding plist shapes.
"""

from __future__ import annotations

import base64
import plistlib
from dataclasses import dataclass, field
from typing import Any

PLAYLIST_PROPERTY_KEY = "playlist_property_plist"
PLAYLIST_DESCRIPTION_KEY = "playlist_description"
PLAYLIST_DESCRIPTION_DUPLICATE_KEY = "Album"


def _decode_raw_body(value: object) -> bytes | None:
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, str):
        try:
            return base64.b64decode(value)
        except Exception:
            return None
    return None


@dataclass(slots=True)
class PlaylistPropertyPlist:
    """Structured representation of MHOD type 55 playlist properties."""

    raw_body: bytes | None = None
    plist: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_raw_body(cls, raw_body: bytes | bytearray | str | None) -> PlaylistPropertyPlist:
        body = _decode_raw_body(raw_body)
        if body is None:
            return cls()
        parsed: dict[str, Any] = {}
        try:
            loaded = plistlib.loads(body)
        except Exception:
            loaded = None
        if isinstance(loaded, dict):
            parsed = dict(loaded)
        return cls(raw_body=body, plist=parsed)

    @classmethod
    def from_parsed(cls, value: object) -> PlaylistPropertyPlist:
        if isinstance(value, cls):
            return value
        if not isinstance(value, dict):
            if isinstance(value, (bytes, bytearray, str)) or value is None:
                return cls.from_raw_body(value)
            return cls()

        raw_body = _decode_raw_body(value.get("raw_body"))
        plist_value = value.get("plist")
        if isinstance(plist_value, dict):
            plist = dict(plist_value)
        else:
            plist = {}

        description = value.get("description")
        if isinstance(description, str):
            plist.setdefault("description", description)

        if not plist and raw_body is not None:
            return cls.from_raw_body(raw_body)
        return cls(raw_body=raw_body, plist=plist)

    @classmethod
    def from_description(
        cls,
        description: str,
        existing: PlaylistPropertyPlist | None = None,
    ) -> PlaylistPropertyPlist:
        plist = dict(existing.plist) if existing is not None else {}
        plist["description"] = description
        raw_body = plistlib.dumps(plist, fmt=plistlib.FMT_BINARY)
        return cls(raw_body=raw_body, plist=plist)

    @property
    def description(self) -> str:
        value = self.plist.get("description")
        return value if isinstance(value, str) else ""

    def to_parsed_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "raw_body": self.raw_body or b"",
            "plist": dict(self.plist),
        }
        if self.description:
            result["description"] = self.description
        return result


def parse_playlist_property_mhod55(raw_body: bytes | bytearray) -> dict[str, Any]:
    """Decode an MHOD type-55 body into the parser's stable dict shape."""

    return PlaylistPropertyPlist.from_raw_body(raw_body).to_parsed_dict()


def playlist_property_from_row(row: dict) -> PlaylistPropertyPlist:
    return PlaylistPropertyPlist.from_parsed(row.get(PLAYLIST_PROPERTY_KEY))


def playlist_description_from_row(row: dict | None) -> str:
    if not row:
        return ""

    description = row.get(PLAYLIST_DESCRIPTION_KEY)
    if isinstance(description, str):
        return description

    property_description = playlist_property_from_row(row).description
    if property_description:
        return property_description

    duplicate = row.get(PLAYLIST_DESCRIPTION_DUPLICATE_KEY)
    if isinstance(duplicate, str):
        return duplicate
    return ""


def normalize_playlist_description(row: dict) -> dict:
    """Ensure a playlist row has the canonical description fields.

    This mutates and returns *row*. The duplicated ``Album`` key is kept aligned
    only for playlist rows because older code and parsed samples expose MHOD
    type 3 through that global string name.
    """

    description = playlist_description_from_row(row)
    if description or PLAYLIST_DESCRIPTION_KEY in row:
        row[PLAYLIST_DESCRIPTION_KEY] = description
        row[PLAYLIST_DESCRIPTION_DUPLICATE_KEY] = description
    return row


def playlist_description_update_fields(
    description: str,
    existing_row: dict | None = None,
) -> dict[str, Any]:
    """Return row fields for a UI edit to playlist description."""

    existing_property = playlist_property_from_row(existing_row or {})
    original_description = playlist_description_from_row(existing_row)
    if not description and not existing_property.raw_body and not original_description:
        return {}

    if description == original_description and existing_property.raw_body is not None:
        prop = existing_property
    else:
        prop = PlaylistPropertyPlist.from_description(description, existing_property)

    return {
        PLAYLIST_DESCRIPTION_KEY: description,
        PLAYLIST_DESCRIPTION_DUPLICATE_KEY: description,
        PLAYLIST_PROPERTY_KEY: prop.to_parsed_dict(),
    }


def playlist_property_raw_body_for_write(row: dict) -> bytes | None:
    """Return the MHOD type-55 body to write for a playlist row."""

    description_present = PLAYLIST_DESCRIPTION_KEY in row and isinstance(
        row.get(PLAYLIST_DESCRIPTION_KEY), str
    )
    prop = playlist_property_from_row(row)

    if description_present and row[PLAYLIST_DESCRIPTION_KEY] != prop.description:
        prop = PlaylistPropertyPlist.from_description(row[PLAYLIST_DESCRIPTION_KEY], prop)

    if prop.raw_body is not None:
        return prop.raw_body

    if description_present:
        return PlaylistPropertyPlist.from_description(row[PLAYLIST_DESCRIPTION_KEY]).raw_body

    return None
