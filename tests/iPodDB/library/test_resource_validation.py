"""Captured resource evidence is checked even when a draft changes no records."""

import hashlib
from dataclasses import replace

import pytest
from tests.iPodDB.library.test_writing import library

from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.writer.signature import verify_hashab
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import (
    IPodLibrary,
    PreparedMedia,
    WriteChecksum,
    WritePhase,
    WriteResources,
    WriteTarget,
)
from iPodDB.library.writing import FileDependency, SourceFile

_DATA = b"captured thumbnail prefix"
_FILE = FileDependency(
    "iPod_Control/Artwork/F1028_1.ithmb", len(_DATA), hashlib.sha256(_DATA).hexdigest()
)
_MEDIA = PreparedMedia(
    1, FileDependency("iPod_Control/Music/F00/other.m4a", 5, "a" * 64), 0, 0, 0, 0, 0
)


@pytest.mark.parametrize("edited", [False, True], ids=["unchanged", "title-edit"])
@pytest.mark.parametrize(
    ("resources", "code"),
    [
        pytest.param(
            WriteResources(media=(_MEDIA,)),
            "resources.unrequested_media",
            id="media-without-intent",
        ),
        pytest.param(
            WriteResources(media=(replace(_MEDIA, track_id=999),)),
            "resources.unrequested_media",
            id="media-for-missing-track",
        ),
        pytest.param(
            WriteResources(media=(_MEDIA, _MEDIA)),
            "resources.duplicate_identity",
            id="duplicate-media",
        ),
        pytest.param(
            WriteResources(file_inventory=(_FILE, replace(_FILE, size=-1))),
            "resources.file_collision",
            id="duplicate-inventory",
        ),
        pytest.param(
            WriteResources(
                file_inventory=(
                    _FILE,
                    replace(_FILE, relative_path=_FILE.relative_path.upper()),
                )
            ),
            "resources.file_collision",
            id="inventory-case-collision",
        ),
        pytest.param(
            WriteResources(file_inventory=(replace(_FILE, size=-1),)),
            "resources.invalid_inventory",
            id="negative-inventory-size",
        ),
        pytest.param(
            WriteResources(file_inventory=(replace(_FILE, sha256="not a hash"),)),
            "resources.invalid_inventory",
            id="invalid-inventory-hash",
        ),
        pytest.param(
            WriteResources(file_inventory=(replace(_FILE, relative_path="../x"),)),
            "resources.invalid_inventory",
            id="unsafe-inventory-path",
        ),
        pytest.param(
            WriteResources(files=(SourceFile(_FILE, b"different bytes"),)),
            "resources.changed_file",
            id="changed-source-bytes",
        ),
        pytest.param(
            WriteResources(
                files=(SourceFile(replace(_FILE, relative_path="../x"), _DATA),)
            ),
            "resources.changed_file",
            id="unsafe-source-path",
        ),
        pytest.param(
            WriteResources(files=(SourceFile(_FILE, _DATA), SourceFile(_FILE, _DATA))),
            "resources.file_collision",
            id="duplicate-source-files",
        ),
    ],
)
def test_invalid_resources_block_before_serialization(
    resources: WriteResources, code: str, edited: bool
) -> None:
    source = library()
    original = source.serialize()
    desired = source.snapshot
    if edited:
        desired = replace(
            desired,
            tracks=(replace(desired.tracks[0], title="Edited"), desired.tracks[1]),
        )
    draft = source.begin_draft(desired)
    phases: list[WritePhase] = []
    result = source.prepare(source.analyze(draft), resources, progress=phases.append)

    assert result.prepared is None
    assert code in {issue.code for issue in result.issues}
    assert phases == [WritePhase.VALIDATION, WritePhase.RESOURCES]
    assert draft.snapshot == desired
    assert source.serialize() == original


@pytest.mark.parametrize("hashing_scheme", [0, 1, 2, 3])
@pytest.mark.parametrize("captured_context", [False, True])
def test_valid_noop_retains_bytes_without_requiring_supported_signing(
    hashing_scheme: int, captured_context: bool
) -> None:
    document = parse_iTunesDB(library().serialize().itunes)
    original = write_iTunesDB(
        replace(
            document, header=replace(document.header, hashing_scheme=hashing_scheme)
        )
    )
    source = IPodLibrary(original)
    resources = (
        WriteResources(
            files=(SourceFile(_FILE, _DATA),),
            file_inventory=(_FILE,),
            pending_playback_sidecars=True,
        )
        if captured_context
        else WriteResources()
    )
    # An unsupported target matters only when producing changed database bytes.
    plan = source.analyze(
        source.begin_draft(), WriteTarget(checksum=WriteChecksum.HASHAB)
    )
    result = source.prepare(plan, resources)

    assert result.prepared is not None, result.issues
    assert result.prepared.itunes == original
    assert result.prepared.artwork is None
    assert result.prepared.artwork_files == ()
    assert source.serialize().itunes == original


def test_itunes_hashab_scheme_three_source_can_be_edited() -> None:
    document = parse_iTunesDB(library().serialize().itunes)
    source = IPodLibrary(
        write_iTunesDB(
            replace(document, header=replace(document.header, hashing_scheme=3))
        )
    )
    guid = bytes.fromhex("f832c65917da6785")
    desired = replace(
        source.snapshot,
        tracks=(
            replace(source.snapshot.tracks[0], title="Edited"),
            source.snapshot.tracks[1],
        ),
    )

    result = source.prepare(
        source.analyze(
            source.begin_draft(desired),
            WriteTarget(checksum=WriteChecksum.HASHAB, firewire_guid=guid),
        )
    )

    assert result.prepared is not None, result.issues
    assert int.from_bytes(result.prepared.itunes[0x30:0x32], "little") == 3
    assert verify_hashab(result.prepared.itunes, guid)


def test_noop_resource_error_is_logged_with_track_context(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("DEBUG", logger="iPodDB.library")
    source = library()
    result = source.prepare(
        source.analyze(source.begin_draft()), WriteResources(media=(_MEDIA,))
    )

    assert result.prepared is None
    assert "resources.unrequested_media" in caplog.text
    assert "subject='track', record_id=1" in caplog.text
    assert "prepared=False" in caplog.text


def test_noop_resource_validation_can_be_cancelled() -> None:
    source = library()
    original = source.serialize()
    phases: list[WritePhase] = []
    cancellation = ValueError("cancelled resource validation")

    def progress(phase: WritePhase) -> None:
        phases.append(phase)
        if phase is WritePhase.RESOURCES:
            raise cancellation

    with pytest.raises(ValueError, match="cancelled resource validation") as caught:
        source.prepare(source.analyze(source.begin_draft()), progress=progress)

    assert caught.value is cancellation
    assert phases == [WritePhase.VALIDATION, WritePhase.RESOURCES]
    assert source.serialize() == original
