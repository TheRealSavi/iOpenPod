"""
iTunesPrefs & iTunesPrefs.plist reader/writer.

Manages iPod sync preferences stored in:
  /iPod_Control/iTunes/iTunesPrefs       — binary (frpd format)
  /iPod_Control/iTunes/iTunesPrefs.plist — XML plist wrapping the binary

Key capabilities:
  1. EstimatedDeviceTotals — device dashboard (space, track counts, capabilities)
  2. Library Link ID — detect if iTunes synced behind our back
  3. Manual sync flag — set to Manual to prevent iTunes auto-sync
  4. Auto-open flag — prevent iTunes from launching when iPod is connected

Binary format (frpd):
  Offset  Field                         Size  Notes
  ──────  ────────────────────────────  ────  ─────────────────────
  0       Magic                          4    b'frpd'
  8       iPod setup done                1    0x01 = yes
  9       Open iTunes on attach          1    0x01 = yes
  10      Manual/Auto sync               1    0x00 = Manual, 0x01 = Automatic
  11      Sync type                      1    0x01 = Entire Library, 0x02 = Selected
  12      iTunes Library Link ID         8    Binds iPod to specific iTunes library
  31      Enable Disk Use                1    0x01 = yes
  34      Only update checked            1    0x01 = yes
  384+    Sync history blocks            N    Repeated (username[64] + hostname[64]) entries
"""

import logging
import os
import plistlib
import hashlib
import socket
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── Binary field offsets (frpd format) ──────────────────────────────────────

_MAGIC = b"frpd"
_OFF_SETUP_DONE = 8
_OFF_AUTO_OPEN = 9
_OFF_SYNC_MODE = 10  # 0x00 = Manual, 0x01 = Automatic
_OFF_SYNC_TYPE = 11  # 0x01 = Entire Library, 0x02 = Selected Playlists
_OFF_LIBRARY_ID = 12  # 8 bytes
_OFF_ENABLE_DISK = 31
_OFF_CHECKED_ONLY = 34


@dataclass
class DeviceTotals:
    """Parsed EstimatedDeviceTotals from iTunesPrefs.plist."""

    total_disk_bytes: int = 0
    free_disk_bytes: int = 0
    other_disk_bytes: int = 0

    total_music_tracks: int = 0
    total_music_bytes: int = 0
    total_music_seconds: int = 0

    total_audio_tracks: int = 0
    total_audio_bytes: int = 0
    total_audio_seconds: int = 0

    total_video_tracks: int = 0
    total_video_bytes: int = 0

    total_podcast_tracks: int = 0
    total_podcast_bytes: int = 0

    total_photos: int = 0
    total_photo_bytes: int = 0

    supports_audio: bool = True
    supports_video: bool = False
    supports_photos: bool = False
    supports_games: bool = False

    @property
    def used_bytes(self) -> int:
        return self.total_disk_bytes - self.free_disk_bytes

    @property
    def music_pct(self) -> float:
        if self.total_disk_bytes == 0:
            return 0.0
        return (self.total_music_bytes / self.total_disk_bytes) * 100


@dataclass
class SyncHistoryEntry:
    """A username + hostname pair from the sync history section."""

    username: str
    hostname: str


@dataclass
class ITunesPrefs:
    """Parsed iTunesPrefs state."""

    # Binary flags
    setup_done: bool = False
    auto_open: bool = False
    sync_mode_auto: bool = True  # True = Automatic, False = Manual
    sync_entire_library: bool = True  # True = Entire Library, False = Selected
    library_link_id: bytes = b"\x00" * 8
    enable_disk_use: bool = False
    checked_only: bool = False

    # Plist data
    device_totals: Optional[DeviceTotals] = None

    # Sync history (embedded in binary at offset 384+)
    sync_history: list[SyncHistoryEntry] = field(default_factory=list)

    # Raw data for round-trip fidelity
    _raw_binary: Optional[bytearray] = field(default=None, repr=False)
    _raw_plist: Optional[dict] = field(default=None, repr=False)


def _read_padded_string(data: bytes, offset: int, length: int = 64) -> str:
    """Read a null-padded string from binary data."""
    raw = data[offset:offset + length]
    # Find first null byte
    null_pos = raw.find(b"\x00")
    if null_pos >= 0:
        raw = raw[:null_pos]
    try:
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return ""


def _write_padded_string(data: bytearray, offset: int, value: str, length: int = 64):
    """Write a null-padded string into binary data."""
    encoded = value.encode("utf-8")[: length - 1]  # Leave room for null
    data[offset:offset + length] = encoded.ljust(length, b"\x00")


