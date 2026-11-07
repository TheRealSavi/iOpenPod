"""Independent publication guards around damaged retained artwork evidence."""

from collections.abc import Callable
from dataclasses import replace

import pytest
from tests.iPodDB.library.test_artwork_native_verification import ArtworkResult
from tests.iPodDB.library.test_write_artwork import (
    BLUE,
    TARGET,
    resources_for,
    with_shared_artwork,
)

from iPodDB.ArtworkDB.parser.parse_ArtworkDB import parse_ArtworkDB
from iPodDB.ArtworkDB.shared.chunk_defs.mhfd import MhfdHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhod_payloads.container_mhod import (
    MhodContainerPayload,
)
from iPodDB.ArtworkDB.shared.chunk_defs.mhod_payloads.string_mhod import (
    MhodStringPayload,
)
from iPodDB.ArtworkDB.shared.constants import ArtworkMhodType
from iPodDB.ArtworkDB.writer.write_ArtworkDB import write_ArtworkDB
from iPodDB.library import IPodLibrary, PreparedFile, _artwork_writing
from iPodDB.library import _write_preparation as preparation
from iPodDB.shared.chunk import DatabaseDocument


def test_independent_verification_rejects_append_into_missing_allocation_tail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    healthy, file = with_shared_artwork()
    original = healthy.serialize()
    assert original.artwork is not None
    document = parse_ArtworkDB(original.artwork)
    selection = document.find_chunks(MhiiHeader)[0]
    row = selection.chunk
    container = row.children[0]
    assert isinstance(container.payload, MhodContainerPayload)
    location = container.payload.child
    changed_location = replace(
        location,
        header=replace(location.header, image_size_2=location.header.image_size * 2),
    )
    document = document.replace_chunk(
        selection,
        replace(
            row,
            children=(
                replace(
                    container,
                    payload=replace(container.payload, child=changed_location),
                ),
                *row.children[1:],
            ),
        ),
    )
    source = IPodLibrary(original.itunes).with_artwork(write_ArtworkDB(document))
    retained = source.serialize()
    desired = replace(
        source.snapshot,
        tracks=tuple(
            replace(track, artwork_id=BLUE.artwork_id)
            for track in source.snapshot.tracks
        ),
    )

    def omit_allocation_evidence(
        _document: DatabaseDocument[MhfdHeader],
    ) -> tuple[tuple[int, str, int], ...]:
        return ()

    # Simulate a faulty allocator overlooking the reserved allocation tail. Its
    # append preserves the full captured raster, so prefix hashing alone passes.
    # The independent verifier still reads the real retained MHNI allocation.
    monkeypatch.setattr(
        _artwork_writing, "retained_artwork_extents", omit_allocation_evidence
    )

    result = source.prepare(
        source.analyze(source.begin_draft(desired), TARGET), resources_for(file)
    )

    assert result.prepared is None
    assert any(
        "overwrites an unavailable reserved path" in issue.message
        for issue in result.issues
    )
    assert source.serialize() == retained


def test_clearing_cover_associations_preserves_an_invalid_retained_filename() -> None:
    healthy, _ = with_shared_artwork()
    original = healthy.serialize()
    assert original.artwork is not None
    document = parse_ArtworkDB(original.artwork)
    selection = document.find_chunks(MhiiHeader)[0]
    row = selection.chunk
    container = row.children[0]
    assert isinstance(container.payload, MhodContainerPayload)
    location = container.payload.child
    filename = location.children[0]
    assert isinstance(filename.payload, MhodStringPayload)
    changed_location = replace(
        location,
        children=(
            replace(
                filename, payload=replace(filename.payload, value=":..:unsafe.ithmb")
            ),
            *location.children[1:],
        ),
    )
    document = document.replace_chunk(
        selection,
        replace(
            row,
            children=(
                replace(
                    container,
                    payload=replace(container.payload, child=changed_location),
                ),
                *row.children[1:],
            ),
        ),
    )
    source = IPodLibrary(original.itunes).with_artwork(write_ArtworkDB(document))
    desired = replace(
        source.snapshot,
        tracks=tuple(replace(track, artwork_id=0) for track in source.snapshot.tracks),
    )

    result = source.prepare(source.analyze(source.begin_draft(desired), TARGET))

    assert result.prepared is not None, result.issues
    assert result.prepared.artwork is not None
    assert not result.prepared.artwork_files
    assert all(track.artwork_id == 0 for track in result.prepared.snapshot.tracks)
    retained = parse_ArtworkDB(result.prepared.artwork).find_chunks(MhiiHeader)[0].chunk
    original_artwork = source.serialize().artwork
    assert original_artwork is not None
    original_row = parse_ArtworkDB(original_artwork).find_chunks(MhiiHeader)[0].chunk
    assert retained.children == original_row.children


