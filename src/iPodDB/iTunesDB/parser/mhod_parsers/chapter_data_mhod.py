import struct

from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.chapter_data_mhod import (
    MhodChapterDataChapHeader,
    MhodChapterDataChapter,
    MhodChapterDataHedrHeader,
    MhodChapterDataNameHeader,
    MhodChapterDataPayload,
    MhodChapterDataPreamble,
    MhodChapterDataRawAtom,
    MhodChapterDataSeanHeader,
)
from iPodDB.shared.binary_struct import parse_binary_struct
from iPodDB.shared.types import MhodPayloadParseContext

_UINT32_LE = struct.Struct("<I")
_UINT32_BE = struct.Struct(">I")


def _get_atom_bounds(
    data: bytes | bytearray,
    offset: int,
    container_end: int,
) -> tuple[int, bytes, int]:
    """
    Read the common first 8 bytes of a chapter-data atom.

    Returns:
        total_size, atom_type, atom_end
    """

    if offset + 8 > container_end:
        raise ValueError(
            f"chapter-data atom header at {offset:#x} "
            f"extends past container end {container_end:#x}"
        )

    total_size = _UINT32_BE.unpack_from(data, offset)[0]
    atom_type = bytes(data[offset + 4 : offset + 8])

    if total_size < 8:
        raise ValueError(
            f"chapter-data atom {atom_type!r} "
            f"at {offset:#x} has invalid size {total_size}"
        )

    atom_end = offset + total_size

    if atom_end > container_end:
        raise ValueError(
            f"chapter-data atom {atom_type!r} "
            f"at {offset:#x} extends past its container: "
            f"{atom_end:#x} > {container_end:#x}"
        )

    return total_size, atom_type, atom_end


def _parse_name_atom(
    data: bytes | bytearray,
    offset: int,
    atom_end: int,
) -> tuple[str, MhodChapterDataNameHeader, bytes]:
    if offset + 0x16 > atom_end:
        raise ValueError(
            f"name atom at {offset:#x} is too short for its 22-byte header"
        )

    header = parse_binary_struct(
        data,
        offset,
        MhodChapterDataNameHeader,
        limit=atom_end,
    )

    if header.atom_type != b"name":
        raise ValueError(f"expected b'name' at {offset:#x}, got {header.atom_type!r}")

    string_offset = offset + 0x16
    string_end = string_offset + header.string_length * 2

    if string_end > atom_end:
        raise ValueError(
            f"name atom at {offset:#x} declares "
            f"{header.string_length} UTF-16BE code units, "
            "which exceeds the atom boundary"
        )

    raw_name = bytes(data[string_offset:string_end])

    return (
        raw_name.decode(
            "utf-16-be",
            errors="replace",
        ),
        header,
        bytes(data[string_end:atom_end]),
    )


def _parse_chap_atom(
    data: bytes | bytearray,
    offset: int,
    atom_end: int,
) -> MhodChapterDataChapter:
    if offset + 0x14 > atom_end:
        raise ValueError(
            f"chap atom at {offset:#x} is too short for its 20-byte header"
        )

    header = parse_binary_struct(
        data,
        offset,
        MhodChapterDataChapHeader,
        limit=atom_end,
    )

    if header.atom_type != b"chap":
        raise ValueError(f"expected b'chap' at {offset:#x}, got {header.atom_type!r}")

    child_offset = offset + 0x14

    name = ""
    name_header: MhodChapterDataNameHeader | None = None
    name_atom_index: int | None = None
    name_trailing_data = b""
    name_atom_raw: bytes | None = None
    other_atoms: list[MhodChapterDataRawAtom] = []

    for _ in range(header.child_count):
        _, atom_type, child_end = _get_atom_bounds(
            data,
            child_offset,
            atom_end,
        )

        if atom_type == b"name":
            # Retain the parser's established last-name-wins behavior while
            # preserving every earlier duplicate as an opaque atom in place.
            if name_atom_raw is not None:
                assert name_atom_index is not None
                other_atoms.insert(
                    name_atom_index,
                    MhodChapterDataRawAtom(
                        atom_type=b"name",
                        raw=name_atom_raw,
                    ),
                )
            name, name_header, name_trailing_data = _parse_name_atom(
                data,
                child_offset,
                child_end,
            )
            name_atom_index = len(other_atoms)
            name_atom_raw = bytes(data[child_offset:child_end])

        else:
            other_atoms.append(
                MhodChapterDataRawAtom(
                    atom_type=atom_type,
                    raw=bytes(data[child_offset:child_end]),
                )
            )

        child_offset = child_end

    return MhodChapterDataChapter(
        name=name,
        start_pos_ms=header.start_position_ms,
        other_atoms=tuple(other_atoms),
        chap_header=header,
        name_header=name_header,
        name_atom_index=name_atom_index,
        name_trailing_data=name_trailing_data,
        trailing_data=bytes(data[child_offset:atom_end]),
    )


