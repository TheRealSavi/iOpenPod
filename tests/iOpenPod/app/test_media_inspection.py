"""Inspection uses all captured streams, exact timing, and bounded subprocesses."""

from __future__ import annotations

import base64
import hashlib
import json
import shutil
import subprocess
import sys
from fractions import Fraction
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from iOpenPod.app.media import MediaInspectionError, MediaInspector, StreamKind
from storage import HostPath

if TYPE_CHECKING:
    from collections.abc import Callable

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "media"


def _fixture(tmp_path: Path, name: str) -> HostPath:
    # Deliberately misleading extension: inspection must sniff actual content.
    path = tmp_path / "selected file.bin"
    path.write_bytes(base64.decodebytes((FIXTURES / f"{name}.b64").read_bytes()))
    return HostPath(path)


@pytest.fixture
def inspector() -> MediaInspector:
    executable = shutil.which("ffprobe")
    if executable is None:
        pytest.skip("FFprobe is required for real media inspection tests")
    return MediaInspector(HostPath(executable))


@pytest.mark.parametrize(
    ("name", "codec", "sample_rate", "channels", "containers"),
    [
        ("tone.wav", "pcm_s16le", 44100, 2, "wav"),
        ("tone.aiff", "pcm_s16be", 44100, 2, "aiff"),
        ("tone.mp3", "mp3", 44100, 2, "mp3"),
        ("tone.m4a", "aac", 44100, 2, "mov"),
        ("lossless.m4a", "alac", 44100, 2, "mov"),
        ("surround.flac", "flac", 96000, 6, "flac"),
    ],
)
def test_inspect_real_audio_facts_without_assuming_device_support(
    tmp_path: Path,
    inspector: MediaInspector,
    name: str,
    codec: str,
    sample_rate: int,
    channels: int,
    containers: str,
) -> None:
    source = _fixture(tmp_path, name)
    result = inspector.inspect(source, checkpoint=lambda: None)
    assert result.source == source
    assert (
        result.fingerprint.sha256
        == hashlib.sha256(Path(source).read_bytes()).hexdigest()
    )
    assert containers in result.containers
    assert len(result.audio_streams) == 1
    audio = result.audio_streams[0]
    assert (audio.codec, audio.sample_rate_hz, audio.channels) == (
        codec,
        sample_rate,
        channels,
    )
    assert result.duration_seconds is not None and result.duration_seconds > 0
    assert result.video_streams == ()
    if name == "surround.flac":
        assert audio.bits_per_raw_sample == 24
    if name == "tone.m4a":
        assert audio.profile == "LC"
        assert {tag.name: tag.value for tag in result.tags}[
            "title"
        ] == "Inspection tone"


def test_video_without_audio_and_non_native_video_remain_inspectable(
    tmp_path: Path,
    inspector: MediaInspector,
) -> None:
    silent = inspector.inspect(
        _fixture(tmp_path, "silent.mp4"), checkpoint=lambda: None
    )
    assert silent.audio_streams == ()
    (video,) = silent.video_streams
    assert video.codec == "h264"
    assert (video.width, video.height) == (320, 240)
    assert video.frame_rate == Fraction(30000, 1001)
    assert video.level == 30
    other = inspector.inspect(_fixture(tmp_path, "source.mkv"), checkpoint=lambda: None)
    assert "matroska" in other.containers
    assert other.video_streams[0].codec == "mpeg4"
    assert other.audio_streams == ()


def test_embedded_cover_is_not_a_movie_and_chapters_keep_exact_positions(
    tmp_path: Path,
    inspector: MediaInspector,
) -> None:
    result = inspector.inspect(
        _fixture(tmp_path, "chapters-cover.m4a"), checkpoint=lambda: None
    )
    assert len(result.audio_streams) == 1
    assert result.video_streams == ()
    assert len(result.pictures) == 1
    assert result.pictures[0].codec == "png"
    assert [chapter.start_seconds for chapter in result.chapters] == [
        0,
        Fraction(1, 10),
    ]
    assert [chapter.end_seconds for chapter in result.chapters] == [
        Fraction(1, 10),
        Fraction(1, 4),
    ]
    assert [
        next(t.value for t in chapter.tags if t.name == "title")
        for chapter in result.chapters
    ] == ["Opening", "Closing"]