def _parse_binary(data: bytes) -> ITunesPrefs:
    """Parse the frpd binary format."""
    prefs = ITunesPrefs()
    prefs._raw_binary = bytearray(data)

    if len(data) < 32 or data[:4] != _MAGIC:
        logger.warning("iTunesPrefs: invalid magic or too short (%d bytes)", len(data))
        return prefs

    prefs.setup_done = data[_OFF_SETUP_DONE] == 0x01
    prefs.auto_open = data[_OFF_AUTO_OPEN] == 0x01
    prefs.sync_mode_auto = data[_OFF_SYNC_MODE] == 0x01
    prefs.sync_entire_library = data[_OFF_SYNC_TYPE] == 0x01
    prefs.library_link_id = bytes(data[_OFF_LIBRARY_ID:_OFF_LIBRARY_ID + 8])
    if len(data) > _OFF_ENABLE_DISK:
        prefs.enable_disk_use = data[_OFF_ENABLE_DISK] == 0x01
    if len(data) > _OFF_CHECKED_ONLY:
        prefs.checked_only = data[_OFF_CHECKED_ONLY] == 0x01

    # Parse sync history entries (offset 384+, each block is 128 bytes: 64 user + 64 host)
    HISTORY_START = 384
    BLOCK_SIZE = 128  # 64-byte username + 64-byte hostname
    if len(data) > HISTORY_START:
        offset = HISTORY_START
        while offset + BLOCK_SIZE <= len(data):
            username = _read_padded_string(data, offset, 64)
            hostname = _read_padded_string(data, offset + 64, 64)
            if username or hostname:
                prefs.sync_history.append(SyncHistoryEntry(username, hostname))
            offset += BLOCK_SIZE

    return prefs


def _parse_plist(plist_data: dict) -> Optional[DeviceTotals]:
    """Parse EstimatedDeviceTotals from the plist."""
    edt = plist_data.get("EstimatedDeviceTotals")
    if not edt or not isinstance(edt, dict):
        return None

    totals = DeviceTotals()
    totals.total_disk_bytes = edt.get("totalDiskBytes", 0)
    totals.free_disk_bytes = edt.get("freeDiskBytes", 0)
    totals.other_disk_bytes = edt.get("otherDiskBytes", 0)

    totals.total_music_tracks = edt.get("totalMusicTracks", 0)
    totals.total_music_bytes = edt.get("totalMusicBytes", 0)
    totals.total_music_seconds = edt.get("totalMusicSeconds", 0)

    totals.total_audio_tracks = edt.get("totalAudioTracks", 0)
    totals.total_audio_bytes = edt.get("totalAudioBytes", 0)
    totals.total_audio_seconds = edt.get("totalAudioSeconds", 0)

    totals.total_video_tracks = edt.get("totalVideoTracks", 0)
    totals.total_video_bytes = edt.get("totalVideoBytes", 0)

    totals.total_podcast_tracks = edt.get("totalPodcastTracks", 0)
    totals.total_podcast_bytes = edt.get("totalPodcastBytes", 0)

    totals.total_photos = edt.get("totalPhotos", 0)
    totals.total_photo_bytes = edt.get("totalPhotoBytes", 0)

    totals.supports_audio = edt.get("supportsAudio", True)
    totals.supports_video = edt.get("supportsVideos", False)
    totals.supports_photos = edt.get("supportsPhotos", False)
    totals.supports_games = edt.get("supportsGames", False)

    return totals


