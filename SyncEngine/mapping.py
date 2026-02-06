"""
iPod Mapping File - Tracks the relationship between PC files and iPod tracks.

Stores: acoustic_fingerprint → {dbid, source info, sync metadata}

Location on iPod: /iPod_Control/iTunes/iOpenPod.json
"""

import json
import logging
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Mapping file location relative to iPod mount point
MAPPING_FILENAME = "iOpenPod.json"
MAPPING_PATH = "iPod_Control/iTunes"


@dataclass
class TrackMapping:
    """Mapping info for a single track."""

    # iPod identifiers
    dbid: int  # 64-bit database ID from iTunesDB

    # Source file info (from PC at time of sync)
    source_format: str  # Original format: "flac", "mp3", etc.
    ipod_format: str  # Format on iPod: "mp3", "m4a", "alac"
    source_size: int  # Size of source file in bytes
    source_mtime: float  # Modification time of source file

    # Sync metadata
    last_sync: str  # ISO timestamp of last sync
    was_transcoded: bool  # True if format conversion was needed

    # Optional: path hint for debugging (not used for matching)
    source_path_hint: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "TrackMapping":
        """Create from dict (JSON parsing)."""
        return cls(
            dbid=data["dbid"],
            source_format=data["source_format"],
            ipod_format=data["ipod_format"],
            source_size=data["source_size"],
            source_mtime=data["source_mtime"],
            last_sync=data["last_sync"],
            was_transcoded=data["was_transcoded"],
            source_path_hint=data.get("source_path_hint"),
        )


@dataclass
class MappingFile:
    """
    The complete mapping file structure.

    Tracks all fingerprint → iPod track relationships.
    """

    version: int = 1
    created: str = ""
    modified: str = ""
    _tracks: dict[str, TrackMapping] | None = None  # fingerprint → TrackMapping

    def __post_init__(self):
        if self._tracks is None:
            self._tracks = {}
        if not self.created:
            self.created = datetime.now(timezone.utc).isoformat()
        if not self.modified:
            self.modified = self.created

    @property
    def tracks(self) -> dict[str, TrackMapping]:
        """Access tracks dict, ensuring it's never None."""
        if self._tracks is None:
            self._tracks = {}
        return self._tracks

    def add_track(
        self,
        fingerprint: str,
        dbid: int,
        source_format: str,
        ipod_format: str,
        source_size: int,
        source_mtime: float,
        was_transcoded: bool,
        source_path_hint: Optional[str] = None,
    ) -> None:
        """Add or update a track mapping."""
        now = datetime.now(timezone.utc).isoformat()
        self.tracks[fingerprint] = TrackMapping(
            dbid=dbid,
            source_format=source_format,
            ipod_format=ipod_format,
            source_size=source_size,
            source_mtime=source_mtime,
            last_sync=now,
            was_transcoded=was_transcoded,
            source_path_hint=source_path_hint,
        )
        self.modified = now

    def get_track(self, fingerprint: str) -> Optional[TrackMapping]:
        """Get track mapping by fingerprint."""
        return self.tracks.get(fingerprint)

    def get_by_dbid(self, dbid: int) -> Optional[tuple[str, TrackMapping]]:
        """Get track mapping by dbid. Returns (fingerprint, mapping) or None."""
        for fp, mapping in self.tracks.items():
            if mapping.dbid == dbid:
                return (fp, mapping)
        return None

    def remove_track(self, fingerprint: str) -> bool:
        """Remove a track mapping. Returns True if removed."""
        if fingerprint in self.tracks:
            del self.tracks[fingerprint]
            self.modified = datetime.now(timezone.utc).isoformat()
            return True
        return False

    def remove_by_dbid(self, dbid: int) -> bool:
        """Remove a track mapping by dbid. Returns True if removed."""
        for fp, mapping in list(self.tracks.items()):
            if mapping.dbid == dbid:
                del self.tracks[fp]
                self.modified = datetime.now(timezone.utc).isoformat()
                return True
        return False

    @property
    def track_count(self) -> int:
        """Number of tracks in mapping."""
        return len(self.tracks)

    def all_fingerprints(self) -> set[str]:
        """Get all fingerprints in mapping."""
        return set(self.tracks.keys())

    def all_dbids(self) -> set[int]:
        """Get all dbids in mapping."""
        return {m.dbid for m in self.tracks.values()}

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "version": self.version,
            "created": self.created,
            "modified": self.modified,
            "tracks": {fp: m.to_dict() for fp, m in self.tracks.items()},
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MappingFile":
        """Create from dict (JSON parsing)."""
        tracks = {}
        for fp, track_data in data.get("tracks", {}).items():
            tracks[fp] = TrackMapping.from_dict(track_data)

        return cls(
            version=data.get("version", 1),
            created=data.get("created", ""),
            modified=data.get("modified", ""),
            _tracks=tracks,
        )


