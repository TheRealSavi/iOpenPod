"""Native F1061 authoring and automatic, recoverable legacy raster correction."""

from dataclasses import replace

import pytest
from tests.iPodDB.library.test_artwork_format_repair import (
    prepare_cover,
    retained_source,
)
from tests.iPodDB.library.test_write_artwork import RED
from tests.iPodDB.library.test_writing import library

from device_registry import DEFAULT_DEVICE_REGISTRY
from iOpenPod.app.artwork_policy import application_cover_formats
from iPodDB.ArtworkDB.ithmb import DecodedImage, IthmbLayout
from iPodDB.ArtworkDB.ithmb_writer import encode_ithmb
from iPodDB.ArtworkDB.parser.parse_ArtworkDB import parse_ArtworkDB
from iPodDB.ArtworkDB.shared.artwork_index import thumbnail_payload
from iPodDB.ArtworkDB.shared.chunk_defs.mhif import MhifHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.ArtworkDB.writer.write_ArtworkDB import write_ArtworkDB
from iPodDB.library import (
    CoverFormat,
    CoverPixelFormat,
    FileDependency,
    IPodLibrary,
    SourceFile,
    WriteResources,
    WriteTarget,
    _artwork_geometry,
    content_sha256,
    read_content,
)


def native_target() -> WriteTarget:
    profile = DEFAULT_DEVICE_REGISTRY.profile_for_model_number("MC293")
    assert profile is not None
    return WriteTarget(
        cover_formats=application_cover_formats(profile), artwork_root_value=6
    )


def test_current_catalog_and_writer_use_native_visible_geometry() -> None:
    target = native_target()
    cover = next(f for f in target.cover_formats if f.format_id == 1061)
    assert (cover.width, cover.height, cover.row_bytes) == (55, 55, 112)
    source = library()
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
    assert result.prepared is not None, result.issues
    assert result.prepared.artwork is not None
    output = parse_ArtworkDB(result.prepared.artwork)
    row = output.find_chunks(MhiiHeader)[0].chunk
    header = next(
        p.child.header
        for c in row.children
        if (p := thumbnail_payload(c)) is not None and p.child.header.format_id == 1061
    )
    assert (header.image_width, header.image_height, header.image_size) == (
        55,
        55,
        6160,
    )
    payload = next(
        f.data for f in result.prepared.artwork_files if "F1061_" in f.relative_path
    )
    assert len(payload) == 6160
    assert all(read_content(payload, y * 112 + 110, 2) == b"\0\0" for y in range(55))


@pytest.mark.parametrize("width,height", [(56, 56), (56, 55), (55, 56)])
def test_unchanged_save_repairs_legacy_geometry_and_then_is_idempotent(
    width: int,
    height: int,
) -> None:
    legacy = CoverFormat(1061, width, height, 112, CoverPixelFormat.RGB565_LE)
    source, _, resources = retained_source((legacy,))
    before = source.serialize()
    target = native_target()
    plan = source.analyze(source.begin_draft(), target)
    assert plan.changes and plan.requires_artwork_inventory
    assert not plan.changes_itunes
    result = source.prepare(plan, replace(resources, artwork=()))
    assert result.prepared is not None, result.issues
    prepared = result.prepared
    assert prepared.itunes == before.itunes
    assert prepared.artwork is not None and prepared.artwork != before.artwork
    assert source.serialize() == before
    output = parse_ArtworkDB(prepared.artwork)
    for row in output.find_chunks(MhiiHeader):
        for child in row.chunk.children:
            payload = thumbnail_payload(child)
            if payload is None:
                continue
            header = payload.child.header
            assert (header.image_width, header.image_height, header.image_size) == (
                55,
                55,
                6160,
            )
    assert output.find_chunks(MhifHeader)[0].chunk.header.image_size == 6160
    old_paths = {f.dependency.relative_path for f in resources.files}
    assert prepared.artwork_files
    assert not old_paths & {f.relative_path for f in prepared.artwork_files}
    reloaded = IPodLibrary(prepared.itunes).with_artwork(prepared.artwork)
    next_plan = reloaded.analyze(reloaded.begin_draft(), target)
    assert not next_plan.changes
    again = reloaded.prepare(next_plan)
    assert again.prepared is not None
    assert again.prepared.artwork == prepared.artwork
    assert not again.prepared.artwork_files


