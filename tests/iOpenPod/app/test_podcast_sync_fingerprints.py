"""Podcast acoustic evidence follows verified Library publication."""

from __future__ import annotations

import base64
import io
import json
import shutil
import wave
from dataclasses import replace
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING

import pytest
from tests.iOpenPod.app.services.test_library_resources import build_device
from tests.iOpenPod.app.test_music_import import FIXTURES

# Reuse the sync tests' fixtures so fingerprint tests exercise the same setup.
from tests.iOpenPod.app.test_podcast_sync_execution import (
    _addition,  # pyright: ignore[reportPrivateUsage]
    _FixedPodcastPlan,  # pyright: ignore[reportPrivateUsage]
    _OpenerFactory,  # pyright: ignore[reportPrivateUsage]
    _request,  # pyright: ignore[reportPrivateUsage]
)
from tests.iOpenPod.app.test_sync_execution import (
    _Executor,  # pyright: ignore[reportPrivateUsage]
    _host,  # pyright: ignore[reportPrivateUsage]
)
from tests.iOpenPod.app.test_sync_execution import (
    _request as _host_request,  # pyright: ignore[reportPrivateUsage]
)

from iOpenPod.app.host_media_fingerprint import (
    FpcalcError,
    FpcalcFingerprinter,
    FpcalcUnavailableError,
    normalize_fpcalc_fingerprint,
)
from iOpenPod.app.library_sync_helper import LIBRARY_SYNC_HELPER_PATH
from iOpenPod.app.media.fingerprint_codec import decode_fingerprint
from iOpenPod.app.media.transcoding import TranscodeSettings
from iOpenPod.app.podcasts import media
from iOpenPod.app.podcasts.sync import PodcastSyncPlan
from iOpenPod.app.sync_execution import SyncExecutionStatus, SyncExecutor
from iPodDB.library import IssueSeverity, MediaKind

if TYPE_CHECKING:
    from collections.abc import Callable

    from iOpenPod.app.library_write import WriteProgress
    from storage import HostPath


pytestmark = pytest.mark.skipif(
    any(shutil.which(tool) is None for tool in ("ffmpeg", "ffprobe")),
    reason="FFmpeg and FFprobe required for actual Podcast preparation",
)


def _mock_fingerprint(
    _self: FpcalcFingerprinter,
    source: HostPath,
    *,
    checkpoint: Callable[[], None],
) -> str:
    checkpoint()
    assert Path(source).is_file()
    return "91,92,93"


def _prepare_addition(monkeypatch: pytest.MonkeyPatch) -> None:
    data = base64.decodebytes((FIXTURES / "tone.m4a.b64").read_bytes())
    monkeypatch.setattr(media, "build_opener", _OpenerFactory(data))
    monkeypatch.setattr(
        "iOpenPod.app.sync_execution.prepare_podcast_sync",
        _FixedPodcastPlan(PodcastSyncPlan(additions=(_addition(),))),
    )