class MappingManager:
    """
    Manages the iPod mapping file.

    Usage:
        manager = MappingManager("/mnt/ipod")
        mapping = manager.load()
        mapping.add_track(fingerprint, dbid, ...)
        manager.save(mapping)
    """

    def __init__(self, ipod_path: str | Path):
        """
        Initialize manager with iPod mount path.

        Args:
            ipod_path: Root path of mounted iPod (e.g., "E:" or "/mnt/ipod")
        """
        self.ipod_path = Path(ipod_path)
        self.mapping_dir = self.ipod_path / MAPPING_PATH
        self.mapping_file = self.mapping_dir / MAPPING_FILENAME

    def exists(self) -> bool:
        """Check if mapping file exists."""
        return self.mapping_file.exists()

    def load(self) -> MappingFile:
        """
        Load mapping file from iPod.

        Returns:
            MappingFile (empty if file doesn't exist)
        """
        if not self.mapping_file.exists():
            logger.info(f"No mapping file found at {self.mapping_file}, creating new")
            return MappingFile()

        try:
            with open(self.mapping_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            mapping = MappingFile.from_dict(data)
            logger.info(f"Loaded mapping with {mapping.track_count} tracks")
            return mapping

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in mapping file: {e}")
            # Backup corrupt file and start fresh
            backup = self.mapping_file.with_suffix(".json.bak")
            self.mapping_file.rename(backup)
            logger.warning(f"Backed up corrupt mapping to {backup}")
            return MappingFile()

        except Exception as e:
            logger.error(f"Error loading mapping file: {e}")
            return MappingFile()

    def save(self, mapping: MappingFile) -> bool:
        """
        Save mapping file to iPod.

        Args:
            mapping: MappingFile to save

        Returns:
            True if successful
        """
        try:
            # Ensure directory exists
            self.mapping_dir.mkdir(parents=True, exist_ok=True)

            # Update modified timestamp
            mapping.modified = datetime.now(timezone.utc).isoformat()

            # Write atomically (temp file + rename)
            temp_file = self.mapping_file.with_suffix(".json.tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(mapping.to_dict(), f, indent=2)

            # Rename to final location
            temp_file.replace(self.mapping_file)

            logger.info(f"Saved mapping with {mapping.track_count} tracks")
            return True

        except Exception as e:
            logger.error(f"Error saving mapping file: {e}")
            return False

    def backup(self) -> Optional[Path]:
        """
        Create a backup of the mapping file.

        Returns:
            Path to backup file, or None if failed
        """
        if not self.mapping_file.exists():
            return None

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = self.mapping_file.with_suffix(f".{timestamp}.bak")

        try:
            import shutil

            shutil.copy2(self.mapping_file, backup_path)
            logger.info(f"Created mapping backup: {backup_path}")
            return backup_path
        except Exception as e:
            logger.error(f"Failed to backup mapping: {e}")
            return None
