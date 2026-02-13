"""
Sync Checkpoint Manager - Provides backup, rollback, and resume capabilities.

Creates point-in-time backups of critical iPod database files before sync
operations, allowing recovery if something goes wrong mid-sync.

Checkpoint directory structure:
    <ipod>/iPod_Control/.iOpenPod/
        checkpoint_<timestamp>/
            iTunesDB              # Backup of iTunesDB
            iOpenPod.json        # Backup of mapping file
            state.json           # Sync state for resume
"""

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)

# Maximum number of checkpoints to keep (older ones are pruned)
MAX_CHECKPOINTS = 3


@dataclass
class SyncState:
    """Tracks sync progress for potential resume."""
    started_at: str
    completed_stages: list[str] = field(default_factory=list)
    current_stage: str = ""
    tracks_added: int = 0
    tracks_removed: int = 0
    tracks_updated: int = 0
    last_error: str = ""
    is_complete: bool = False
    is_failed: bool = False

    def mark_stage_complete(self, stage: str):
        """Mark a stage as successfully completed."""
        if stage not in self.completed_stages:
            self.completed_stages.append(stage)
        self.current_stage = ""

    def mark_stage_started(self, stage: str):
        """Mark that we're starting a new stage."""
        self.current_stage = stage

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SyncState":
        return cls(
            started_at=data.get("started_at", ""),
            completed_stages=data.get("completed_stages", []),
            current_stage=data.get("current_stage", ""),
            tracks_added=data.get("tracks_added", 0),
            tracks_removed=data.get("tracks_removed", 0),
            tracks_updated=data.get("tracks_updated", 0),
            last_error=data.get("last_error", ""),
            is_complete=data.get("is_complete", False),
            is_failed=data.get("is_failed", False),
        )


