"""Semantic-only Extras chapter encoding through the shared Chunk definitions."""

from iPodDB.iTunesDB.builder.build_iTunesDB import new_itunes_chunk
from iPodDB.iTunesDB.shared.chunk_defs.mhod import DEFINITION as MHOD
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.chapter_data_mhod import (
    MhodChapterDataChapter,
    MhodChapterDataHedrHeader,
    MhodChapterDataNameHeader,
    MhodChapterDataPayload,
    MhodChapterDataPreamble,
    MhodChapterDataSeanHeader,
)
from iPodDB.iTunesDB.shared.constants import MhodPayloadKind, MhodType
from iPodDB.iTunesDB.writer.mhod_encoder import encode_mhod_body
from iPodDB.library.models import TrackChapter


def chapter_blob(chapters: tuple[TrackChapter, ...]) -> bytes:
    for chapter in chapters:
        if not 0 <= chapter.start_ms <= 0xFFFFFFFF:
            raise ValueError("A chapter position must fit an unsigned 32-bit field")
    chunk = new_itunes_chunk(
        MHOD,
        MhodHeader(mhod_type=MhodType.CHAPTER_DATA),
        payload=MhodChapterDataPayload(
            MhodChapterDataPreamble(0, 0, 0),
            MhodChapterDataSeanHeader(atom_type=b"sean", unk_0x08=1),
            MhodChapterDataHedrHeader(atom_type=b"hedr", unk_0x08=1, unk_0x18=1),
            tuple(
                MhodChapterDataChapter(
                    chapter.title,
                    chapter.start_ms,
                    (),
                    name_header=MhodChapterDataNameHeader(
                        atom_type=b"name", unk_0x08=1
                    ),
                )
                for chapter in chapters
            ),
            (),
        ),
    )
    data, _ = encode_mhod_body(chunk, MhodPayloadKind.CHAPTER_DATA)
    return data
