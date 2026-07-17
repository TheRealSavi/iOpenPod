"""Initialize the on-disk database layout for an identified iPod."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from .capabilities import capabilities_for_family_gen
from .checksum import ChecksumType
from .durability import flush_filesystem
from .info import (
    DeviceInfo,
    get_current_device,
    get_firewire_id,
    require_exact_model_number,
    resolve_itdb_path,
    set_current_device,
)
from .path_safety import UnsafeDevicePathError, resolve_device_path
from .write_guard import DeviceWriteGuard, DeviceWriteSafetyError
from .write_readiness import (
    inspect_device_write_readiness,
    revalidate_device_write_readiness,
    volume_lock_key,
)


def ensure_device_itunes_database(
    ipod_path: str | os.PathLike[str],
    device_info: DeviceInfo,
) -> str | None:
    """Create an empty database for an identified device when it is safe.

    Returns the existing or newly created iTunesDB/iTunesCDB path.  Returns
    ``None`` when the selected device lacks the checksum material required to
    create a database its firmware can accept.
    """

    root = Path(ipod_path).expanduser().resolve()
    require_exact_model_number(device_info)
    _require_verified_ipod_root(root, device_info)
    existing = resolve_itdb_path(str(root))
    if existing:
        return existing

    capabilities = capabilities_for_family_gen(
        device_info.model_family,
        device_info.generation,
        capacity=device_info.capacity,
        model_number=device_info.model_number,
    )
    if capabilities is None:
        return None

    filesystem_profile = inspect_device_write_readiness(
        root,
        reported_volume_format=device_info.reported_volume_format,
    )
    with DeviceWriteGuard(
        root,
        volume_key=volume_lock_key(filesystem_profile),
    ) as write_guard:
        filesystem_profile = revalidate_device_write_readiness(
            filesystem_profile,
            probe_case_sensitivity=True,
        )

        def revalidate_volume() -> None:
            nonlocal filesystem_profile
            filesystem_profile = revalidate_device_write_readiness(
                filesystem_profile,
                probe_case_sensitivity=False,
            )

        # Another guarded caller may have initialized the database while this
        # process waited for the host-side writer lock.
        existing = resolve_itdb_path(str(root))
        if existing:
            return existing

        if not _has_checksum_material(root, device_info, capabilities.checksum):
            return None

        previous_device = get_current_device()
        set_current_device(device_info)
        try:
            _seed_ipod_layout(
                root,
                uses_sqlite_db=capabilities.uses_sqlite_db,
                before_device_mutation=revalidate_volume,
            )

            from iopenpod.itunesdb_writer import write_itunesdb

            ok = write_itunesdb(
                str(root),
                [],
                backup=False,
                pc_file_paths=None,
                capabilities=capabilities,
                master_playlist_name=(
                    device_info.ipod_name or device_info.mount_name or "iPod"
                ),
                before_database_replace=write_guard.assert_database_unchanged,
                before_device_mutation=revalidate_volume,
            )
        finally:
            set_current_device(previous_device)

        if not ok:
            raise RuntimeError("Failed to create an empty iTunesDB for the selected iPod")
        write_guard.refresh_database_generation()
        revalidate_volume()
        flush_ok, flush_message = flush_filesystem(root)
        if not flush_ok:
            raise RuntimeError(
                "Created the empty iTunesDB, but its durability barrier failed: "
                f"{flush_message}"
            )
        return resolve_itdb_path(str(root))


def _require_verified_ipod_root(root: Path, device_info: DeviceInfo) -> None:
    """Reject a stale, mismatched, or unrecognized selection without writing."""
    if not root.is_dir():
        raise DeviceWriteSafetyError(
            f"The selected iPod root is not an accessible directory: {root}"
        )

    identified_path = str(device_info.path or "").strip()
    if not identified_path:
        raise DeviceWriteSafetyError(
            "The identified iPod does not include a verified mount path. "
            "iOpenPod stopped before creating device files."
        )
    identified_root = Path(identified_path).expanduser().resolve()
    if os.path.normcase(str(identified_root)) != os.path.normcase(str(root)):
        raise DeviceWriteSafetyError(
            "The selected iPod path does not match the device that was identified. "
            f"Selected path: {root}; identified path: {identified_root}."
        )

    ipod_control = root / "iPod_Control"
    if not ipod_control.is_dir():
        raise DeviceWriteSafetyError(
            "The selected volume is not a verified iPod root: iPod_Control is "
            "missing. iOpenPod stopped before creating device files."
        )
    try:
        resolve_device_path(
            root,
            "iPod_Control",
            allowed_subtree="iPod_Control",
        )
    except UnsafeDevicePathError as exc:
        raise DeviceWriteSafetyError(
            "The selected iPod_Control directory resolves outside the iPod root. "
            "iOpenPod stopped before creating device files."
        ) from exc


def _has_checksum_material(
    root: Path,
    device_info: DeviceInfo,
    checksum: ChecksumType,
) -> bool:
    if checksum == ChecksumType.NONE:
        return True
    if checksum in (ChecksumType.HASH58, ChecksumType.HASHAB):
        try:
            firewire_id = get_firewire_id(
                str(root),
                known_guid=device_info.firewire_guid,
            )
        except RuntimeError:
            return False
        return 8 <= len(firewire_id) <= 20
    if checksum == ChecksumType.HASH72:
        if (
            len(device_info.hash_info_iv) == 16
            and len(device_info.hash_info_rndpart) == 12
        ):
            return True
        hash_info_path = root / "iPod_Control" / "Device" / "HashInfo"
        try:
            hash_info = hash_info_path.read_bytes()
        except OSError:
            return False
        return len(hash_info) == 54 and hash_info.startswith(b"HASHv0")
    return False


def _seed_ipod_layout(
    root: Path,
    *,
    uses_sqlite_db: bool,
    before_device_mutation: Callable[[], None] | None = None,
) -> None:
    for folder in ("Device", "iTunes", "Music", "Artwork"):
        if before_device_mutation is not None:
            before_device_mutation()
        (root / "iPod_Control" / folder).mkdir(parents=True, exist_ok=True)
    if uses_sqlite_db:
        if before_device_mutation is not None:
            before_device_mutation()
        (root / "iPod_Control" / "iTunes" / "iTunes Library.itlp").mkdir(
            parents=True,
            exist_ok=True,
        )
