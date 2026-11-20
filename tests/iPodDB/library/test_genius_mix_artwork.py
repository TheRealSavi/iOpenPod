"""Mix covers publish native identities/pixels without changing Track artwork."""

from dataclasses import replace

import pytest
from tests.iPodDB.library.test_classic_genius_mixes import authored
from tests.iPodDB.library.test_genius_writing import retained_resources, update

from iPodDB.ArtworkDB.parser.parse_ArtworkDB import parse_ArtworkDB
from iPodDB.ArtworkDB.shared.artwork_index import build_artwork_index
from iPodDB.ArtworkDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.library import IPodLibrary
from iPodDB.library.artwork import ArtworkPixels, CoverFormat, CoverPixelFormat
from iPodDB.library.file_content import content_sha256, read_content
from iPodDB.library.genius import GeniusMix, GeniusUpdate
from iPodDB.library.writing import (
    FileDependency,
    GeniusMixArtwork,
    PreparedLibrary,
    SourceFile,
    WriteResources,
    WriteTarget,
)

FORMAT = CoverFormat(1069, 142, 142, 284, CoverPixelFormat.RGB565_LE)
TARGET = WriteTarget(
    classic_genius_mixes=True, genius_mix_artwork_format=FORMAT, artwork_root_value=6
)
PIXELS = ArtworkPixels(142, 142, bytes((32, 96, 192)) * (142 * 142))
COVER = GeniusMixArtwork(900, PIXELS)


def resources(prepared: PreparedLibrary) -> WriteResources:
    files = tuple(
        SourceFile(
            FileDependency(f.relative_path, len(f.data), content_sha256(f.data)), f.data
        )
        for f in prepared.artwork_files
    )
    return replace(
        retained_resources(prepared),
        files=files,
        file_inventory=tuple(f.dependency for f in files),
    )


def covered() -> PreparedLibrary:
    first = authored()
    source = load(first)
    plan = source.analyze(source.begin_draft(genius_mix_artwork=(COVER,)), TARGET)
    assert plan.requires_artwork_inventory
    result = source.prepare(plan, resources(first))
    assert result.prepared is not None, result.issues
    assert result.prepared.itunes == first.itunes
    return result.prepared


def load(prepared: PreparedLibrary) -> IPodLibrary:
    source = IPodLibrary(prepared.itunes)
    return source.with_artwork(prepared.artwork) if prepared.artwork else source


def test_cover_uses_mix_pid_and_native_f1069_pixels() -> None:
    result = covered()
    assert result.artwork is not None
    index = build_artwork_index(parse_ArtworkDB(result.artwork))
    image = index.item_for_db_track_id(900)
    assert image is not None
    assert len(image.locations) == 1
    loc = image.locations[0]
    assert (loc.format_id, loc.width, loc.height, loc.byte_length) == (
        1069,
        142,
        142,
        40328,
    )
    assert len(result.artwork_files) == 1
    assert result.artwork_files[0].relative_path == "iPod_Control/Artwork/F1069_1.ithmb"
    assert read_content(result.artwork_files[0].data, 0, 2) == b"\x18\x23"
    assert all(t.artwork_id != image.image_id for t in result.snapshot.tracks)


def test_repeat_save_keeps_exact_artwork_and_does_not_append_pixels() -> None:
    first = covered()
    source = load(first)
    result = source.prepare(
        source.analyze(source.begin_draft(genius_mix_artwork=(COVER,)), TARGET),
        resources(first),
    )
    assert result.prepared is not None, result.issues
    assert result.prepared.itunes == first.itunes
    assert result.prepared.artwork == first.artwork
    assert result.prepared.artwork_files == ()


def test_removal_retires_only_the_reverse_link_and_preserves_pixel_ranges() -> None:
    first = covered()
    source = load(first)
    result = source.prepare(
        source.analyze(
            source.begin_draft(
                genius_update=GeniusUpdate(None, mix_removals=(900,)),
                genius_mix_artwork=(GeniusMixArtwork(900, None),),
            ),
            TARGET,
        ),
        resources(first),
    )
    assert result.prepared is not None, result.issues
    assert result.prepared.artwork is not None and first.artwork is not None
    before = build_artwork_index(parse_ArtworkDB(first.artwork))
    after = build_artwork_index(parse_ArtworkDB(result.prepared.artwork))
    assert after.item_for_db_track_id(900) is None
    assert [i.locations for i in after.items] == [i.locations for i in before.items]
    assert result.prepared.artwork_files == ()

    assert result.prepared.genius == first.genius
    assert result.prepared.snapshot.tracks == first.snapshot.tracks


def test_changed_cover_appends_without_overwriting_retained_pixels() -> None:
    first = covered()
    source = load(first)
    new = GeniusMixArtwork(900, ArtworkPixels(142, 142, b"\xff\x00\x00" * (142 * 142)))
    result = source.prepare(
        source.analyze(source.begin_draft(genius_mix_artwork=(new,)), TARGET),
        resources(first),
    )
    assert result.prepared is not None, result.issues
    assert result.prepared.artwork is not None
    rows = tuple(
        s.chunk.header
        for s in parse_ArtworkDB(result.prepared.artwork).find_chunks(MhiiHeader)
    )
    assert [r.db_track_id_ref for r in rows] == [0, 900]
    assert result.prepared.artwork_files[0].relative_path.endswith("F1069_2.ithmb")
    assert read_content(result.prepared.artwork_files[0].data, 0, 2) == b"\x00\xf8"


@pytest.mark.parametrize(
    "target",
    [
        WriteTarget(),
        WriteTarget(sqlite_database=True),
        WriteTarget(classic_genius_mixes=True),
    ],
)
def test_unqualified_targets_reject_cover_intent(target: WriteTarget) -> None:
    first = authored()
    source = IPodLibrary(first.itunes)
    plan = source.analyze(source.begin_draft(genius_mix_artwork=(COVER,)), target)
    assert plan.blocked
    assert any(i.code == "genius.unsupported_mix_artwork" for i in plan.issues)


def test_two_full_ids_with_same_low_word_cannot_enter_native_cover_cache() -> None:
    first = authored()
    source = IPodLibrary(first.itunes)
    other = (1 << 32) | 900
    result = source.prepare(
        source.analyze(
            source.begin_draft(
                genius_update=replace(
                    update(),
                    mixes=None,
                    mix_additions=(GeniusMix(other, "Other", (1,)),),
                ),
                genius_mix_artwork=(COVER, GeniusMixArtwork(other, PIXELS)),
            ),
            TARGET,
        ),
        resources(first),
    )
    assert result.prepared is None
    assert any("32-bit artwork cache" in i.message for i in result.issues)
