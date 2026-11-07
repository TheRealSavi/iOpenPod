"""Retained Podcast covers reuse Storage's device capture evidence."""

import hashlib
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from tests.iOpenPod.app.podcast_sync_test_support import podcast_request
from tests.iOpenPod.app.services.test_library_resources import build_device

from iOpenPod.app import sync_execution
from iOpenPod.app.library_write import LibraryPreparationRequest
from iPodDB.library import ArtworkPixels
from storage import DevicePath, FileFingerprint, FilesystemSession, HostPath


@pytest.mark.parametrize("changed_during_extraction", [False, True])
def test_retained_cover_reads_device_once_and_keeps_publication_dependency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changed_during_extraction: bool
) -> None:
    payload = b"captured Podcast media"
    device = build_device(tmp_path, media_payload=payload, host_recovery=True)
    try:
        source = device.active.library
        podcast = replace(
            source.tracks[0],
            artwork_id=0,
            metadata=replace(source.tracks[0].metadata, podcast=True),
        )
        desired = replace(source, tracks=(podcast, *source.tracks[1:]))
        review = device.prepare(desired)
        saved = device.save(review)
        assert saved.active is not None, saved.issues
        device.coordinator.finalize_sync_success(saved.active, saved.recovery_path)
        path = DevicePath(podcast.metadata.location)
        original_fingerprint = FilesystemSession.fingerprint

        def fingerprint(
            session: FilesystemSession, target: DevicePath
        ) -> FileFingerprint:
            assert target != path, "Cover extraction must use its copy's fingerprint"
            return original_fingerprint(session, target)

        def extract(captured: HostPath, _size: int, **_kwargs: object) -> ArtworkPixels:
            assert Path(captured).read_bytes() == payload
            if changed_during_extraction:
                (device.root / str(path)).write_bytes(b"X" * len(payload))
            return ArtworkPixels(1, 1, bytes((0, 0, 255)))

        with monkeypatch.context() as capture:
            capture.setattr(FilesystemSession, "fingerprint", fingerprint)
            capture.setattr(sync_execution, "capture_embedded_artwork", extract)
            repairs, issues = sync_execution._capture_retained_podcast_artwork(  # pyright: ignore[reportPrivateUsage]
                podcast_request(device.active),
                device.coordinator,
                [],
                (),
                (),
                lambda _: None,
                lambda: None,
            )
        assert not issues
        assert len(repairs) == 1
        dependency = repairs[0].dependency
        assert dependency is not None
        assert dependency.sha256 == hashlib.sha256(payload).hexdigest()
        review = device.coordinator.prepare_library(
            LibraryPreparationRequest(
                device.active.library,
                device.active,
                1,
                1,
                artwork_dependencies=(dependency,),
            ),
            lambda _: None,
            Event(),
            allow_unchanged=True,
        )
        assert (review.result.prepared is None) is changed_during_extraction, (
            review.result.issues
        )
    finally:
        device.coordinator.close()
