"""Evidence-bounded image-list repair for the nominal MHFD database families."""

from collections.abc import Callable
from dataclasses import dataclass, replace

from iPodDB.shared.binary_struct import (
    binary_fields,
    binary_struct_extent,
    parse_binary_struct,
    write_binary_struct_into,
)
from iPodDB.shared.chunk import (
    ChunkHeader,
    DatabaseDocument,
    EmptyChunkHeader,
    GenericHeader,
    MhsdChunkHeader,
)
from iPodDB.shared.chunk_reader import parse_chunk_as
from iPodDB.shared.types import (
    ChunkDefinition,
    DatabaseParserDefinition,
    MhsdDatasetDefinition,
)


@dataclass(frozen=True, slots=True)
class ImageListCountRepair:
    """A list count established by complete records inside its dataset extent."""

    list_offset: int
    previous_count: int
    corrected_count: int


@dataclass(frozen=True, slots=True)
class ImageListRepairResult[RootH: ChunkHeader]:
    data: bytes
    document: DatabaseDocument[RootH]
    repairs: tuple[ImageListCountRepair, ...]


def repair_image_list_counts[RootH: ChunkHeader, ImageH: ChunkHeader](
    data: bytes | bytearray,
    *,
    parser_definition: DatabaseParserDefinition[RootH],
    parse: Callable[[bytes], DatabaseDocument[RootH]],
    image_dataset_type: int,
    image_definition: ChunkDefinition[ImageH],
    image_identity: Callable[[ImageH], int],
) -> ImageListRepairResult[RootH]:
    """Correct only counts proved by the supplied artifact's structural parser.

    The registered root count and dataset lengths bound every read. Complete,
    contiguous image records must fill their dataset; opaque suffixes, incomplete
    children and duplicate identities cannot authorize a repair. No image bytes,
    record lengths, other datasets or source suffixes change.
    """
    definition = parser_definition.database
    definition.require_registered(image_definition)
    dataset_definition = definition.chunk_definition(b"mhsd")
    image_dataset = definition.dataset_definition(image_dataset_type)
    if dataset_definition is None or not isinstance(
        image_dataset, MhsdDatasetDefinition
    ):
        raise ValueError(
            "Image count repair requires registered MHSD and image-list definitions"
        )
    root_counts = tuple(
        field.attribute_name
        for field in binary_fields(definition.root_chunk.header_type)
        if field.schema.counts_children
    )
    if len(root_counts) != 1:
        raise ValueError("Image count repair requires one registered root child count")

    source = bytes(data)
    candidate: bytearray | None = None
    repairs: list[ImageListCountRepair] = []
    root = _bounded_header(source, 0, len(source), definition.root_chunk)
    if root is not None:
        root_end = root.length_or_child_count
        root_header = parse_binary_struct(
            source, 0, definition.root_chunk.header_type, limit=root.header_length
        )
        count = getattr(root_header, root_counts[0])
        if type(count) is not int:
            raise ValueError("The registered root child count must be an integer")
        dataset_offset = root.header_length
        for _ in range(count):
            dataset = _bounded_header(
                source, dataset_offset, root_end, dataset_definition
            )
            if dataset is None:
                break
            dataset_end = dataset_offset + dataset.length_or_child_count
            header = parse_binary_struct(
                source,
                dataset_offset,
                dataset_definition.header_type,
                limit=dataset_offset + dataset.header_length,
            )
            if not isinstance(header, MhsdChunkHeader):
                raise ValueError("The registered MHSD requires a dataset header")
            if header.dataset_type == image_dataset_type:
                repair = _image_count_repair(
                    source,
                    dataset_offset + dataset.header_length,
                    dataset_end,
                    image_dataset.child_definition,
                    image_definition,
                    parser_definition,
                    image_identity,
                )
                if repair is not None:
                    if candidate is None:
                        candidate = bytearray(source)
                    repairs.append(repair)
                    generic = parse_binary_struct(
                        source, repair.list_offset, GenericHeader
                    )
                    write_binary_struct_into(
                        candidate,
                        replace(generic, length_or_child_count=repair.corrected_count),
                        offset=repair.list_offset,
                        limit=repair.list_offset + generic.header_length,
                    )
            dataset_offset = dataset_end
    corrected = source if candidate is None else bytes(candidate)
    document = parse(corrected)
    if repairs:
        identities = [
            image_identity(selection.chunk.header)
            for selection in document.find_chunks(image_definition.header_type)
        ]
        if len(set(identities)) != len(identities):
            # Separate image datasets can conflict even if each local candidate
            # is unique. Retain the strict original prefix; choose no winner.
            return ImageListRepairResult(source, parse(source), ())
    return ImageListRepairResult(corrected, document, tuple(repairs))


def _bounded_header[H: ChunkHeader](
    data: bytes,
    offset: int,
    end: int,
    definition: ChunkDefinition[H],
) -> GenericHeader | None:
    if offset + binary_struct_extent(GenericHeader) > end:
        return None
    header = parse_binary_struct(data, offset, GenericHeader, limit=end)
    if (
        header.header_marker != definition.marker
        or header.header_length < definition.minimum_header_size
        or offset + header.header_length > end
    ):
        return None
    if definition.extent_type == "length" and (
        header.length_or_child_count < header.header_length
        or offset + header.length_or_child_count > end
    ):
        return None
    return header


def _image_count_repair[RootH: ChunkHeader, ImageH: ChunkHeader](
    data: bytes,
    list_offset: int,
    dataset_end: int,
    list_definition: ChunkDefinition[EmptyChunkHeader],
    image_definition: ChunkDefinition[ImageH],
    parser_definition: DatabaseParserDefinition[RootH],
    image_identity: Callable[[ImageH], int],
) -> ImageListCountRepair | None:
    image_list = _bounded_header(data, list_offset, dataset_end, list_definition)
    if image_list is None:
        return None
    image_offset = list_offset + image_list.header_length
    image_offsets: list[int] = []
    while image_offset < dataset_end:
        image = _bounded_header(data, image_offset, dataset_end, image_definition)
        if image is None:
            # An opaque suffix or incomplete record cannot establish the count.
            return None
        image_offsets.append(image_offset)
        image_offset += image.length_or_child_count
    count = len(image_offsets)
    if count == image_list.length_or_child_count:
        return None
    bounded_data = data[:dataset_end]
    identities: set[int] = set()
    for offset in image_offsets:
        try:
            parsed_image, _ = parse_chunk_as(
                bounded_data,
                offset,
                image_definition,
                parser_definition=parser_definition,
            )
        except ValueError:
            return None
        identity = image_identity(parsed_image.header)
        if identity in identities:
            return None
        identities.add(identity)
    return ImageListCountRepair(list_offset, image_list.length_or_child_count, count)
