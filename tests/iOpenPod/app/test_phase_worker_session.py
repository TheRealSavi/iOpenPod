"""Bounded requests, cancellation and cleanup for the optional Phase worker."""

import json
import time
from collections.abc import Callable
from pathlib import Path
from threading import Event, Thread, get_ident
from typing import IO, Any, cast

import pytest

from iOpenPod.app import phase_worker_session as runtime
from iOpenPod.app.phase_activity import PhaseStage
from iOpenPod.assets.phase_runtime import worker as worker_protocol
from storage import HostPath
from storage.media_processing import ToolOutput


class Worker:
    def __init__(self) -> None:
        self.directory: Path | None = None
        self.requests: list[int] = []
        self.exited = Event()
        self.ready = Event()
        self.stall = False
        self.fail = False
        self.starts = 0
        self.reply: Callable[[int], dict[str, object]] = lambda sequence: {
            "protocol": 2,
            "sequence": sequence,
            "identity": "test-cpu",
        }

    def run(
        self,
        _executable: HostPath,
        arguments: tuple[str, ...],
        *,
        checkpoint: Callable[[], None],
        **_kwargs: object,
    ) -> ToolOutput:
        self.directory = Path(arguments[-1])
        self.starts += 1
        self.ready.set()
        try:
            if self.fail:
                raise OSError("worker failed")
            while True:
                checkpoint()
                request = self.directory / "request.json"
                raw = (
                    None if self.stall else worker_protocol._take_request(request)  # pyright: ignore[reportPrivateUsage]
                )
                if raw is not None:
                    data = json.loads(raw)
                    sequence = int(data["sequence"])
                    self.requests.append(sequence)
                    (self.directory / "parts.npz").write_bytes(b"evidence")
                    pending = self.directory / "response.pending"
                    pending.write_text(json.dumps(self.reply(sequence)))
                    pending.replace(self.directory / "response.json")
                time.sleep(0.001)
        finally:
            self.exited.set()


def session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, worker: Worker
) -> runtime.PhaseWorkerSession:
    monkeypatch.setattr(runtime, "run_media_tool", worker.run)
    return runtime.PhaseWorkerSession(
        tmp_path / "python", tmp_path / "worker.py", tmp_path / "models"
    )


def test_live_activity_is_request_scoped_and_cannot_grant_overlap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = Worker()
    source = session(tmp_path, monkeypatch, worker)
    seen: list[tuple[str, str]] = []

    def reply(sequence: int) -> dict[str, object]:
        assert worker.directory is not None
        (worker.directory / "activity.json").write_text(
            json.dumps(
                {
                    "sequence": sequence,
                    "stage": "sources",
                    "backend": "cuda" if sequence == 1 else "cpu",
                    "device_name": "RTX 4070" if sequence == 1 else "",
                }
            )
        )
        # The ordinary response remains the sole scheduling authority.
        return {"protocol": 2, "sequence": sequence, "identity": "test"}

    worker.reply = reply
    try:
        for _ in range(2):
            source.request(
                b"pcm", sample_rate=44100, channels=2, checkpoint=lambda: None
            )
            assert worker.directory is not None
            source._read_activity(worker.directory)  # pyright: ignore[reportPrivateUsage]
            seen.append((source.activity.backend, source.activity.device_name))
            assert not source.last_supports_mix_overlap
        assert seen == [("cuda", "RTX 4070"), ("cpu", "")]
    finally:
        source.close()
    assert source.activity.stage is PhaseStage.LOADING
    assert not source.activity.backend


@pytest.mark.parametrize(
    "raw",
    [
        b"bad json",
        b"x" * 4097,
        b"[]",
        b'{"sequence":99,"stage":"sources","backend":"cuda","device_name":"GPU"}',
        b'{"sequence":0,"stage":"sources","backend":"made-up","device_name":"GPU"}',
        b'{"sequence":0,"stage":"finalizing","backend":"cuda","device_name":"GPU"}',
        b'{"sequence":false,"stage":"sources","backend":"cuda","device_name":"GPU"}',
    ],
)
def test_bad_or_stale_activity_does_not_change_runtime_state(
    tmp_path: Path, raw: bytes
) -> None:
    source = runtime.PhaseWorkerSession(
        tmp_path / "python", tmp_path / "worker", tmp_path
    )
    (tmp_path / "activity.json").write_bytes(raw)
    source._read_activity(tmp_path)  # pyright: ignore[reportPrivateUsage]
    assert source.activity.stage is PhaseStage.LOADING
    assert not source.activity.backend
    assert not source.last_supports_mix_overlap