def test_repair_rejects_changed_captured_pixels() -> None:
    source, _, resources = retained_source(
        (CoverFormat(1061, 56, 56, 112, CoverPixelFormat.RGB565_LE),)
    )
    first = resources.files[0]
    bad = bytearray(read_content(first.data, 0, len(first.data)))
    bad[0] ^= 255
    changed = replace(
        resources, artwork=(), files=(SourceFile(first.dependency, bytes(bad)),)
    )
    result = source.prepare(
        source.analyze(source.begin_draft(), native_target()), changed
    )
    assert result.prepared is None


def test_repair_skips_unavailable_pixels_with_diagnostic() -> None:
    source, _, resources = retained_source(
        (CoverFormat(1061, 56, 56, 112, CoverPixelFormat.RGB565_LE),)
    )
    before = source.serialize()
    result = source.prepare(
        source.analyze(source.begin_draft(), native_target()),
        replace(resources, artwork=(), files=()),
    )
    assert result.prepared is not None, result.issues
    assert result.prepared.artwork == before.artwork
    assert not result.prepared.artwork_files
    assert any(
        issue.code == "artwork.geometry_repair_deferred" for issue in result.issues
    )


def test_valid_55_pixel_content_keeps_its_6272_byte_allocation() -> None:
    source, _, resources = retained_source(
        (CoverFormat(1061, 55, 55, 112, CoverPixelFormat.RGB565_LE),)
    )
    original = source.serialize()
    assert original.artwork is not None
    document = parse_ArtworkDB(original.artwork)
    selected = document.find_chunks(MhiiHeader)[0]
    row = selected.chunk
    child = row.children[0]
    payload = thumbnail_payload(child)
    assert payload is not None
    padded = replace(payload.child.header, image_size=6272, image_size_2=6272)
    document = document.replace_chunk(
        selected,
        replace(
            row,
            children=(
                replace(
                    child,
                    payload=replace(
                        payload, child=replace(payload.child, header=padded)
                    ),
                ),
                *row.children[1:],
            ),
        ),
    )
    source = IPodLibrary(original.itunes).with_artwork(write_ArtworkDB(document))
    old_file = resources.files[0]
    data = read_content(old_file.data, 0, len(old_file.data)) + bytes(112)
    captured = SourceFile(
        FileDependency(
            old_file.dependency.relative_path, len(data), content_sha256(data)
        ),
        data,
    )
    result = source.prepare(
        source.analyze(source.begin_draft(), native_target()),
        WriteResources(files=(captured,), file_inventory=(captured.dependency,)),
    )
    assert result.prepared is not None and result.prepared.artwork is not None, (
        result.issues
    )
    assert not result.prepared.artwork_files
    updated = (
        parse_ArtworkDB(result.prepared.artwork)
        .find_chunks(MhiiHeader)[0]
        .chunk.children[0]
    )
    checked = thumbnail_payload(updated)
    assert checked is not None
    assert checked.child.header == replace(padded, image_size=6160)


