"""Saved native Genius Playlist plists, without Library or filesystem authority.

Classic 6.5G version 0 has parallel zero-based master indexes/persistent Track
IDs. Nano 7G version 0 omits indexes and adds a Playlist persistent ID. Absent
fields stay absent; the timestamp remains an uninterpreted integer.
Unedited documents retain every original byte. XML edits retain untouched value
and framing bytes; binary edits retain unrepresented property-list values.
"""

from __future__ import annotations

import plistlib
from dataclasses import dataclass, replace
from typing import cast
from xml.parsers.expat import ExpatError, ParserCreate

from iPodDB.sidecars.codec import MAX_SIDECAR_BYTES

_U32 = (1 << 32) - 1
_U64 = (1 << 64) - 1
_FIELDS = {
    "version": "version",
    "saved_index": "savedIndex",
    "name": "name",
    "seed_track_persistent_id": "seedTrackPersistentID",
    "database_timestamp": "DBTimestampMacOSDate",
    "track_master_indexes": "trackMasterIndexes",
    "track_persistent_ids": "trackPersistentIDs",
    "playlist_persistent_id": "playlistPersistentID",
}


@dataclass(frozen=True, slots=True)
class GeniusPlaylist:
    """Known fields; absent master indexes distinguish the identity-only variant."""

    saved_index: int
    name: str
    seed_track_persistent_id: int
    database_timestamp: int
    track_master_indexes: tuple[int, ...] | None
    track_persistent_ids: tuple[int, ...]
    version: int = 0
    playlist_persistent_id: int | None = None


@dataclass(frozen=True, slots=True)
class GeniusPlaylistDocument:
    """Editable known fields over retained source bytes.

    An unsupported version has no interpreted Playlist. It remains lossless but
    cannot be edited or positionally remapped. Use ``dataclasses.replace`` to edit
    the Playlist, then ``write_genius_playlist`` to encode it.
    """

    source_bytes: bytes
    playlist: GeniusPlaylist | None

    def serialize(self) -> bytes:
        return write_genius_playlist(self)


class _UniqueDict(dict[str, object]):
    def __setitem__(self, key: str, value: object) -> None:
        if key in self:
            raise ValueError("Duplicate Genius Playlist property-list key.")
        super().__setitem__(key, value)


def _load(data: bytes) -> dict[str, object]:
    if len(data) > MAX_SIDECAR_BYTES:
        raise ValueError("Genius Playlist exceeds the capture limit.")
    try:
        root: object = plistlib.loads(data, dict_type=_UniqueDict)
    except (ValueError, TypeError, OverflowError, RecursionError, ExpatError) as error:
        raise ValueError("Invalid Genius Playlist property list.") from error
    if not isinstance(root, dict):
        raise ValueError("Genius Playlist requires a property-list dictionary.")
    properties = cast("dict[object, object]", root)
    if any(not isinstance(key, str) for key in properties):
        raise ValueError("Genius Playlist requires a property-list dictionary.")
    return cast("dict[str, object]", properties)


def _integer(value: object, field: str, maximum: int = _U32) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError(f"Invalid Genius Playlist {field}.")
    return value


def _identity(value: object, field: str) -> int:
    if type(value) is not int or not -(1 << 63) <= value <= _U64:
        raise ValueError(f"Invalid Genius Playlist {field}.")
    identity = value & _U64
    if not identity:
        raise ValueError(f"Missing Genius Playlist {field}.")
    return identity


def _array(value: object, field: str, *, identities: bool = False) -> tuple[int, ...]:
    if not isinstance(value, list):
        raise ValueError(f"Genius Playlist requires a {field} array.")
    reader = _identity if identities else _integer
    return tuple(reader(item, field) for item in cast("list[object]", value))


def _playlist(root: dict[str, object]) -> GeniusPlaylist | None:
    version = _integer(root.get("version"), "version")
    if version != 0:
        return None
    name = root.get("name")
    if not isinstance(name, str):
        raise ValueError("Genius Playlist requires a name string.")
    positions = (
        _array(root["trackMasterIndexes"], "trackMasterIndexes")
        if "trackMasterIndexes" in root
        else None
    )
    identities = _array(
        root.get("trackPersistentIDs"), "trackPersistentIDs", identities=True
    )
    if positions is not None and len(positions) != len(identities):
        raise ValueError("Genius Playlist Track arrays have different lengths.")
    return GeniusPlaylist(
        saved_index=_integer(root.get("savedIndex"), "savedIndex"),
        name=name,
        seed_track_persistent_id=_identity(
            root.get("seedTrackPersistentID"), "seedTrackPersistentID"
        ),
        database_timestamp=_integer(
            root.get("DBTimestampMacOSDate"), "DBTimestampMacOSDate", _U64
        ),
        track_master_indexes=positions,
        track_persistent_ids=identities,
        version=version,
        playlist_persistent_id=(
            _identity(root["playlistPersistentID"], "playlistPersistentID")
            if "playlistPersistentID" in root
            else None
        ),
    )


