"""Fresh and incremental multi-format shards retain exact image associations."""

from dataclasses import replace

import pytest
from tests.iPodDB.library.test_write_artwork import COVER, TARGET
from tests.iPodDB.library.test_writing import library

from iPodDB.ArtworkDB.parser.parse_ArtworkDB import parse_ArtworkDB
from iPodDB.ArtworkDB.shared.chunk_defs.mhif import MhifHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhod_payloads.container_mhod import (
    MhodContainerPayload,
)
from iPodDB.ArtworkDB.shared.chunk_defs.mhod_payloads.string_mhod import (
    MhodStringPayload,
)
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import (
    ArtworkAsset,
    ArtworkPixels,
    CoverFormat,
    CoverPixelFormat,
    FileDependency,
    IPodLibrary,
    SourceFile,
    WriteResources,
    content_sha256,
    read_content,
)

# Synthetic sizes force rollover with a few bytes. They are not device profiles.
PADDED_COVER = CoverFormat(1060, 3, 3, 8, CoverPixelFormat.RGB565_BE)
# RGB888 inputs and independent RGB565 words: no production encoder as oracle.
COLORS = (
    ((255, 0, 0), 0xF800),
    ((0, 255, 0), 0x07E0),
    ((0, 0, 255), 0x001F),
    ((0, 255, 255), 0x07FF),
    ((255, 0, 255), 0xF81F),
    ((255, 255, 0), 0xFFE0),
    ((255, 255, 255), 0xFFFF),
    ((0, 0, 0), 0x0000),
)


def _source() -> IPodLibrary:
    document = parse_iTunesDB(library().serialize().itunes)
    template = document.find_chunks(MhitHeader)[0].chunk
    dataset = next(
        s for s in document.find_chunks(MhsdHeader) if s.chunk.header.dataset_type == 1
    )
    tracks = tuple(
        replace(
            template, header=replace(template.header, track_id=i, db_track_id=100 + i)
        )
        for i in range(1, 9)
    )
    document = document.replace_chunk(
        dataset,
        replace(
            dataset.chunk,
            children=(replace(dataset.chunk.children[0], children=tracks),),
        ),
    )
    return IPodLibrary(write_iTunesDB(document))


def _asset(index: int) -> ArtworkAsset:
    return ArtworkAsset(-(index + 1), ArtworkPixels(4, 4, bytes(COLORS[index][0]) * 16))


def _assert_references(
    source: IPodLibrary, files: dict[str, bytes], count: int, limit: int
) -> None:
    serialized = source.serialize()
    assert serialized.artwork is not None
    document = parse_ArtworkDB(serialized.artwork)
    rows = {s.chunk.header.image_id: s.chunk for s in document.find_chunks(MhiiHeader)}
    assert len(rows) == count
    assert {
        s.chunk.header.format_id: s.chunk.header.image_size
        for s in document.find_chunks(MhifHeader)
    } == {1055: 32, 1060: 24}
    expected_files: dict[str, bytes] = {}
    for index, track in enumerate(source.snapshot.tracks[:count]):
        row = rows[track.artwork_id]
        locations = {
            child.payload.child.header.format_id: child.payload.child
            for child in row.children
            if isinstance(child.payload, MhodContainerPayload)
        }
        assert set(locations) == {1055, 1060}
        word = COLORS[index][1]
        frames = {
            1055: word.to_bytes(2, "little") * 16,
            1060: (word.to_bytes(2, "big") * 3 + bytes(2)) * 3,
        }
        for format_id, frame in frames.items():
            # At 63 bytes the 32-byte frame cannot share a shard; 64 fits two.
            capacity = 1 if format_id == 1055 and limit == 63 else 2
            number, slot = divmod(index, capacity)
            filename = f"F{format_id}_{number + 1}.ithmb"
            path = f"iPod_Control/Artwork/{filename}"
            offset = slot * len(frame)
            location = locations[format_id]
            assert (
                location.header.ithmb_offset,
                location.header.image_size,
                location.header.image_size_2,
            ) == (offset, len(frame), len(frame))
            assert [
                child.payload.value
                for child in location.children
                if isinstance(child.payload, MhodStringPayload)
            ] == [f":{filename}"]
            assert files[path][offset : offset + len(frame)] == frame
            assert offset + location.header.image_size_2 <= len(files[path]) <= limit
            expected_files[path] = expected_files.get(path, b"") + frame
    assert files == expected_files


@pytest.mark.parametrize("limit", [63, 64])
def test_fresh_shards_reload_and_append_without_changing_retained_images(
    limit: int,
) -> None:
    source = _source()
    original = source.serialize()
    target = replace(
        TARGET,
        cover_formats=(COVER, PADDED_COVER),
        max_artwork_file_bytes=limit,
    )
    desired = replace(
        source.snapshot,
        tracks=tuple(
            replace(track, artwork_id=-(index + 1)) if index < 5 else track
            for index, track in enumerate(source.snapshot.tracks)
        ),
    )
    first = source.prepare(
        source.analyze(source.begin_draft(desired), target),
        WriteResources(artwork=tuple(_asset(i) for i in range(5)), file_inventory=()),
    )
    assert first.prepared is not None and first.prepared.artwork is not None, (
        first.issues
    )
    files = {
        file.relative_path: read_content(file.data, 0, len(file.data))
        for file in first.prepared.artwork_files
    }
    reloaded = IPodLibrary(first.prepared.itunes).with_artwork(first.prepared.artwork)
    assert reloaded.snapshot == first.prepared.snapshot
    _assert_references(reloaded, files, 5, limit)
    retained = reloaded.serialize()
    desired = replace(
        reloaded.snapshot,
        tracks=tuple(
            track if index < 5 else replace(track, artwork_id=-(index + 1))
            for index, track in enumerate(reloaded.snapshot.tracks)
        ),
    )
    captured = tuple(
        SourceFile(FileDependency(path, len(data), content_sha256(data)), data)
        for path, data in files.items()
    )
    second = reloaded.prepare(
        reloaded.analyze(reloaded.begin_draft(desired), target),
        WriteResources(
            artwork=tuple(_asset(i) for i in range(5, 8)),
            files=captured,
            file_inventory=tuple(file.dependency for file in captured),
        ),
    )
    assert second.prepared is not None and second.prepared.artwork is not None, (
        second.issues
    )
    combined = files | {
        file.relative_path: read_content(file.data, 0, len(file.data))
        for file in second.prepared.artwork_files
    }
    assert len(combined["iPod_Control/Artwork/F1060_3.ithmb"]) == 48
    assert "iPod_Control/Artwork/F1060_4.ithmb" in combined
    for path, prefix in files.items():
        assert combined[path][: len(prefix)] == prefix
    final = IPodLibrary(second.prepared.itunes).with_artwork(second.prepared.artwork)
    assert final.snapshot == second.prepared.snapshot
    assert final.snapshot.tracks[:5] == reloaded.snapshot.tracks[:5]
    _assert_references(final, combined, 8, limit)
    assert source.serialize() == original
    assert reloaded.serialize() == retained
