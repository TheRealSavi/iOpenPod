"""Provisional Sync storage projections from captured scan facts, without I/O."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from iOpenPod.app.media.transcoding import (
    TranscodeSettings,
    nominal_lossy_bitrate_kbps,
)
from iOpenPod.app.sync_plan import SyncPlanAction, SyncPlanMediaKind, host_path_identity
from iPodDB.library import MediaKind

if TYPE_CHECKING:
    from device_registry import DeviceProfile
    from iOpenPod.app.host_media_library import HostMediaLibrary
    from iOpenPod.app.library_sync_helper import IPodMediaLibrary
    from iOpenPod.app.models.device import DeviceCandidate
    from iOpenPod.app.sync_plan import SyncPlan
    from iPodDB.library import Track


@dataclass(frozen=True, slots=True)
class SyncStorageEstimate:
    """Projected media bytes, never a prepared-output or space guarantee."""

    total_bytes: int
    current_used_bytes: int
    incoming_bytes: int
    outgoing_bytes: int
    unknown_items: int

    @property
    def net_bytes(self) -> int:
        return self.incoming_bytes - self.outgoing_bytes

    @property
    def projected_used_bytes(self) -> int:
        return max(0, self.current_used_bytes + self.net_bytes)

    @property
    def free_bytes(self) -> int:
        """Negative values preserve how far the provisional projection exceeds capacity."""

        return self.total_bytes - self.projected_used_bytes


class SyncStorageProjection:
    """Index scan facts once and project only the selected plan's proposed changes.

    Incoming Track media uses a settings- and profile-aware output estimate when
    the scan facts identify a conversion. Otherwise it uses Host source bytes.
    Outgoing bytes use scanned iPod files, including replaced files. Shared files
    are credited once, only when every scanned reference leaves the iPod. Packed
    Photo representations, artwork, databases, and transaction overhead are outside
    this provisional projection. Attention and missing facts remain explicit.
    """

    def __init__(
        self,
        host: HostMediaLibrary,
        ipod: IPodMediaLibrary,
        candidate: DeviceCandidate,
        profile: DeviceProfile | None = None,
    ) -> None:
        self._total = max(0, candidate.total_bytes)
        self._used = min(self._total, max(0, candidate.used_bytes))
        self._profile = profile
        self._host_sizes = {
            host_path_identity(str(source.path)): source.size_bytes
            for source in host.sources
            if source.size_bytes >= 0
        }
        self._host_tracks = {
            host_path_identity(track.metadata.location): track
            for track in host.snapshot.tracks
            if track.metadata.location
        }
        self._ipod_files = {
            (SyncPlanMediaKind.TRACK, track.track_id): (
                str(track.path),
                track.size_bytes,
            )
            for track in ipod.tracks
        }
        self._ipod_files.update(
            {
                (SyncPlanMediaKind.PHOTO, photo.image_id): (
                    str(photo.path),
                    photo.size_bytes,
                )
                for photo in ipod.images
            }
        )

    def estimate(
        self, plan: SyncPlan, *, settings: TranscodeSettings | None = None
    ) -> SyncStorageEstimate:
        settings = settings or TranscodeSettings()
        incoming = 0
        unknown = 0
        outgoing: dict[str, int] = {}
        released: set[tuple[SyncPlanMediaKind, int]] = set()
        for item in plan.items:
            if item.action is SyncPlanAction.ATTENTION:
                unknown += 1
                continue
            missing_size = False
            incoming_size = 0
            replaces_media = item.action is SyncPlanAction.ADD or (
                item.action is SyncPlanAction.UPDATE
                and (
                    item.media_kind is SyncPlanMediaKind.PHOTO
                    or item.audio_payload_changed
                )
            )
            if replaces_media:
                size = (
                    self._host_sizes.get(host_path_identity(item.host_path))
                    if item.host_path is not None
                    else None
                )
                if size is None:
                    missing_size = True
                else:
                    incoming_size = size
                    if (
                        item.media_kind is SyncPlanMediaKind.TRACK
                        and item.host_path is not None
                    ):
                        track = self._host_tracks.get(
                            host_path_identity(item.host_path)
                        )
                        if track is not None and self._profile is not None:
                            incoming_size = _estimated_track_bytes(
                                track, size, self._profile, settings
                            )
            key = (item.media_kind, item.ipod_id) if item.ipod_id is not None else None
            file = None
            if item.action is SyncPlanAction.REMOVE or (
                item.action is SyncPlanAction.UPDATE and replaces_media
            ):
                file = self._ipod_files.get(key) if key is not None else None
                if file is None:
                    missing_size = True
            if missing_size:
                unknown += 1
                continue
            incoming += incoming_size
            if file is not None and key is not None:
                released.add(key)
                path, size = file
                outgoing[path] = size

        # A retained Track or Photo may still reference the same physical file.
        for key, (path, _size) in self._ipod_files.items():
            if key not in released:
                outgoing.pop(path, None)
        return SyncStorageEstimate(
            self._total,
            self._used,
            incoming,
            sum(outgoing.values()),
            unknown,
        )


_LOSSLESS_FORMATS = frozenset({"flac", "alac", "wav", "aif", "aiff", "wv"})
_PCM_FORMATS = frozenset({"wav", "aif", "aiff"})
_INCOMPATIBLE_LOSSY_FORMATS = frozenset({"oga", "ogg", "opus", "wma"})
_VIDEO_FORMATS = frozenset(
    {"avi", "m4v", "mkv", "mov", "mp4", "mpeg", "mpg", "webm", "wmv"}
)


def _estimated_track_bytes(
    track: Track, source_bytes: int, profile: DeviceProfile, settings: TranscodeSettings
) -> int:
    """Estimate the output policy from scan facts; retain source bytes if uncertain.

    FFmpeg's variable-rate output and lossless compression cannot be predicted
    exactly before preparation. The estimate follows the selected bitrate and
    profile limits without opening Host files on every selection change.
    """
    if track.length_ms <= 0:
        return source_bytes
    format_name = track.metadata.file_format.casefold()
    if format_name in _VIDEO_FORMATS:
        caps = profile.capabilities.video
        if not caps.supported:
            return source_bytes
        # CRF video has no fixed bitrate. The device ceiling supplies a useful
        # upper projection for oversized or non-MP4 source containers.
        cap_kbps = caps.max_bitrate_kbps + caps.max_audio_bitrate_kbps
        cap_bytes = _bitrate_bytes(track.length_ms, cap_kbps)
        if format_name in {"mp4", "m4v", "mov"} and source_bytes <= cap_bytes:
            return source_bytes
        return min(source_bytes, cap_bytes)

    spoken = settings.smart_spoken_word and track.media_kind in (
        MediaKind.PODCAST,
        MediaKind.AUDIOBOOK,
    )
    lossless = format_name in _LOSSLESS_FORMATS
    if (
        spoken
        or (lossless and settings.lossless_to_lossy)
        or (not lossless and settings.retranscode_lossy)
        or format_name in _INCOMPATIBLE_LOSSY_FORMATS
    ):
        return _bitrate_bytes(
            track.length_ms, nominal_lossy_bitrate_kbps(settings, spoken=spoken)
        )
    if (
        format_name in _PCM_FORMATS
        and settings.wav_aiff_to_alac
        and profile.capabilities.audio.supports_alac
    ):
        # Typical ALAC is around half of 16-bit PCM; content varies.
        return max(1, source_bytes * 55 // 100)
    if format_name in {"flac", "wv"} and profile.capabilities.audio.supports_alac:
        # Both formats are compressed lossless; ALAC commonly needs somewhat more.
        return max(1, source_bytes * 11 // 10)
    return source_bytes


def _bitrate_bytes(length_ms: int, bitrate_kbps: int) -> int:
    # Include a small allowance for the output container and metadata.
    return max(1, (length_ms * bitrate_kbps * 102 + 799) // 800)


__all__ = ["SyncStorageEstimate", "SyncStorageProjection"]
