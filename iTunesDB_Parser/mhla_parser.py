from typing import Any


def parse_albumList(data, offset, header_length, albumCount) -> dict[str, Any]:
    from .chunk_parser import parse_chunk

    albumList = []

    # Parse Children
    next_offset = offset + header_length
    for i in range(albumCount):
        response = parse_chunk(data, next_offset)
        next_offset = response["nextOffset"]
        albumList.append(response["result"])

    return {"nextOffset": next_offset, "result": albumList}