def parse_chapter_data_payload(
    context: MhodPayloadParseContext[None],
) -> MhodChapterDataPayload:
    data = context.data
    payload_offset = context.payload_offset
    payload_end = context.payload_end

    preamble_end = payload_offset + 0x0C

    if preamble_end > payload_end:
        raise ValueError(
            f"MHOD 17 at {context.chunk_offset:#x} "
            "is too short for its 12-byte preamble"
        )

    preamble = MhodChapterDataPreamble(
        unk_0x18=_UINT32_LE.unpack_from(
            data,
            payload_offset,
        )[0],
        unk_0x1C=_UINT32_LE.unpack_from(
            data,
            payload_offset + 0x04,
        )[0],
        unk_0x20=_UINT32_LE.unpack_from(
            data,
            payload_offset + 0x08,
        )[0],
    )

    sean_offset = preamble_end

    if sean_offset + 0x14 > payload_end:
        raise ValueError(
            f"MHOD 17 at {context.chunk_offset:#x} is too short for its sean atom"
        )

    _, atom_type, sean_end = _get_atom_bounds(
        data,
        sean_offset,
        payload_end,
    )

    if atom_type != b"sean":
        raise ValueError(
            f"MHOD 17 at {context.chunk_offset:#x} "
            f"expected b'sean' at {sean_offset:#x}, "
            f"got {atom_type!r}"
        )

    sean = parse_binary_struct(
        data,
        sean_offset,
        MhodChapterDataSeanHeader,
        limit=sean_end,
    )

    child_offset = sean_offset + 0x14

    chapters: list[MhodChapterDataChapter] = []
    chapter_atom_indices: list[int] = []
    other_atoms: list[MhodChapterDataRawAtom] = []
    hedr: MhodChapterDataHedrHeader | None = None
    hedr_atom_index: int | None = None
    hedr_other_atom_index: int | None = None
    hedr_raw: bytes | None = None
    hedr_trailing_data = b""

    for child_index in range(sean.child_count):
        _, child_type, child_end = _get_atom_bounds(
            data,
            child_offset,
            sean_end,
        )

        if child_type == b"chap":
            chapter = _parse_chap_atom(
                data,
                child_offset,
                child_end,
            )

            chapters.append(chapter)
            chapter_atom_indices.append(child_index)

        elif child_type == b"hedr":
            if child_offset + 0x1C > child_end:
                raise ValueError(
                    f"hedr atom at {child_offset:#x} "
                    "is too short for its 28-byte header"
                )

            # The last hedr is the editable semantic header. Earlier duplicates
            # remain opaque atoms so an edit cannot erase or reorder them.
            if hedr_raw is not None:
                assert hedr_other_atom_index is not None
                other_atoms.insert(
                    hedr_other_atom_index,
                    MhodChapterDataRawAtom(
                        atom_type=b"hedr",
                        raw=hedr_raw,
                    ),
                )

            hedr = parse_binary_struct(
                data,
                child_offset,
                MhodChapterDataHedrHeader,
                limit=child_end,
            )
            hedr_atom_index = child_index
            hedr_other_atom_index = len(other_atoms)
            hedr_raw = bytes(data[child_offset:child_end])
            hedr_trailing_data = bytes(data[child_offset + 0x1C : child_end])

        else:
            other_atoms.append(
                MhodChapterDataRawAtom(
                    atom_type=child_type,
                    raw=bytes(data[child_offset:child_end]),
                )
            )

        child_offset = child_end

    if child_offset != sean_end:
        raise ValueError(
            f"MHOD 17 sean atom at {sean_offset:#x} "
            f"ended parsing at {child_offset:#x}, "
            f"but declared end is {sean_end:#x}"
        )

    if sean_end != payload_end:
        raise ValueError(
            f"MHOD 17 at {context.chunk_offset:#x} "
            f"has {payload_end - sean_end} trailing bytes "
            "after its sean atom"
        )

    return MhodChapterDataPayload(
        preamble=preamble,
        sean=sean,
        hedr=hedr,
        chapters=tuple(chapters),
        other_atoms=tuple(other_atoms),
        chapter_atom_indices=tuple(chapter_atom_indices),
        hedr_atom_index=hedr_atom_index,
        hedr_trailing_data=hedr_trailing_data,
    )
