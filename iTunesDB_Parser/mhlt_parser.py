from typing import List

def parse_trackList(data, offset, header_length, trackCount) -> List[dict]:
  from .chunk_parser import parse_chunk

  trackList = []

  #Parse Children
  next_offset = offset+header_length
  for i in range(trackCount):
    response = parse_chunk(data, next_offset)
    next_offset = response["nextOffset"]
    trackList.append(response["result"])

  return trackList