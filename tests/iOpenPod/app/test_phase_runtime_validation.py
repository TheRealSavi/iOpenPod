"""Prelaunch validation keeps optional work within the supported PCM contract."""

import json
import sys
from pathlib import Path
from typing import IO, Any, cast

import pytest

from iOpenPod.app import phase_runtime, phase_sources
from iOpenPod.app.phase_runtime import ManagedPhaseSources
from iOpenPod.assets.phase_runtime import worker


@pytest.mark.parametrize(
    "pcm,rate,channels",
    [(b"", 22_050, 1), (b"bad", 44_100, 2), (bytes(16), 0, 2), (bytes(16), 44_100, 0)],
)
def test_invalid_managed_audio_never_launches_a_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    pcm: bytes,
    rate: int,
    channels: int,
) -> None:
    def unexpected_process(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Invalid PCM launched the analysis process")

    monkeypatch.setattr(phase_runtime, "PhaseWorkerSession", unexpected_process)
    with pytest.raises(ValueError, match="Phase separation PCM"):
        ManagedPhaseSources(tmp_path, "test").analyze(
            pcm, sample_rate=rate, channels=channels, checkpoint=lambda: None
        )


@pytest.mark.parametrize("option,value", [("--rate", "0"), ("--channels", "3")])
def test_worker_rejects_unsupported_format_before_loading_libraries(
    monkeypatch: pytest.MonkeyPatch, option: str, value: str
) -> None:
    monkeypatch.setattr(sys, "argv", ["worker", "--models", "unused", option, value])
    with pytest.raises(SystemExit) as error:
        worker.main()
    assert error.value.code == 2


@pytest.mark.parametrize(
    "field,value",
    [
        ("protocol", 1),
        ("protocol", 2.0),
        ("sequence", 0),
        ("sequence", True),
        ("rate", 44_100.0),
        ("rate", 48_000),
        ("channels", True),
        ("channels", 3),
    ],
)
def test_server_rejects_invalid_request_before_inference(
    tmp_path: Path, field: str, value: object
) -> None:
    request: dict[str, object] = {
        "protocol": 2,
        "sequence": 1,
        "rate": 44_100,
        "channels": 2,
    }
    request[field] = value
    (tmp_path / "request.json").write_text(json.dumps(request))
    with pytest.raises(ValueError, match="Invalid Phase worker request"):
        worker._serve(tmp_path)  # pyright: ignore[reportPrivateUsage]


def test_server_rejects_oversized_request(tmp_path: Path) -> None:
    (tmp_path / "request.json").write_bytes(b"x" * 4097)
    with pytest.raises(ValueError, match="Oversized Phase worker request"):
        worker._serve(tmp_path)  # pyright: ignore[reportPrivateUsage]


@pytest.mark.parametrize("operation", ["open", "unlink"])
def test_server_retries_a_temporarily_locked_request_without_advancing_sequence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps({"protocol": 2, "sequence": 1, "rate": 44100, "channels": 2})
    )
    (tmp_path / "audio.f32").write_bytes(bytes(8))
    original_open, original_unlink = Path.open, Path.unlink
    failures = 0

    class AnalyzedError(Exception):
        pass

    def open_file(path: Path, *args: Any, **kwargs: Any) -> IO[Any]:
        nonlocal failures
        if operation == "open" and path == request and failures < 2:
            failures += 1
            raise PermissionError("request is still held during publication")
        return cast("IO[Any]", original_open(path, *args, **kwargs))

    def unlink(path: Path, missing_ok: bool = False) -> None:
        nonlocal failures
        if operation == "unlink" and path == request and failures < 2:
            failures += 1
            raise PermissionError("request handle is closing")
        original_unlink(path, missing_ok=missing_ok)

    def analyze(*_args: object, **_kwargs: object) -> None:
        assert failures == 2 and not request.exists()
        raise AnalyzedError()

    monkeypatch.setattr(Path, "open", open_file)
    monkeypatch.setattr(Path, "unlink", unlink)
    monkeypatch.setattr(phase_sources.DemucsPhaseSources, "analyze", analyze)
    with pytest.raises(AnalyzedError):
        worker._serve(tmp_path)  # pyright: ignore[reportPrivateUsage]
