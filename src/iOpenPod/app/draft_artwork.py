"""Thread-safe draft artwork snapshots layered over retained device artwork."""

from __future__ import annotations

from dataclasses import dataclass, replace
from threading import Lock
from types import MappingProxyType
from typing import TYPE_CHECKING
from uuid import uuid4

from PIL import Image

from iOpenPod.app.models.artwork import ArtworkImage, ArtworkRequest
from iPodDB.library import ArtworkAsset, ArtworkGroupReference, TimedArtworkAsset

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from iOpenPod.app.artwork_controller import ArtworkLoader
    from iPodDB.library import ArtworkPixels


@dataclass(frozen=True, slots=True)
class _DraftSnapshot:
    generation: int
    assets: Mapping[int, ArtworkAsset | TimedArtworkAsset]


class DraftArtworkLoader:
    """Resolve immutable draft images on the existing artwork worker pool."""

    def __init__(
        self,
        source: ArtworkLoader,
        display_times: Callable[[int], tuple[int, ...]] | None = None,
    ) -> None:
        self._source = source
        self._source_display_times = display_times
        self._identity = uuid4().hex
        self._lock = Lock()
        self._snapshot = _DraftSnapshot(0, MappingProxyType({}))

    def replace_assets(
        self, assets: tuple[ArtworkAsset | TimedArtworkAsset, ...]
    ) -> bool:
        """Publish a complete immutable snapshot; report whether caches must reset."""

        by_id = {asset.artwork_id: asset for asset in assets}
        if len(by_id) != len(assets) or any(identity >= 0 for identity in by_id):
            raise ValueError("Draft artwork requires unique negative identities")
        with self._lock:
            if by_id == self._snapshot.assets:
                return False
            self._snapshot = _DraftSnapshot(
                self._snapshot.generation + 1, MappingProxyType(by_id)
            )
        return True

    def _capture(self) -> _DraftSnapshot:
        with self._lock:
            return self._snapshot

    def display_times(self, artwork_id: int) -> tuple[int, ...]:
        """List exact authored groups without loading or resizing pixels."""

        if artwork_id > 0:
            return (
                self._source_display_times(artwork_id)
                if self._source_display_times is not None
                else (0,)
            )
        asset = self._capture().assets.get(artwork_id)
        if isinstance(asset, ArtworkAsset):
            return (0,)
        if isinstance(asset, TimedArtworkAsset):
            return tuple(sorted(frame.display_time_ms for frame in asset.frames))
        return ()

    def load_artwork(self, request: ArtworkRequest) -> ArtworkImage | None:
        if request.artwork_id > 0:
            return self._source.load_artwork(request)
        snapshot = self._capture()
        asset = snapshot.assets.get(request.artwork_id)
        if asset is None:
            return None
        time_ms = 0 if request.display_time_ms is None else request.display_time_ms
        source: ArtworkPixels | ArtworkGroupReference | None
        if isinstance(asset, ArtworkAsset):
            source = asset.pixels if time_ms == 0 else None
        else:
            source = next(
                (
                    frame.source
                    for frame in asset.frames
                    if frame.display_time_ms == time_ms
                ),
                None,
            )
        if source is None:
            return None
        cache_key = (
            f"draft/{self._identity}/{snapshot.generation}/{request.artwork_id}/"
            f"{request.display_time_ms}/{request.target_px}"
        )
        if isinstance(source, ArtworkGroupReference):
            retained = self._source.load_artwork(
                ArtworkRequest(
                    source.artwork_id,
                    request.target_px,
                    display_time_ms=source.display_time_ms,
                )
            )
            if retained is None:
                return None
            return replace(
                retained,
                cache_key=f"{cache_key}/{retained.cache_key}",
                artwork_id=request.artwork_id,
                display_time_ms=request.display_time_ms,
            )
        pixels = Image.frombytes("RGB", (source.width, source.height), source.rgb888)
        pixels.thumbnail(
            (request.target_px, request.target_px), Image.Resampling.LANCZOS
        )
        return ArtworkImage(
            cache_key=cache_key,
            artwork_id=request.artwork_id,
            format_id=1,
            width=pixels.width,
            height=pixels.height,
            rgb888=pixels.tobytes(),
            display_time_ms=request.display_time_ms,
        )
