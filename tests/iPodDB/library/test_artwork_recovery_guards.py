"""Independent publication guards around damaged retained artwork evidence."""

from dataclasses import replace

import pytest
from tests.iPodDB.library.test_write_artwork import (
    BLUE,
    TARGET,
    resources_for,
    with_shared_artwork,
)

from iPodDB.ArtworkDB.parser.parse_ArtworkDB import parse_ArtworkDB
from iPodDB.ArtworkDB.shared.chunk_defs.mhfd import MhfdHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhod_payloads.container_mhod import (
    MhodContainerPayload,
)
from iPodDB.ArtworkDB.shared.chunk_defs.mhod_payloads.string_mhod import (
    MhodStringPayload,
)
from iPodDB.ArtworkDB.writer.write_ArtworkDB import write_ArtworkDB
from iPodDB.library import IPodLibrary, _artwork_writing
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
