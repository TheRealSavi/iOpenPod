"""
ArtworkDB Writer for iPod Classic/Nano.

Writes ArtworkDB binary files and .ithmb image files from PC music
file embedded album art.

Usage:
    from ArtworkDB_Writer import write_artworkdb

    # pc_file_paths maps track dbid → PC source file path
    dbid_to_art = write_artworkdb(
        ipod_path="/media/ipod",
        tracks=track_list,
        pc_file_paths={12345: "/home/user/Music/song.mp3", ...},
    )

    # Then set mhiiLink and artworkSize on each track in iTunesDB
    for track in tracks:
        art_info = dbid_to_art.get(track.dbid)
        if art_info:
            img_id, src_size = art_info
            track.mhii_link = img_id
            track.artwork_size = src_size
"""

from .artwork_writer import write_artworkdb, ArtworkEntry
from .art_extractor import extract_art, art_hash
from .rgb565 import (
    convert_art_for_ipod,
    image_from_bytes,
    rgb888_to_rgb565,
    IPOD_CLASSIC_FORMATS,
)

__all__ = [
    'write_artworkdb',
    'ArtworkEntry',
    'extract_art',
    'art_hash',
    'convert_art_for_ipod',
    'image_from_bytes',
    'rgb888_to_rgb565',
    'IPOD_CLASSIC_FORMATS',
]
