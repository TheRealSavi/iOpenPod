"""Canonical format extension sets for the iopenpod.sync.

All modules that need to classify files by extension import from here.
This avoids duplicated, slightly-divergent sets across pc_library,
transcoder, integrity, and sync_executor.
"""

from __future__ import annotations

# ── Audio extensions ─────────────────────────────────────────────────────────

# Formats the iPod can play natively (audio only, no transcoding needed)
IPOD_NATIVE_AUDIO: frozenset[str] = frozenset({
    ".mp3", ".m4a", ".m4p", ".m4b", ".aac",
})

# Video containers the iPod can play (only if codec is H.264 Baseline + AAC)
IPOD_NATIVE_VIDEO: frozenset[str] = frozenset({
    ".m4v", ".mp4",
})

# All iPod-native extensions (audio + video)
IPOD_NATIVE_FORMATS: frozenset[str] = IPOD_NATIVE_AUDIO | IPOD_NATIVE_VIDEO

# ── Non-native extensions (need transcoding) ────────────────────────────────

# Lossless → ALAC (or AAC if prefer_lossy)
NON_NATIVE_LOSSLESS: frozenset[str] = frozenset({
    ".flac", ".wav", ".aif", ".aiff",
})

# Lossy non-native → AAC
NON_NATIVE_LOSSY: frozenset[str] = frozenset({
    ".ogg", ".opus", ".wma", ".aa", ".aax",
})

# Non-native video → H.264/AAC re-encode
NON_NATIVE_VIDEO: frozenset[str] = frozenset({
    ".mov", ".mkv", ".avi", ".webm", ".wmv", ".mpg", ".mpeg", ".3gp",
    ".3g2", ".flv", ".mts", ".m2ts", ".ts", ".ogv",
})

# Still images that can be imported into the iPod photo database.
PHOTO_EXTENSIONS: frozenset[str] = frozenset({
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff",
    ".webp", ".heic", ".heif",
})

# Playlist formats parsed by iopenpod.sync.playlist_parser.
PLAYLIST_EXTENSIONS: frozenset[str] = frozenset({
    ".m3u", ".m3u8", ".pls", ".xspf",
})

# All extensions that always require transcoding (audio)
NEEDS_TRANSCODING: frozenset[str] = NON_NATIVE_LOSSLESS | NON_NATIVE_LOSSY

# Video containers that always need re-encoding (non-iPod containers)
VIDEO_ALWAYS_TRANSCODE: frozenset[str] = NON_NATIVE_VIDEO

# Video containers that MIGHT be iPod-native (need ffprobe to confirm codec)
VIDEO_PROBE_CONTAINERS: frozenset[str] = IPOD_NATIVE_VIDEO

# ── Aggregate sets ───────────────────────────────────────────────────────────

# All supported audio extensions (native + needs-transcode)
AUDIO_EXTENSIONS: frozenset[str] = IPOD_NATIVE_AUDIO | NEEDS_TRANSCODING

# All supported video extensions
VIDEO_EXTENSIONS: frozenset[str] = IPOD_NATIVE_VIDEO | NON_NATIVE_VIDEO

# All supported media extensions (used for scanning / orphan detection)
MEDIA_EXTENSIONS: frozenset[str] = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS

# All extensions accepted by drag-and-drop import.
IMPORT_EXTENSIONS: frozenset[str] = (
    MEDIA_EXTENSIONS | PHOTO_EXTENSIONS | PLAYLIST_EXTENSIONS
)
