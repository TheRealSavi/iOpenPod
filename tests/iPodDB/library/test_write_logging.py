"""Large Syncs retain diagnostic samples without flooding the rotating log."""

from dataclasses import replace

import pytest
from tests.iPodDB.library.test_writing import library

from iPodDB.library import FileDependency, PreparedMedia, WriteResources
from iPodDB.library._write_logging import log_resources, log_result
from iPodDB.library.writing import IdentityMapping


def test_large_library_analysis_logs_counts_and_bounded_details(
    caplog: pytest.LogCaptureFixture,
) -> None:
    source = library()
    desired = replace(
        source.snapshot,
        tracks=tuple(
            replace(
                source.snapshot.tracks[0], track_id=index + 1, ipod=None, album="Batch"
            )
            for index in range(500)
        ),
    )
    caplog.set_level("DEBUG", logger="iPodDB.library")
    plan = source.analyze(source.begin_draft(desired))
    source.prepare(plan)
    assert "tracks=500" in caplog.text
    assert "field=album" in caplog.text
    assert "omitted=" in caplog.text
    assert len(caplog.text) < 64_000
    assert len(caplog.records) < 250


def test_large_resources_and_identity_results_log_bounded_samples(
    caplog: pytest.LogCaptureFixture,
) -> None:
    source = library()
    result = source.prepare(source.analyze(source.begin_draft()))
    assert result.prepared is not None
    media = tuple(
        PreparedMedia(
            index + 1,
            FileDependency(f"iPod_Control/Music/F00/{index}.m4a", 5, "a" * 64),
            0,
            0,
            0,
            0,
            0,
        )
        for index in range(500)
    )
    prepared = replace(
        result.prepared,
        identities=tuple(
            IdentityMapping("track", index, index) for index in range(500)
        ),
    )
    caplog.set_level("DEBUG", logger="iPodDB.library")
    log_resources(
        prepared.source_revision,
        WriteResources(media=media, file_inventory=tuple(m.file for m in media)),
    )
    log_result(prepared.source_revision, replace(result, prepared=prepared))
    assert "media=500" in caplog.text
    assert "Library identity" in caplog.text
    assert "omitted=" in caplog.text
    assert len(caplog.text) < 40_000
    assert len(caplog.records) < 80