def parse_genius_playlist(data: bytes) -> GeniusPlaylistDocument:
    """Read version 0; retain other versioned plists as opaque documents."""
    return GeniusPlaylistDocument(bytes(data), _playlist(_load(data)))


def _properties(playlist: GeniusPlaylist) -> dict[str, object]:
    properties: dict[str, object] = {}
    for attribute, key in _FIELDS.items():
        value: object = getattr(playlist, attribute)
        if value is not None:
            properties[key] = (
                list(cast("tuple[object, ...]", value))
                if isinstance(value, tuple)
                else value
            )
    if playlist.version != 0 or _playlist(properties) != playlist:
        raise ValueError("Only canonical version-0 Genius Playlists can be written.")
    return properties


def create_genius_playlist(
    playlist: GeniusPlaylist, *, binary: bool = False
) -> GeniusPlaylistDocument:
    """Author a saved Playlist; caller owns Track identity and timestamp intent."""
    data = plistlib.dumps(
        _properties(playlist),
        fmt=plistlib.FMT_BINARY if binary else plistlib.FMT_XML,
        sort_keys=False,
    )
    return parse_genius_playlist(data)


def _xml_value_spans(data: bytes) -> dict[str, tuple[int, int]]:
    """Locate direct dictionary values without reformatting retained XML bytes."""
    parser = ParserCreate()
    depth = 0
    key_parts: list[str] = []
    key = ""
    value_start = 0
    value_empty_end = 0
    reading_key = False
    spans: dict[str, tuple[int, int]] = {}

    def declaration(_version: str, encoding: str | None, _standalone: int) -> None:
        if encoding is not None and encoding.casefold() not in ("utf-8", "utf8"):
            raise ValueError("Only UTF-8 Genius Playlist XML can be edited.")

    def tag_end(start: int) -> int:
        quote = 0
        for offset in range(start, len(data)):
            value = data[offset]
            if quote:
                if value == quote:
                    quote = 0
            elif value in (34, 39):
                quote = value
            elif value == 62:
                return offset + 1
        raise ValueError("Incomplete Genius Playlist XML element.")

    def start(name: str, _attributes: dict[str, str]) -> None:
        nonlocal depth, reading_key, value_start, value_empty_end
        depth += 1
        if depth != 3:
            return
        reading_key = name == "key"
        if reading_key:
            key_parts.clear()
        else:
            value_start = parser.CurrentByteIndex
            opening_end = tag_end(value_start)
            value_empty_end = (
                opening_end if data[value_start:opening_end].endswith(b"/>") else 0
            )

    def text(value: str) -> None:
        if depth == 3 and reading_key:
            key_parts.append(value)

    def end(_name: str) -> None:
        nonlocal depth, key, reading_key
        if depth == 3:
            if reading_key:
                key = "".join(key_parts)
                reading_key = False
            else:
                value_end = (
                    value_empty_end or data.find(b">", parser.CurrentByteIndex) + 1
                )
                spans[key] = (value_start, value_end)
        depth -= 1

    parser.StartElementHandler = start
    parser.XmlDeclHandler = declaration
    parser.CharacterDataHandler = text
    parser.EndElementHandler = end
    parser.Parse(data, True)
    return spans


def _xml_value(value: object) -> bytes:
    encoded = plistlib.dumps({"value": value}, sort_keys=False)
    start, end = _xml_value_spans(encoded)["value"]
    return encoded[start:end]


