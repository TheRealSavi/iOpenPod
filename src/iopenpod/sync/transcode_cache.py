"""
Transcode Cache — Caches transcoded audio files to avoid redundant transcoding.

Benefits:
- Multiple iPods: Transcode once, copy to all devices.
- Re-sync: If an iPod is wiped, cached files are still available.
- Quality upgrades: Only retranscode if the source file actually changed.

Cache location: platform-appropriate (configurable via settings)
  Windows: ~/iOpenPod/cache/
  macOS:   ~/Library/Caches/iOpenPod/
  Linux:   $XDG_CACHE_HOME/iOpenPod/ (~/.cache/iOpenPod/)

Cache structure:
  index.json — Maps fingerprint/source identity + format/bitrate → metadata
  files/     — Actual transcoded files, named by cache identity hash

Change detection (layered, fastest first):
  1. Source identity differs          → invalid for this source
  2. Cached file is missing           → prune index entry
  3. Source file size differs         → invalid unless content hash matches
  4. Source mtime changed             → recompute content hash to confirm
  5. Content hash matches stored hash → still valid (e.g. M4A tag-only edit)
  6. Content hash differs             → invalidate and retranscode

LRU eviction:
  When a new file would push the cache past max_cache_size_gb, the least-recently-
  used entries (by last_accessed timestamp) are removed until there is room.
"""

import hashlib
import json
import logging
import os
import shutil
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

from .source_identity import hash_source_file, source_content_identity

logger = logging.getLogger(__name__)

# Default cache location (XDG-aware on Linux)


def _resolve_default_cache_dir() -> Path:
    try:
        from iopenpod.infrastructure.settings_paths import default_cache_dir
        return Path(default_cache_dir())
    except Exception:
        return Path.home() / "iOpenPod" / "cache"


DEFAULT_CACHE_DIR = _resolve_default_cache_dir()


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class CachedFile:
    """Metadata for one cached transcoded file."""

    fingerprint: str        # Acoustic fingerprint of source audio
    source_format: str      # Original file extension (flac, wav, …)
    target_format: str      # Transcoded format (alac, aac, mp3)
    filename: str           # Filename inside cache/files/
    size: int               # Transcoded file size in bytes
    created: str            # ISO-8601 timestamp when entry was created
    source_size: int        # Source file size at cache time (fast change check)
    bitrate: int | None = None    # Nominal bitrate for lossy formats (kbps)
    source_hash: str | None = None  # SHA-256 of source content (definitive check)
    source_mtime: float = 0.0          # Source file mtime at cache time (triggers hash recheck)
    last_accessed: str = ""            # ISO-8601 timestamp of last cache hit (LRU key)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "CachedFile":
        """Construct from a dict, tolerating missing fields from older index versions."""
        return cls(
            fingerprint=data["fingerprint"],
            source_format=data["source_format"],
            target_format=data["target_format"],
            filename=data["filename"],
            size=data["size"],
            created=data["created"],
            source_size=data["source_size"],
            bitrate=data.get("bitrate"),
            source_hash=data.get("source_hash"),
            source_mtime=float(data.get("source_mtime") or 0.0),
            last_accessed=data.get("last_accessed", ""),
        )


