"""Repair retained MHIF sizes only from consistent, captured artwork evidence."""

import hashlib
import logging
from dataclasses import replace

import pytest
from tests.iPodDB.library.test_write_artwork import BLUE, COVER, RED, TARGET
from tests.iPodDB.library.test_writing import library

from iPodDB.ArtworkDB.parser.parse_ArtworkDB import parse_ArtworkDB
from iPodDB.ArtworkDB.shared.chunk_defs.mhif import MhifHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhod_payloads.container_mhod import (
    MhodContainerPayload,
)
from iPodDB.ArtworkDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.ArtworkDB.writer.write_ArtworkDB import write_ArtworkDB
from iPodDB.library import (
    CoverFormat,
    CoverPixelFormat,
    FileDependency,
    IPodLibrary,
    LibraryWriteResult,
    SourceFile,
    WriteResources,
    WriteTarget,
    content_sha256,
)

NANO_FORMATS = (
    replace(COVER, format_id=1010, width=240, height=240, row_bytes=480),
    replace(COVER, format_id=1013, width=50, height=50, row_bytes=100),
    replace(COVER, format_id=1015, width=58, height=58, row_bytes=116),
    replace(COVER, format_id=1016, width=57, height=57, row_bytes=116),
)


def retained_source(
    formats: tuple[CoverFormat, ...] = (COVER,),
) -> tuple[IPodLibrary, WriteTarget, WriteResources]:
    source = library()
    target = replace(TARGET, cover_formats=formats)
    desired = replace(
        source.snapshot,
        tracks=tuple(
            replace(t, artwork_id=RED.artwork_id) for t in source.snapshot.tracks
        ),
    )
    result = source.prepare(
        source.analyze(source.begin_draft(desired), target),
        WriteResources(artwork=(RED,), file_inventory=()),
    )
    assert result.prepared is not None and result.prepared.artwork is not None
    document = parse_ArtworkDB(result.prepared.artwork)
    # Unknown header bytes and a suffix must survive the correction unchanged.
    for selection in document.find_chunks(MhifHeader):
        chunk = selection.chunk
        document = document.replace_chunk(
            selection, replace(chunk, raw_header=chunk.raw_header[:-4] + b"KEEP")
        )
    artwork = write_ArtworkDB(document) + b"retained suffix"
    files = tuple(
        SourceFile(
            FileDependency(f.relative_path, len(f.data), content_sha256(f.data)),
            f.data,
        )
        for f in result.prepared.artwork_files
    )
    return (
        IPodLibrary(result.prepared.itunes).with_artwork(artwork),
        target,
        WriteResources(
            artwork=(BLUE,),
            files=files,
            file_inventory=tuple(f.dependency for f in files),
        ),
    )


def with_wrong_sizes(source: IPodLibrary) -> IPodLibrary:
    original = source.serialize()
    assert original.artwork is not None
    document = parse_ArtworkDB(original.artwork)
    for selection in document.find_chunks(MhifHeader):
        chunk = selection.chunk
        document = document.replace_chunk(
            selection,
            replace(
                chunk,
                header=replace(chunk.header, image_size=chunk.header.image_size * 760),
            ),
        )
    return IPodLibrary(original.itunes).with_artwork(write_ArtworkDB(document))


def prepare_cover(
    source: IPodLibrary, target: WriteTarget, resources: WriteResources
) -> LibraryWriteResult:
    first, second = source.snapshot.tracks
    desired = replace(
        source.snapshot, tracks=(replace(first, artwork_id=BLUE.artwork_id), second)
    )
    return source.prepare(
        source.analyze(source.begin_draft(desired), target), resources
    )


def test_nano_sizes_are_corrected_automatically_without_other_changes(
    caplog: pytest.LogCaptureFixture,
) -> None:
    healthy, target, resources = retained_source(NANO_FORMATS)
    source = with_wrong_sizes(healthy)
    original = source.serialize()
    expected = prepare_cover(healthy, target, resources)
    with caplog.at_level(logging.INFO, logger="iPodDB.library._artwork_writing"):
        actual = prepare_cover(source, target, resources)
    assert actual.prepared is not None, actual.issues
    assert expected.prepared is not None
    assert actual.prepared.artwork == expected.prepared.artwork
    assert actual.prepared.itunes == expected.prepared.itunes
    assert actual.prepared.artwork_files == expected.prepared.artwork_files
    assert actual.prepared.retained_files == expected.prepared.retained_files
    assert source.serialize() == original
    assert actual.prepared.artwork is not None
    assert {
        s.chunk.header.format_id: s.chunk.header.image_size
        for s in parse_ArtworkDB(actual.prepared.artwork).find_chunks(MhifHeader)
    } == {1010: 115200, 1013: 5000, 1015: 6728, 1016: 6612}
    assert "87552000" in caplog.text and "115200" in caplog.text


@pytest.mark.parametrize("change", [False, True])
def test_reading_and_unrelated_edits_preserve_wrong_sizes(change: bool) -> None:
    healthy, target, _ = retained_source()
    source = with_wrong_sizes(healthy)
    original = source.serialize()
    desired = (
        replace(source.snapshot, device_name="Renamed") if change else source.snapshot
    )
    result = source.prepare(source.analyze(source.begin_draft(desired), target))
    assert result.prepared is not None, result.issues
    assert result.prepared.artwork == original.artwork
    assert not result.prepared.artwork_files
    assert original.artwork is not None
    assert write_ArtworkDB(parse_ArtworkDB(original.artwork)) == original.artwork


