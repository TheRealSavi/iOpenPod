"""
Transcode Cache - Caches transcoded audio files to avoid redundant transcoding.

Benefits:
- Multiple iPods: Transcode once, copy to all devices
- Re-sync: If iPod is wiped, cached files are still available
- Quality upgrades: Only retranscode if source file changed

Cache location: ~/.iopenpod/transcode_cache/ (cross-platform)

Cache structure:
  index.json - Maps fingerprint → cached file info
  files/     - Actual transcoded files (named by fingerprint hash)
"""

import json
import hashlib
import logging
import shutil
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Default cache location
DEFAULT_CACHE_DIR = Path.home() / ".iopenpod" / "transcode_cache"


@dataclass
class CachedFile:
    """Info about a cached transcoded file."""

    fingerprint: str  # Acoustic fingerprint of source
    source_format: str  # Original format (flac, wav, etc.)
    target_format: str  # Transcoded format (alac, aac)
    filename: str  # Filename in cache
    size: int  # File size in bytes
    created: str  # ISO timestamp
    source_size: int  # Original source file size (to detect changes)
    bitrate: Optional[int] = None  # For lossy formats (AAC bitrate)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "CachedFile":
        return cls(**data)


@dataclass
class CacheIndex:
    """Index of all cached transcoded files."""

    version: int = 1
    _files: dict[str, CachedFile] | None = None  # cache_key → CachedFile

    def __post_init__(self):
        if self._files is None:
            self._files = {}

    @property
    def files(self) -> dict[str, CachedFile]:
        """Access files dict, ensuring it's never None."""
        if self._files is None:
            self._files = {}
        return self._files

    def _make_key(self, fingerprint: str, target_format: str, bitrate: Optional[int] = None) -> str:
        """Create cache key from fingerprint + format + bitrate."""
        if bitrate:
            return f"{fingerprint}:{target_format}:{bitrate}"
        return f"{fingerprint}:{target_format}"

    def get(
        self, fingerprint: str, target_format: str, bitrate: Optional[int] = None
    ) -> Optional[CachedFile]:
        """Get cached file info if exists."""
        key = self._make_key(fingerprint, target_format, bitrate)
        return self.files.get(key)

    def add(self, cached_file: CachedFile) -> None:
        """Add or update a cached file entry."""
        key = self._make_key(
            cached_file.fingerprint, cached_file.target_format, cached_file.bitrate
        )
        self.files[key] = cached_file

    def remove(self, fingerprint: str, target_format: str, bitrate: Optional[int] = None) -> bool:
        """Remove a cached file entry. Returns True if removed."""
        key = self._make_key(fingerprint, target_format, bitrate)
        if key in self.files:
            del self.files[key]
            return True
        return False

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "files": {k: v.to_dict() for k, v in self.files.items()},
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CacheIndex":
        files = {}
        for key, file_data in data.get("files", {}).items():
            files[key] = CachedFile.from_dict(file_data)
        return cls(version=data.get("version", 1), _files=files)

    @property
    def count(self) -> int:
        return len(self.files)

    @property
    def total_size(self) -> int:
        return sum(f.size for f in self.files.values())


