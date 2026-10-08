"""Recover bounded image-list counts without losing original database evidence."""

from dataclasses import replace

import pytest
from tests.iPodDB.library.test_write_artwork import TARGET, with_shared_artwork

from iPodDB.ArtworkDB.parser.parse_ArtworkDB import parse_ArtworkDB
from iPodDB.ArtworkDB.shared.chunk_defs.mhfd import MhfdHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.ArtworkDB.writer.write_ArtworkDB import write_ArtworkDB
from iPodDB.iTunesDB.cdb import compress_iTunesCDB
from iPodDB.library import IPodLibrary, WriteChecksum, _write_preparation
from iPodDB.shared.chunk import DatabaseDocument


@pytest.mark.parametrize("recorded_count", [0, 2, 0xFFFFFFFF])
@pytest.mark.parametrize("edit", [False, True])
def test_recover_count_for_display_and_publish_repair_with_original_retained(
    recorded_count: int, edit: bool
) -> None:
    healthy, _ = with_shared_artwork()
    original = healthy.serialize()
    assert original.artwork is not None
    image_list = (
        parse_ArtworkDB(original.artwork).find_chunks(MhsdHeader)[0].chunk.children[0]
    )
    count_offset = image_list.offset + 8
    damaged = (
        original.artwork[:count_offset]
        + recorded_count.to_bytes(4, "little")
        + original.artwork[count_offset + 4 :]
    )

    source = IPodLibrary(original.itunes).with_artwork(damaged)

    assert source.snapshot == healthy.snapshot
    assert source.serialize().artwork == damaged
    desired = (
        replace(source.snapshot, device_name="Recovered") if edit else source.snapshot
    )
    plan = source.analyze(source.begin_draft(desired), TARGET)
    assert any(change.subject == "artwork_database" for change in plan.changes)
    assert plan.changes_itunes is edit
    result = source.prepare(plan)
    assert result.prepared is not None, result.issues
    assert result.prepared.artwork is not None
    assert result.prepared.artwork == original.artwork
    assert not result.prepared.artwork_files
    if not edit:
        assert result.prepared.itunes == original.itunes
    assert source.serialize().artwork == damaged
    assert any(issue.code == "artwork.repaired_image_count" for issue in result.issues)
    repaired = IPodLibrary(result.prepared.itunes).with_artwork(result.prepared.artwork)
    assert not repaired.artwork_repairs
    assert not repaired.analyze(repaired.begin_draft(), TARGET).changes


def test_count_repair_cannot_bypass_artwork_signature_requirements() -> None:
    healthy, _ = with_shared_artwork()
    original = healthy.serialize()
    assert original.artwork is not None
    image_list = (
        parse_ArtworkDB(original.artwork).find_chunks(MhsdHeader)[0].chunk.children[0]
    )
    count_offset = image_list.offset + 8
    damaged = (
        original.artwork[:count_offset]
        + bytes(4)
        + original.artwork[count_offset + 4 :]
    )
    source = IPodLibrary(original.itunes).with_artwork(damaged)
    result = source.prepare(
        source.analyze(
            source.begin_draft(), replace(TARGET, artwork_checksum=WriteChecksum.HASH58)
        )
    )
    assert result.prepared is None
    assert any(
        issue.code == "target.unsupported_artwork_signature" for issue in result.issues
    )


def test_count_repair_verification_rejects_unrelated_serializer_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    healthy, _ = with_shared_artwork()
    original = healthy.serialize()
    assert original.artwork is not None
    image_list = (
        parse_ArtworkDB(original.artwork).find_chunks(MhsdHeader)[0].chunk.children[0]
    )
    count_offset = image_list.offset + 8
    damaged = (
        original.artwork[:count_offset]
        + bytes(4)
        + original.artwork[count_offset + 4 :]
    )
    source = IPodLibrary(original.itunes).with_artwork(damaged)

    def corrupt_writer(document: DatabaseDocument[MhfdHeader]) -> bytes:
        # An idempotent writer fault still passes serialize/reparse/serialize.
        # Verification must compare with the separately established repair bytes.
        changed = replace(document, header=replace(document.header, unk_mhfd_0x34=999))
        return write_ArtworkDB(changed)

    monkeypatch.setattr(_write_preparation, "write_ArtworkDB", corrupt_writer)

    result = source.prepare(source.analyze(source.begin_draft(), TARGET))

    assert result.prepared is None
    assert any(
        issue.code == "verification.unrequested_artwork" for issue in result.issues
    )
    assert source.serialize().artwork == damaged


def test_artwork_only_repair_retains_compressed_source_without_conversion_target() -> (
    None
):
    healthy, _ = with_shared_artwork()
    original = healthy.serialize()
    assert original.artwork is not None
    image_list = (
        parse_ArtworkDB(original.artwork).find_chunks(MhsdHeader)[0].chunk.children[0]
    )
    offset = image_list.offset + 8
    damaged = original.artwork[:offset] + bytes(4) + original.artwork[offset + 4 :]
    compressed = compress_iTunesCDB(original.itunes)
    source = IPodLibrary(compressed).with_artwork(damaged)

    result = source.prepare(source.analyze(source.begin_draft()))

    assert result.prepared is not None, " | ".join(i.message for i in result.issues)
    assert result.prepared.itunes == compressed
    assert result.prepared.artwork == original.artwork
    assert result.prepared.sqlite is None
