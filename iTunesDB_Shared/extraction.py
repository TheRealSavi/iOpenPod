"""Parser post-processing helpers for flattening parsed iTunesDB dicts.

These functions walk the nested chunk structures produced by the iTunesDB
parser and extract them into flat, easy-to-consume dictionaries.  They are
used by ``iTunesDB_Parser.ipod_library`` and ``SyncEngine.sync_executor``.
"""

from .constants import (
    MHOD_TYPE_CHAPTER_DATA,
    MHOD_TYPE_COLUMN_SIZE_OR_ORDER,
    MHOD_TYPE_LIBRARY_PLAYLIST_INDEX,
    MHOD_TYPE_PLAYLIST_SETTINGS,
    MHOD_TYPE_SMART_PLAYLIST_DATA,
    MHOD_TYPE_SMART_PLAYLIST_RULES,
    chunk_type_map,
    mhod_type_map,
)


def extract_datasets(mhbd: dict) -> dict:
    """Walk the MHBD children and extract datasets into a flat dict.

    Returns a dict with:
      - All MHBD header fields (excluding 'children')
      - "mhlt", "mhlp", "mhlp_podcast", "mhla", "mhlp_smart", etc.
        mapped from MHSD dataset_type via chunk_type_map
      - Each value is the list of item dicts from the list chunk
    """
    result = {}
    for key, value in mhbd.items():
        if key != "children":
            result[key] = value

    for mhsd_wrapper in mhbd.get("children", []):
        mhsd_data = mhsd_wrapper.get("data", {})
        dataset_type = mhsd_data.get("dataset_type")
        result_key = chunk_type_map.get(dataset_type)
        if result_key is None:
            continue

        mhsd_children = mhsd_data.get("children", [])
        if not mhsd_children:
            result[result_key] = []
            continue

        # The MHSD has one child: the list chunk (mhlt, mhlp, mhla, mhli)
        list_chunk = mhsd_children[0]
        items = list_chunk.get("data", [])

        # Extract items from their wrapper dicts
        flat_items = []
        for item in items:
            if isinstance(item, dict) and "data" in item:
                flat_items.append(item["data"])
            else:
                flat_items.append(item)
        result[result_key] = flat_items

    return result


def extract_mhod_strings(children: list) -> dict:
    """Extract MHOD string values from a chunk's children list.

    Args:
        children: The 'children' list from a parsed track/album/artist/playlist.

    Returns:
        dict mapping mhod_type_map field keys to string values,
        e.g. {"Title": "My Song", "Artist": "Foo"}
    """
    strings = {}
    for wrapper in children:
        mhod_data = wrapper.get("data", {})
        mhod_type = mhod_data.get("mhod_type")
        if mhod_type is None:
            continue
        field_name = mhod_type_map.get(mhod_type)
        if field_name and "string" in mhod_data:
            strings[field_name] = mhod_data["string"]
    return strings


def extract_track_extras(mhod_children: list) -> dict:
    """Extract non-string MHOD data from track children.

    Returns dict with optional keys:
      - "chapter_data": parsed MHOD type 17 data
    """
    extras = {}
    for wrapper in mhod_children:
        mhod_data = wrapper.get("data", {})
        if (
            mhod_data.get("mhod_type") != MHOD_TYPE_CHAPTER_DATA
            or "data" not in mhod_data
        ):
            continue

        raw_chapter_data = mhod_data["data"]
        if not isinstance(raw_chapter_data, dict):
            continue

        extras["chapter_data"] = raw_chapter_data

    return extras


def extract_playlist_extras(mhod_children: list) -> dict:
    """Extract non-string MHOD data from playlist children.

    Returns dict with optional keys:
      - "smart_playlist_data": SPL prefs dict (from MHOD type 50)
      - "smart_playlist_rules": SPL rules dict (from MHOD type 51)
      - "library_indices": sorted index data (from MHOD type 52)
      - "playlist_prefs": column prefs (from MHOD type 100)
      - "playlist_settings": settings blob (from MHOD type 102)
    """
    extras = {}
    for wrapper in mhod_children:
        mhod_data = wrapper.get("data", {})
        mhod_type = mhod_data.get("mhod_type")
        if mhod_type == MHOD_TYPE_SMART_PLAYLIST_DATA and "data" in mhod_data:
            extras["smart_playlist_data"] = mhod_data["data"]
        elif mhod_type == MHOD_TYPE_SMART_PLAYLIST_RULES and "data" in mhod_data:
            extras["smart_playlist_rules"] = mhod_data["data"]
        elif mhod_type == MHOD_TYPE_LIBRARY_PLAYLIST_INDEX and "data" in mhod_data:
            extras.setdefault("library_indices", []).append(mhod_data["data"])
        elif mhod_type == MHOD_TYPE_COLUMN_SIZE_OR_ORDER and "data" in mhod_data:
            extras["playlist_prefs"] = mhod_data["data"]
        elif mhod_type == MHOD_TYPE_PLAYLIST_SETTINGS and "data" in mhod_data:
            extras["playlist_settings"] = mhod_data["data"]
    return extras