class TranscodeCache:
    """
    Manages a cache of transcoded audio files.

    Usage:
        cache = TranscodeCache()

        # Check if already cached
        cached = cache.get(fingerprint, "alac")
        if cached:
            shutil.copy(cached, dest_path)
        else:
            # Transcode and add to cache
            transcode(source, temp_path)
            cache.add(fingerprint, temp_path, "flac", "alac", source_size)

        # Clean up old/orphaned files
        cache.cleanup()
    """

    def __init__(self, cache_dir: Optional[Path] = None):
        """
        Initialize cache.

        Args:
            cache_dir: Cache directory (default: ~/.iopenpod/transcode_cache)
        """
        self.cache_dir = cache_dir or DEFAULT_CACHE_DIR
        self.files_dir = self.cache_dir / "files"
        self.index_path = self.cache_dir / "index.json"

        # Ensure directories exist
        self.files_dir.mkdir(parents=True, exist_ok=True)

        # Load index
        self._index = self._load_index()

    def _load_index(self) -> CacheIndex:
        """Load cache index from disk."""
        if not self.index_path.exists():
            return CacheIndex()

        try:
            with open(self.index_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            index = CacheIndex.from_dict(data)
            logger.debug(f"Loaded cache index: {index.count} files")
            return index
        except Exception as e:
            logger.warning(f"Failed to load cache index: {e}")
            return CacheIndex()

    def _save_index(self) -> None:
        """Save cache index to disk."""
        try:
            with open(self.index_path, "w", encoding="utf-8") as f:
                json.dump(self._index.to_dict(), f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save cache index: {e}")

    def _fingerprint_to_filename(
        self, fingerprint: str, target_format: str,
        bitrate: Optional[int] = None,
    ) -> str:
        """Convert fingerprint to a safe filename."""
        # Hash the fingerprint to get a fixed-length, filesystem-safe name
        fp_hash = hashlib.sha256(fingerprint.encode()).hexdigest()[:24]
        ext = ".m4a" if target_format in ("alac", "aac") else f".{target_format}"
        bitrate_tag = f"_{bitrate}" if bitrate else ""
        return f"{fp_hash}_{target_format}{bitrate_tag}{ext}"

    def get(
        self,
        fingerprint: str,
        target_format: str,
        source_size: Optional[int] = None,
        bitrate: Optional[int] = None,
    ) -> Optional[Path]:
        """
        Get path to cached transcoded file if it exists and is valid.

        Args:
            fingerprint: Acoustic fingerprint of source
            target_format: Target format (alac, aac)
            source_size: Original source file size (for validation)
            bitrate: For AAC, the bitrate used

        Returns:
            Path to cached file, or None if not cached/invalid
        """
        cached = self._index.get(fingerprint, target_format, bitrate)
        if cached is None:
            return None

        # Check if cached file exists
        cached_path = self.files_dir / cached.filename
        if not cached_path.exists():
            logger.debug(f"Cached file missing: {cached.filename}")
            self._index.remove(fingerprint, target_format, bitrate)
            self._save_index()
            return None

        # Validate source hasn't changed (if source_size provided)
        if source_size is not None and cached.source_size != source_size:
            logger.debug(
                f"Source size changed: {cached.source_size} → {source_size}, invalidating cache"
            )
            # Clean up the stale entry and file
            self._index.remove(fingerprint, target_format, bitrate)
            if cached_path.exists():
                try:
                    cached_path.unlink()
                except Exception:
                    pass
            self._save_index()
            return None

        logger.debug(f"Cache hit: {fingerprint[:20]}... → {cached.filename}")
        return cached_path

    def add(
        self,
        fingerprint: str,
        transcoded_path: Path,
        source_format: str,
        target_format: str,
        source_size: int,
        bitrate: Optional[int] = None,
    ) -> Optional[Path]:
        """
        Add a transcoded file to the cache.

        Args:
            fingerprint: Acoustic fingerprint of source
            transcoded_path: Path to the transcoded file
            source_format: Original format
            target_format: Target format
            source_size: Original source file size
            bitrate: For AAC, the bitrate used

        Returns:
            Path to the cached file, or None if caching failed
        """
        if not transcoded_path.exists():
            logger.error(f"Cannot cache non-existent file: {transcoded_path}")
            return None

        # Generate cache filename (include bitrate to differentiate quality levels)
        filename = self._fingerprint_to_filename(fingerprint, target_format, bitrate)
        cached_path = self.files_dir / filename

        try:
            # Copy to cache (preserving the transcoded file for the caller)
            shutil.copy2(transcoded_path, cached_path)

            # Update index
            cached_file = CachedFile(
                fingerprint=fingerprint,
                source_format=source_format,
                target_format=target_format,
                filename=filename,
                size=cached_path.stat().st_size,
                created=datetime.now(timezone.utc).isoformat(),
                source_size=source_size,
                bitrate=bitrate,
            )
            self._index.add(cached_file)
            self._save_index()

            logger.info(f"Cached: {fingerprint[:20]}... → {filename}")
            return cached_path

        except Exception as e:
            logger.error(f"Failed to cache file: {e}")
            return None

    def copy_from_cache(
        self,
        fingerprint: str,
        target_format: str,
        dest_path: Path,
        source_size: Optional[int] = None,
        bitrate: Optional[int] = None,
    ) -> bool:
        """
        Copy a cached file to destination if it exists.

        Args:
            fingerprint: Acoustic fingerprint
            target_format: Target format
            dest_path: Destination path
            source_size: For validation
            bitrate: For AAC

        Returns:
            True if copied from cache, False if not cached
        """
        cached_path = self.get(fingerprint, target_format, source_size, bitrate)
        if cached_path is None:
            return False

        try:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(cached_path, dest_path)
            logger.debug(f"Copied from cache: {cached_path.name} → {dest_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to copy from cache: {e}")
            return False

    def invalidate(
        self, fingerprint: str, target_format: Optional[str] = None
    ) -> int:
        """
        Invalidate cached files for a fingerprint.

        Args:
            fingerprint: Acoustic fingerprint
            target_format: If provided, only invalidate this format

        Returns:
            Number of entries invalidated
        """
        count = 0
        keys_to_remove = []

        for key, cached in self._index.files.items():
            if cached.fingerprint == fingerprint:
                if target_format is None or cached.target_format == target_format:
                    keys_to_remove.append(key)

        for key in keys_to_remove:
            cached = self._index.files[key]
            cached_path = self.files_dir / cached.filename
            if cached_path.exists():
                try:
                    cached_path.unlink()
                except Exception as e:
                    logger.warning(f"Failed to delete cached file: {e}")
            del self._index.files[key]
            count += 1

        if count > 0:
            self._save_index()
            logger.info(f"Invalidated {count} cached entries for {fingerprint[:20]}...")

        return count

    def cleanup(self, max_age_days: Optional[int] = None) -> tuple[int, int]:
        """
        Clean up orphaned files and optionally old entries.

        Args:
            max_age_days: If provided, remove entries older than this

        Returns:
            (orphaned_files_removed, old_entries_removed)
        """
        orphaned = 0
        old = 0

        # Find orphaned files (in filesystem but not in index)
        indexed_files = {c.filename for c in self._index.files.values()}
        for file_path in self.files_dir.iterdir():
            if file_path.name not in indexed_files:
                try:
                    file_path.unlink()
                    orphaned += 1
                    logger.debug(f"Removed orphaned file: {file_path.name}")
                except Exception as e:
                    logger.warning(f"Failed to remove orphan: {e}")

        # Remove old entries if max_age specified
        if max_age_days is not None:
            from datetime import timedelta

            cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
            keys_to_remove = []

            for key, cached in self._index.files.items():
                try:
                    created = datetime.fromisoformat(cached.created)
                    if created < cutoff:
                        keys_to_remove.append(key)
                except Exception:
                    pass

            for key in keys_to_remove:
                cached = self._index.files[key]
                cached_path = self.files_dir / cached.filename
                if cached_path.exists():
                    try:
                        cached_path.unlink()
                    except Exception:
                        pass
                del self._index.files[key]
                old += 1

            if old > 0:
                self._save_index()

        if orphaned or old:
            logger.info(f"Cleanup: {orphaned} orphaned files, {old} old entries removed")

        return orphaned, old

    def stats(self) -> dict:
        """Get cache statistics."""
        return {
            "total_files": self._index.count,
            "total_size_bytes": self._index.total_size,
            "total_size_mb": round(self._index.total_size / (1024 * 1024), 2),
            "cache_dir": str(self.cache_dir),
        }

    def clear(self) -> int:
        """
        Clear the entire cache.

        Returns:
            Number of files removed
        """
        count = self._index.count

        # Remove all files
        for cached in self._index.files.values():
            cached_path = self.files_dir / cached.filename
            if cached_path.exists():
                try:
                    cached_path.unlink()
                except Exception as e:
                    logger.warning(f"Failed to delete: {e}")

        # Clear index
        self._index = CacheIndex()
        self._save_index()

        logger.info(f"Cache cleared: {count} files removed")
        return count
