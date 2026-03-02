"""
iTunesDB entry-point parser.

Accepts a file path (str) or file-like readable object pointing to
an iPod's ``/iPod_Control/iTunes/iTunesDB`` binary file.  Returns
the fully-parsed database as a nested dict/list structure.

Usage::

    from iTunesDB_Parser.parser import parse_itunesdb
    db = parse_itunesdb("/Volumes/IPOD/iPod_Control/iTunes/iTunesDB")
"""


def parse_itunesdb(file) -> dict:
    from .chunk_parser import parse_chunk

    if isinstance(file, str):  # If it's a file path, open the file
        with open(file, "rb") as f:
            data = f.read()
    elif hasattr(file, "read"):  # If it's a file-like object, read it directly
        data = file.read()
    else:
        raise TypeError("file must be a path (str) or a file-like object")

    result = parse_chunk(data, 0)

    # Return just the parsed data, not the wrapper with nextOffset
    return result.get("result", result)
