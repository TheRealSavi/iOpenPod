from typing import List

def parse_albumList(data, offset, header_length, albumCount) -> List[dict]:
  from .chunk_parser import parse_chunk

  albumList = []

  #Parse Children
  next_offset = offset+header_length
  for i in range(albumCount):
    response = parse_chunk(data, next_offset)
    next_offset = response["nextOffset"]
    albumList.append(response["result"])

  return albumList