def _build_device_totals(
    ipod_path: Path,
    track_count: int,
    total_music_bytes: int,
    total_music_seconds: int,
) -> dict:
    """Build an EstimatedDeviceTotals dict for writing to the plist."""
    try:
        import shutil
        usage = shutil.disk_usage(ipod_path)
        total_bytes = usage.total
        free_bytes = usage.free
    except OSError:
        total_bytes = 0
        free_bytes = 0

    other_bytes = total_bytes - free_bytes - total_music_bytes
    if other_bytes < 0:
        other_bytes = 0

    return {
        "freeDiskBytes": free_bytes,
        "otherDiskBytes": other_bytes,
        "reservedDiskBytes": 0,
        "supportsApplications": False,
        "supportsAudio": True,
        "supportsBooks": False,
        "supportsGames": True,
        "supportsPhotos": True,
        "supportsVideos": True,
        "totalAlertToneBytes": 0,
        "totalAlertToneSeconds": 0,
        "totalAlertToneTracks": 0,
        "totalApplicationBytes": 0,
        "totalApplications": 0,
        "totalAudioBytes": total_music_bytes,
        "totalAudioSeconds": total_music_seconds,
        "totalAudioTracks": track_count,
        "totalAudiobookBytes": 0,
        "totalAudiobookSeconds": 0,
        "totalAudiobookTracks": 0,
        "totalBookBytes": 0,
        "totalBookTracks": 0,
        "totalBookletBytes": 0,
        "totalBookletTracks": 0,
        "totalDiskBytes": total_bytes,
        "totalGameBytes": 0,
        "totalGames": 0,
        "totalITunesUBytes": 0,
        "totalITunesUSeconds": 0,
        "totalITunesUTracks": 0,
        "totalMovieBytes": 0,
        "totalMovieRentalBytes": 0,
        "totalMovieRentalSeconds": 0,
        "totalMovieRentalTracks": 0,
        "totalMovieSeconds": 0,
        "totalMovieTracks": 0,
        "totalMusicBytes": total_music_bytes,
        "totalMusicSeconds": total_music_seconds,
        "totalMusicTracks": track_count,
        "totalMusicVideoBytes": 0,
        "totalMusicVideoSeconds": 0,
        "totalMusicVideoTracks": 0,
        "totalPhotoBytes": 0,
        "totalPhotos": 0,
        "totalPodcastBytes": 0,
        "totalPodcastSeconds": 0,
        "totalPodcastTracks": 0,
        "totalRingtoneBytes": 0,
        "totalRingtoneSeconds": 0,
        "totalRingtoneTracks": 0,
        "totalSystemBytes": 0,
        "totalTVShowBytes": 0,
        "totalTVShowRentalBytes": 0,
        "totalTVShowRentalSeconds": 0,
        "totalTVShowRentalTracks": 0,
        "totalTVShowSeconds": 0,
        "totalTVShowTracks": 0,
        "totalVideoBytes": 0,
        "totalVideoSeconds": 0,
        "totalVideoTracks": 0,
        "totalVoiceMemoBytes": 0,
        "totalVoiceMemoSeconds": 0,
        "totalVoiceMemoTracks": 0,
    }


# ── Public API ──────────────────────────────────────────────────────────────


def generate_library_id() -> bytes:
    """
    Generate a deterministic 8-byte library ID for iOpenPod.

    Based on a hash of "iOpenPod" + hostname so the same computer
    always produces the same ID, but different computers produce
    different IDs.
    """
    identity = f"iOpenPod:{socket.gethostname()}".encode("utf-8")
    return hashlib.sha256(identity).digest()[:8]


def read_prefs(ipod_path: str | Path) -> ITunesPrefs:
    """
    Read iTunesPrefs and iTunesPrefs.plist from the iPod.

    Falls back gracefully if either file is missing.
    """
    ipod_path = Path(ipod_path)
    itunes_dir = ipod_path / "iPod_Control" / "iTunes"
    binary_path = itunes_dir / "iTunesPrefs"
    plist_path = itunes_dir / "iTunesPrefs.plist"

    prefs = ITunesPrefs()

    # Read binary
    if binary_path.exists():
        try:
            data = binary_path.read_bytes()
            prefs = _parse_binary(data)
            logger.info(
                "iTunesPrefs: setup=%s, auto_open=%s, sync_mode=%s, "
                "library_id=%s, disk_use=%s",
                prefs.setup_done,
                prefs.auto_open,
                "Auto" if prefs.sync_mode_auto else "Manual",
                prefs.library_link_id.hex(),
                prefs.enable_disk_use,
            )
            if prefs.sync_history:
                latest = prefs.sync_history[-1]
                logger.info(
                    "iTunesPrefs: last synced by %s@%s (%d history entries)",
                    latest.username,
                    latest.hostname,
                    len(prefs.sync_history),
                )
        except Exception as e:
            logger.warning("Failed to read iTunesPrefs: %s", e)

    # Read plist
    if plist_path.exists():
        try:
            with open(plist_path, "rb") as f:
                plist_data = plistlib.load(f)
            prefs._raw_plist = plist_data
            prefs.device_totals = _parse_plist(plist_data)
            if prefs.device_totals:
                dt = prefs.device_totals
                logger.info(
                    "iTunesPrefs.plist: %d tracks, %.1f MB music, "
                    "%.1f GB free / %.1f GB total",
                    dt.total_music_tracks,
                    dt.total_music_bytes / (1024 * 1024),
                    dt.free_disk_bytes / (1024**3),
                    dt.total_disk_bytes / (1024**3),
                )
        except Exception as e:
            logger.warning("Failed to read iTunesPrefs.plist: %s", e)

    return prefs


def check_library_owner(prefs: ITunesPrefs) -> Optional[str]:
    """
    Check if the iPod was synced by a different iTunes library
    since our last sync.

    Returns:
        None if everything is fine (our ID or never synced).
        Warning message string if a foreign library was detected.
    """
    our_id = generate_library_id()
    their_id = prefs.library_link_id

    # All zeros = never synced / fresh iPod — that's fine
    if their_id == b"\x00" * 8:
        return None

    if their_id == our_id:
        return None

    return (
        f"iPod was last synced by a different program/library "
        f"(library ID: {their_id.hex()}). "
        f"The database may have been modified externally."
    )


