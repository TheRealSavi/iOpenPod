"""Recover complete Photos while retaining exact damaged input until publication."""

from dataclasses import replace

import pytest
from tests.iPodDB.library.test_photos import (
    _source,  # pyright: ignore[reportPrivateUsage]
)
from tests.iPodDB.library.test_writing import library

from iPodDB.library import IPodLibrary, _write_preparation
from iPodDB.PhotosDB.parser.parse_PhotosDB import parse_PhotosDB
from iPodDB.PhotosDB.shared.chunk_defs.mhfd import MhfdHeader
from iPodDB.PhotosDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.PhotosDB.writer.write_PhotosDB import write_PhotosDB
from iPodDB.shared.chunk import DatabaseDocument


@pytest.mark.parametrize("count", [0, 2, 0xFFFFFFFF])
@pytest.mark.parametrize("edit", [False, True])
def test_recovered_photos_publish_only_evidenced_count_changes(
    count: int, edit: bool
) -> None:
    photo_bytes = _source().serialize().photos
    assert photo_bytes is not None
    healthy = library().with_photos(photo_bytes)
    original = healthy.serialize()
    assert original.photos is not None
    image_list = (
        parse_PhotosDB(original.photos).find_chunks(MhsdHeader)[0].chunk.children[0]
    )
    offset = image_list.offset + 8
    damaged = (
        original.photos[:offset]
        + count.to_bytes(4, "little")
        + original.photos[offset + 4 :]
    )
    source = IPodLibrary(original.itunes).with_photos(damaged)
    assert source.snapshot == healthy.snapshot
    assert source.serialize().photos == damaged
    desired = (
        replace(source.snapshot, device_name="Recovered") if edit else source.snapshot
    )
    plan = source.analyze(source.begin_draft(desired))
    assert plan.changes_itunes is edit
    assert any(change.subject == "photos_database" for change in plan.changes)
    result = source.prepare(plan)
    assert result.prepared is not None, result.issues
    assert result.prepared.photos is not None
    assert result.prepared.photos == original.photos
    assert source.serialize().photos == damaged
    assert any(issue.code == "photos.repaired_image_count" for issue in result.issues)
    if not edit:
        assert result.prepared.itunes == original.itunes
    reloaded = IPodLibrary(result.prepared.itunes).with_photos(result.prepared.photos)
    assert not reloaded.photos_repairs
    assert not reloaded.analyze(reloaded.begin_draft()).changes


def test_count_repair_rejects_unrelated_writer_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = _source().serialize()
    assert original.photos is not None
    image_list = (
        parse_PhotosDB(original.photos).find_chunks(MhsdHeader)[0].chunk.children[0]
    )
    offset = image_list.offset + 8
    damaged = original.photos[:offset] + bytes(4) + original.photos[offset + 4 :]
    source = IPodLibrary(original.itunes).with_photos(damaged)

    def corrupt(document: DatabaseDocument[MhfdHeader]) -> bytes:
        return write_PhotosDB(
            replace(document, header=replace(document.header, unk_mhfd_0x34=999))
        )

    monkeypatch.setattr(_write_preparation, "write_PhotosDB", corrupt)
    result = source.prepare(source.analyze(source.begin_draft()))
    assert result.prepared is None
    assert any(
        issue.code == "verification.unrequested_photos" for issue in result.issues
    )
    assert source.serialize().photos == damaged