def test_multiple_requests_share_one_worker_then_reap_and_remove_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = Worker()
    source = session(tmp_path, monkeypatch, worker)
    callers: list[int] = []
    try:
        for _ in range(3):
            target, identity = source.request(
                b"pcm",
                sample_rate=44100,
                channels=2,
                checkpoint=lambda: callers.append(get_ident()),
            )
            assert target.read_bytes() == b"evidence"
            assert identity == "test-cpu"
        assert worker.requests == [1, 2, 3]
        assert worker.starts == 1
        assert set(callers) == {get_ident()}
    finally:
        source.close()
    assert worker.exited.is_set()
    assert worker.directory is not None and not worker.directory.exists()
    source.close()
    with pytest.raises(RuntimeError, match="closed"):
        source.request(b"pcm", sample_rate=44100, channels=2, checkpoint=lambda: None)


def test_overlap_capability_follows_live_responses_and_defaults_to_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = Worker()

    def reply(sequence: int) -> dict[str, object]:
        response: dict[str, object] = {
            "protocol": 2,
            "sequence": sequence,
            "identity": "model-cuda-shifts0",
        }
        if sequence < 3:
            response["supports_mix_overlap"] = sequence == 1
        return response

    worker.reply = reply
    source = session(tmp_path, monkeypatch, worker)
    assert not source.last_supports_mix_overlap
    try:
        for expected in (True, False, False):
            source.request(
                b"pcm", sample_rate=44100, channels=2, checkpoint=lambda: None
            )
            assert source.last_supports_mix_overlap is expected
    finally:
        source.close()
    assert not source.last_supports_mix_overlap


@pytest.mark.parametrize("invalid", [None, 0, 1, "true", [], {}])
def test_invalid_overlap_capability_rejects_response_and_clears_prior_capability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, invalid: object
) -> None:
    worker = Worker()
    worker.reply = lambda sequence: {
        "protocol": 2,
        "sequence": sequence,
        "identity": "model-cuda-shifts0",
        "supports_mix_overlap": True if sequence == 1 else invalid,
    }
    source = session(tmp_path, monkeypatch, worker)
    source.request(b"pcm", sample_rate=44100, channels=2, checkpoint=lambda: None)
    assert source.last_supports_mix_overlap
    with pytest.raises(ValueError, match="Invalid Phase worker result"):
        source.request(b"pcm", sample_rate=44100, channels=2, checkpoint=lambda: None)
    assert not source.last_supports_mix_overlap
    assert worker.exited.is_set()


def test_access_retry_does_not_hide_a_persistent_permission_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = PermissionError("persistent permission failure")

    def fail() -> None:
        raise failure

    monkeypatch.setattr(runtime, "_ACCESS_RETRY_SECONDS", 0)
    with pytest.raises(PermissionError) as caught:
        runtime._retry_access(fail, lambda: None)  # pyright: ignore[reportPrivateUsage]
    assert caught.value is failure


def test_access_retry_checks_cancellation_between_attempts() -> None:
    attempts = 0
    cancelled = InterruptedError("cancelled while waiting for a handle")

    def fail() -> None:
        nonlocal attempts
        attempts += 1
        raise PermissionError("temporarily locked")

    def checkpoint() -> None:
        if attempts:
            raise cancelled

    with pytest.raises(InterruptedError) as caught:
        runtime._retry_access(fail, checkpoint)  # pyright: ignore[reportPrivateUsage]
    assert caught.value is cancelled and attempts == 1


def test_cancellation_reaps_worker_and_preserves_callers_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = Worker()
    worker.stall = True
    source = session(tmp_path, monkeypatch, worker)
    interrupted = ValueError("device disconnected")

    def checkpoint() -> None:
        if worker.ready.is_set():
            raise interrupted

    with pytest.raises(ValueError) as caught:
        source.request(b"pcm", sample_rate=44100, channels=2, checkpoint=checkpoint)
    assert caught.value is interrupted
    assert worker.exited.is_set()
    assert worker.directory is not None and not worker.directory.exists()


@pytest.mark.parametrize(
    "reply",
    [
        {"protocol": 2, "sequence": 0, "identity": "stale"},
        {"protocol": 1, "sequence": 1, "identity": "old"},
        {"protocol": 2, "sequence": 1, "identity": ""},
        {"protocol": 2, "sequence": 1, "identity": "x" * 5000},
        {"protocol": 2.0, "sequence": 1, "identity": "float-protocol"},
        {"protocol": 2, "sequence": True, "identity": "boolean-sequence"},
        {"protocol": 2, "sequence": 1.0, "identity": "float-sequence"},
    ],
)
def test_invalid_or_stale_response_closes_the_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reply: dict[str, object]
) -> None:
    worker = Worker()
    worker.reply = lambda _sequence: reply
    source = session(tmp_path, monkeypatch, worker)
    with pytest.raises(ValueError, match="Invalid Phase worker"):
        source.request(b"pcm", sample_rate=44100, channels=2, checkpoint=lambda: None)
    assert worker.exited.is_set()
    assert worker.directory is not None and not worker.directory.exists()