@pytest.mark.parametrize("has_other_representation", [False, True])
def test_6050_byte_raster_requires_a_valid_same_time_alternative(
    has_other_representation: bool,
) -> None:
    covers: tuple[CoverFormat, ...] = (
        CoverFormat(1061, 55, 55, 110, CoverPixelFormat.RGB565_LE),
    )
    if has_other_representation:
        covers += (CoverFormat(1055, 128, 128, 256, CoverPixelFormat.RGB565_LE),)
    source, _, resources = retained_source(covers)
    before = source.serialize()
    result = source.prepare(
        source.analyze(source.begin_draft(), native_target()),
        replace(resources, artwork=()),
    )
    assert result.prepared is not None, result.issues
    if has_other_representation:
        assert result.prepared.artwork != before.artwork
        assert any(i.code == "artwork.geometry_repaired" for i in result.issues)
        assert not any(
            i.code == "artwork.geometry_repair_deferred" for i in result.issues
        )
    else:
        assert result.prepared.artwork == before.artwork
        assert not result.prepared.artwork_files
        assert any(i.code == "artwork.geometry_repair_deferred" for i in result.issues)


def test_repair_resamples_last_visible_row_and_column_instead_of_cropping() -> None:
    source, _, resources = retained_source(
        (CoverFormat(1061, 56, 56, 112, CoverPixelFormat.RGB565_LE),)
    )
    # Red square with a blue right edge and green bottom edge. Blindly relabeling
    # this as 55x55 would discard both borders; a real resample preserves them.
    data = (b"\x00\xf8" * 55 + b"\x1f\x00") * 55 + b"\xe0\x07" * 56
    original_file = resources.files[0]
    dependency = replace(original_file.dependency, sha256=content_sha256(data))
    result = source.prepare(
        source.analyze(source.begin_draft(), native_target()),
        WriteResources(
            files=(SourceFile(dependency, data),), file_inventory=(dependency,)
        ),
    )
    assert result.prepared is not None and result.prepared.artwork is not None, (
        result.issues
    )
    loaded = IPodLibrary(result.prepared.itunes).with_artwork(result.prepared.artwork)
    read = loaded.artwork_read(
        loaded.snapshot.tracks[0].artwork_id, native_target().cover_formats, 55
    )
    assert read is not None
    output = next(
        f
        for f in result.prepared.artwork_files
        if f.relative_path == read.relative_path
    )
    pixels = read.decode(read_content(output.data, read.offset, read.length))
    right = (20 * 55 + 54) * 3
    bottom = (54 * 55 + 20) * 3
    assert pixels.rgb888[right + 2] > 200
    assert pixels.rgb888[bottom + 1] > 200


def test_other_device_target_does_not_reinterpret_f1061() -> None:
    source, _, _ = retained_source(
        (CoverFormat(1061, 56, 56, 112, CoverPixelFormat.RGB565_LE),)
    )
    before = source.serialize()
    target = WriteTarget(
        cover_formats=(CoverFormat(1029, 200, 200, 400, CoverPixelFormat.RGB565_LE),)
    )
    plan = source.analyze(source.begin_draft(), target)
    assert not plan.changes
    result = source.prepare(plan)
    assert result.prepared is not None
    assert result.prepared.artwork == before.artwork


def test_new_cover_and_retained_legacy_cover_are_both_native() -> None:
    source, _, resources = retained_source(
        (CoverFormat(1061, 56, 56, 112, CoverPixelFormat.RGB565_LE),)
    )
    result = prepare_cover(source, native_target(), resources)
    assert result.prepared is not None and result.prepared.artwork is not None, (
        result.issues
    )
    headers = [
        p.child.header
        for row in parse_ArtworkDB(result.prepared.artwork).find_chunks(MhiiHeader)
        for child in row.chunk.children
        if (p := thumbnail_payload(child)) is not None
        and p.child.header.format_id == 1061
    ]
    assert len(headers) == 2
    assert all(
        (h.image_width, h.image_height, h.image_size) == (55, 55, 6160) for h in headers
    )


