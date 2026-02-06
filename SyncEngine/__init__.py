"""
SyncEngine - Bridge between PC music library and iPod

Core components:
- PCLibrary: Scans PC music folder, extracts metadata
- FingerprintDiffEngine: Computes sync plan using acoustic fingerprints
- SyncExecutor: Executes sync plan (copy, transcode, update mapping)
- MappingManager: Tracks fingerprint → dbid relationships
- Transcoder: Converts non-iPod formats (FLAC, etc.) to ALAC/AAC

Legacy:
- DiffEngine: Old signature-based diff (deprecated)
"""

from .pc_library import PCLibrary, PCTrack
from .diff_engine import DiffEngine, QualityChange
from .fingerprint_diff_engine import FingerprintDiffEngine, SyncAction, SyncPlan, SyncItem
from .sync_executor import SyncExecutor, SyncResult, SyncProgress
from .audio_fingerprint import (
    compute_fingerprint,
    read_fingerprint,
    write_fingerprint,
    get_or_compute_fingerprint,
    is_fpcalc_available,
)
from .mapping import MappingManager, MappingFile, TrackMapping
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
    # iPod mapping
    "MappingManager",
    "MappingFile",
    "TrackMapping",
    # Transcoding
    "transcode",
    "needs_transcoding",
    "is_ffmpeg_available",
    "TranscodeTarget",
    "TranscodeResult",
    "TranscodeCache",
    "CachedFile",
    "CacheIndex",
    "IPOD_NATIVE_FORMATS",
    # Legacy (signature-based)
    "DiffEngine",
    "QualityChange",
]
