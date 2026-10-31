"""Canonical F1061 authoring repair over captured bytes, without device I/O.

Repair is a separate final pass over an already verified Library candidate.
It preserves identities, times, unknown records and every existing file byte.
New rasters use fresh shards; their metadata and pixels are verified before
publication. Unsupported or unavailable source data remains untouched.
"""

from contextlib import suppress
from dataclasses import dataclass, replace
from hashlib import sha256

from iPodDB.ArtworkDB.ithmb import (
    DecodedImage,
    IthmbLayout,
    IthmbPixelFormat,
    decode_ithmb,
)
from iPodDB.ArtworkDB.ithmb_writer import encode_ithmb
from iPodDB.ArtworkDB.parser.parse_ArtworkDB import parse_ArtworkDB
from iPodDB.ArtworkDB.shared.artwork_index import thumbnail_payload
from iPodDB.ArtworkDB.shared.chunk_defs.mhfd import MhfdHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhif import MhifHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhni import MhniHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhod_payloads.container_mhod import (
    MhodContainerPayload,
)
from iPodDB.ArtworkDB.shared.chunk_defs.mhod_payloads.string_mhod import (
    MhodStringPayload,
)
from iPodDB.ArtworkDB.shared.constants import ArtworkMhodType
from iPodDB.ArtworkDB.writer.write_ArtworkDB import write_ArtworkDB
from iPodDB.library._artwork_paths import artwork_path
from iPodDB.library._document_edit import rebuild
from iPodDB.library.artwork import CoverFormat
from iPodDB.library.file_content import ContentBuffer, MemoryContentBuffer, read_content
from iPodDB.library.writing import (
    IssueSeverity,
    PreparedFile,
    WriteIssue,
    WriteResources,
    WriteTarget,
)
from iPodDB.shared.chunk import ChunkHeader, DatabaseDocument, ParsedChunk

_NATIVE = IthmbLayout(55, 55, 112, IthmbPixelFormat.RGB565_LE)
_SIZE = 6160


def _native_target(target: WriteTarget) -> bool:
    return any(
        (f.format_id, f.width, f.height, f.row_bytes, f.pixel_format)
        == (1061, 55, 55, 112, IthmbPixelFormat.RGB565_LE)
        for f in target.cover_formats
    )


def _needs_repair(header: MhniHeader) -> bool:
    return header.format_id == 1061 and (
        header.image_size != _SIZE
        or not 0 <= header.horizontal_padding < header.image_width <= 55
        or not 0 <= header.vertical_padding < header.image_height <= 55
        or (header.image_size_2 != 0 and header.image_size_2 < _SIZE)
    )


def _path(location: ParsedChunk[MhniHeader]) -> str:
    names = [
        c.payload.value
        for c in location.children
        if _filename(c) and isinstance(c.payload, MhodStringPayload)
    ]
    if len(names) != 1:
        raise ValueError("A thumbnail needs one unambiguous filename.")
    return artwork_path(names[0])


def _filename(child: ParsedChunk[ChunkHeader]) -> bool:
    return (
        isinstance(child.header, MhodHeader)
        and child.header.mhod_type == ArtworkMhodType.FILE_NAME
        and isinstance(child.payload, MhodStringPayload)
    )


def geometry_requirements(
    artwork: DatabaseDocument[MhfdHeader] | None,
    target: WriteTarget,
) -> tuple[bool, tuple[str, ...]]:
    """Describe repair and full source capture needs without guessing file access."""
    if artwork is None or not _native_target(target):
        return False, ()
    required = any(
        s.chunk.header.format_id == 1061 and s.chunk.header.image_size != _SIZE
        for s in artwork.find_chunks(MhifHeader)
    )
    paths: set[str] = set()
    for selection in artwork.find_chunks(MhiiHeader):
        locations = tuple(
            p.child
            for c in selection.chunk.children
            if (p := thumbnail_payload(c)) is not None
        )
        times = {c.header.image_time_key for c in locations if _needs_repair(c.header)}
        if not times:
            continue
        required = True
        for location in locations:
            if (
                location.header.image_time_key in times
                and location.header.format_id in (1055, 1060, 1061)
            ):
                with suppress(ValueError):
                    paths.add(_path(location))
    return required, tuple(sorted(paths))


@dataclass(frozen=True, slots=True)
class _Replacement:
    image_id: int
    child_index: int
    original: ParsedChunk[MhniHeader]
    header: MhniHeader
    filename: str
    digest: str | None


