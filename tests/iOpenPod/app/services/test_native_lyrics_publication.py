"""Classic lyrics preparation enforces native limits before file publication."""

import hashlib
from dataclasses import replace
from pathlib import Path
from threading import Event
from typing import BinaryIO

import pytest
from tests.iOpenPod.app.services.test_library_lyrics import desired_lyrics, read_lyrics
from tests.iOpenPod.app.services.test_library_resources import Device, build_device
from tests.iOpenPod.app.test_media_lyrics import fixture, media_payload

from iOpenPod.app.export_tagging import ExportMediaTagger
from iOpenPod.app.library_write import LibraryPreparationRequest, LibraryReview
from iOpenPod.app.media.lyrics import rewrite_lyrics, rewrite_lyrics_stream
from iOpenPod.app.services import library_resources
from iPodDB.library import (
    ArtworkPixels,
    FileDependency,
    IPodLibrary,
    IssueSeverity,
    LibrarySnapshot,
    MediaType,
    PreparedLyrics,
    Track,
    WriteResources,
)

BOUNDARY_TEXT = "é" * 5120
OVERSIZED_TEXT = BOUNDARY_TEXT + "x"


def prepare(
    device: Device, snapshot: LibrarySnapshot, *, rockbox: bool = False
) -> LibraryReview:
    return device.coordinator.prepare_library(
        LibraryPreparationRequest(
            snapshot, device.active, 1, 1, rockbox_metadata=rockbox
        ),
        lambda _: None,
        Event(),
    )


@pytest.mark.parametrize("rockbox", [False, True])
@pytest.mark.parametrize("disk_staged", [False, True])
def test_classic_rejects_oversized_utf8_lyrics_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    rockbox: bool,
    disk_staged: bool,
) -> None:
    device = build_device(tmp_path, media_payload=fixture("tone.m4a"))
    try:
        if disk_staged:
            monkeypatch.setattr(library_resources, "_MAX_CAPTURE_BYTES", 10)
        review = prepare(
            device, desired_lyrics(device, OVERSIZED_TEXT), rockbox=rockbox
        )
        assert review.result.prepared is None
        assert not review.file_changes
        assert any(
            "10,240" in issue.detail or "10240" in issue.detail
            for issue in review.result.issues
        ), review.result.issues
        assert device.save(review).active is None
        device.assert_original()
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("rockbox", [False, True])
def test_classic_publishes_exact_utf8_byte_limit_without_truncating_media(
    tmp_path: Path, rockbox: bool
) -> None:
    original = fixture("tone.m4a")
    device = build_device(tmp_path, media_payload=original)
    try:
        review = prepare(device, desired_lyrics(device, BOUNDARY_TEXT), rockbox=rockbox)
        assert review.result.prepared is not None, review.result.issues
        device.assert_original()
        saved = device.save(review)
        assert saved.active is not None, saved.issues
        track = saved.active.library.tracks[0]
        published = (device.root / track.metadata.location).read_bytes()
        assert read_lyrics(published) == BOUNDARY_TEXT
        assert len(read_lyrics(published).encode("utf-8")) == 10240
        assert track.metadata.lyrics == BOUNDARY_TEXT
        assert track.metadata.has_lyrics
        assert media_payload(published, ".m4a") == media_payload(original, ".m4a")
    finally:
        device.coordinator.close()