def _source_with_non_thumbnail_container() -> tuple[IPodLibrary, PreparedFile]:
    healthy, file = with_shared_artwork()
    original = healthy.serialize()
    assert original.artwork is not None
    document = parse_ArtworkDB(original.artwork)
    selection = document.find_chunks(MhiiHeader)[0]
    row = selection.chunk
    container = row.children[0]
    assert isinstance(container.header, MhodHeader)
    assert isinstance(container.payload, MhodContainerPayload)
    non_thumbnail = replace(
        container,
        header=replace(container.header, mhod_type=ArtworkMhodType.FULL_RES_IMAGE),
        payload=replace(
            container.payload,
            child=replace(
                container.payload.child,
                header=replace(container.payload.child.header, image_time_key=15000),
            ),
            trailing_data=b"retained non-thumbnail data",
        ),
    )
    document = document.replace_chunk(
        selection, replace(row, children=(*row.children, non_thumbnail))
    )
    source = IPodLibrary(original.itunes).with_artwork(write_ArtworkDB(document))
    return source, file


def test_cover_replacement_preserves_non_thumbnail_container_bytes() -> None:
    source, file = _source_with_non_thumbnail_container()
    retained = source.serialize()
    assert retained.artwork is not None
    first, second = source.snapshot.tracks
    assert first.ipod is not None
    desired = replace(source.snapshot, tracks=(replace(first, artwork_id=-2), second))
    result = source.prepare(
        source.analyze(source.begin_draft(desired), TARGET), resources_for(file)
    )
    assert result.prepared is not None and result.prepared.artwork is not None, (
        result.issues
    )
    output = parse_ArtworkDB(result.prepared.artwork)
    created = next(
        item.chunk
        for item in output.find_chunks(MhiiHeader)
        if item.chunk.header.image_id == result.prepared.snapshot.tracks[0].artwork_id
    )
    preserved = next(
        child
        for child in created.children
        if isinstance(child.header, MhodHeader)
        and child.header.mhod_type == ArtworkMhodType.FULL_RES_IMAGE
    )
    prior = next(
        item.chunk
        for item in parse_ArtworkDB(retained.artwork).find_chunks(MhodHeader)
        if item.chunk.header.mhod_type == ArtworkMhodType.FULL_RES_IMAGE
    )
    assert (
        result.prepared.artwork[
            preserved.offset : preserved.offset
            + preserved.generic_header.length_or_child_count
        ]
        == retained.artwork[
            prior.offset : prior.offset + prior.generic_header.length_or_child_count
        ]
    )
    assert source.serialize() == retained