def repair_geometry(
    data: bytes | None,
    files: tuple[PreparedFile, ...],
    target: WriteTarget,
    resources: WriteResources,
) -> tuple[bytes | None, tuple[PreparedFile, ...], tuple[WriteIssue, ...]]:
    """Repair evidenced legacy F1061 rasters; defer unsafe records individually."""
    if data is None or not _native_target(target):
        return data, files, ()
    document = parse_ArtworkDB(data)
    required, _ = geometry_requirements(document, target)
    if not required:
        return data, files, ()
    if resources.file_inventory is None:
        return (
            data,
            files,
            (_deferred(None, "A captured thumbnail inventory is required."),),
        )
    inventory = {f.relative_path.casefold(): f for f in resources.file_inventory}
    sources = {f.dependency.relative_path.casefold(): f for f in resources.files}
    outputs = {f.relative_path.casefold(): f.data for f in files}
    reserved = (
        set(inventory)
        | set(outputs)
        | {p.casefold() for p in resources.reserved_artwork_paths}
    )
    extents: dict[str, set[tuple[int, int]]] = {}
    for selection in document.find_chunks(MhiiHeader):
        for child in selection.chunk.children:
            if not isinstance(child.payload, MhodContainerPayload):
                continue
            location = child.payload.child
            try:
                path = _path(location).casefold()
            except ValueError:
                continue
            reserved.add(path)
            h = location.header
            extents.setdefault(path, set()).add(
                (h.ithmb_offset, h.ithmb_offset + max(h.image_size, h.image_size_2))
            )
    formats = {f.format_id: f for f in target.cover_formats}
    ambiguous: dict[str, set[tuple[int, int]]] = {}
    for path, ranges in extents.items():
        furthest = (0, 0)
        for extent in sorted(ranges):
            if extent[0] < furthest[1]:
                ambiguous.setdefault(path, set()).update((furthest, extent))
            if extent[1] > furthest[1]:
                furthest = extent
    buffers: dict[str, ContentBuffer] = {}
    replacements: list[_Replacement] = []
    changes: dict[int, ParsedChunk[ChunkHeader] | None] = {}
    issues: list[WriteIssue] = []
    number = 1
    limit = min(target.max_artwork_file_bytes, 0xFFFFFFFF)

    def pixels(location: ParsedChunk[MhniHeader], cover: CoverFormat) -> DecodedImage:
        h = location.header
        path = _path(location).casefold()
        allocation = h.image_size_2 or h.image_size
        extent = (h.ithmb_offset, h.ithmb_offset + allocation)
        if allocation < h.image_size or extent in ambiguous.get(path, ()):
            raise ValueError(
                "Thumbnail allocations overlap or do not contain the raster."
            )
        dependency = inventory.get(path)
        source = sources.get(path)
        content = outputs.get(path)
        if content is None:
            if dependency is None or source is None or source.dependency != dependency:
                raise ValueError(
                    "The thumbnail's complete captured source is unavailable."
                )
            content = source.data
        if extent[0] < 0 or extent[1] > len(content):
            raise ValueError("The thumbnail allocation is outside its captured file.")
        max_width, max_height = cover.width, cover.height
        if h.format_id == 1061:
            if h.image_size not in (6160, 6272):
                raise ValueError(
                    "The F1061 row layout is not established; use another representation."
                )
            max_width, max_height = 56, h.image_size // 112
        if not (
            0 <= h.horizontal_padding < h.image_width <= max_width
            and 0 <= h.vertical_padding < h.image_height <= max_height
        ):
            raise ValueError("The thumbnail's visible geometry is not established.")
        return decode_ithmb(
            read_content(content, h.ithmb_offset, h.image_size),
            IthmbLayout(
                h.image_width,
                h.image_height,
                cover.row_bytes,
                cover.pixel_format,
                h.horizontal_padding,
                h.vertical_padding,
            ),
        )

    def append(encoded: bytes) -> tuple[str, int]:
        nonlocal number
        if len(encoded) > limit:
            raise ValueError("The native F1061 raster exceeds the artwork file limit.")
        while True:
            path = f"iPod_Control/Artwork/F1061_{number}.ithmb"
            buffer = buffers.get(path)
            if path.casefold() in reserved or (
                buffer is not None and len(buffer) + len(encoded) > limit
            ):
                number += 1
                continue
            if buffer is None:
                buffer = (resources.create_file_buffer or MemoryContentBuffer)()
                buffers[path] = buffer
            offset = len(buffer)
            buffer.append(encoded)
            return path, offset

    for selection in document.find_chunks(MhiiHeader):
        row = selection.chunk
        children = list(row.children)
        for index, child in enumerate(row.children):
            payload = thumbnail_payload(child)
            if payload is None or not _needs_repair(payload.child.header):
                continue
            location = payload.child
            h = location.header
            try:
                _path(location)
            except ValueError as error:
                issues.append(_deferred(row.header.image_id, str(error)))
                continue
            # Preserve this rendition when its storage is understood. A damaged
            # or tight/truncated raster may use a valid primary rendition at the
            # SAME time; never another Chapter or a video-associated thumbnail.
            candidates = [
                location,
                *sorted(
                    (
                        p.child
                        for c in row.children
                        if (p := thumbnail_payload(c)) is not None
                        and p.child.header.image_time_key == h.image_time_key
                        and p.child.header.format_id in (1055, 1060)
                        and p.child.header.format_id in formats
                    ),
                    key=lambda c: formats[c.header.format_id].width,
                    reverse=True,
                ),
            ]
            reason = "No proven source representation is available."
            image: DecodedImage | None = None
            source_location: ParsedChunk[MhniHeader] | None = None
            for candidate in candidates:
                try:
                    image = pixels(candidate, formats[candidate.header.format_id])
                    source_location = candidate
                    break
                except ValueError as error:
                    reason = str(error)
            if image is None or source_location is None:
                issues.append(_deferred(row.header.image_id, reason))
                continue
            if (
                source_location is location
                and h.image_width <= 55
                and h.image_height <= 55
            ):
                # Extra stored rows are not visible pixels. Keep the established
                # allocation and exact pixels; only bound the native read length.
                header = replace(
                    h, image_size=_SIZE, image_size_2=max(h.image_size, h.image_size_2)
                )
                children[index] = replace(
                    child,
                    payload=replace(payload, child=replace(location, header=header)),
                )
                replacements.append(
                    _Replacement(
                        row.header.image_id,
                        index,
                        location,
                        header,
                        _path(location),
                        None,
                    )
                )
                continue
            encoded = encode_ithmb(image, _NATIVE)
            path, offset = append(encoded)
            header = replace(
                h,
                ithmb_offset=offset,
                image_size=_SIZE,
                image_size_2=_SIZE,
                image_width=55,
                image_height=55,
                horizontal_padding=0,
                vertical_padding=0,
            )
            filename = ":" + path.rsplit("/", 1)[1]
            names = tuple(
                replace(c, payload=replace(c.payload, value=filename))
                if _filename(c) and isinstance(c.payload, MhodStringPayload)
                else c
                for c in location.children
            )
            children[index] = replace(
                child,
                payload=replace(
                    payload, child=replace(location, header=header, children=names)
                ),
            )
            replacements.append(
                _Replacement(
                    row.header.image_id,
                    index,
                    location,
                    header,
                    filename,
                    sha256(encoded).hexdigest(),
                )
            )
        if tuple(children) != row.children:
            changes[id(row)] = replace(row, children=tuple(children))
    # A nominal format size must not conceal an unresolved unsupported raster.
    if not issues:
        for format_selection in document.find_chunks(MhifHeader):
            if (
                format_selection.chunk.header.format_id == 1061
                and format_selection.chunk.header.image_size != _SIZE
            ):
                changes[id(format_selection.chunk)] = replace(
                    format_selection.chunk,
                    header=replace(format_selection.chunk.header, image_size=_SIZE),
                )
    if not changes:
        return data, files, tuple(issues)
    corrected = write_ArtworkDB(rebuild(document, changes))
    created = tuple(
        PreparedFile(path, buffer.finish()) for path, buffer in buffers.items()
    )
    _verify_repair(data, corrected, created, replacements, reserved, limit, not issues)
    issues.append(
        WriteIssue(
            "artwork.geometry_repaired",
            "Existing album artwork was corrected for this iPod.",
            severity=IssueSeverity.INFO,
            phase="artwork",
            artifact="ArtworkDB",
            detail=f"{len(replacements)} thumbnail representations corrected.",
        )
    )
    return corrected, (*files, *created), tuple(issues)


