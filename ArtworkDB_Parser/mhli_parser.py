from typing import Any


def parse_mhli(data, offset, header_length, imageCount) -> dict[str, Any]:
    from .chunk_parser import parse_chunk

    imageList = []

    # Parse Children
    next_offset = offset + header_length
    for i in range(imageCount):
        response = parse_chunk(data, next_offset)
        next_offset = response["nextOffset"]
        imageList.append(response["result"])

    return {"nextOffset": next_offset, "result": imageList}