def test_missing_quicktime_chapter_reference_does_not_hide_valid_audio(
    tmp_path: Path, inspector: MediaInspector
) -> None:
    data = bytearray(
        base64.decodebytes((FIXTURES / "chapters-cover.m4a.b64").read_bytes())
    )
    # Author a stale tref/chap reference like chapter-split M4B containers.
    marker = data.index(b"chap")
    data[marker + 4 : marker + 8] = (9999).to_bytes(4, "big")
    path = tmp_path / "stale-chapter.m4b"
    path.write_bytes(data)
    result = inspector.inspect(HostPath(path), checkpoint=lambda: None)
    assert result.audio_streams[0].codec == "aac"
    assert result.audio_streams[0].duration_seconds is not None


@pytest.mark.parametrize(
    ("filename", "sample_entry"),
    [("multi-track.mov", "text"), ("multi-track.m4v", "tx3g")],
)
def test_every_audio_track_and_subtitle_sample_entry_is_retained(
    tmp_path: Path,
    inspector: MediaInspector,
    filename: str,
    sample_entry: str,
) -> None:
    result = inspector.inspect(_fixture(tmp_path, filename), checkpoint=lambda: None)
    assert len(result.audio_streams) == 2
    assert len(result.video_streams) == 1
    assert {
        next(t.value for t in audio.tags if t.name == "language")
        for audio in result.audio_streams
    } == {"eng", "fra"}
    (subtitle,) = (s for s in result.streams if s.kind is StreamKind.SUBTITLE)
    assert (subtitle.codec, subtitle.codec_tag) == ("mov_text", sample_entry)
    assert (subtitle.width, subtitle.height) == (320, 240)


@pytest.mark.parametrize(
    "data",
    [
        b"not a media file",
        b"ffconcat version 1.0\nfile 'elsewhere.mp3'\n",
        b"#EXTM3U\nhttps://example.invalid/media.mp3\n",
    ],
)
def test_invalid_files_and_external_playlists_are_rejected(
    tmp_path: Path,
    inspector: MediaInspector,
    data: bytes,
) -> None:
    path = tmp_path / "input"
    path.write_bytes(data)
    with pytest.raises(MediaInspectionError):
        inspector.inspect(HostPath(path), checkpoint=lambda: None)


def _report() -> dict[str, object]:
    return {
        "format": {"format_name": "mov,mp4", "size": "3", "duration": "N/A"},
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "h264",
                "duration_ts": 1001,
                "time_base": "1/30000",
                "avg_frame_rate": "0/0",
            }
        ],
    }


def _use_report(monkeypatch: pytest.MonkeyPatch, report: bytes) -> None:
    from iOpenPod.app.media import inspection

    def probe(
        executable: HostPath,
        source: HostPath,
        checkpoint: Callable[[], None],
        *,
        timeout_seconds: float,
        max_output_bytes: int,
    ) -> bytes:
        assert Path(source).read_bytes() == b"abc"
        return report

    monkeypatch.setattr(inspection, "probe", probe)


def test_missing_facts_are_not_fabricated_and_tick_duration_is_exact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_report(monkeypatch, json.dumps(_report()).encode())
    path = tmp_path / "input"
    path.write_bytes(b"abc")
    result = MediaInspector(HostPath(sys.executable)).inspect(
        HostPath(path), checkpoint=lambda: None
    )
    (stream,) = result.streams
    assert stream.duration_seconds == Fraction(1001, 30000)
    assert stream.frame_rate is None
    assert stream.attached_picture is None
    assert stream.channels is None
    assert stream.bitrate_bps is None
    assert result.duration_seconds is None
    assert result.video_streams == ()


@pytest.mark.parametrize(
    "data",
    [
        b'{"format":{},"format":{}}',
        b'{"format":NaN}',
        b"[]",
        b"\xff",
        b"{",
        b'{"format":{"format_name":"wav","size":"4"},"streams":[]}',
        json.dumps(
            {
                "format": {"format_name": "wav", "size": "3"},
                "streams": [{"index": True}],
            }
        ).encode(),
        json.dumps(
            {
                "format": {"format_name": "wav", "size": "3", "duration": "NaN"},
                "streams": [{"index": 0}],
            }
        ).encode(),
        json.dumps(
            {
                "format": {"format_name": "wav", "size": "3", "duration": "1e99999999"},
                "streams": [{"index": 0}],
            }
        ).encode(),
        json.dumps(
            {
                "format": {"format_name": "wav", "size": "3"},
                "streams": [{"index": 0}, {"index": 0}],
            }
        ).encode(),
    ],
)
def test_malformed_inspection_output_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    data: bytes,
) -> None:
    _use_report(monkeypatch, data)
    path = tmp_path / "input"
    path.write_bytes(b"abc")
    with pytest.raises(MediaInspectionError) as error:
        MediaInspector(HostPath(sys.executable)).inspect(
            HostPath(path), checkpoint=lambda: None
        )
    assert error.value.code == "media.probe_invalid"