class CheckpointManager:
    """Manages database backups and sync state for rollback/resume."""

    def __init__(self, ipod_path: str | Path):
        self.ipod_path = Path(ipod_path)
        self.checkpoint_base = self.ipod_path / "iPod_Control" / ".iOpenPod"
        self._current_checkpoint: Optional[Path] = None
        self._state: Optional[SyncState] = None

    @property
    def itunesdb_path(self) -> Path:
        return self.ipod_path / "iPod_Control" / "iTunes" / "iTunesDB"

    @property
    def mapping_path(self) -> Path:
        return self.ipod_path / "iPod_Control" / "iTunes" / "iOpenPod.json"

    def create_checkpoint(self) -> bool:
        """
        Create a new checkpoint before sync starts.

        Backs up iTunesDB and mapping file so we can rollback if sync fails.
        Returns True if checkpoint created successfully.
        """
        try:
            # Create checkpoint directory
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            checkpoint_dir = self.checkpoint_base / f"checkpoint_{timestamp}"
            checkpoint_dir.mkdir(parents=True, exist_ok=True)
            self._current_checkpoint = checkpoint_dir

            # Backup iTunesDB
            if self.itunesdb_path.exists():
                shutil.copy2(self.itunesdb_path, checkpoint_dir / "iTunesDB")
                logger.info(f"Backed up iTunesDB to {checkpoint_dir / 'iTunesDB'}")

            # Backup mapping file
            if self.mapping_path.exists():
                shutil.copy2(self.mapping_path, checkpoint_dir / "iOpenPod.json")
                logger.info(f"Backed up mapping to {checkpoint_dir / 'iOpenPod.json'}")

            # Initialize sync state
            self._state = SyncState(started_at=datetime.now().isoformat())
            self._save_state()

            # Prune old checkpoints
            self._prune_old_checkpoints()

            logger.info(f"Created checkpoint: {checkpoint_dir.name}")
            return True

        except Exception as e:
            logger.error(f"Failed to create checkpoint: {e}")
            return False

    def update_state(
        self,
        stage: Optional[str] = None,
        stage_complete: bool = False,
        tracks_added: int = 0,
        tracks_removed: int = 0,
        tracks_updated: int = 0,
        error: Optional[str] = None,
    ):
        """Update current sync state for resume capability."""
        if not self._state:
            return

        if stage and not stage_complete:
            self._state.mark_stage_started(stage)
        if stage and stage_complete:
            self._state.mark_stage_complete(stage)

        self._state.tracks_added += tracks_added
        self._state.tracks_removed += tracks_removed
        self._state.tracks_updated += tracks_updated

        if error:
            self._state.last_error = error
            self._state.is_failed = True

        self._save_state()

    def mark_complete(self):
        """Mark the sync as successfully completed."""
        if self._state:
            self._state.is_complete = True
            self._state.is_failed = False
            self._state.current_stage = ""
            self._save_state()

        # On success, we can remove the checkpoint (data is safely written)
        # But keep it for a bit in case user wants to rollback manually
        logger.info("Sync completed successfully, checkpoint preserved for safety")

    def mark_failed(self, error: str):
        """Mark the sync as failed."""
        if self._state:
            self._state.is_failed = True
            self._state.last_error = error
            self._save_state()
        logger.error(f"Sync failed: {error}")

    def rollback(self) -> bool:
        """
        Rollback to the last checkpoint.

        Restores iTunesDB and mapping file from the most recent checkpoint.
        Returns True if rollback was successful.
        """
        checkpoint = self._find_latest_checkpoint()
        if not checkpoint:
            logger.warning("No checkpoint available for rollback")
            return False

        try:
            # Restore iTunesDB
            backup_itdb = checkpoint / "iTunesDB"
            if backup_itdb.exists():
                shutil.copy2(backup_itdb, self.itunesdb_path)
                logger.info(f"Restored iTunesDB from {backup_itdb}")

            # Restore mapping
            backup_mapping = checkpoint / "iOpenPod.json"
            if backup_mapping.exists():
                shutil.copy2(backup_mapping, self.mapping_path)
                logger.info(f"Restored mapping from {backup_mapping}")

            # Update state to reflect rollback
            if self._state:
                self._state.last_error = "Rolled back to checkpoint"
                self._save_state()

            logger.info(f"Successfully rolled back to checkpoint: {checkpoint.name}")
            return True

        except Exception as e:
            logger.error(f"Rollback failed: {e}")
            return False

    def get_last_failed_sync(self) -> Optional[SyncState]:
        """
        Check if there's an incomplete/failed sync that could be resumed.

        Returns the SyncState if a resume is possible, None otherwise.
        """
        checkpoint = self._find_latest_checkpoint()
        if not checkpoint:
            return None

        state_file = checkpoint / "state.json"
        if not state_file.exists():
            return None

        try:
            with open(state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            state = SyncState.from_dict(data)

            # Only return if sync failed or was interrupted
            if state.is_failed or (not state.is_complete and state.current_stage):
                return state
            return None

        except Exception as e:
            logger.warning(f"Could not read sync state: {e}")
            return None

    def cleanup_on_success(self):
        """Remove checkpoint after successful sync (optional, keeps last N)."""
        # We keep checkpoints for safety - just prune old ones
        self._prune_old_checkpoints()

    def _save_state(self):
        """Save current state to checkpoint directory."""
        if not self._current_checkpoint or not self._state:
            return

        state_file = self._current_checkpoint / "state.json"
        try:
            with open(state_file, "w", encoding="utf-8") as f:
                json.dump(self._state.to_dict(), f, indent=2)
        except Exception as e:
            logger.warning(f"Could not save sync state: {e}")

    def _find_latest_checkpoint(self) -> Optional[Path]:
        """Find the most recent checkpoint directory."""
        if not self.checkpoint_base.exists():
            return None

        checkpoints = sorted(
            [d for d in self.checkpoint_base.iterdir() if d.is_dir() and d.name.startswith("checkpoint_")],
            key=lambda p: p.name,
            reverse=True,
        )
        return checkpoints[0] if checkpoints else None

    def _prune_old_checkpoints(self):
        """Remove old checkpoints, keeping only the most recent N."""
        if not self.checkpoint_base.exists():
            return

        checkpoints = sorted(
            [d for d in self.checkpoint_base.iterdir() if d.is_dir() and d.name.startswith("checkpoint_")],
            key=lambda p: p.name,
            reverse=True,
        )

        for old_checkpoint in checkpoints[MAX_CHECKPOINTS:]:
            try:
                shutil.rmtree(old_checkpoint)
                logger.debug(f"Pruned old checkpoint: {old_checkpoint.name}")
            except Exception as e:
                logger.warning(f"Could not remove old checkpoint {old_checkpoint}: {e}")


def check_for_interrupted_sync(ipod_path: str | Path) -> Optional[SyncState]:
    """
    Quick check if there's an interrupted sync on the iPod.

    Useful for prompting user on app startup or device connect.
    """
    manager = CheckpointManager(ipod_path)
    return manager.get_last_failed_sync()


def offer_rollback(ipod_path: str | Path) -> bool:
    """
    Rollback to last checkpoint if available.

    Returns True if rollback succeeded, False otherwise.
    """
    manager = CheckpointManager(ipod_path)
    return manager.rollback()