@pytest.mark.skipif(shutil.which("fpcalc") is None, reason="fpcalc is required")
@pytest.mark.parametrize("transcode", (True, False), ids=("transcoded", "unchanged"))
def test_real_podcast_fingerprint_is_published_without_temporary_host_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    transcode: bool,
) -> None:
    device = build_device(tmp_path)
    content = io.BytesIO()
    with wave.open(content, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(44100)
        audio.writeframes(bytes(44100 * 12 * 2))
    addition = _addition()
    addition = replace(
        addition,
        episode=replace(
            addition.episode, enclosure_url="https://publisher.example/episode.wav"
        ),
    )
    monkeypatch.setattr(media, "build_opener", _OpenerFactory(content.getvalue()))
    monkeypatch.setattr(
        "iOpenPod.app.sync_execution.prepare_podcast_sync",
        _FixedPodcastPlan(PodcastSyncPlan(additions=(addition,))),
    )
    try:
        request = replace(
            _request(device.active),
            settings=TranscodeSettings(
                smart_spoken_word=transcode, wav_aiff_to_alac=transcode
            ),
        )
        result = SyncExecutor(device.coordinator).execute(
            request, lambda _: None, Event()
        )

        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert result.active is not None
        podcast = next(
            track
            for track in result.active.library.tracks
            if track.media_kind is MediaKind.PODCAST
        )
        if not transcode:
            assert (device.root / podcast.metadata.location).read_bytes() == (
                content.getvalue()
            )
        assert result.helper is not None and result.helper.persisted
        record = next(
            record
            for record in result.helper.tracks
            if record.track_id == podcast.track_id
        )
        assert record.acoustic_fingerprint == normalize_fpcalc_fingerprint(
            record.acoustic_fingerprint
        )
        assert len(record.acoustic_fingerprint.split(",")) > 10
        assert record.sync is None
        document = json.loads(
            (device.root / str(LIBRARY_SYNC_HELPER_PATH)).read_bytes()
        )
        persisted = next(
            row for row in document["tracks"] if row["track_id"] == podcast.track_id
        )
        assert (
            decode_fingerprint(persisted["acoustic_fingerprint"])
            == record.acoustic_fingerprint
        )
        assert persisted["sync"] is None
        assert not any(
            issue.code == "sync.podcast_fingerprint_unavailable"
            for issue in result.issues
        )
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("error_type", (FpcalcUnavailableError, FpcalcError))
def test_optional_fingerprint_failure_keeps_committed_episode_without_invented_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[FpcalcError],
) -> None:
    device = build_device(tmp_path)
    _prepare_addition(monkeypatch)

    def unavailable(
        _self: FpcalcFingerprinter,
        source: HostPath,
        *,
        checkpoint: Callable[[], None],
    ) -> str:
        checkpoint()
        assert Path(source).is_file()
        raise error_type("Acoustic matching is unavailable")

    monkeypatch.setattr(FpcalcFingerprinter, "fingerprint", unavailable)
    try:
        result = SyncExecutor(device.coordinator).execute(
            _request(device.active), lambda _: None, Event()
        )

        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert result.active is not None
        podcast = next(
            track
            for track in result.active.library.tracks
            if track.media_kind is MediaKind.PODCAST
        )
        assert (device.root / podcast.metadata.location).is_file()
        warning = next(
            issue
            for issue in result.issues
            if issue.code == "sync.podcast_fingerprint_unavailable"
        )
        assert warning.severity is IssueSeverity.WARNING
        assert warning.detail == "Acoustic matching is unavailable"
        assert result.helper is not None and result.helper.persisted
        assert all(
            record.track_id != podcast.track_id for record in result.helper.tracks
        )
        document = json.loads(
            (device.root / str(LIBRARY_SYNC_HELPER_PATH)).read_bytes()
        )
        assert all(row["track_id"] != podcast.track_id for row in document["tracks"])
    finally:
        device.coordinator.close()


def test_cancellation_before_publication_preserves_existing_helper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device = build_device(tmp_path)
    _prepare_addition(monkeypatch)
    monkeypatch.setattr(FpcalcFingerprinter, "fingerprint", _mock_fingerprint)
    helper = device.root / str(LIBRARY_SYNC_HELPER_PATH)
    cancellation = Event()

    def progress(event: WriteProgress) -> None:
        if event.phase == "save.storage.prepared":
            cancellation.set()

    try:
        baseline = device.coordinator.publish_sync_success(
            device.active, _request(device.active).ipod, ()
        )
        assert baseline.persisted
        original_helper = helper.read_bytes()
        result = SyncExecutor(device.coordinator).execute(
            _request(device.active), progress, cancellation
        )

        assert result.status is SyncExecutionStatus.CANCELLED, result.issues
        assert cancellation.is_set()
        assert result.helper is None
        assert helper.read_bytes() == original_helper
        device.assert_original()
    finally:
        device.coordinator.close()


def test_combined_host_and_podcast_sync_publishes_both_fingerprints(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device = build_device(tmp_path)
    _prepare_addition(monkeypatch)
    monkeypatch.setattr(FpcalcFingerprinter, "fingerprint", _mock_fingerprint)
    host = _host(tmp_path, "Host song")
    request = replace(
        _host_request(device, host), podcasts=_request(device.active).podcasts
    )
    try:
        result = _Executor(device.coordinator).execute(request, lambda _: None, Event())

        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert result.active is not None
        assert result.helper is not None and result.helper.persisted
        tracks = {track.title: track for track in result.active.library.tracks}
        records = {record.track_id: record for record in result.helper.tracks}
        host_record = records[tracks["Host song"].track_id]
        podcast_record = records[tracks[_addition().episode.title].track_id]
        assert host_record.acoustic_fingerprint == host.sources[0].acoustic_fingerprint
        assert host_record.sync is not None
        assert host_record.sync.host_path_hint == str(host.sources[0].path)
        assert podcast_record.acoustic_fingerprint == "91,92,93"
        assert podcast_record.sync is None
        document = json.loads(
            (device.root / str(LIBRARY_SYNC_HELPER_PATH)).read_bytes()
        )
        persisted = {row["track_id"]: row for row in document["tracks"]}
        assert persisted[host_record.track_id]["acoustic_fingerprint"] == (
            host_record.acoustic_fingerprint
        )
        assert persisted[podcast_record.track_id]["acoustic_fingerprint"] == "91,92,93"
        assert persisted[podcast_record.track_id]["sync"] is None
    finally:
        device.coordinator.close()
