# ADR-0208: Synchronize Jellyfin play counts through an iPod memory

- Status: Proposed
- Date: 2026-10-29
- Extends: ADR-0101, ADR-0184

Users who also listen through a Jellyfin server want one play count per song on
both sides. Jellyfin and the iPod expose only cumulative totals, so an additive
merge needs a remembered baseline. A Host-side baseline breaks when several
computers sync one iPod: each Host would add plays another Host already merged.
Volume Identity is also not stable across operating systems or Windows reconnects.

iOpenPod therefore keeps a **Play Count Memory** on the iPod it describes, at
`iPod_Control/iOpenPod/Integrations/jellyfin-play-counts-v1.json`. It is keyed by
Jellyfin server and user, then by persistent iPod Track ID, and records the
agreed total and the count last confirmed on each side. A song's merged total is
the agreed total plus new plays on each side. The first pairing keeps the larger
count, and decreases are not propagated. Matching uses normalized title, album,
artist, track and disc numbers, and length; ambiguous or missing matches are
reported rather than guessed.

The iPod changes only through the existing Library preparation and verified save
under an exclusive device reservation. `DeviceCoordinator.prepare_library` accepts
`application_writes`, which join the Library's single Storage transaction, so play
counts and the memory publish or roll back together. Standalone
`load_application_document` and `save_application_document` read and atomically
replace one bounded document by revision. Both paths accept only documents under
the reserved `iPod_Control/iOpenPod/Integrations` folder, so integrations cannot
replace documents other workflows own.

The memory is written with final values before Jellyfin is updated. Jellyfin
updates that fail are rewritten with Jellyfin's previous count and retried.
Interruptions can miss a play but never count one twice. An unreadable memory
stops the sync before any change and is preserved. Backup Snapshots include the
memory, so restores roll it back with the play counts.

Jellyfin access requires version 10.9 or later and uses only the
`Authorization: MediaBrowser` scheme that Jellyfin 12 accepts by default. The
password is exchanged once for an access token kept in the native OS keyring,
as scrobbling credentials are under ADR-0101. Settings keep only the server
address, username, and a device ID.

Regression tests cover additive merges, a second Host continuing from the iPod
memory, retried Jellyfin updates, failed saves that write neither file, refused
paths outside the reserved folder, and restore of new and replaced documents.