@dataclass
class CacheIndex:
    """In-memory index: cache_key → CachedFile."""

    version: int = 1
    _files: dict[str, CachedFile] | None = None

    def __post_init__(self):
        if self._files is None:
            self._files = {}

    @property
    def files(self) -> dict[str, CachedFile]:
        if self._files is None:
            self._files = {}
        return self._files

    def _make_key(
        self,
        fingerprint: str,
        target_format: str,
        bitrate: int | None = None,
        source_hash: str | None = None,
    ) -> str:
        source_tag = f":{source_hash}" if source_hash else ""
        if bitrate:
            return f"{fingerprint}{source_tag}:{target_format}:{bitrate}"
        return f"{fingerprint}{source_tag}:{target_format}"

    def _legacy_key(
        self,
        fingerprint: str,
        target_format: str,
        bitrate: int | None = None,
    ) -> str:
        return self._make_key(
            fingerprint,
            target_format,
            bitrate,
            source_hash=None,
        )

    def get(
        self,
        fingerprint: str,
        target_format: str,
        bitrate: int | None = None,
        source_hash: str | None = None,
    ) -> CachedFile | None:
        if source_hash:
            return self.files.get(
                self._make_key(
                    fingerprint,
                    target_format,
                    bitrate,
                    source_hash,
                )
            ) or self.files.get(self._legacy_key(fingerprint, target_format, bitrate))
        return self.files.get(self._legacy_key(fingerprint, target_format, bitrate))

    def add(self, cached_file: CachedFile) -> None:
        key = self._make_key(
            cached_file.fingerprint,
            cached_file.target_format,
            cached_file.bitrate,
            cached_file.source_hash,
        )
        self.files[key] = cached_file

    def remove(
        self,
        fingerprint: str,
        target_format: str,
        bitrate: int | None = None,
        source_hash: str | None = None,
    ) -> bool:
        key = self._make_key(
            fingerprint,
            target_format,
            bitrate,
            source_hash,
        )
        if key in self.files:
            del self.files[key]
            return True
        if source_hash:
            legacy_key = self._legacy_key(fingerprint, target_format, bitrate)
            if legacy_key in self.files:
                del self.files[legacy_key]
                return True
        return False

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "files": {k: v.to_dict() for k, v in self.files.items()},
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CacheIndex":
        files: dict[str, CachedFile] = {}
        for key, file_data in data.get("files", {}).items():
            try:
                files[key] = CachedFile.from_dict(file_data)
            except Exception as exc:
                logger.warning("Skipping malformed cache entry %r: %s", key, exc)
        return cls(version=data.get("version", 1), _files=files)

    @property
    def count(self) -> int:
        return len(self.files)

    @property
    def total_size(self) -> int:
        return sum(f.size for f in self.files.values())


# ── Main class ────────────────────────────────────────────────────────────────

