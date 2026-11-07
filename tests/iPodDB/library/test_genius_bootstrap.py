"""Explicit Classic generation initializes only the evidenced CUID envelope."""

from dataclasses import replace

import pytest
from tests.iPodDB.library.test_genius_writing import update
from tests.iPodDB.library.test_writing import library

from iPodDB.iTunesDB.builder.build_iTunesDB import new_itunes_chunk
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import DEFINITION as MHSD
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import IPodLibrary, WriteTarget, _write_preparation
from iPodDB.library.genius import GeniusData, GeniusUpdate
from iPodDB.shared.chunk import DatabaseDocument, RawPayload


def _dataset_bytes(data: bytes, kind: int) -> tuple[bytes, ...]:
    return tuple(
        row.chunk.raw_header + row.chunk.raw_body
        for row in parse_iTunesDB(data).find_chunks(MhsdHeader)
        if row.chunk.header.dataset_type == kind
    )


def test_explicit_classic_generation_adds_stable_bounded_cuid() -> None:
    source = library()
    original = source.serialize().itunes
    assert not _dataset_bytes(original, 9)
    plan = source.analyze(source.begin_draft(genius_update=update()))
    first = source.prepare(plan)
    second = source.prepare(plan)
    assert first.prepared is not None, first.issues
    assert second.prepared is not None, second.issues
    assert first.prepared.itunes == second.prepared.itunes
    datasets = tuple(
        row.chunk
        for row in parse_iTunesDB(first.prepared.itunes).find_chunks(MhsdHeader)
        if row.chunk.header.dataset_type == 9
    )
    assert len(datasets) == 1
    dataset = datasets[0]
    assert dataset.generic_header.header_length == MHSD.default_header_size
    assert dataset.generic_header.length_or_child_count == MHSD.default_header_size + 32
    cuid = dataset.payload_as(RawPayload).data
    assert len(cuid) == 32 and all(value in b"0123456789ABCDEF" for value in cuid)
    assert _dataset_bytes(first.prepared.itunes, 999) == _dataset_bytes(original, 999)
    assert source.serialize().itunes == original


@pytest.mark.parametrize("operation", ("noop", "metadata", "clear", "sqlite"))
def test_other_writes_never_initialize_classic_cuid(operation: str) -> None:
    source = library()
    snapshot = source.snapshot
    if operation == "metadata":
        snapshot = replace(
            snapshot,
            tracks=(replace(snapshot.tracks[0], title="Changed"), *snapshot.tracks[1:]),
        )
    intent = (
        update()
        if operation == "sqlite"
        else GeniusUpdate(GeniusData(), mixes=())
        if operation == "clear"
        else None
    )
    result = source.prepare(
        source.analyze(
            source.begin_draft(snapshot, genius_update=intent),
            WriteTarget(sqlite_database=operation == "sqlite"),
        )
    )
    assert result.prepared is not None, result.issues
    assert not _dataset_bytes(result.prepared.itunes, 9)


@pytest.mark.parametrize("payload", (b"", b"future\x00\xffCUID", b"A" * 32))
def test_existing_cuid_remains_opaque_and_exact(payload: bytes) -> None:
    document = parse_iTunesDB(library().serialize().itunes)
    document = document.append_child(
        new_itunes_chunk(MHSD, MhsdHeader(dataset_type=9), payload=RawPayload(payload))
    )
    source = IPodLibrary(write_iTunesDB(document))
    original = source.serialize().itunes
    result = source.prepare(source.analyze(source.begin_draft(genius_update=update())))
    assert result.prepared is not None, result.issues
    assert _dataset_bytes(result.prepared.itunes, 9) == _dataset_bytes(original, 9)


@pytest.mark.parametrize(
    "change", ("remove", "duplicate", "body", "header", "unrelated")
)
def test_bootstrap_verification_rejects_unpermitted_dataset_changes(
    change: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = library()
    original = source.serialize()
    tampered = False

    def corrupt_once(document: DatabaseDocument[MhbdHeader]) -> bytes:
        nonlocal tampered
        if tampered:
            return write_iTunesDB(document)
        tampered = True
        selected = next(
            row
            for row in document.find_chunks(MhsdHeader)
            if row.chunk.header.dataset_type == (999 if change == "unrelated" else 9)
        )
        if change == "remove":
            document = replace(
                document,
                children=tuple(
                    child for child in document.children if child is not selected.chunk
                ),
            )
        elif change == "duplicate":
            document = document.append_child(selected.chunk)
        elif change == "header":
            # The generic writer retains unknown header bytes from a parsed row.
            encoded = write_iTunesDB(document)
            parsed = parse_iTunesDB(encoded)
            selected = next(
                row
                for row in parsed.find_chunks(MhsdHeader)
                if row.chunk.header.dataset_type == 9
            )
            header = bytearray(selected.chunk.raw_header)
            header[-1] = 1
            document = parsed.replace_chunk(
                selected, replace(selected.chunk, raw_header=bytes(header))
            )
        else:
            document = document.replace_chunk(
                selected,
                replace(selected.chunk, payload=RawPayload(b"B" * 32)),
            )
        return write_iTunesDB(document)

    monkeypatch.setattr(_write_preparation, "write_iTunesDB", corrupt_once)
    result = source.prepare(source.analyze(source.begin_draft(genius_update=update())))
    assert result.prepared is None
    assert any("unrelated iTunesDB dataset" in issue.message for issue in result.issues)
    assert source.serialize() == original
