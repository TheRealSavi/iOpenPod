"""Signed native Sparkle installation through a compiled, typed block bridge."""

from __future__ import annotations

import ctypes
import plistlib
from queue import Empty, SimpleQueue
from typing import TYPE_CHECKING

from .backend import UpdateOutcome, UpdateProgress, UpdateResult
from .releases import FEED_URL

if TYPE_CHECKING:
    from collections.abc import Callable
    from threading import Event

    from .installation import Installation
    from .releases import ReleaseAsset
    from .transport import UpdateTransport

_Callback = ctypes.CFUNCTYPE(None, ctypes.c_int, ctypes.c_double, ctypes.c_char_p)
# Native Sparkle may still deliver cancellation callbacks after backend.close().
_callbacks: list[object] = []


class SparkleInstaller:
    def __init__(self, installation: Installation) -> None:
        contents = installation.executable.parent.parent
        if contents.name != "Contents" or contents.parent.suffix != ".app":
            raise ValueError("Sparkle requires a packaged macOS application")
        with (contents / "Info.plist").open("rb") as stream:
            info = plistlib.load(stream)
        expected_feed = FEED_URL.rsplit("/", 1)[0] + f"/{installation.target}.xml"
        if (
            info.get("CFBundleIdentifier") != "com.iopenpod.app"
            or info.get("SUFeedURL") != expected_feed
            or info.get("SUPublicEDKey") not in installation.public_keys
            or info.get("SURequireSignedFeed") is not True
            or info.get("SUSignedFeedFailureExpirationInterval") != 0
        ):
            raise ValueError(
                "The macOS bundle has no matching signed update configuration"
            )
        self._bridge = ctypes.CDLL(str(contents / "Frameworks/iOpenPodSparkle.dylib"))
        self._bridge.iop_update_start.argtypes = [
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_uint64,
            _Callback,
        ]
        self._bridge.iop_update_start.restype = ctypes.c_int
        for name in ("iop_update_resume", "iop_update_cancel"):
            function = getattr(self._bridge, name)
            function.argtypes = []
            function.restype = None
        self._events: SimpleQueue[UpdateResult | UpdateProgress] = SimpleQueue()
        self._handed_off = False
        self._closed = False
        self._callback = _Callback(self._event)
        _callbacks.append(self._callback)

    def _event(self, event: int, fraction: float, detail: bytes | None) -> None:
        if self._closed:
            return
        message = (detail or b"").decode("utf-8", errors="replace")
        if event == 0:
            self._events.put(
                UpdateProgress(message, max(0.0, min(1.0, fraction)), False)
            )
        elif event == 1:
            self._events.put(UpdateResult(UpdateOutcome.HANDOFF))
        else:
            self._events.put(UpdateResult(UpdateOutcome.FAILED, message))

    def stage(
        self,
        asset: ReleaseAsset,
        metadata: bytes,
        transport: UpdateTransport,
        cancel: Event,
        progress: Callable[[float], None],
    ) -> None:
        raise RuntimeError(
            "Sparkle owns download and installation after the work guard"
        )

    def install(self, asset: ReleaseAsset) -> None:
        if not self._bridge.iop_update_start(
            asset.version.encode(), asset.url.encode(), asset.size, self._callback
        ):
            raise RuntimeError("Sparkle could not start this update")

    def poll(self) -> UpdateResult | UpdateProgress | None:
        latest = None
        while True:
            try:
                event = self._events.get_nowait()
            except Empty:
                return latest
            if isinstance(event, UpdateResult):
                return event
            latest = event

    def complete_handoff(self) -> None:
        self._handed_off = True
        self._bridge.iop_update_resume()

    def close(self) -> None:
        if not self._handed_off:
            self._bridge.iop_update_cancel()
        self._closed = True