def _deferred(image_id: int | None, detail: str) -> WriteIssue:
    return WriteIssue(
        "artwork.geometry_repair_deferred",
        "An existing album artwork thumbnail could not be safely corrected and was preserved.",
        severity=IssueSeverity.WARNING,
        phase="artwork",
        artifact="ArtworkDB",
        record_id=image_id,
        detail=detail,
    )


def _verify_repair(
    before: bytes,
    after: bytes,
    files: tuple[PreparedFile, ...],
    replacements: list[_Replacement],
    reserved: set[str],
    limit: int,
    fix_mhif: bool,
) -> None:
    """Undo only authorized edits in the reparsed output and demand exact bytes."""
    original = parse_ArtworkDB(before)
    checked = parse_ArtworkDB(after)
    by_id = {s.chunk.header.image_id: s.chunk for s in checked.find_chunks(MhiiHeader)}
    output = {f.relative_path.casefold(): f.data for f in files}
    if (
        len(output) != len(files)
        or reserved & output.keys()
        or any(len(b) > limit for b in output.values())
    ):
        raise ValueError("Artwork repair has conflicting output paths or file sizes.")
    undo: dict[int, ParsedChunk[ChunkHeader] | None] = {}
    coverage: dict[str, list[tuple[int, int]]] = {p: [] for p in output}
    for repair in replacements:
        row = by_id.get(repair.image_id)
        if row is None or repair.child_index >= len(row.children):
            raise ValueError("Artwork repair lost a retained image or representation.")
        child = row.children[repair.child_index]
        payload = thumbnail_payload(child)
        if payload is None or payload.child.header != repair.header:
            raise ValueError("Artwork repair changed unexpected native metadata.")
        path = _path(payload.child).casefold()
        if path != artwork_path(repair.filename).casefold():
            raise ValueError("Artwork repair changed its verified filename.")
        h = payload.child.header
        if repair.digest is None:
            old = repair.original.header
            if h != replace(
                old,
                image_size=_SIZE,
                image_size_2=max(old.image_size, old.image_size_2),
            ):
                raise ValueError("Artwork repair changed a retained allocation.")
        else:
            content = output.get(path)
            if content is None:
                raise ValueError("Artwork repair lost its verified output pixels.")
            encoded = read_content(content, h.ithmb_offset, h.image_size)
            if sha256(encoded).hexdigest() != repair.digest or any(
                encoded[y * 112 + 110 : y * 112 + 112] != b"\0\0" for y in range(55)
            ):
                raise ValueError(
                    "Artwork repair pixels or stride padding did not verify."
                )
            if (h.image_width, h.image_height, h.image_size, h.image_size_2) != (
                55,
                55,
                _SIZE,
                _SIZE,
            ):
                raise ValueError("Artwork repair did not produce native geometry.")
            coverage[path].append((h.ithmb_offset, h.ithmb_offset + h.image_size))
        restored_names = tuple(
            replace(c, payload=old.payload) if _filename(old) else c
            for c, old in zip(
                payload.child.children, repair.original.children, strict=True
            )
        )
        children = list(row.children)
        children[repair.child_index] = replace(
            child,
            payload=replace(
                payload,
                child=replace(
                    payload.child,
                    header=repair.original.header,
                    children=restored_names,
                ),
            ),
        )
        by_id[repair.image_id] = replace(row, children=tuple(children))
    for selection in checked.find_chunks(MhiiHeader):
        undo[id(selection.chunk)] = by_id[selection.chunk.header.image_id]
    if fix_mhif:
        old_sizes = original.find_chunks(MhifHeader)
        for new, old_format in zip(
            checked.find_chunks(MhifHeader), old_sizes, strict=True
        ):
            if old_format.chunk.header.format_id == 1061:
                if new.chunk.header.image_size != _SIZE:
                    raise ValueError(
                        "Artwork repair has an incorrect nominal format size."
                    )
                undo[id(new.chunk)] = replace(
                    new.chunk,
                    header=replace(
                        new.chunk.header, image_size=old_format.chunk.header.image_size
                    ),
                )
    if write_ArtworkDB(rebuild(checked, undo)) != before:
        raise ValueError("Artwork repair changed unrelated retained data.")
    for path, ranges in coverage.items():
        end = 0
        for start, stop in sorted(ranges):
            if start != end:
                raise ValueError(
                    "Artwork repair allocations overlap or have unexplained gaps."
                )
            end = stop
        if end != len(output[path]):
            raise ValueError("Artwork repair wrote unreferenced pixels.")
