"""Contained, identity-locked writes for small iPod metadata files."""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .durability import durable_replace, durable_unlink, flush_parent_directory, flush_written_file
from .filesystem_profile import FilesystemProfile
from .path_safety import resolve_device_path
from .storage_safety import allocated_size, require_file_size_supported
from .write_guard import DeviceWriteGuard, DeviceWriteSafetyError
from .write_readiness import (
    inspect_device_write_readiness,
    revalidate_device_write_readiness,
    volume_lock_key,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DeviceMetadataWriteSession:
    """Perform small metadata mutations on one retained, guarded iPod volume."""

    mount_path: Path
    filesystem_profile: FilesystemProfile

    def revalidate(self) -> FilesystemProfile:
        """Refresh the retained profile or raise before the next mutation."""
        self.filesystem_profile = revalidate_device_write_readiness(
            self.filesystem_profile
        )
        return self.filesystem_profile

    def write_bytes_atomic(
        self,
        relative_path: str | Path,
        data: bytes,
        *,
        allowed_subtree: str | Path,
    ) -> Path:
        """Flush a sibling temp file and atomically install it on the iPod."""
        payload = bytes(data)
        target = self._resolve(relative_path, allowed_subtree=allowed_subtree)
        self._validate_component(target.name)
        require_file_size_supported(
            len(payload),
            max_file_size_bytes=self.filesystem_profile.max_file_size_bytes,
            display_name=target.name,
        )
        self._ensure_free_space(len(payload), target.name)
        self._ensure_parent(relative_path, allowed_subtree=allowed_subtree)

        self.revalidate()
        target = self._resolve(relative_path, allowed_subtree=allowed_subtree)
        fd, raw_temp = tempfile.mkstemp(
            dir=str(target.parent),
            prefix=".iop-",
            suffix=".tmp",
        )
        temp_path = Path(raw_temp)
        try:
            with os.fdopen(fd, "wb") as file:
                fd = -1
                file.write(payload)
                flush_written_file(file)

            self.revalidate()
            target = self._resolve(relative_path, allowed_subtree=allowed_subtree)
            durable_replace(temp_path, target)
            return target
        except Exception:
            if fd >= 0:
                os.close(fd)
            self._cleanup_temp_if_still_safe(temp_path)
            raise

    def write_text_atomic(
        self,
        relative_path: str | Path,
        text: str,
        *,
        allowed_subtree: str | Path,
        encoding: str = "utf-8",
    ) -> Path:
        """Encode and atomically install a small text metadata file."""
        return self.write_bytes_atomic(
            relative_path,
            text.encode(encoding),
            allowed_subtree=allowed_subtree,
        )

    def delete(
        self,
        relative_path: str | Path,
        *,
        allowed_subtree: str | Path,
        missing_ok: bool = False,
    ) -> None:
        """Durably remove a contained metadata file after revalidation."""
        self.revalidate()
        target = self._resolve(relative_path, allowed_subtree=allowed_subtree)
        durable_unlink(target, missing_ok=missing_ok)

    def _resolve(
        self,
        relative_path: str | Path,
        *,
        allowed_subtree: str | Path,
    ) -> Path:
        return resolve_device_path(
            self.mount_path,
            relative_path,
            allowed_subtree=allowed_subtree,
        )

    def _ensure_parent(
        self,
        relative_path: str | Path,
        *,
        allowed_subtree: str | Path,
    ) -> None:
        self.revalidate()
        target = self._resolve(relative_path, allowed_subtree=allowed_subtree)
        if target.parent.is_dir():
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        flush_parent_directory(target.parent)

    def _validate_component(self, name: str) -> None:
        limit = int(self.filesystem_profile.max_component_length or 0)
        if limit > 0 and len(name) > limit:
            raise DeviceWriteSafetyError(
                f"The metadata filename {name!r} exceeds this iPod "
                f"filesystem's {limit}-character component limit."
            )

    def _ensure_free_space(self, logical_size: int, display_name: str) -> None:
        try:
            free = shutil.disk_usage(self.mount_path).free
        except OSError as exc:
            raise DeviceWriteSafetyError(
                f"Could not verify iPod free space before writing {display_name}: {exc}"
            ) from exc
        required = allocated_size(
            logical_size,
            self.filesystem_profile.allocation_unit_size,
        )
        if free < required:
            raise DeviceWriteSafetyError(
                f"The iPod does not have enough free space to safely write "
                f"{display_name}. iOpenPod stopped before creating the file."
            )

    def _cleanup_temp_if_still_safe(self, temp_path: Path) -> None:
        try:
            self.revalidate()
            durable_unlink(temp_path, missing_ok=True)
        except Exception as exc:
            logger.warning(
                "Could not safely remove temporary iPod metadata file %s: %s",
                temp_path,
                exc,
            )


@contextmanager
def guarded_device_metadata_session(
    mount_path: str | Path,
    *,
    reported_volume_format: str = "",
    expected_volume_identity_key: str = "",
) -> Iterator[DeviceMetadataWriteSession]:
    """Yield a contained metadata writer while the exact volume lock is held."""
    profile = inspect_device_write_readiness(
        mount_path,
        reported_volume_format=reported_volume_format,
    )
    current_key = volume_lock_key(profile)
    if expected_volume_identity_key and current_key != expected_volume_identity_key:
        raise DeviceWriteSafetyError(
            "A different volume is mounted at the selected iPod path. "
            "iOpenPod stopped before writing device metadata."
        )

    with DeviceWriteGuard(mount_path, volume_key=current_key):
        profile = revalidate_device_write_readiness(
            profile,
            probe_case_sensitivity=True,
        )
        yield DeviceMetadataWriteSession(
            mount_path=Path(os.path.realpath(mount_path)),
            filesystem_profile=profile,
        )