class TranscodeCache:
    """
    Manages a persistent cache of transcoded audio files.

    Usage::

        cache = TranscodeCache.get_instance()

        # Check if already cached
        cached = cache.get(fingerprint, "alac", source_size, source_path=path)
        if cached:
            shutil.copy(cached, dest)
        else:
            reserve_path = cache.reserve(fingerprint, "alac")
            transcode(source, reserve_path.parent, reserve_path.stem)
            cache.commit(fingerprint, "flac", "alac", source_size, source_path=path)
    """

    _instance: Optional["TranscodeCache"] = None
    _instance_lock = threading.Lock()

    @classmethod
    def get_instance(
        cls,
        cache_dir: Path | None = None,
        *,
        max_cache_size_gb: float = 5.0,
    ) -> "TranscodeCache":
        """Return the shared singleton, creating it on first call.

        If *cache_dir* differs from the current instance's directory,
        the singleton is replaced with a new one pointing at the new path.
        """
        resolved = cache_dir or DEFAULT_CACHE_DIR
        with cls._instance_lock:
            if cls._instance is None or cls._instance.cache_dir != resolved:
                cls._instance = cls(
                    cache_dir,
                    max_cache_size_gb=max_cache_size_gb,
                )
            else:
                cls._instance.max_cache_size_gb = max_cache_size_gb
        return cls._instance

    def __init__(
        self,
        cache_dir: Path | None = None,
        *,
        max_cache_size_gb: float = 5.0,
    ):
        self.cache_dir = cache_dir or DEFAULT_CACHE_DIR
        self.max_cache_size_gb = max_cache_size_gb
        self.files_dir = self.cache_dir / "files"
        self.index_path = self.cache_dir / "index.json"
        self._lock = threading.Lock()
        self.files_dir.mkdir(parents=True, exist_ok=True)
        self._index = self._load_index()

    # ── Persistence ───────────────────────────────────────────────────────

    def _load_index(self) -> CacheIndex:
        if not self.index_path.exists():
            return CacheIndex()
        try:
            with open(self.index_path, encoding="utf-8") as f:
                data = json.load(f)
            idx = CacheIndex.from_dict(data)
            logger.info("Loaded cache index: %d files, %.1f MB",
                        idx.count, idx.total_size / 1_048_576)
            return idx
        except Exception as exc:
            logger.warning("Failed to load cache index: %s", exc)
            return CacheIndex()

    def _save_index(self) -> None:
        """Write index to disk atomically via a temp file."""
        tmp = self.index_path.with_suffix(".json.tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._index.to_dict(), f, indent=2)
            os.replace(tmp, self.index_path)
        except Exception as exc:
            logger.error("Failed to save cache index: %s", exc)
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass

    # ── File naming ───────────────────────────────────────────────────────

    def _cache_filename(
        self,
        fingerprint: str,
        target_format: str,
        bitrate: int | None = None,
        source_hash: str | None = None,
    ) -> str:
        identity = f"{fingerprint}:{source_hash}" if source_hash else fingerprint
        fp_hash = hashlib.sha256(identity.encode()).hexdigest()[:24]
        ext = ".m4a" if target_format in ("alac", "aac") else ".mp3" if target_format == "mp3" else f".{target_format}"
        bitrate_tag = f"_{bitrate}" if bitrate else ""
        return f"{fp_hash}_{target_format}{bitrate_tag}{ext}"

    def describe_source(self, source_path: Path | None) -> tuple[str | None, float]:
        """Return the stable source identity used for cache segregation."""
        return _probe_source_meta(source_path)

    # ── Size limit ────────────────────────────────────────────────────────

    def _get_max_bytes(self) -> int:
        """Return the configured max cache size in bytes. 0 = unlimited."""
        try:
            gb = float(self.max_cache_size_gb)
            return int(gb * 1_073_741_824) if gb > 0 else 0
        except Exception:
            return 0

    def _evict_to_fit(self, incoming_bytes: int) -> None:
        """Remove LRU entries (by last_accessed, then created) until there is
        room for *incoming_bytes*.  Must be called while holding ``_lock``."""
        max_bytes = self._get_max_bytes()
        if max_bytes <= 0:
            return  # unlimited

        current = self._index.total_size
        needed = current + incoming_bytes
        if needed <= max_bytes:
            return

        # Sort by LRU: entries never accessed sort first (empty last_accessed),
        # then by last_accessed ascending, with created as tiebreak.
        def _sort_key(kv: tuple) -> tuple:
            cf = kv[1]
            ts = cf.last_accessed or cf.created or ""
            return (ts,)

        entries = sorted(self._index.files.items(), key=_sort_key)
        evicted = 0
        for key, cached in entries:
            if current + incoming_bytes <= max_bytes:
                break
            path = self.files_dir / cached.filename
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("Could not remove cache file %s: %s", cached.filename, exc)
            current -= cached.size
            del self._index.files[key]
            evicted += 1
            logger.debug("Evicted (LRU): %s (%.1f MB)", cached.filename, cached.size / 1_048_576)

        if evicted:
            logger.info("LRU eviction: removed %d cache entries to stay within limit", evicted)

    # ── Public API ────────────────────────────────────────────────────────

    def get(
        self,
        fingerprint: str,
        target_format: str,
        source_size: int | None = None,
        bitrate: int | None = None,
        source_path: Path | None = None,
        source_hash: str | None = None,
        source_mtime: float | None = None,
    ) -> Path | None:
        """Return path to a valid cached file, or ``None`` on miss / stale entry.

        Validation layers (fastest → most expensive):
          1. Index miss          → None immediately
          2. File missing on disk→ prune index entry, return None
          3. Size mismatch       → invalidate unless content hash matches
          4. mtime changed       → recompute content hash to confirm change
          5. Hash mismatch       → invalidate, return None
          6. All checks pass     → update ``last_accessed``, return path
        """
        with self._lock:
            cached = self._index.get(
                fingerprint,
                target_format,
                bitrate,
                source_hash,
            )
            if cached is None:
                return None

            if (
                source_hash
                and cached.source_hash
                and cached.source_hash != source_hash
            ):
                logger.debug(
                    "Cache entry fingerprint matched but source hash differed for %s…",
                    fingerprint[:20],
                )
                return None

            cached_path = self.files_dir / cached.filename

            # Layer 2: file existence
            if not cached_path.exists():
                logger.debug("Cached file gone from disk: %s", cached.filename)
                self._index.remove(
                    fingerprint,
                    target_format,
                    bitrate,
                    cached.source_hash if cached.source_hash else source_hash,
                )
                self._save_index()
                return None

            same_source_hash = bool(
                source_hash
                and cached.source_hash
                and cached.source_hash == source_hash
            )

            # Layer 3: size.  A metadata-insensitive source hash match wins over
            # container size changes (for example M4A tag/art edits).
            if source_size is not None and cached.source_size != source_size:
                if same_source_hash:
                    logger.debug(
                        "Source size changed (%d → %d) but content hash matched",
                        cached.source_size,
                        source_size,
                    )
                    cached.source_size = source_size
                else:
                    logger.debug("Source size changed (%d → %d), invalidating", cached.source_size, source_size)
                    self._invalidate_entry(
                        fingerprint,
                        target_format,
                        bitrate,
                        cached_path,
                        cached.source_hash if cached.source_hash else source_hash,
                    )
                    return None

            # Layers 4–5: mtime + hash (only when source_path is provided)
            if source_path is not None:
                current_mtime = source_mtime if source_mtime is not None else 0.0
                if source_mtime is None:
                    try:
                        current_mtime = source_path.stat().st_mtime
                    except OSError:
                        current_mtime = 0.0

                mtime_changed = cached.source_mtime and current_mtime and (
                    abs(current_mtime - cached.source_mtime) > 1.0
                )
                if mtime_changed:
                    # mtime changed — verify content via hash before invalidating
                    if cached.source_hash:
                        actual_hash = source_hash
                        if actual_hash is None:
                            try:
                                actual_hash = hash_source_file(source_path)
                            except OSError:
                                actual_hash = None
                        if actual_hash and actual_hash != cached.source_hash:
                            logger.debug("Source content changed (hash mismatch), invalidating %s",
                                         fingerprint[:20])
                            self._invalidate_entry(
                                fingerprint,
                                target_format,
                                bitrate,
                                cached_path,
                                cached.source_hash,
                            )
                            return None
                        # Hash matches — content is the same despite mtime change
                        # (e.g. file was copied; update stored mtime)
                        if actual_hash:
                            cached.source_mtime = current_mtime
                    # No stored hash → trust mtime change, invalidate
                    else:
                        logger.debug("Source mtime changed, no stored hash → invalidating %s",
                                     fingerprint[:20])
                        self._invalidate_entry(
                            fingerprint,
                            target_format,
                            bitrate,
                            cached_path,
                            cached.source_hash if cached.source_hash else source_hash,
                        )
                        return None

            # Cache hit — update last_accessed
            cached.last_accessed = datetime.now(UTC).isoformat()
            self._save_index()

            logger.debug("Cache hit: %s… → %s", fingerprint[:20], cached.filename)
            return cached_path

    def _invalidate_entry(
        self,
        fingerprint: str,
        target_format: str,
        bitrate: int | None,
        cached_path: Path,
        source_hash: str | None = None,
    ) -> None:
        """Remove index entry and cached file.  Caller must hold ``_lock``."""
        self._index.remove(
            fingerprint,
            target_format,
            bitrate,
            source_hash,
        )
        try:
            cached_path.unlink(missing_ok=True)
        except OSError:
            pass
        self._save_index()

    def add(
        self,
        fingerprint: str,
        transcoded_path: Path,
        source_format: str,
        target_format: str,
        source_size: int,
        bitrate: int | None = None,
        source_path: Path | None = None,
        source_hash: str | None = None,
        source_mtime: float | None = None,
    ) -> Path | None:
        """Copy *transcoded_path* into the cache and register it in the index.

        Evicts LRU entries if needed to stay within the configured size limit.
        Returns the cached path on success, ``None`` on failure.
        """
        if not transcoded_path.exists():
            logger.error("Cannot cache non-existent file: %s", transcoded_path)
            return None

        if source_hash is None and source_path is not None:
            source_hash, source_mtime = _probe_source_meta(source_path)
        filename = self._cache_filename(
            fingerprint,
            target_format,
            bitrate,
            source_hash,
        )
        cached_path = self.files_dir / filename

        try:
            incoming = transcoded_path.stat().st_size
        except OSError:
            incoming = 0

        try:
            with self._lock:
                self._evict_to_fit(incoming)
                shutil.copy2(transcoded_path, cached_path)
                source_mtime_value = (
                    source_mtime if source_mtime is not None else 0.0
                )
                cached_file = CachedFile(
                    fingerprint=fingerprint,
                    source_format=source_format,
                    target_format=target_format,
                    filename=filename,
                    size=cached_path.stat().st_size,
                    created=datetime.now(UTC).isoformat(),
                    source_size=source_size,
                    bitrate=bitrate,
                    source_hash=source_hash,
                    source_mtime=source_mtime_value,
                )
                self._index.add(cached_file)
                self._save_index()
            logger.info("Cached: %s… → %s", fingerprint[:20], filename)
            return cached_path
        except Exception as exc:
            logger.error("Failed to cache file: %s", exc)
            return None

    def reserve(
        self,
        fingerprint: str,
        target_format: str,
        bitrate: int | None = None,
        source_hash: str | None = None,
    ) -> Path:
        """Return the destination path for a direct-write transcode.

        The caller transcodes directly to this path, then calls :meth:`commit`.
        No index entry is created yet; eviction happens in :meth:`commit`
        once the actual file size is known.
        """
        filename = self._cache_filename(
            fingerprint,
            target_format,
            bitrate,
            source_hash,
        )
        path = self.files_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def commit(
        self,
        fingerprint: str,
        source_format: str,
        target_format: str,
        source_size: int,
        bitrate: int | None = None,
        source_path: Path | None = None,
        source_hash: str | None = None,
        source_mtime: float | None = None,
    ) -> Path | None:
        """Register a previously-reserved cache file in the index.

        The file at the path returned by :meth:`reserve` must already exist.
        Evicts LRU entries if needed before registering.
        Returns the cached path on success, ``None`` on failure.
        """
        if source_hash is None and source_path is not None:
            source_hash, source_mtime = _probe_source_meta(source_path)
        filename = self._cache_filename(
            fingerprint,
            target_format,
            bitrate,
            source_hash,
        )
        cached_path = self.files_dir / filename
        if not cached_path.exists():
            logger.error("Cannot commit non-existent cache file: %s", cached_path)
            return None

        try:
            file_size = cached_path.stat().st_size
        except OSError:
            file_size = 0

        try:
            with self._lock:
                self._evict_to_fit(file_size)
                source_mtime_value = (
                    source_mtime if source_mtime is not None else 0.0
                )
                cached_file = CachedFile(
                    fingerprint=fingerprint,
                    source_format=source_format,
                    target_format=target_format,
                    filename=filename,
                    size=file_size,
                    created=datetime.now(UTC).isoformat(),
                    source_size=source_size,
                    bitrate=bitrate,
                    source_hash=source_hash,
                    source_mtime=source_mtime_value,
                )
                self._index.add(cached_file)
                self._save_index()
            # logger.info("Committed: %s… → %s", fingerprint[:20], filename)
            return cached_path
        except Exception as exc:
            logger.error("Failed to commit cache entry: %s", exc)
            return None

    def copy_from_cache(
        self,
        fingerprint: str,
        target_format: str,
        dest_path: Path,
        source_size: int | None = None,
        bitrate: int | None = None,
        source_path: Path | None = None,
    ) -> bool:
        """Copy a cached file to *dest_path*.  Returns ``True`` on success."""
        cached = self.get(fingerprint, target_format, source_size, bitrate, source_path)
        if cached is None:
            return False
        try:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(cached, dest_path)
            logger.debug("Copied from cache: %s → %s", cached.name, dest_path)
            return True
        except Exception as exc:
            logger.error("Failed to copy from cache: %s", exc)
            return False

    def invalidate(self, fingerprint: str, target_format: str | None = None) -> int:
        """Remove all cached entries for *fingerprint* (or a specific format).
        Returns the number of entries removed.
        """
        count = 0
        keys_to_remove: list[str] = []

        with self._lock:
            for key, cached in self._index.files.items():
                if cached.fingerprint == fingerprint:
                    if target_format is None or cached.target_format == target_format:
                        keys_to_remove.append(key)

            for key in keys_to_remove:
                cached = self._index.files[key]
                try:
                    (self.files_dir / cached.filename).unlink(missing_ok=True)
                except OSError as exc:
                    logger.warning("Could not delete cached file %s: %s", cached.filename, exc)
                del self._index.files[key]
                count += 1

            if count:
                self._save_index()
                logger.info("Invalidated %d cache entries for %s…", count, fingerprint[:20])

        return count

    def trim_to_limit(self) -> int:
        """Evict LRU entries until the cache is within the configured size limit.

        Called after the user lowers the limit in settings.
        Returns the number of entries removed.
        """
        with self._lock:
            before = self._index.count
            self._evict_to_fit(0)
            removed = before - self._index.count
            if removed:
                self._save_index()
        return removed

    def cleanup(self, max_age_days: int | None = None) -> tuple[int, int]:
        """Remove orphaned files and optionally age-out old entries.

        Returns ``(orphaned_files_removed, old_entries_removed)``.
        """
        orphaned = 0
        old = 0

        with self._lock:
            indexed_files = {c.filename for c in self._index.files.values()}
            for file_path in self.files_dir.iterdir():
                if file_path.name not in indexed_files:
                    try:
                        file_path.unlink()
                        orphaned += 1
                    except OSError as exc:
                        logger.warning("Could not remove orphan %s: %s", file_path.name, exc)

            if max_age_days is not None:
                from datetime import timedelta
                cutoff = datetime.now(UTC) - timedelta(days=max_age_days)
                keys_to_remove: list[str] = []
                for key, cached in self._index.files.items():
                    try:
                        if datetime.fromisoformat(cached.created) < cutoff:
                            keys_to_remove.append(key)
                    except Exception:
                        pass
                for key in keys_to_remove:
                    cached = self._index.files[key]
                    try:
                        (self.files_dir / cached.filename).unlink(missing_ok=True)
                    except OSError:
                        pass
                    del self._index.files[key]
                    old += 1

            if old:
                self._save_index()

        if orphaned or old:
            logger.info("Cleanup: %d orphaned, %d aged-out entries removed", orphaned, old)

        return orphaned, old

    def stats(self) -> dict:
        """Return cache statistics as a dict."""
        with self._lock:
            total_bytes = self._index.total_size
            count = self._index.count
        max_bytes = self._get_max_bytes()
        return {
            "total_files": count,
            "total_size_bytes": total_bytes,
            "total_size_mb": round(total_bytes / 1_048_576, 2),
            "total_size_gb": round(total_bytes / 1_073_741_824, 2),
            "max_size_bytes": max_bytes,
            "max_size_gb": round(max_bytes / 1_073_741_824, 2) if max_bytes > 0 else 0,
            "cache_dir": str(self.cache_dir),
        }

    def clear(self) -> int:
        """Delete all cached files and reset the index.  Returns file count removed."""
        with self._lock:
            count = self._index.count
            for cached in self._index.files.values():
                try:
                    (self.files_dir / cached.filename).unlink(missing_ok=True)
                except OSError as exc:
                    logger.warning("Could not delete %s: %s", cached.filename, exc)
            self._index = CacheIndex()
            self._save_index()
        logger.info("Cache cleared: %d files removed", count)
        return count


# ── Internal helpers ──────────────────────────────────────────────────────────

def _probe_source_meta(source_path: Path | None) -> tuple[str | None, float]:
    """Return ``(content_hash_or_None, mtime_or_0)`` for a source file.

    MP4-family files hash media data payloads so tag/container-only edits keep
    cache identity.  Other formats currently use full-file SHA-256.  Returns
    ``(None, 0.0)`` if *source_path* is None or the file cannot be read.
    """
    return source_content_identity(source_path)
