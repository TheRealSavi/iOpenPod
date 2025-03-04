import struct

def parse_chunk(data, offset) -> dict:
  chunk_type = data[offset:offset+4].decode("utf-8")
  header_length = struct.unpack("<I", data[offset+4:offset+8])[0]
  chunk_length = struct.unpack("<I", data[offset+8:offset+12])[0]

  match chunk_type:
    case "mhfd":
      #Data file
      return
    case "mhsd":
      #Data Set
      return
    case "mhli":
      #Image List
      return
    case "mhii":
      #Image Item
      return
    case "mhni":
      #Image Name
      return
    case "mhla":
      #Photo Album List
      return
    case "mhba":
      #Photo Album
      return
    case "mhia":
      #Photo Album Item
      return
    case "mhlf":
      #File List
      return
    case "mhif":
      #File Item
      return
    case "mhod":
      #Data Object
      return
    case _:
      raise ValueError(f"Unknown chunk type: {chunk_type}")
