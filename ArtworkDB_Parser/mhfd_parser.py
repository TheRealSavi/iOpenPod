import base64
import struct


def parse_mhfd(data, offset, header_length, chunk_length) -> dict:
  from .chunk_parser import parse_chunk
  from .constants import chunk_type_map

  datafile = {}

  datafile["unk1"] = struct.unpack("<I", data[offset+12:offset+16])[0] #always 0
  datafile["unk2"] = struct.unpack("<I", data[offset+16:offset+20])[0] #1 until iTunes 4.9. 2 after

  datafile["childCount"] = struct.unpack("<I", data[offset+20:offset+24])[0] 

  datafile["unk3"] = struct.unpack("<I", data[offset+24:offset+28])[0] #always 0

  #ID of last mhii + 1. On iPod video seems to be last mhii + mhba count + 1
  datafile["next_mhii_id"] = struct.unpack("<I", data[offset+28:offset+32])[0]

  datafile["unk4"] = struct.unpack("<Q", data[offset+32:offset+40])[0]
  datafile["unk5"] = struct.unpack("<Q", data[offset+40:offset+48])[0]
  
  datafile["unk6"] = struct.unpack("<I", data[offset+48:offset+52])[0] #always 2
  datafile["unk7"] = struct.unpack("<I", data[offset+52:offset+56])[0] #always 0
  datafile["unk8"] = struct.unpack("<I", data[offset+56:offset+60])[0] #always 0

  datafile["unk9"] =  struct.unpack("<I", data[offset+60:offset+64])[0] 
  datafile["unk10"] = struct.unpack("<I", data[offset+64:offset+68])[0] 

  #parse children
  next_offset = offset + header_length
  for i in range(datafile["childCount"]):
    childResult = parse_chunk(data, next_offset)
    next_offset = childResult["nextOffset"]
    resultData = childResult["result"]
    resultType = childResult["datasetType"]
    datafile[chunk_type_map[resultType]] = resultData

    #TODO: TEMPORARY FIX FOR FIXING BYTE DATA INTO BASE64 TO BE JSON WRITABLE
    def replace_bytes_with_base64(data):
      if isinstance(data, dict):  # If it's a dictionary, process each key-value pair
        return {key: replace_bytes_with_base64(value) for key, value in data.items()}
      elif isinstance(data, list):  # If it's a list, process each item
        return [replace_bytes_with_base64(item) for item in data]
      elif isinstance(data, bytes):  # If it's bytes, encode to Base64
        return base64.b64encode(data).decode("utf-8")
      else:
        return data  # If it's not bytes, return as-is

    cleaned_database = replace_bytes_with_base64(datafile)

    return cleaned_database

  