def test_explicit_clear_removes_existing_oversized_lyrics(tmp_path: Path) -> None:
    original = rewrite_lyrics(fixture("tone.m4a"), "tone.m4a", OVERSIZED_TEXT)
    device = build_device(tmp_path, media_payload=original)
    try:
        # Model an already populated device; native limits apply to the requested
        # result and must not prevent replacing or clearing incompatible input.
        device.coordinator.close()
        database = device.root / "iPod_Control/iTunes/iTunesDB"
        source = IPodLibrary(database.read_bytes())
        first, second = source.snapshot.tracks
        seeded = replace(first, metadata=replace(first.metadata, lyrics=OVERSIZED_TEXT))
        result = source.prepare(
            source.analyze(
                source.begin_draft(replace(source.snapshot, tracks=(seeded, second)))
            ),
            WriteResources(
                lyrics=(
                    PreparedLyrics(
                        first.track_id,
                        OVERSIZED_TEXT,
                        FileDependency(
                            first.metadata.location,
                            len(original),
                            hashlib.sha256(original).hexdigest(),
                        ),
                    ),
                )
            ),
        )
        assert result.prepared is not None, result.issues
        database.write_bytes(result.prepared.itunes)
        device.original["iPod_Control/iTunes/iTunesDB"] = result.prepared.itunes
        device.coordinator.select_device(
            device.coordinator.discover_devices().candidates[0].id
        )
        assert device.active.library.tracks[0].metadata.lyrics == OVERSIZED_TEXT
        review = prepare(device, desired_lyrics(device, ""))
        assert review.result.prepared is not None, review.result.issues
        device.assert_original()
        saved = device.save(review)
        assert saved.active is not None, saved.issues
        track = saved.active.library.tracks[0]
        published = (device.root / track.metadata.location).read_bytes()
        assert read_lyrics(published) == ""
        assert track.metadata.lyrics == "" and not track.metadata.has_lyrics
        assert media_payload(published, ".m4a") == media_payload(original, ".m4a")
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("media_type", [MediaType.PODCAST, MediaType.AUDIOBOOK])
@pytest.mark.parametrize("description", ["", "Description shown by the native player"])
def test_description_precedence_warns_without_discarding_lyrics(
    tmp_path: Path, media_type: MediaType, description: str
) -> None:
    original = fixture("tone.m4a")
    text = "Complete lyrics remain available to other readers."
    device = build_device(tmp_path, media_payload=original)
    try:
        desired = desired_lyrics(device, text)
        first, second = desired.tracks
        first = replace(
            first,
            media_types=(media_type,),
            metadata=replace(first.metadata, description=description),
        )
        review = prepare(device, replace(desired, tracks=(first, second)))
        assert review.result.prepared is not None, review.result.issues
        warnings = [
            issue
            for issue in review.result.issues
            if issue.code == "lyrics.description_precedence"
        ]
        assert len(warnings) == 1
        assert warnings[0].severity is IssueSeverity.WARNING
        assert warnings[0].record_id == first.track_id
        device.assert_original()
        saved = device.save(review)
        assert saved.active is not None, saved.issues
        track = saved.active.library.tracks[0]
        published = (device.root / track.metadata.location).read_bytes()
        assert read_lyrics(published) == text
        assert track.metadata.lyrics == text and track.metadata.has_lyrics
        assert track.metadata.description == description
        assert media_payload(published, ".m4a") == media_payload(original, ".m4a")
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("rockbox", [False, True])
def test_unqualified_nano_retains_existing_lyrics_preparation_policy(
    tmp_path: Path, rockbox: bool
) -> None:
    original = fixture("tone.m4a")
    device = build_device(tmp_path, media_payload=original, model="MB754")
    try:
        review = prepare(
            device, desired_lyrics(device, OVERSIZED_TEXT), rockbox=rockbox
        )
        assert review.result.prepared is not None, review.result.issues
        device.assert_original()
        saved = device.save(review)
        assert saved.active is not None, saved.issues
        track = saved.active.library.tracks[0]
        published = (device.root / track.metadata.location).read_bytes()
        assert read_lyrics(published) == OVERSIZED_TEXT
        assert media_payload(published, ".m4a") == media_payload(original, ".m4a")
    finally:
        device.coordinator.close()


def test_native_preparation_repairs_output_after_optional_rockbox_tagging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    device = build_device(tmp_path, media_payload=fixture("tone.m4a"))
    tag = ExportMediaTagger.prepare_stream

    def oversized_output(
        tagger: ExportMediaTagger,
        buffer: BinaryIO,
        file_name: str,
        track: Track,
        artwork: ArtworkPixels | None = None,
        *,
        preserve_artwork: bool = False,
    ) -> None:
        tag(
            tagger,
            buffer,
            file_name,
            track,
            artwork,
            preserve_artwork=preserve_artwork,
        )
        rewrite_lyrics_stream(buffer, file_name, OVERSIZED_TEXT)

    monkeypatch.setattr(ExportMediaTagger, "prepare_stream", oversized_output)
    try:
        review = prepare(
            device, desired_lyrics(device, "Initially valid lyrics"), rockbox=True
        )
        assert review.result.prepared is not None, review.result.issues
        device.assert_original()
        saved = device.save(review)
        assert saved.active is not None, saved.issues
        track = saved.active.library.tracks[0]
        published = (device.root / track.metadata.location).read_bytes()
        assert read_lyrics(published) == "Initially valid lyrics"
        assert media_payload(published, ".m4a") == media_payload(
            fixture("tone.m4a"), ".m4a"
        )
    finally:
        device.coordinator.close()
