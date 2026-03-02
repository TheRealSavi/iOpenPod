from typing import Any


def parse_playlistList(data, offset, header_length, playlistCount) -> dict[str, Any]:
    """
    Parse an MHLP (Playlist List) chunk.

    MHLP is the container for all playlists or podcast playlists.
    It appears as a child of MHSD type 2 (playlists), type 3 (podcasts),
    or type 5 (smart playlists). The third field in the header is the
    number of child MHYP playlists (not total_length like most chunks).

    Structure:
        +0x00: 'mhlp' magic (4 bytes)
        +0x04: header_length (4 bytes) - typically 92
        +0x08: playlist_count (4 bytes) - number of MHYP children
        +0x0C..header: padding/zeros

    Children: MHYP (playlist) chunks

    Args:
        data: Raw iTunesDB bytes
        offset: Start of this MHLP chunk
        header_length: Size of header (from chunk_parser)
        playlistCount: Number of MHYP children (passed as chunk_length
                       by chunk_parser, but actually the playlist count)

    Returns:
        {"nextOffset": int, "result": list[dict]}
    """
    from .chunk_parser import parse_chunk

    playlists = []

    next_offset = offset + header_length
    for i in range(playlistCount):
        response = parse_chunk(data, next_offset)
        next_offset = response["nextOffset"]
        playlists.append(response["result"])

    return {"nextOffset": next_offset, "result": playlists}
