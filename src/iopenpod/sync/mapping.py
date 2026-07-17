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
import shutil
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from iopenpod.device.durability import (
    durable_replace,
    durable_unlink,
    flush_written_file,
    open_unique_sibling_temp,
)

logger = logging.getLogger(__name__)

# Mapping file location relative to iPod mount point
MAPPING_FILENAME = "iOpenPod.json"
MAPPING_PATH = "iPod_Control/iTunes"


@dataclass
class TrackMapping:
    """Mapping info for a single track."""

    # iPod identifiers
    db_track_id: int  # 64-bit MHIT track persistent ID from iTunesDB

    # Source file info (from PC at time of sync)
    source_format: str  # Original format: "flac", "mp3", etc.
    ipod_format: str  # Format on iPod: "mp3", "m4a", "alac"
    source_size: int  # Size of source file in bytes
    source_mtime: float  # Modification time of source file

    # Sync metadata
    last_sync: str  # ISO timestamp of last sync
    was_transcoded: bool  # True if format conversion was needed

    # Optional: path hint for disambiguation (not used as primary key)
    source_path_hint: str | None = None

    # Artwork hash for change detection (MD5 of embedded image bytes)
    art_hash: str | None = None

    # Metadata-insensitive source content hash when available.
    source_hash: str | None = None

    # Aggregate/container metadata.  Chaptered album conversions use one iPod
    # track to represent multiple source fingerprints.
    aggregate_kind: str | None = None
    contains_fingerprints: list[str] | None = None
    contains_sources: list[dict] | None = None

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        d = asdict(self)
        contains_fingerprints = d.pop("contains_fingerprints", None)
        contains_sources = d.pop("contains_sources", None)
        if contains_fingerprints is not None:
            d["containsFingerprints"] = contains_fingerprints
        if contains_sources is not None:
            d["containsSources"] = contains_sources
        # Omit None fields for cleaner JSON
        return {k: v for k, v in d.items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict) -> "TrackMapping":
        """Create from dict (JSON parsing)."""
        return cls(
            db_track_id=data.get("db_track_id", data.get("db_id", 0)),
            source_format=data["source_format"],
            ipod_format=data["ipod_format"],
            source_size=data["source_size"],
            source_mtime=data["source_mtime"],
            last_sync=data["last_sync"],
            was_transcoded=data["was_transcoded"],
            source_path_hint=data.get("source_path_hint"),
            art_hash=data.get("art_hash"),
            source_hash=data.get("source_hash"),
            aggregate_kind=data.get("aggregate_kind"),
            contains_fingerprints=(
                data.get("contains_fingerprints")
                or data.get("containsFingerprints")
                or None
            ),
            contains_sources=(
                data.get("contains_sources")
                or data.get("containsSources")
                or None
            ),
        )


