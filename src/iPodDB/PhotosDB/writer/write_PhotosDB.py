"""Lossless, definition-driven PhotosDB serialization."""

from iPodDB.ArtworkDB.writer.mhod_serializer import serialize_artwork_mhod_body
from iPodDB.PhotosDB.shared.chunk_defs.mhfd import MhfdHeader
from iPodDB.PhotosDB.shared.database_definition import DATABASE_DEFINITION
from iPodDB.shared.chunk import DatabaseDocument
from iPodDB.shared.chunk_writer import serialize_database


def write_PhotosDB(database: DatabaseDocument[MhfdHeader]) -> bytes:
    """Serialize a Photo Database through the shared structural writer.

    Raises:
        iPodDBWriteError: The Chunk tree cannot be serialized losslessly.
        TypeError: A Chunk uses a header or payload representation of the wrong type.
    """

    return serialize_database(
        database,
        DATABASE_DEFINITION,
        serialize_artwork_mhod_body,
    )
