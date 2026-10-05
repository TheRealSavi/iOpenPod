"""Corruption after artwork reconciliation must never become a Prepared Library."""

from collections.abc import Callable
from dataclasses import replace

import pytest
from tests.iPodDB.library.test_write_artwork import (
    TARGET,
    resources_for,
    with_shared_artwork,
)

from iPodDB.ArtworkDB.shared.chunk_defs.mhfd import MhfdHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhif import MhifHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhod_payloads.container_mhod import (
    MhodContainerPayload,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.library import IdentityMapping, PreparedFile
from iPodDB.library import _write_preparation as preparation
from iPodDB.library._artwork_writing import reconcile_artwork
from iPodDB.library._document_edit import rebuild
from iPodDB.shared.chunk import DatabaseDocument

type ArtworkResult = tuple[
    DatabaseDocument[MhbdHeader],
    DatabaseDocument[MhfdHeader] | None,
    tuple[PreparedFile, ...],
    tuple[IdentityMapping, ...],
]


def _fault[**P](
    method: Callable[P, ArtworkResult], mode: str
) -> Callable[P, ArtworkResult]:
    def corrupt(*args: P.args, **kwargs: P.kwargs) -> ArtworkResult:
        itunes, artwork, files, identities = method(*args, **kwargs)
        assert artwork is not None and files
        if mode == "prefix":
            first = files[0]
            assert isinstance(first.data, bytes)
            files = (
                replace(first, data=bytes([first.data[0] ^ 255]) + first.data[1:]),
                *files[1:],
            )
        elif mode == "retained_range":
            old = next(
                s.chunk
                for s in artwork.find_chunks(MhodHeader)
                if isinstance(s.chunk.payload, MhodContainerPayload)
            )
            payload = old.payload
            assert isinstance(payload, MhodContainerPayload)
            child = payload.child
            changed = replace(
                old,
                payload=replace(
                    payload,
                    child=replace(
                        child,
                        header=replace(
                            child.header, ithmb_offset=child.header.ithmb_offset + 1
                        ),
                    ),
                ),
            )
            artwork = rebuild(artwork, {id(old): changed})
        elif mode == "duplicate_file":
            files = (*files, files[0])
        elif mode == "root_id":
            artwork = replace(artwork, header=replace(artwork.header, next_mhii_id=1))
        elif mode == "file_size":
            selection = artwork.find_chunks(MhifHeader)[0]
            artwork = artwork.replace_chunk(
                selection,
                replace(
                    selection.chunk,
                    header=replace(selection.chunk.header, image_size=1),
                ),
            )
        elif mode == "track_flag":
            track_selection = itunes.find_chunks(MhitHeader)[0]
            itunes = itunes.replace_chunk(
                track_selection,
                replace(
                    track_selection.chunk,
                    header=replace(track_selection.chunk.header, has_artwork=0),
                ),
            )
        else:
            image_selection = artwork.find_chunks(MhiiHeader)[-1]
            row = image_selection.chunk
            container = row.children[0]
            payload = container.payload
            assert isinstance(payload, MhodContainerPayload)
            header = payload.child.header
            if mode == "dimensions":
                header = replace(header, image_width=1)
            elif mode == "padding":
                header = replace(header, horizontal_padding=1)
            else:
                header = replace(header, image_size_2=1)
            container = replace(
                container,
                payload=replace(payload, child=replace(payload.child, header=header)),
            )
            artwork = artwork.replace_chunk(
                image_selection, replace(row, children=(container, *row.children[1:]))
            )
        return itunes, artwork, files, identities

    return corrupt


@pytest.mark.parametrize(
    "mode",
    [
        "prefix",
        "retained_range",
        "duplicate_file",
        "root_id",
        "file_size",
        "track_flag",
        "dimensions",
        "padding",
        "secondary_size",
    ],
)
def test_corrupt_artwork_output_is_withheld(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    source, file = with_shared_artwork()
    first, second = source.snapshot.tracks
    desired = replace(source.snapshot, tracks=(replace(first, artwork_id=-2), second))
    plan = source.analyze(source.begin_draft(desired), TARGET)
    resources = resources_for(file)
    assert source.prepare(plan, resources).prepared is not None
    monkeypatch.setattr(
        preparation, "reconcile_artwork", _fault(reconcile_artwork, mode)
    )
    result = source.prepare(plan, resources)
    assert result.prepared is None
    assert any(i.code == "verification.failed" for i in result.issues)