@dataclass
class MappingFile:
    """
    The complete mapping file structure.

    Maps fingerprint → list[TrackMapping].
    Most fingerprints map to exactly one entry. Multiple entries occur when
    the same song appears on multiple albums (same acoustic fingerprint).
    """

    version: int = 5  # v5: optional aggregate/container metadata
    created: str = ""
    modified: str = ""
    _tracks: dict[str, list[TrackMapping]] | None = None
    _db_track_id_index: dict[int, tuple[str, TrackMapping]] | None = None
    _source_was_corrupt: bool = False

    def __post_init__(self):
        if self._tracks is None:
            self._tracks = {}
        if not self.created:
            self.created = datetime.now(UTC).isoformat()
        if not self.modified:
            self.modified = self.created
        self._db_track_id_index = None

    @property
    def tracks(self) -> dict[str, list[TrackMapping]]:
        """Access tracks dict, ensuring it's never None."""
        if self._tracks is None:
            self._tracks = {}
        return self._tracks

    @property
    def source_was_corrupt(self) -> bool:
        """Whether load detected an on-device mapping that needs rebuilding."""
        return self._source_was_corrupt

    def add_track(
        self,
        fingerprint: str,
        db_track_id: int,
        source_format: str,
        ipod_format: str,
        source_size: int,
        source_mtime: float,
        was_transcoded: bool,
        source_path_hint: str | None = None,
        art_hash: str | None = None,
        source_hash: str | None = None,
        aggregate_kind: str | None = None,
        contains_fingerprints: list[str] | tuple[str, ...] | None = None,
        contains_sources: list[dict] | tuple[dict, ...] | None = None,
    ) -> None:
        """Add or update a track mapping.

        If entry with same db_track_id exists under this fingerprint, update it.
        Otherwise append a new entry.
        """
        now = datetime.now(UTC).isoformat()

        new_mapping = TrackMapping(
            db_track_id=db_track_id,
            source_format=source_format,
            ipod_format=ipod_format,
            source_size=source_size,
            source_mtime=source_mtime,
            last_sync=now,
            was_transcoded=was_transcoded,
            source_path_hint=source_path_hint,
            art_hash=art_hash,
            source_hash=source_hash,
            aggregate_kind=aggregate_kind,
            contains_fingerprints=(
                list(contains_fingerprints)
                if contains_fingerprints is not None else None
            ),
            contains_sources=(
                [dict(source) for source in contains_sources]
                if contains_sources is not None else None
            ),
        )

        entries = self.tracks.get(fingerprint, [])

        # Check if this db_track_id already exists in the list
        for i, entry in enumerate(entries):
            if entry.db_track_id == db_track_id:
                entries[i] = new_mapping
                self.tracks[fingerprint] = entries
                self.modified = now
                self._db_track_id_index = None  # invalidate reverse index
                return

        # New entry
        entries.append(new_mapping)
        self.tracks[fingerprint] = entries
        self.modified = now
        self._db_track_id_index = None  # invalidate reverse index

    def get_entries(self, fingerprint: str) -> list[TrackMapping]:
        """Get all mapping entries for a fingerprint. Returns empty list if none."""
        return self.tracks.get(fingerprint, [])

    def get_single(self, fingerprint: str) -> TrackMapping | None:
        """Get mapping for a fingerprint that has exactly one entry.

        Returns None if fingerprint not found or has multiple entries.
        Use get_entries() for collision-aware access.
        """
        entries = self.tracks.get(fingerprint, [])
        if len(entries) == 1:
            return entries[0]
        return None

    def get_by_db_track_id(self, db_track_id: int) -> tuple[str, TrackMapping] | None:
        """Get track mapping by db_track_id. Returns (fingerprint, mapping) or None."""
        if self._db_track_id_index is None:
            self._db_track_id_index = {}
            for fp, entries in self.tracks.items():
                for entry in entries:
                    self._db_track_id_index[entry.db_track_id] = (fp, entry)
        return self._db_track_id_index.get(db_track_id)

    def aggregate_entries(self) -> list[tuple[str, TrackMapping]]:
        """Return all mappings that represent an aggregate/container track."""
        return [
            (fp, entry)
            for fp, entry in self.all_entries()
            if entry.aggregate_kind
        ]

    def aggregate_entries_by_contained_fingerprint(self) -> dict[str, tuple[str, TrackMapping]]:
        """Map each contained source fingerprint to its aggregate mapping."""
        result: dict[str, tuple[str, TrackMapping]] = {}
        for fp, entry in self.aggregate_entries():
            for contained_fp in entry.contains_fingerprints or []:
                result[contained_fp] = (fp, entry)
        return result

    def remove_track(self, fingerprint: str, db_track_id: int | None = None) -> bool:
        """Remove a track mapping.

        If db_track_id is provided, remove only that specific entry (for collisions).
        If db_track_id is None and only one entry exists, remove it.
        If db_track_id is None and multiple entries exist, remove all.

        Returns True if anything was removed.
        """
        entries = self.tracks.get(fingerprint, [])
        if not entries:
            return False

        if db_track_id is not None:
            new_entries = [e for e in entries if e.db_track_id != db_track_id]
            if len(new_entries) == len(entries):
                return False  # db_track_id not found
            if new_entries:
                self.tracks[fingerprint] = new_entries
            else:
                del self.tracks[fingerprint]
        else:
            del self.tracks[fingerprint]

        self.modified = datetime.now(UTC).isoformat()
        self._db_track_id_index = None  # invalidate reverse index
        return True

    def remove_by_db_track_id(self, db_track_id: int) -> bool:
        """Remove a track mapping by db_track_id (searches all fingerprints).

        Returns True if removed.
        """
        for fp, entries in list(self.tracks.items()):
            new_entries = [e for e in entries if e.db_track_id != db_track_id]
            if len(new_entries) < len(entries):
                if new_entries:
                    self.tracks[fp] = new_entries
                else:
                    del self.tracks[fp]
                self.modified = datetime.now(UTC).isoformat()
                self._db_track_id_index = None  # invalidate reverse index
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

    def all_db_track_ids(self) -> set[int]:
        """Get all db_track_ids in mapping."""
        db_track_ids: set[int] = set()
        for entries in self.tracks.values():
            for entry in entries:
                db_track_ids.add(entry.db_track_id)
        return db_track_ids

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

        Handles v1 (single entry), v2 (list entries), v3 (db_track_id key),
        v4 (source_hash), and v5 (aggregate metadata) formats.
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
            version=5,  # Always upgrade to current format
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
        mapping.add_track(fingerprint, db_track_id, ...)
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
        """Load mapping state without modifying any on-device files."""
        if not self.mapping_file.exists():
            logger.info(f"No mapping file found at {self.mapping_file}; starting with empty mapping")
            return MappingFile()

        try:
            with open(self.mapping_file, encoding="utf-8") as f:
                data = json.load(f)
            mapping = MappingFile.from_dict(data)
            logger.info(f"Loaded mapping with {mapping.track_count} tracks "
                        f"({mapping.fingerprint_count} fingerprints)")
            return mapping

        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            logger.error("Invalid iOpenPod mapping file: %s", e)
            logger.warning(
                "The corrupt mapping remains untouched until a guarded sync "
                "can back it up and rebuild it"
            )
            return MappingFile(_source_was_corrupt=True)

        except OSError as e:
            logger.error("Could not read mapping file: %s", e)
            raise MappingLoadError(
                f"Could not read the iPod mapping file: {e}"
            ) from e

    def save(self, mapping: MappingFile) -> bool:
        """Save mapping file to iPod atomically."""
        temp_file: Path | None = None
        try:
            self.mapping_dir.mkdir(parents=True, exist_ok=True)
            mapping.modified = datetime.now(UTC).isoformat()

            if mapping.source_was_corrupt and self.mapping_file.exists():
                self._backup_corrupt_mapping()

            temp_file, opened_temp = open_unique_sibling_temp(
                self.mapping_file,
                mode="w",
                encoding="utf-8",
            )
            with opened_temp as f:
                json.dump(mapping.to_dict(), f, indent=2)
                flush_written_file(f)

            durable_replace(temp_file, self.mapping_file)
            mapping._source_was_corrupt = False
            logger.info(f"Saved mapping with {mapping.track_count} tracks")
            return True

        except Exception as e:
            logger.error(f"Error saving mapping file: {e}")
            return False
        finally:
            if temp_file is not None:
                try:
                    durable_unlink(temp_file, missing_ok=True)
                except OSError as cleanup_error:
                    logger.warning(
                        "Could not remove incomplete mapping temp %s: %s",
                        temp_file,
                        cleanup_error,
                    )

    def _backup_corrupt_mapping(self) -> Path:
        """Durably preserve a corrupt mapping immediately before replacement."""
        backup_path = self.mapping_file.with_suffix(".json.bak")
        temp_backup: Path | None = None
        try:
            temp_backup, opened_temp = open_unique_sibling_temp(
                backup_path,
                mode="wb",
            )
            with opened_temp as target:
                with open(self.mapping_file, "rb") as source:
                    shutil.copyfileobj(source, target)
                flush_written_file(target)
            durable_replace(temp_backup, backup_path)
        except Exception:
            if temp_backup is not None:
                durable_unlink(temp_backup, missing_ok=True)
            raise
        logger.warning("Backed up corrupt mapping to %s", backup_path)
        return backup_path

    def backup(self) -> Path | None:
        """Create a timestamped backup of the mapping file."""
        if not self.mapping_file.exists():
            return None

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = self.mapping_file.with_suffix(f".{timestamp}.bak")
        temp_backup: Path | None = None

        try:
            temp_backup, opened_temp = open_unique_sibling_temp(
                backup_path,
                mode="wb",
            )
            with opened_temp as target:
                with open(self.mapping_file, "rb") as source:
                    shutil.copyfileobj(source, target)
                flush_written_file(target)
            durable_replace(temp_backup, backup_path)
            logger.info(f"Created mapping backup: {backup_path}")
            return backup_path
        except Exception as e:
            logger.error(f"Failed to backup mapping: {e}")
            return None
        finally:
            if temp_backup is not None:
                try:
                    durable_unlink(temp_backup, missing_ok=True)
                except OSError as cleanup_error:
                    logger.warning(
                        "Could not remove incomplete mapping backup temp %s: %s",
                        temp_backup,
                        cleanup_error,
                    )


class MappingLoadError(RuntimeError):
    """Raised when mapping state cannot be read safely."""
