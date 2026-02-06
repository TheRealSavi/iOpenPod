"""
iPod Mapping File - Tracks the relationship between PC files and iPod tracks.

Stores: acoustic_fingerprint → list[TrackMapping]

The mapping is fingerprint → list because the same acoustic fingerprint can
legitimately appear on multiple albums (e.g., a song on both the original album
and a Greatest Hits compilation). The common case (99%+) is a list of length 1.

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

    # Optional: path hint for disambiguation (not used as primary key)
    source_path_hint: Optional[str] = None

    # Artwork hash for change detection (MD5 of embedded image bytes)
    art_hash: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        d = asdict(self)
        # Omit None fields for cleaner JSON
        return {k: v for k, v in d.items() if v is not None}

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
            art_hash=data.get("art_hash"),
        )


@dataclass
class MappingFile:
    """
    The complete mapping file structure.

    Maps fingerprint → list[TrackMapping].
    Most fingerprints map to exactly one entry. Multiple entries occur when
    the same song appears on multiple albums (same acoustic fingerprint).
    """

    version: int = 2  # v2: tracks are lists
    created: str = ""
    modified: str = ""
    _tracks: dict[str, list[TrackMapping]] | None = None

    def __post_init__(self):
        if self._tracks is None:
            self._tracks = {}
        if not self.created:
            self.created = datetime.now(timezone.utc).isoformat()
        if not self.modified:
            self.modified = self.created

    @property
    def tracks(self) -> dict[str, list[TrackMapping]]:
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
        art_hash: Optional[str] = None,
    ) -> None:
        """Add or update a track mapping.

        If entry with same dbid exists under this fingerprint, update it.
        Otherwise append a new entry.
        """
        now = datetime.now(timezone.utc).isoformat()

        new_mapping = TrackMapping(
            dbid=dbid,
            source_format=source_format,
            ipod_format=ipod_format,
            source_size=source_size,
            source_mtime=source_mtime,
            last_sync=now,
            was_transcoded=was_transcoded,
            source_path_hint=source_path_hint,
            art_hash=art_hash,
        )

        entries = self.tracks.get(fingerprint, [])

        # Check if this dbid already exists in the list
        for i, entry in enumerate(entries):
            if entry.dbid == dbid:
                entries[i] = new_mapping
                self.tracks[fingerprint] = entries
                self.modified = now
                return

        # New entry
        entries.append(new_mapping)
        self.tracks[fingerprint] = entries
        self.modified = now

    def get_entries(self, fingerprint: str) -> list[TrackMapping]:
        """Get all mapping entries for a fingerprint. Returns empty list if none."""
        return self.tracks.get(fingerprint, [])

    def get_single(self, fingerprint: str) -> Optional[TrackMapping]:
        """Get mapping for a fingerprint that has exactly one entry.

        Returns None if fingerprint not found or has multiple entries.
        Use get_entries() for collision-aware access.
        """
        entries = self.tracks.get(fingerprint, [])
        if len(entries) == 1:
            return entries[0]
        return None

    def get_by_dbid(self, dbid: int) -> Optional[tuple[str, TrackMapping]]:
        """Get track mapping by dbid. Returns (fingerprint, mapping) or None."""
        for fp, entries in self.tracks.items():
            for entry in entries:
                if entry.dbid == dbid:
                    return (fp, entry)
        return None

    def remove_track(self, fingerprint: str, dbid: Optional[int] = None) -> bool:
        """Remove a track mapping.

        If dbid is provided, remove only that specific entry (for collisions).
        If dbid is None and only one entry exists, remove it.
        If dbid is None and multiple entries exist, remove all.

        Returns True if anything was removed.
        """
        entries = self.tracks.get(fingerprint, [])
        if not entries:
            return False

        if dbid is not None:
            new_entries = [e for e in entries if e.dbid != dbid]
            if len(new_entries) == len(entries):
                return False  # dbid not found
            if new_entries:
                self.tracks[fingerprint] = new_entries
            else:
                del self.tracks[fingerprint]
        else:
            del self.tracks[fingerprint]

        self.modified = datetime.now(timezone.utc).isoformat()
        return True

    def remove_by_dbid(self, dbid: int) -> bool:
        """Remove a track mapping by dbid (searches all fingerprints).

        Returns True if removed.
        """
        for fp, entries in list(self.tracks.items()):
            new_entries = [e for e in entries if e.dbid != dbid]
            if len(new_entries) < len(entries):
                if new_entries:
                    self.tracks[fp] = new_entries
                else:
                    del self.tracks[fp]
                self.modified = datetime.now(timezone.utc).isoformat()
                return True
        return False

    @property
    def track_count(self) -> int:
        """Total number of individual track entries (across all fingerprints)."""
        return sum(len(entries) for entries in self.tracks.values())

    @property
    def fingerprint_count(self) -> int:
        """Number of unique fingerprints in mapping."""
        return len(self.tracks)

    def all_fingerprints(self) -> set[str]:
        """Get all fingerprints in mapping."""
        return set(self.tracks.keys())

    def all_dbids(self) -> set[int]:
        """Get all dbids in mapping."""
        dbids: set[int] = set()
        for entries in self.tracks.values():
            for entry in entries:
                dbids.add(entry.dbid)
        return dbids

    def all_entries(self) -> list[tuple[str, TrackMapping]]:
        """Return all (fingerprint, mapping) pairs flattened."""
        result = []
        for fp, entries in self.tracks.items():
            for entry in entries:
                result.append((fp, entry))
        return result

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "version": self.version,
            "created": self.created,
            "modified": self.modified,
            "tracks": {
                fp: [m.to_dict() for m in entries]
                for fp, entries in self.tracks.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MappingFile":
        """Create from dict (JSON parsing).

        Handles both v1 (single entry) and v2 (list entries) formats.
        """
        version = data.get("version", 1)
        tracks: dict[str, list[TrackMapping]] = {}

        for fp, track_data in data.get("tracks", {}).items():
            if version >= 2 and isinstance(track_data, list):
                # v2: each fingerprint maps to a list
                tracks[fp] = [TrackMapping.from_dict(entry) for entry in track_data]
            elif isinstance(track_data, dict):
                # v1: each fingerprint maps to a single entry — upgrade to list
                tracks[fp] = [TrackMapping.from_dict(track_data)]
            else:
                logger.warning(f"Unexpected track data format for {fp}: {type(track_data)}")

        return cls(
            version=2,  # Always upgrade to v2
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
        self.ipod_path = Path(ipod_path)
        self.mapping_dir = self.ipod_path / MAPPING_PATH
        self.mapping_file = self.mapping_dir / MAPPING_FILENAME

    def exists(self) -> bool:
        """Check if mapping file exists."""
        return self.mapping_file.exists()

    def load(self) -> MappingFile:
        """Load mapping file from iPod. Returns empty MappingFile if not found."""
        if not self.mapping_file.exists():
            logger.info(f"No mapping file found at {self.mapping_file}, creating new")
            return MappingFile()

        try:
            with open(self.mapping_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            mapping = MappingFile.from_dict(data)
            logger.info(f"Loaded mapping with {mapping.track_count} tracks "
                        f"({mapping.fingerprint_count} fingerprints)")
            return mapping

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in mapping file: {e}")
            backup = self.mapping_file.with_suffix(".json.bak")
            self.mapping_file.rename(backup)
            logger.warning(f"Backed up corrupt mapping to {backup}")
            return MappingFile()

        except Exception as e:
            logger.error(f"Error loading mapping file: {e}")
            return MappingFile()

    def save(self, mapping: MappingFile) -> bool:
        """Save mapping file to iPod atomically."""
        try:
            self.mapping_dir.mkdir(parents=True, exist_ok=True)
            mapping.modified = datetime.now(timezone.utc).isoformat()

            temp_file = self.mapping_file.with_suffix(".json.tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(mapping.to_dict(), f, indent=2)

            temp_file.replace(self.mapping_file)
            logger.info(f"Saved mapping with {mapping.track_count} tracks")
            return True

        except Exception as e:
            logger.error(f"Error saving mapping file: {e}")
            return False

    def backup(self) -> Optional[Path]:
        """Create a timestamped backup of the mapping file."""
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