@pytest.mark.parametrize("overlap", [False, True])
def test_timed_repairs_reserve_old_paths_and_bound_new_shards(overlap: bool) -> None:
    source, _, resources = retained_source(
        (CoverFormat(1061, 56, 56, 112, CoverPixelFormat.RGB565_LE),)
    )
    before = source.serialize()
    assert before.artwork is not None
    document = parse_ArtworkDB(before.artwork)
    selected = document.find_chunks(MhiiHeader)[0]
    row = selected.chunk
    child = row.children[0]
    payload = thumbnail_payload(child)
    assert payload is not None
    second = replace(
        child,
        payload=replace(
            payload,
            child=replace(
                payload.child,
                header=replace(
                    payload.child.header,
                    image_time_key=1000,
                    ithmb_offset=2 if overlap else 0,
                ),
            ),
        ),
    )
    document = document.replace_chunk(
        selected, replace(row, children=(*row.children, second))
    )
    source = IPodLibrary(before.itunes).with_artwork(write_ArtworkDB(document))
    target = replace(native_target(), max_artwork_file_bytes=6160)
    result = source.prepare(
        source.analyze(source.begin_draft(), target), replace(resources, artwork=())
    )
    assert result.prepared is not None and result.prepared.artwork is not None, (
        result.issues
    )
    if overlap:
        assert result.prepared.artwork == source.serialize().artwork
        assert not result.prepared.artwork_files
        assert (
            sum(i.code == "artwork.geometry_repair_deferred" for i in result.issues)
            == 2
        )
    else:
        assert [f.relative_path for f in result.prepared.artwork_files] == [
            "iPod_Control/Artwork/F1061_2.ithmb",
            "iPod_Control/Artwork/F1061_3.ithmb",
        ]
        assert all(len(f.data) == 6160 for f in result.prepared.artwork_files)
        assert result.prepared.itunes == before.itunes
        checked = (
            parse_ArtworkDB(result.prepared.artwork).find_chunks(MhiiHeader)[0].chunk
        )
        assert {
            p.child.header.image_time_key
            for c in checked.children
            if (p := thumbnail_payload(c)) is not None
        } == {0, 1000}


def test_fallback_never_uses_another_display_time() -> None:
    source, _, resources = retained_source(
        (
            CoverFormat(1061, 55, 55, 110, CoverPixelFormat.RGB565_LE),
            CoverFormat(1055, 128, 128, 256, CoverPixelFormat.RGB565_LE),
        )
    )
    before = source.serialize()
    assert before.artwork is not None
    document = parse_ArtworkDB(before.artwork)
    selected = document.find_chunks(MhiiHeader)[0]
    children = []
    for child in selected.chunk.children:
        payload = thumbnail_payload(child)
        if payload is not None and payload.child.header.format_id == 1055:
            child = replace(
                child,
                payload=replace(
                    payload,
                    child=replace(
                        payload.child,
                        header=replace(payload.child.header, image_time_key=1000),
                    ),
                ),
            )
        children.append(child)
    document = document.replace_chunk(
        selected, replace(selected.chunk, children=tuple(children))
    )
    source = IPodLibrary(before.itunes).with_artwork(write_ArtworkDB(document))
    result = source.prepare(
        source.analyze(source.begin_draft(), native_target()),
        replace(resources, artwork=()),
    )
    assert result.prepared is not None, result.issues
    assert result.prepared.artwork == source.serialize().artwork
    assert not result.prepared.artwork_files
    assert any(i.code == "artwork.geometry_repair_deferred" for i in result.issues)


def test_independent_repair_verification_rejects_invalid_row_padding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, _, resources = retained_source(
        (CoverFormat(1061, 56, 56, 112, CoverPixelFormat.RGB565_LE),)
    )

    def bad_padding(image: DecodedImage, layout: IthmbLayout) -> bytes:
        output = bytearray(encode_ithmb(image, layout))
        output[110] = 1
        return bytes(output)

    monkeypatch.setattr(_artwork_geometry, "encode_ithmb", bad_padding)
    result = source.prepare(
        source.analyze(source.begin_draft(), native_target()),
        replace(resources, artwork=()),
    )
    assert result.prepared is None
    assert any("stride padding did not verify" in i.message for i in result.issues)
