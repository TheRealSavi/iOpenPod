# ADR-0119: Compare Track tags and artwork before Sync Update

- Status: Accepted
- Date: 2026-10-05
- Extends: ADR-0065, ADR-0066, and ADR-0076

## Context

ADR-0066 planned an Update whenever a previously synced Host file's size or
modification time changed. A tag-only edit needed an Update, but a file change with
the same Library tags and cover also replaced an iPod Track unnecessarily. A
folder-level cover can change without changing the media file's facts at all.

## Decision

For a correlated Track with proven Sync Details, compare current Host size and
modification time with the facts from the last successful Sync. The Host Media Scan
reuses cached tags when those file facts match. Library Sync Helper v4 also records
a fingerprint of the resulting iPod Track's semantic tags after a verified Sync.
If current iPod details differ from that baseline while Host file facts match,
reread the Host Track before finalizing the Sync Plan and propose an Update.
Comparing against the committed iPod baseline avoids repeat Updates for fields
that Sync intentionally normalizes for the device. Older helpers without this
baseline retain the prior Host-fact gate, except migrated v3 records explicitly
marked as awaiting their first v4 baseline; those records compare current Host
and iPod tags conservatively. If Host file facts changed, compare scanned Host
tags with current iPod tags as before. ADR-0120 extends this decision with Acoustic
Fingerprint comparison and separate Host/iPod tag baselines: matching tags and artwork
alone cannot prove that a Track is In sync.

Compare artwork independently of the media file's facts so a changed folder cover
can propose an Update. The Host Media Scan supplies the source artwork SHA-256.
Embedded artwork is re-extracted only when its Track file facts change. The Host
Media Scan Cache retains each selected folder cover's path, size, modification
time, and digest independently of Track records. A later scan lists the folder
but reuses that digest without reading image bytes while those file facts match.
If the selected cover changes or its size or modification time differs, the scan
reads and hashes it again, then updates the cached artwork reference without
rereading unchanged Track tags. A same-size, same-mtime edit is deliberately
outside this check.
Host Media Scan Cache v9 remains readable. During the next scan, folder-cover
references embedded in v9 Track records are recovered into the independent
folder-artwork catalog, unchanged media and covers are reused, and the normal
cache write upgrades the document to v10. A v9 folder whose cover was never
represented because every Track used embedded artwork may be read once to seed
the new independent catalog.
Library Sync Helper v4 retains that digest and the committed iPod artwork identity
alongside Sync Details. The plan compares the current Host digest and iPod artwork
link with those recorded after the prior verified Sync. It also detects adding or
removing a cover. Earlier helper versions remain readable; missing artwork
provenance is treated conservatively until a later successful Sync records it.
When an iPod Media Scan reads a v3 helper, it upgrades records in memory without
recapturing unchanged media: existing device size and modification-time checks
still validate reusable records, and cached acoustic and Photo fingerprints are
retained. V3 Sync Details do not contain a committed iPod tag or artwork
baseline, so migration must not stamp the current iTunesDB Track as if it were
the post-Sync value; doing so would hide edits made before migration. Until a
successful Sync records a v4 baseline, the plan conservatively compares the
current Host and iPod semantic Track projections. The first writable helper
publication atomically writes the v4 helper, while read-only scans defer the
rewrite until that publication.
Unique content matches without Sync Details remain In sync without inventing
provenance. Photo Update planning retains its existing file-fact rule.

Selected Track Updates continue through the existing verified media and Library
publication path. The new Host cover replaces the iPod link, and removal of a Host
cover clears that link. If artwork capture fails, the previous iPod cover is
retained and its new Host digest is not recorded as successfully applied.

## Consequences

An iPod Track edit can trigger a targeted Host reread despite unchanged Host file
facts. The Host file is validated against the scanned facts; an unreadable or changed
source stops comparison rather than proposing an Update from stale tags. Artwork
asset bytes changed externally while retaining the same iPod artwork identity are
outside the helper's evidence; a future device-artwork scan would be needed to
detect that case.
