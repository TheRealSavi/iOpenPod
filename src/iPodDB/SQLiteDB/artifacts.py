"""Dependency-neutral contracts for one late-iPod SQLite artifact set."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SQLiteDatabaseSet:
    """One coherent set of firmware-facing SQLite database bytes."""

    library: bytes
    locations: bytes
    dynamic: bytes
    extras: bytes
    genius: bytes
    locations_cbk: bytes

    def artifacts(self) -> tuple[tuple[str, bytes], ...]:
        """Return artifact names and bytes without assuming a device path."""

        return (
            ("Library.itdb", self.library),
            ("Locations.itdb", self.locations),
            ("Dynamic.itdb", self.dynamic),
            ("Extras.itdb", self.extras),
            ("Genius.itdb", self.genius),
            ("Locations.itdb.cbk", self.locations_cbk),
        )