def _mutate_non_thumbnail[**P](
    method: Callable[P, ArtworkResult], *, first_row: bool, change: str
) -> Callable[P, ArtworkResult]:
    def corrupt(*args: P.args, **kwargs: P.kwargs) -> ArtworkResult:
        itunes, artwork, files, mappings = method(*args, **kwargs)
        assert artwork is not None
        selection = artwork.find_chunks(MhiiHeader)[0 if first_row else -1]
        row = selection.chunk
        container = next(
            child
            for child in row.children
            if isinstance(child.header, MhodHeader)
            and child.header.mhod_type == ArtworkMhodType.FULL_RES_IMAGE
        )
        assert isinstance(container.payload, MhodContainerPayload)
        location = container.payload.child
        if change == "offset":
            location = replace(
                location,
                header=replace(
                    location.header, ithmb_offset=location.header.ithmb_offset + 1
                ),
            )
        else:
            name = location.children[0]
            assert isinstance(name.payload, MhodStringPayload)
            name = replace(name, payload=replace(name.payload, value=":tampered.ithmb"))
            location = replace(location, children=(name, *location.children[1:]))
        replacement = replace(
            container, payload=replace(container.payload, child=location)
        )
        artwork = artwork.replace_chunk(
            selection,
            replace(
                row,
                children=tuple(
                    replacement if child is container else child
                    for child in row.children
                ),
            ),
        )
        return itunes, artwork, files, mappings

    return corrupt


@pytest.mark.parametrize("row", ["retained", "created", "clone", "retained_clone"])
@pytest.mark.parametrize("change", ["offset", "filename"])
def test_verification_rejects_mutated_non_thumbnail_container(
    monkeypatch: pytest.MonkeyPatch,
    row: str,
    change: str,
) -> None:
    source, file = _source_with_non_thumbnail_container()
    if row == "retained_clone":
        first, second = source.snapshot.tracks
        cleared = source.prepare(
            source.analyze(
                source.begin_draft(
                    replace(
                        source.snapshot, tracks=(first, replace(second, artwork_id=0))
                    )
                ),
                TARGET,
            )
        )
        assert cleared.prepared is not None and cleared.prepared.artwork is not None
        source = IPodLibrary(cleared.prepared.itunes).with_artwork(
            cleared.prepared.artwork
        )
    retained = source.serialize()
    first, second = source.snapshot.tracks
    desired = replace(
        source.snapshot,
        tracks=(
            replace(first, artwork_id=-2),
            replace(second, artwork_id=-2) if row == "clone" else second,
        ),
    )
    target = (
        replace(TARGET, supports_sparse_artwork=False)
        if row in {"clone", "retained_clone"}
        else TARGET
    )
    if row == "retained_clone":
        desired = replace(
            source.snapshot,
            tracks=(first, replace(second, artwork_id=first.artwork_id)),
        )
    plan = source.analyze(source.begin_draft(desired), target)
    resources = resources_for(file)
    if row == "retained_clone":
        resources = replace(resources, artwork=())
    assert source.prepare(plan, resources).prepared is not None
    monkeypatch.setattr(
        preparation,
        "reconcile_artwork",
        _mutate_non_thumbnail(
            _artwork_writing.reconcile_artwork,
            first_row=row == "retained",
            change=change,
        ),
    )
    result = source.prepare(plan, resources)
    assert result.prepared is None
    assert any("non-thumbnail" in issue.message for issue in result.issues)
    assert source.serialize() == retained


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        (":nested:表紙.ithmb", "iPod_Control/Artwork/nested/表紙.ithmb"),
        (":nested/cover.ithmb", "iPod_Control/Artwork/nested/cover.ithmb"),
        ("random.ithmb", "iPod_Control/Artwork/random.ithmb"),
        (
            ":iPod_Control:Artwork:nested:cover.ithmb",
            "iPod_Control/Artwork/nested/cover.ithmb",
        ),
    ],
)
def test_artwork_filename_resolution_preserves_all_path_components(
    token: str,
    expected: str,
) -> None:
    assert _artwork_writing.artwork_path(token) == expected


@pytest.mark.parametrize(
    "token",
    [
        "",
        ":",
        "::cover.ithmb",
        ":../cover.ithmb",
        ":nested:..:cover.ithmb",
        ":nested::cover.ithmb",
        ":nested\\cover.ithmb",
        ":/absolute.ithmb",
        "/absolute.ithmb",
        ":cover.png",
        ":nul\0.ithmb",
    ],
)
def test_artwork_filename_resolution_rejects_unsafe_or_unsupported_tokens(
    token: str,
) -> None:
    with pytest.raises(ValueError):
        _artwork_writing.artwork_path(token)