def protect_from_itunes(
    ipod_path: str | Path,
    track_count: int = 0,
    total_music_bytes: int = 0,
    total_music_seconds: int = 0,
) -> ITunesPrefs:
    """
    Apply protective settings to prevent iTunes from clobbering our database:

    1. Set sync mode to Manual (prevents iTunes auto-sync)
    2. Set auto-open to NO (prevents iTunes launching on connect)
    3. Write our library link ID (we can detect if iTunes synced later)
    4. Update EstimatedDeviceTotals with current state

    Call this AFTER writing the iTunesDB successfully.

    Args:
        ipod_path: Path to iPod mountpoint.
        track_count: Number of tracks now on iPod.
        total_music_bytes: Total bytes of music files.
        total_music_seconds: Total duration in seconds.

    Returns:
        The updated ITunesPrefs.
    """
    ipod_path = Path(ipod_path)
    itunes_dir = ipod_path / "iPod_Control" / "iTunes"
    binary_path = itunes_dir / "iTunesPrefs"
    plist_path = itunes_dir / "iTunesPrefs.plist"

    # Read existing
    prefs = read_prefs(ipod_path)

    # ── Update binary ───────────────────────────────────────────────────
    if prefs._raw_binary and len(prefs._raw_binary) >= 32:
        buf = prefs._raw_binary
    else:
        # Create a minimal valid frpd binary (1232 bytes is the observed size)
        buf = bytearray(1232)
        buf[:4] = _MAGIC

    # Force Manual sync mode (prevents iTunes auto-overwrite)
    buf[_OFF_SYNC_MODE] = 0x00
    prefs.sync_mode_auto = False

    # Force auto-open OFF (prevents iTunes launching on connect)
    buf[_OFF_AUTO_OPEN] = 0x00
    prefs.auto_open = False

    # Write our library link ID
    our_id = generate_library_id()
    buf[_OFF_LIBRARY_ID:_OFF_LIBRARY_ID + 8] = our_id
    prefs.library_link_id = our_id

    # Ensure setup_done is set (so iTunes doesn't show setup wizard)
    buf[_OFF_SETUP_DONE] = 0x01
    prefs.setup_done = True

    # Enable disk use (iPod Classic should always have this)
    buf[_OFF_ENABLE_DISK] = 0x01
    prefs.enable_disk_use = True

    # Write binary atomically
    try:
        itunes_dir.mkdir(parents=True, exist_ok=True)
        tmp = binary_path.with_suffix(".tmp")
        tmp.write_bytes(buf)
        os.replace(str(tmp), str(binary_path))
        logger.info(
            "iTunesPrefs: wrote protective settings "
            "(manual sync, no auto-open, library_id=%s)",
            our_id.hex(),
        )
    except Exception as e:
        logger.error("Failed to write iTunesPrefs: %s", e)

    # ── Update plist ────────────────────────────────────────────────────
    plist_data = prefs._raw_plist if prefs._raw_plist else {}

    # Embed updated binary as iPodPrefs
    plist_data["iPodPrefs"] = bytes(buf)

    # Update EstimatedDeviceTotals
    plist_data["EstimatedDeviceTotals"] = _build_device_totals(
        ipod_path, track_count, total_music_bytes, total_music_seconds
    )

    # Ensure standard empty arrays exist (iTunes expects these)
    for key in [
        "AudiobookPlaylistIDs",
        "AudiobookTrackIDs",
        "MoviePlaylistIDs",
        "MovieTrackIDs",
        "MusicAlbumIDs",
        "MusicArtistIDs",
        "MusicGenreNames",
        "MusicPlaylistIDs",
        "MusicTrackIDs",
        "PodcastChannelIDs",
        "PodcastPlaylistIDs",
        "PodcastTrackIDs",
        "TVShowAlbumIDs",
        "TVShowNames",
        "TVShowPlaylistIDs",
        "TVShowTrackIDs",
    ]:
        if key not in plist_data:
            plist_data[key] = []

    # Write plist atomically
    try:
        tmp = plist_path.with_suffix(".tmp")
        with open(tmp, "wb") as f:
            plistlib.dump(plist_data, f, fmt=plistlib.FMT_XML)
        os.replace(str(tmp), str(plist_path))
        logger.info("iTunesPrefs.plist: updated with %d tracks, device totals refreshed", track_count)
    except Exception as e:
        logger.error("Failed to write iTunesPrefs.plist: %s", e)

    prefs._raw_binary = buf
    prefs._raw_plist = plist_data
    prefs.device_totals = _parse_plist(plist_data)

    return prefs
