# ADR-0115: Treat SysInfo files as optional metadata

- Status: Accepted
- Date: 2026-10-05
- Extends: ADR-0010, ADR-0013, ADR-0100
- Supersedes: ADR-0061's requirement for device-supplied SQLite postprocessing

SysInfo and SysInfoExtended can be absent, empty, or incomplete on real iPods.
Requiring Nano 5 postprocess commands from SysInfoExtended prevented Library saves
and, after ADR-0100, prevented selection from committing pending playback history
and On-The-Go Playlists. These files are optional evidence and caches; no workflow
may require them as its sole source of device knowledge.

Device Registry remains the authority for known model capabilities. The built-in
SQLite projection supplies the Library Artifact Set without device commands on
every supported SQLite profile, including Nano 5. The registry no longer models a
requirement for external postprocess commands. Original iOpenPod's SQLite writer
also builds its databases without that command source; it is a behavioral reference,
not proof of physical Nano 5 firmware acceptance.

Usable SysInfoExtended commands remain optional supplements, executed against the
isolated in-memory database group. Missing, empty, unrelated, or malformed command
metadata uses the built-in projection; malformed declarations produce a log warning.
Only metadata actually used to select commands becomes a reviewed file dependency.
Once selected, failing SQL or failed output validation still blocks publication;
the application does not silently retry a partially transformed database. Changed
or removed command input invalidates its reviewed output.

Signing uses the current Connection Generation's hardware Device Evidence directly,
with SysInfo and SysInfoExtended as alternate metadata sources when hardware lacks
a transport identifier. Equally authoritative conflicting GUIDs are not guessed.
The same identity is checked again before publication. An actual signing identity
and valid device-bound HashInfo material remain required where the checksum needs
them; optional metadata does not authorize invented identity or unsigned output.

Selection-time reconciliation, complete artifact publication, sidecar archiving,
verification, and recoverable Storage Transactions retain their existing contracts.
Regression tests cover absent and empty files, unusable command declarations,
hardware-backed signing, metadata-only signing, conflicting or unavailable identity,
and exactly-once playback and On-The-Go Playlist consumption on virtual Nano 5s.
Physical firmware validation remains separate.
