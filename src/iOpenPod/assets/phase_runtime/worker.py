"""Isolated optional runtime; one-shot and preparation protocols, no device I/O."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from contextlib import redirect_stdout
from dataclasses import asdict
from functools import partial
from pathlib import Path
from threading import Thread
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Callable

    from iOpenPod.app.phase_activity import PhaseActivity
    from iOpenPod.app.phase_sources import DemucsPhaseSources

# The shared analysis modules are copied as source into frozen bundles.
# -I prevents user site packages and PYTHONPATH from entering this interpreter.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

_ACCESS_RETRY_SECONDS = 1.0


def _retry_access[T](operation: Callable[[], T]) -> T:
    """Retry transient sharing failures without concealing a persistent lock."""
    deadline = time.monotonic() + _ACCESS_RETRY_SECONDS
    while True:
        try:
            return operation()
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.01)


def _take_request(request: Path) -> bytes | None:
    def take() -> bytes:
        with request.open("rb") as stream:
            raw = stream.read(4097)
        request.unlink()
        return raw

    try:
        return _retry_access(take)
    except FileNotFoundError:
        return None


def _watch_owner() -> None:
    # The app retains the write end without sending bytes. EOF also arrives on
    # an app crash. Terminate without waiting for the next analysis checkpoint;
    # this worker owns only disposable Host outputs, never device writes.
    # A blocking CRT read can stall Windows native-library imports. Python 3.12
    # supports nonblocking pipes on every supported Host platform.
    try:
        descriptor = sys.stdin.fileno()
        os.set_blocking(descriptor, False)
        while True:
            try:
                os.read(descriptor, 1)
                break
            except BlockingIOError:
                time.sleep(0.05)
    finally:
        # EOF, unexpected input and a failed monitor all end this private worker.
        os._exit(70)


def _activity_reporter(
    directory: Path, source: DemucsPhaseSources, sequence: int
) -> Callable[[], None]:
    last_activity: PhaseActivity | None = None

    def report() -> None:
        nonlocal last_activity
        activity = source.activity
        if activity == last_activity:
            return
        try:
            pending = directory / "activity.pending"
            pending.write_text(
                json.dumps({"sequence": sequence, **asdict(activity)}),
                encoding="utf-8",
            )
            pending.replace(directory / "activity.json")
            last_activity = activity
        except OSError:
            pass  # Optional display telemetry cannot fail analysis.

    return report


def _serve(directory: Path) -> None:
    import numpy as np

    from iOpenPod.app.phase_sources import DemucsPhaseSources

    source = DemucsPhaseSources()
    sequence = 0
    while True:
        request = directory / "request.json"
        raw = _take_request(request)
        if raw is None:
            time.sleep(0.05)
            continue
        if len(raw) > 4096:
            raise ValueError("Oversized Phase worker request")
        value: object = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("Invalid Phase worker request")
        data = cast("dict[str, object]", value)
        rate, channels = data.get("rate"), data.get("channels")
        sequence += 1
        if (
            type(data.get("protocol")) is not int
            or data.get("protocol") != 2
            or type(data.get("sequence")) is not int
            or data.get("sequence") != sequence
            or type(rate) is not int
            or rate not in (22_050, 44_100)
            or type(channels) is not int
            or channels not in (1, 2)
        ):
            raise ValueError("Invalid Phase worker request")
        with (directory / "audio.f32").open("rb") as stream:
            pcm = stream.read(1801 * rate * channels * 4 + 1)
        with redirect_stdout(sys.stderr):
            # Reconsider accelerator availability for each Track, retaining the
            # loaded weights and the existing whole-Track CPU retry policy.
            source = source.for_analysis()
            report_activity = _activity_reporter(directory, source, sequence)
            report_activity()
            parts = source.analyze(
                pcm, sample_rate=rate, channels=channels, checkpoint=report_activity
            )
        np.savez(
            directory / "parts.npz",
            **{
                f"{part.kind.value}_{field}": getattr(part, field)
                for part in parts
                for field in ("bands", "energy", "chroma", "magnitudes")
            },
        )
        pending = directory / "response.pending"
        pending.write_text(
            json.dumps(
                {
                    "protocol": 2,
                    "sequence": sequence,
                    "identity": source.identity,
                    "supports_mix_overlap": source.supports_mix_overlap,
                }
            ),
            encoding="utf-8",
        )
        _retry_access(partial(pending.replace, directory / "response.json"))
        del pcm, parts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", required=True)
    parser.add_argument("--health", action="store_true")
    parser.add_argument("--serve", type=Path)
    parser.add_argument("--input")
    parser.add_argument("--output")
    parser.add_argument("--rate", type=int, choices=(22_050, 44_100), default=44_100)
    parser.add_argument("--channels", type=int, choices=(1, 2), default=2)
    args = parser.parse_args()
    os.environ["TORCH_HOME"] = args.models
    if args.serve is not None:
        if args.health or args.input or args.output:
            parser.error("--serve cannot be combined with one-shot analysis")
        Thread(target=_watch_owner, name="phase-owner", daemon=True).start()
        _serve(args.serve)
        return
    import numpy as np

    from iOpenPod.app.phase_sources import DemucsPhaseSources

    if args.health:
        times = np.arange(44_100 * 2, dtype=np.float32) / 44_100
        mono = np.sin(times * (2 * np.pi * 440)).astype("<f4") * 0.1
        pcm = np.column_stack((mono, mono)).astype("<f4").tobytes()
    else:
        if not args.input or not args.output:
            parser.error("Analysis requires --input and --output")
        with Path(args.input).open("rb") as stream:
            pcm = stream.read(1801 * 44_100 * 2 * 4 + 1)
    # Model providers may print first-download notices. Stdout is reserved for
    # the bounded protocol response; diagnostics belong on stderr.
    with redirect_stdout(sys.stderr):
        source = DemucsPhaseSources()
        parts = source.analyze(
            pcm,
            sample_rate=args.rate,
            channels=args.channels,
            checkpoint=lambda: None,
        )
    if not args.health:
        arrays = {
            f"{part.kind.value}_{field}": getattr(part, field)
            for part in parts
            for field in ("bands", "energy", "chroma", "magnitudes")
        }
        np.savez(args.output, **arrays)
    print(json.dumps({"protocol": 1, "identity": source.identity}))


if __name__ == "__main__":
    main()
