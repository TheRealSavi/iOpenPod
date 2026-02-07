"""
SyncEngine - Bridge between PC music library and iPod

Core components:
- PCLibrary: Scans PC music folder, extracts metadata
- FingerprintDiffEngine: Computes sync plan using acoustic fingerprints
- SyncExecutor: Executes sync plan (copy, transcode, update mapping)
- MappingManager: Tracks fingerprint → list[dbid] relationships
- Transcoder: Converts non-iPod formats (FLAC, etc.) to ALAC/AAC

"""

from .pc_library import PCLibrary, PCTrack
from .fingerprint_diff_engine import (
    FingerprintDiffEngine,
    SyncAction,
    SyncPlan,
    SyncItem,
    StorageSummary,
)
from .sync_executor import SyncExecutor, SyncResult, SyncProgress
from .audio_fingerprint import (
    compute_fingerprint,
    read_fingerprint,
    write_fingerprint,
    get_or_compute_fingerprint,
    is_fpcalc_available,
)
from .mapping import MappingManager, MappingFile, TrackMapping
from .integrity import check_integrity, IntegrityReport
from .itunes_prefs import (
    read_prefs,
    protect_from_itunes,
    check_library_owner,
    generate_library_id,
    ITunesPrefs,
    DeviceTotals,
    SyncHistoryEntry,
)
from .transcoder import (
    transcode,
    needs_transcoding,
    is_ffmpeg_available,
    TranscodeTarget,
    TranscodeResult,
    IPOD_NATIVE_FORMATS,
)
from .transcode_cache import TranscodeCache, CachedFile, CacheIndex

__all__ = [
    # PC Library
    "PCLibrary",
    "PCTrack",
    # Fingerprint-based sync (primary)
    "FingerprintDiffEngine",
    "SyncAction",
    "SyncPlan",
    "SyncItem",
    "StorageSummary",
    # Sync execution
    "SyncExecutor",
    "SyncResult",
    "SyncProgress",
    # Audio fingerprinting
    "compute_fingerprint",
    "read_fingerprint",
    "write_fingerprint",
    "get_or_compute_fingerprint",
    "is_fpcalc_available",
    # Mapping
    "MappingManager",
    "MappingFile",
    "TrackMapping",
    # Integrity
    "check_integrity",
    "IntegrityReport",
    # iTunes Prefs
    "read_prefs",
    "protect_from_itunes",
    "check_library_owner",
    "generate_library_id",
    "ITunesPrefs",
    "DeviceTotals",
    "SyncHistoryEntry",
    # Transcoding
    "transcode",
    "needs_transcoding",
    "is_ffmpeg_available",
    "TranscodeTarget",
    "TranscodeResult",
    "IPOD_NATIVE_FORMATS",
    # Transcode cache
    "TranscodeCache",
    "CachedFile",
    "CacheIndex",
]
