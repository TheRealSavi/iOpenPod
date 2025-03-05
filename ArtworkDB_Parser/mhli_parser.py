def parse_mhli(data,offset, header_length, imageCount) -> dict:
  from .chunk_parser import parse_chunk

  imageList = []

  #Parse Children
  next_offset = offset+header_length
  for i in range(imageCount):
    response = parse_chunk(data, next_offset)
    next_offset = response["nextOffset"]
    imageList.append(response["result"])

  return imageList