@pytest.mark.parametrize(
    "problem",
    [
        "primary_size",
        "secondary_size",
        "dimensions",
        "padding",
        "missing_name",
        "duplicate_name",
        "missing_file",
        "out_of_bounds",
        "partial_overlap",
        "no_images",
    ],
)
def test_unsafe_retained_evidence_still_blocks_repair(problem: str) -> None:
    healthy, target, resources = retained_source()
    source = with_wrong_sizes(healthy)
    original = source.serialize()
    assert original.artwork is not None
    document = parse_ArtworkDB(original.artwork)
    selection = document.find_chunks(MhiiHeader)[-1]
    row = selection.chunk
    container = row.children[0]
    assert isinstance(container.payload, MhodContainerPayload)
    location = container.payload.child
    header = location.header
    if problem == "primary_size":
        location = replace(location, header=replace(header, image_size=31))
    elif problem == "secondary_size":
        location = replace(location, header=replace(header, image_size_2=31))
    elif problem == "dimensions":
        location = replace(location, header=replace(header, image_width=3))
    elif problem == "padding":
        location = replace(location, header=replace(header, vertical_padding=-1))
    elif problem == "missing_name":
        location = replace(location, children=())
    elif problem == "duplicate_name":
        location = replace(location, children=location.children * 2)
    elif problem == "out_of_bounds":
        location = replace(location, header=replace(header, ithmb_offset=32))
    elif problem == "partial_overlap":
        location = replace(location, header=replace(header, ithmb_offset=1))
        file = resources.files[0]
        assert isinstance(file.data, bytes)
        data = file.data + b"\0"
        dependency = replace(
            file.dependency, size=len(data), sha256=hashlib.sha256(data).hexdigest()
        )
        resources = replace(
            resources,
            files=(SourceFile(dependency, data),),
            file_inventory=(dependency,),
        )
    elif problem == "missing_file":
        resources = replace(resources, files=(), file_inventory=())
    if problem == "no_images":
        for image in document.find_chunks(MhiiHeader):
            document = document.replace_chunk(image, replace(image.chunk, children=()))
    else:
        document = document.replace_chunk(
            selection,
            replace(
                row,
                children=(
                    replace(
                        container, payload=replace(container.payload, child=location)
                    ),
                    *row.children[1:],
                ),
            ),
        )
    if problem == "partial_overlap":
        dataset = next(
            s
            for s in document.find_chunks(MhsdHeader)
            if s.chunk.header.dataset_type == 1
        )
        other = replace(
            row,
            header=replace(
                row.header, image_id=row.header.image_id + 100, db_track_id_ref=0
            ),
        )
        document = document.replace_chunk(
            dataset,
            replace(
                dataset.chunk, children=(dataset.chunk.children[0].append_child(other),)
            ),
        )
    source = IPodLibrary(original.itunes).with_artwork(write_ArtworkDB(document))
    result = prepare_cover(source, target, resources)
    assert result.prepared is None
    assert any(i.code == "preparation.cannot_encode" for i in result.issues)
    assert any("Automatic correction is unsafe" in i.message for i in result.issues)


def test_full_shard_needs_only_its_captured_fingerprint_for_repair() -> None:
    healthy, target, resources = retained_source()
    source = with_wrong_sizes(healthy)
    target = replace(target, max_artwork_file_bytes=32)
    resources = replace(resources, files=())
    result = prepare_cover(source, target, resources)
    assert result.prepared is not None, result.issues
    assert [f.relative_path for f in result.prepared.artwork_files] == [
        "iPod_Control/Artwork/F1055_2.ithmb"
    ]


def test_variable_size_artwork_is_not_automatically_corrected() -> None:
    healthy, target, resources = retained_source(
        (replace(COVER, pixel_format=CoverPixelFormat.JPEG),)
    )
    result = prepare_cover(with_wrong_sizes(healthy), target, resources)
    assert result.prepared is None
    assert any("Variable-size artwork" in i.message for i in result.issues)


def test_corrected_database_needs_no_further_repair(
    caplog: pytest.LogCaptureFixture,
) -> None:
    healthy, target, resources = retained_source()
    result = prepare_cover(with_wrong_sizes(healthy), target, resources)
    assert result.prepared is not None and result.prepared.artwork is not None
    source = IPodLibrary(result.prepared.itunes).with_artwork(result.prepared.artwork)
    files = tuple(
        SourceFile(
            FileDependency(f.relative_path, len(f.data), content_sha256(f.data)),
            f.data,
        )
        for f in result.prepared.artwork_files
    )
    resources = replace(
        resources, files=files, file_inventory=tuple(f.dependency for f in files)
    )
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="iPodDB.library._artwork_writing"):
        again = prepare_cover(source, target, resources)
    assert again.prepared is not None, again.issues
    assert "Automatically corrected" not in caplog.text


def test_centered_retained_image_dimensions_allow_automatic_repair() -> None:
    healthy, target, resources = retained_source()
    original = with_wrong_sizes(healthy).serialize()
    assert original.artwork is not None
    document = parse_ArtworkDB(original.artwork)
    for selection in document.find_chunks(MhiiHeader):
        row = selection.chunk
        container = row.children[0]
        assert isinstance(container.payload, MhodContainerPayload)
        location = container.payload.child
        location = replace(
            location,
            header=replace(location.header, image_height=3, vertical_padding=1),
        )
        container = replace(
            container, payload=replace(container.payload, child=location)
        )
        document = document.replace_chunk(
            selection, replace(row, children=(container, *row.children[1:]))
        )
    source = IPodLibrary(original.itunes).with_artwork(write_ArtworkDB(document))
    result = prepare_cover(source, target, resources)
    assert result.prepared is not None, result.issues