def write_genius_playlist(document: GeniusPlaylistDocument) -> bytes:
    """Write known edits, preserving the source format and unknown properties.

    Untouched XML elements, comments, declaration, and whitespace remain verbatim.
    Edited binary plists retain all unknown values, but their object-table layout
    is rebuilt. Every unchanged document returns its exact original bytes.
    """
    original = _load(document.source_bytes)
    baseline = _playlist(original)
    if baseline == document.playlist:
        return document.source_bytes
    if baseline is None or document.playlist is None:
        raise ValueError("Unsupported Genius Playlist versions cannot be edited.")
    updated = _properties(document.playlist)
    baseline_values = _properties(baseline)
    if updated.keys() != baseline_values.keys():
        raise ValueError(
            "A retained Genius Playlist's field presence cannot be changed."
        )
    changed = {
        key: value for key, value in updated.items() if value != baseline_values[key]
    }
    if document.source_bytes.startswith(b"bplist00"):
        original.update(changed)
        result = plistlib.dumps(original, fmt=plistlib.FMT_BINARY, sort_keys=False)
    else:
        # plistlib accepts UTF-8 XML. A different byte encoding cannot be patched
        # with UTF-8 fragments while promising unchanged unknown framing bytes.
        if b"\x00" in document.source_bytes:
            raise ValueError("Only UTF-8 Genius Playlist XML can be edited.")
        spans = _xml_value_spans(document.source_bytes)
        if not changed.keys() <= spans.keys():
            raise ValueError("Unsupported Genius Playlist XML dictionary framing.")
        result = document.source_bytes
        for start, end, value in sorted(
            ((*spans[key], value) for key, value in changed.items()), reverse=True
        ):
            result = result[:start] + _xml_value(value) + result[end:]
    checked = parse_genius_playlist(result)
    if checked.playlist != document.playlist:
        raise ValueError("Genius Playlist serialization changed known fields.")
    return result


def _track_ids(identities: tuple[int, ...]) -> None:
    if any(type(value) is not int or not 0 < value <= _U64 for value in identities):
        raise ValueError(
            "Genius Playlist requires nonzero persistent Track identities."
        )
    if len(set(identities)) != len(identities):
        raise ValueError("Genius Playlist requires unique Library Track identities.")


def validate_genius_playlist_tracks(
    playlist: GeniusPlaylist, track_persistent_ids: tuple[int, ...]
) -> None:
    """Check both evidenced reference representations against one Track order."""
    _properties(playlist)
    _track_ids(track_persistent_ids)
    if playlist.seed_track_persistent_id not in track_persistent_ids:
        raise ValueError("Genius Playlist references an unavailable seed Track.")
    if playlist.track_master_indexes is None:
        if not set(playlist.track_persistent_ids) <= set(track_persistent_ids):
            raise ValueError("Genius Playlist references an unavailable Track.")
        return
    for position, identity in zip(
        playlist.track_master_indexes, playlist.track_persistent_ids, strict=True
    ):
        if (
            position >= len(track_persistent_ids)
            or track_persistent_ids[position] != identity
        ):
            raise ValueError(
                "Genius Playlist Track position and persistent identity disagree."
            )


def remap_genius_playlist(
    data: bytes,
    original_persistent_ids: tuple[int, ...],
    desired_persistent_ids: tuple[int, ...],
    *,
    replacement_seed: int | None = None,
) -> bytes | None:
    """Retain surviving ordered occurrences and update both reference arrays.

    A deleted seed becomes the first surviving member, or a caller-supplied
    canonical seed. Return None when deletion empties this collection. Unknown
    versions are preserved for unchanged or append-only Track order, and cannot
    authorize destructive positional changes.
    The database timestamp is retained; its invalidation semantics are unknown.
    Identity-only variants keep their absent master-index array. This pure helper
    requires the final prepared Library's persistent IDs and Track order.
    """
    document = parse_genius_playlist(data)
    _track_ids(original_persistent_ids)
    _track_ids(desired_persistent_ids)
    playlist = document.playlist
    if playlist is None:
        if (
            desired_persistent_ids[: len(original_persistent_ids)]
            == original_persistent_ids
        ):
            return data
        raise ValueError("Unsupported Genius Playlist version cannot be remapped.")
    validate_genius_playlist_tracks(playlist, original_persistent_ids)
    positions = {
        identity: index for index, identity in enumerate(desired_persistent_ids)
    }
    surviving = tuple(
        identity for identity in playlist.track_persistent_ids if identity in positions
    )
    lost_seed = playlist.seed_track_persistent_id not in positions
    if not surviving and (playlist.track_persistent_ids or lost_seed):
        return None
    seed = playlist.seed_track_persistent_id
    if lost_seed:
        seed = replacement_seed if replacement_seed is not None else surviving[0]
        if seed not in positions:
            raise ValueError("Replacement Genius seed is absent from the Library.")
    return write_genius_playlist(
        replace(
            document,
            playlist=replace(
                playlist,
                seed_track_persistent_id=seed,
                track_master_indexes=(
                    tuple(positions[identity] for identity in surviving)
                    if playlist.track_master_indexes is not None
                    else None
                ),
                track_persistent_ids=surviving,
            ),
        )
    )
