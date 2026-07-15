"""Initialize the on-disk database layout for an identified iPod."""

from __future__ import annotations

import os
from pathlib import Path

from .capabilities import capabilities_for_family_gen
from .checksum import ChecksumType
from .info import DeviceInfo, get_current_device, get_firewire_id, resolve_itdb_path, set_current_device


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

    previous_device = get_current_device()
    set_current_device(device_info)
    try:
        if not _has_checksum_material(root, device_info, capabilities.checksum):
            return None

        _seed_ipod_layout(root, uses_sqlite_db=capabilities.uses_sqlite_db)

        from iopenpod.itunesdb_writer import write_itunesdb

        ok = write_itunesdb(
            str(root),
            [],
            backup=False,
            pc_file_paths=None,
            capabilities=capabilities,
            master_playlist_name=device_info.ipod_name or device_info.mount_name or "iPod",
        )
    finally:
        set_current_device(previous_device)

    if not ok:
        raise RuntimeError("Failed to create an empty iTunesDB for the selected iPod")
    return resolve_itdb_path(str(root))


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


def _seed_ipod_layout(root: Path, *, uses_sqlite_db: bool) -> None:
    for folder in ("Device", "iTunes", "Music", "Artwork"):
        (root / "iPod_Control" / folder).mkdir(parents=True, exist_ok=True)
    if uses_sqlite_db:
        (root / "iPod_Control" / "iTunes" / "iTunes Library.itlp").mkdir(
            parents=True,
            exist_ok=True,
        )