@pytest.mark.parametrize(
    ("script", "expected_code", "timeout", "limit"),
    [
        ("import time; time.sleep(30)", "media.probe_timeout", 0.2, 4096),
        (
            "import sys; sys.stdout.buffer.write(b'x'*1000000)",
            "media.probe_output_limit",
            5,
            4096,
        ),
        (
            "import sys; sys.stderr.buffer.write(b'x'*1000000)",
            "media.probe_output_limit",
            5,
            4096,
        ),
        (
            "import sys; sys.stderr.write('decode error'); sys.exit(1)",
            "media.probe_failed",
            5,
            4096,
        ),
        ("raise SystemExit(3)", "media.probe_failed", 5, 4096),
    ],
)
def test_subprocess_failure_is_bounded_reaped_and_capture_cleaned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    script: str,
    expected_code: str,
    timeout: float,
    limit: int,
) -> None:
    original = subprocess.Popen
    processes: list[subprocess.Popen[bytes]] = []
    snapshots: list[Path] = []

    def launch(
        args: list[str], *, stdin: int, stdout: int, stderr: int, creationflags: int
    ) -> subprocess.Popen[bytes]:
        assert args[args.index("-protocol_whitelist") + 1] == "file"
        assert "concat" not in args[args.index("-format_whitelist") + 1].split(",")
        snapshots.append(Path(args[-1]))
        process = original(
            [sys.executable, "-c", script],
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            creationflags=creationflags,
        )
        processes.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", launch)
    path = tmp_path / "input"
    path.write_bytes(b"abc")
    with pytest.raises(MediaInspectionError) as error:
        MediaInspector(
            HostPath(sys.executable), timeout_seconds=timeout, max_output_bytes=limit
        ).inspect(HostPath(path), checkpoint=lambda: None)
    assert error.value.code == expected_code
    assert len(processes) == 1 and processes[0].poll() is not None
    assert not snapshots[0].parent.exists()
    assert path.read_bytes() == b"abc"


def test_cancel_running_probe_terminates_child_and_cleans_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = subprocess.Popen
    processes: list[subprocess.Popen[bytes]] = []
    snapshots: list[Path] = []
    cancellation = InterruptedError("cancel this inspection")

    def launch(
        args: list[str], *, stdin: int, stdout: int, stderr: int, creationflags: int
    ) -> subprocess.Popen[bytes]:
        snapshots.append(Path(args[-1]))
        process = original(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            creationflags=creationflags,
        )
        processes.append(process)
        return process

    def checkpoint() -> None:
        if processes:
            raise cancellation

    monkeypatch.setattr(subprocess, "Popen", launch)
    path = tmp_path / "input"
    path.write_bytes(b"abc")
    with pytest.raises(InterruptedError) as caught:
        MediaInspector(HostPath(sys.executable)).inspect(
            HostPath(path), checkpoint=checkpoint
        )
    assert caught.value is cancellation
    assert len(processes) == 1 and processes[0].poll() is not None
    assert not snapshots[0].parent.exists()


def test_real_probe_observes_snapshot_when_original_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    inspector: MediaInspector,
) -> None:
    from iOpenPod.app.media import inspection
    from storage.media_probe import probe as original_probe

    source = _fixture(tmp_path, "tone.m4a")
    original_hash = hashlib.sha256(Path(source).read_bytes()).hexdigest()

    def probe(
        executable: HostPath,
        captured: HostPath,
        checkpoint: Callable[[], None],
        *,
        timeout_seconds: float,
        max_output_bytes: int,
    ) -> bytes:
        assert captured != source
        Path(source).write_bytes(b"changed while inspecting")
        return original_probe(
            executable,
            captured,
            checkpoint,
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
        )

    monkeypatch.setattr(inspection, "probe", probe)
    result = inspector.inspect(source, checkpoint=lambda: None)
    assert result.fingerprint.sha256 == original_hash
    assert result.audio_streams[0].codec == "aac"
    assert Path(source).read_bytes() == b"changed while inspecting"


def test_missing_probe_is_a_clear_failure_without_capturing_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_executable(_command: str) -> None:
        return None

    monkeypatch.setattr(
        "storage.media_processing.find_host_executable", missing_executable
    )
    with pytest.raises(MediaInspectionError) as error:
        MediaInspector().inspect(
            HostPath(tmp_path / "unopened"), checkpoint=lambda: None
        )
    assert error.value.code == "media.probe_unavailable"
    assert "PATH" in str(error.value)