def test_child_failure_closes_the_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = Worker()
    worker.fail = True
    source = session(tmp_path, monkeypatch, worker)
    with pytest.raises(RuntimeError, match="worker failed"):
        source.request(b"pcm", sample_rate=44100, channels=2, checkpoint=lambda: None)
    assert worker.directory is not None and not worker.directory.exists()


def test_unused_session_does_not_launch_a_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = Worker()
    source = session(tmp_path, monkeypatch, worker)
    source.close()
    assert not worker.ready.is_set()


@pytest.mark.parametrize("failure", ["pcm", "publish"])
def test_failed_request_publication_reaps_the_started_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    worker = Worker()
    source = session(tmp_path, monkeypatch, worker)
    write_bytes, replace = Path.write_bytes, Path.replace

    def write(path: Path, data: bytes) -> int:
        if failure == "pcm" and path.name == "audio.f32":
            raise OSError("disk full")
        return write_bytes(path, data)

    def publish(path: Path, target: str | Path) -> Path:
        if failure == "publish" and path.name == "request.pending":
            raise OSError("publish failed")
        return replace(path, target)

    monkeypatch.setattr(Path, "write_bytes", write)
    monkeypatch.setattr(Path, "replace", publish)
    with pytest.raises(OSError, match=r"disk full|publish failed"):
        source.request(b"pcm", sample_rate=44100, channels=2, checkpoint=lambda: None)
    assert worker.exited.is_set()
    assert worker.directory is not None and not worker.directory.exists()


def test_cancellation_before_second_request_closes_existing_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = Worker()
    source = session(tmp_path, monkeypatch, worker)
    source.request(b"pcm", sample_rate=44100, channels=2, checkpoint=lambda: None)
    cancelled = InterruptedError("cancelled before next Track")

    def checkpoint() -> None:
        raise cancelled

    with pytest.raises(InterruptedError) as caught:
        source.request(b"next", sample_rate=44100, channels=2, checkpoint=checkpoint)
    assert caught.value is cancelled
    assert worker.exited.is_set()


def test_concurrent_request_is_rejected_without_replacing_the_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = Worker()
    worker.stall = True
    source = session(tmp_path, monkeypatch, worker)
    results: list[str] = []

    def request() -> None:
        _, identity = source.request(
            b"first", sample_rate=44100, channels=2, checkpoint=lambda: None
        )
        results.append(identity)

    caller = Thread(target=request)
    caller.start()
    try:
        assert worker.ready.wait(2)
        with pytest.raises(RuntimeError, match="already has a request"):
            source.request(
                b"second", sample_rate=44100, channels=2, checkpoint=lambda: None
            )
        worker.stall = False
        caller.join(2)
        assert not caller.is_alive()
        assert results == ["test-cpu"] and worker.requests == [1]
    finally:
        source.close()
        caller.join(2)


def test_track_deadline_stops_the_worker_and_removes_partial_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = Worker()
    worker.stall = True
    source = session(tmp_path, monkeypatch, worker)
    monkeypatch.setattr(runtime, "_TRACK_TIMEOUT_SECONDS", 0.05)
    with pytest.raises(TimeoutError, match="Track deadline"):
        source.request(b"pcm", sample_rate=44100, channels=2, checkpoint=lambda: None)
    assert worker.exited.is_set()
    assert worker.directory is not None and not worker.directory.exists()


def test_response_can_be_read_after_a_temporary_publication_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = Worker()
    source = session(tmp_path, monkeypatch, worker)
    original_open = Path.open
    failures = 0

    def open_file(path: Path, *args: Any, **kwargs: Any) -> IO[Any]:
        nonlocal failures
        if path.name == "response.json" and path.exists() and failures < 2:
            failures += 1
            raise PermissionError("response publication handle is closing")
        return cast("IO[Any]", original_open(path, *args, **kwargs))

    monkeypatch.setattr(Path, "open", open_file)
    try:
        _, identity = source.request(
            b"pcm", sample_rate=44100, channels=2, checkpoint=lambda: None
        )
        assert identity == "test-cpu" and failures == 2
        assert worker.requests == [1]
    finally:
        source.close()
