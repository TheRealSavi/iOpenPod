"""Type-6 MHAF bodies use the enclosing MHOD extent, not a guessed Chunk size."""

from dataclasses import replace
from struct import pack

from iPodDB.ArtworkDB.builder.build_ArtworkDB import new_artwork_chunk, new_ArtworkDB
from iPodDB.ArtworkDB.parser.parse_ArtworkDB import parse_ArtworkDB
from iPodDB.ArtworkDB.shared.chunk_defs.mhii import DEFINITION as MHII
from iPodDB.ArtworkDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhod import DEFINITION as MHOD
from iPodDB.ArtworkDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhod_payloads.opaque_mhod import (
    MhodOpaquePayload,
)
from iPodDB.ArtworkDB.writer.write_ArtworkDB import write_ArtworkDB


def auxiliary_body() -> bytes:
    # Observed in the local Nano 5 and Nano 7 captures and Original iOpenPod's
    # writer: these words are 96 and 60, so they cannot be generic Chunk lengths.
    return b"mhaf" + pack("<II", 96, 60) + bytes(84)


def test_type6_auxiliary_body_survives_creation_parse_and_parent_edit() -> None:
    body = auxiliary_body()
    row = new_artwork_chunk(
        MHII,
        MhiiHeader(image_id=100),
        children=(
            new_artwork_chunk(
                MHOD, MhodHeader(mhod_type=6), payload=MhodOpaquePayload(body)
            ),
        ),
    )
    encoded = write_ArtworkDB(
        new_ArtworkDB(next_mhii_id=101, unk_mhfd_0x10=6, image_items=(row,))
    )
    parsed = parse_ArtworkDB(encoded)
    assert write_ArtworkDB(parsed) == encoded
    auxiliary = parsed.find_chunks(MhodHeader)[0].chunk
    assert auxiliary.payload == MhodOpaquePayload(body)
    selection = parsed.find_chunks(MhiiHeader)[0]
    edited = parsed.replace_chunk(
        selection,
        replace(
            selection.chunk,
            header=replace(selection.chunk.header, source_image_size=24),
        ),
    )
    reread = parse_ArtworkDB(write_ArtworkDB(edited))
    assert reread.find_chunks(MhodHeader)[0].chunk.raw_body == body
