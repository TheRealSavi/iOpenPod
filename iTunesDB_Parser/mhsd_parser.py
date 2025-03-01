import struct

def parse_dataset(data, offset, header_length, chunk_length) -> dict:
  from .chunk_parser import parse_chunk

  datasetType = struct.unpack("<I", data[offset+12:offset+16])[0]
  # In order for the iPod to list podcasts
  # the type 3 Data Set MUST come between the type 1 and type 2 Data Sets.

  #Parse Child
  next_offset = offset + header_length
  childResult = parse_chunk(data, next_offset)
  return {"datasetType": datasetType, "result": childResult, "nextOffset": offset+chunk_length}