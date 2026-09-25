"""Checkpoints describe real work and let callers stop pure preparation."""

from dataclasses import replace

import pytest
from tests.iPodDB.library.test_writing import library

from iPodDB.library import WriteChecksum, WritePhase, WriteTarget


def test_progress_tracks_actual_stages_without_changing_output() -> None:
    source = library()
    desired = replace(
        source.snapshot,
        playlists=(replace(source.snapshot.playlists[0], name="Changed"),),
    )
    target = WriteTarget(
        checksum=WriteChecksum.HASH58, firewire_guid=bytes.fromhex("000A270012345678")
    )
    plan = source.analyze(source.begin_draft(desired), target)
    phases: list[WritePhase] = []
    observed = source.prepare(plan, progress=phases.append)
    assert observed == source.prepare(plan)
    assert observed.prepared is not None
    assert phases == list(WritePhase)


def test_noop_only_reports_the_stages_it_performs() -> None:
    source = library()
    phases: list[WritePhase] = []
    result = source.prepare(
        source.analyze(source.begin_draft()), progress=phases.append
    )
    assert result.prepared is not None
    assert result.prepared.itunes == source.serialize().itunes
    assert phases == [
        WritePhase.VALIDATION,
        WritePhase.RESOURCES,
        WritePhase.SERIALIZATION,
    ]


@pytest.mark.parametrize("stop", tuple(WritePhase))
def test_caller_cancellation_propagates_at_each_checkpoint(stop: WritePhase) -> None:
    source = library()
    original = source.serialize()
    desired = replace(
        source.snapshot,
        playlists=(replace(source.snapshot.playlists[0], name="Changed"),),
    )
    plan = source.analyze(
        source.begin_draft(desired),
        WriteTarget(
            checksum=WriteChecksum.HASH58,
            firewire_guid=bytes.fromhex("000A270012345678"),
        ),
    )
    phases: list[WritePhase] = []
    error = ValueError("caller cancelled")

    def progress(phase: WritePhase) -> None:
        phases.append(phase)
        if phase is stop:
            raise error

    with pytest.raises(ValueError, match="caller cancelled") as caught:
        source.prepare(plan, progress=progress)
    assert caught.value is error
    assert phases[-1] is stop
    assert source.serialize() == original
    assert source.snapshot.playlists[0].name != "Changed"


def test_blocked_resource_validation_does_not_report_reconciliation() -> None:
    source = library()
    desired = replace(
        source.snapshot,
        tracks=(
            *source.snapshot.tracks,
            replace(source.snapshot.tracks[0], track_id=-1, ipod=None),
        ),
    )
    phases: list[WritePhase] = []
    result = source.prepare(
        source.analyze(source.begin_draft(desired)), progress=phases.append
    )
    assert result.prepared is None
    assert any(i.code == "resources.missing_media" for i in result.issues)
    assert phases == [WritePhase.VALIDATION, WritePhase.RESOURCES]


def test_debug_log_explains_album_edit_output_and_timings(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("DEBUG", logger="iPodDB.library")
    source = library()
    desired = replace(
        source.snapshot,
        tracks=tuple(replace(t, album="New album") for t in source.snapshot.tracks),
    )
    target = WriteTarget(
        checksum=WriteChecksum.HASH58, firewire_guid=bytes.fromhex("000A270012345678")
    )
    plan = source.analyze(source.begin_draft(desired), target)
    result = source.prepare(plan)
    assert result.prepared is not None, result.issues
    text = caplog.text
    assert f"source={plan.draft.source_revision}" in text
    assert "origin=requested subject=track id=1" in text
    assert "field=album before='' after='New album'" in text
    assert "Library requirements" in text and "pending_sidecars=None" in text
    assert "checksum=hash58" in text and "signing_identity_present=True" in text
    assert "iTunesDB_sha256=" in text and "artifact=iTunesDB" in text
    assert "prepared=True" in text and "Library stage elapsed" in text
    assert "phase=verification elapsed_ms=" in text
    assert target.firewire_guid.hex() not in text.lower()


def test_info_logging_does_not_emit_write_debug_details(
    caplog: pytest.LogCaptureFixture,
) -> None:
    source = library()
    caplog.set_level("INFO", logger="iPodDB.library")
    desired = replace(
        source.snapshot,
        tracks=tuple(replace(t, album="Private album") for t in source.snapshot.tracks),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    assert "Private album" not in caplog.text
    assert "Library candidate" not in caplog.text
