"""Filesystem-specific label constraints, independent of application naming policy."""

import unicodedata

from storage.errors import UnsupportedStorageOperationError


def volume_label(name: str, filesystem: str) -> str:
    """Return a nonempty representable label without changing the caller's name."""
    filesystem = filesystem.casefold()
    name = "".join(" " if ord(c) < 32 else c for c in name).strip()
    if not name:
        raise ValueError("A Volume label must not be empty")
    if filesystem in {"fat", "fat16", "fat32", "vfat", "msdos", "msdosfs"}:
        # Use the portable ASCII subset of the Host-dependent OEM character set.
        value = (
            unicodedata.normalize("NFKD", name)
            .encode("ascii", "ignore")
            .decode()
            .upper()
        )
        value = "".join(c for c in value if c not in '*?/\\|.,;:+=<>[]"')
        return value.strip()[:11].rstrip() or "VOLUME"
    if filesystem in {"hfs", "hfs+", "hfsplus", "apfs", "virtual"}:
        limit, encoding = 255, "utf-16-le"
        name = name.replace(":", "-").replace("/", "-")
    elif filesystem in {"exfat", "ntfs"}:
        limit, encoding = (15 if filesystem == "exfat" else 32), "utf-16-le"
        name = "".join(c for c in name if c not in '*?/\\|.,;:+=<>[]"')
    elif filesystem in {"ext2", "ext3", "ext4"}:
        limit, encoding = 16, "utf-8"
    else:
        raise UnsupportedStorageOperationError(
            f"Volume labels are not supported for {filesystem}"
        )
    byte_limit = limit * (2 if encoding == "utf-16-le" else 1)
    return (
        name.encode(encoding)[:byte_limit].decode(encoding, errors="ignore").rstrip()
        or "Volume"
    )
