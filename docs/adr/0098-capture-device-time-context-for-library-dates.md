# ADR-0098: Capture Device Time Context for Library dates

- Status: Accepted
- Date: 2026-09-30
- Extends: ADR-0019, ADR-0022, ADR-0057, ADR-0097

Library dates are Unix instants. The Application Layer captures firmware
Preferences through Storage and resolves geographical timezone rules before
publishing a Library. iPodDB retains this immutable Device Time Context for
projection, validation, reconciliation, verification, and subsequent source
adoption. It receives timezone rules as data; it does not read Preferences files,
load timezone databases, or consult the Host clock or local timezone.

Paired nano 5 and nano 7 CDB/SQLite captures establish historical local Mac time
for modified, added, played, and skipped dates, but UTC Mac time for released and
purchased dates. SQLite uses UTC seconds since 2001. This overrides the earlier
blanket database-header-offset assumption and rejects libgpod's current-offset
approximation and extra SQLite header subtraction. See the
[evidence and limits](../research/ipod-time-reconciliation.md).

Known city Preferences supply historical IANA rules. Older offset Preferences
supply their effective fixed offset, already including encoded DST. Unknown or
unreadable Preferences can use a valid database header offset only as a diagnosed
fallback; no Host timezone or invented UTC fallback is permitted. A header offset
does not establish historical DST. The header remains unchanged even when it
differs from Preferences. The nano 3 manual DST byte remains separate because its
interaction with city rules is unverified.

Mac zero means missing. Representable pre-1970 instants remain valid. A DST gap or
fold has no unique local-to-Unix interpretation: its semantic date is unavailable,
a diagnostic is published, and unchanged native bytes remain intact. New dates
that lose fold identity are rejected. Absolute Smart Playlist conditions can name
Unix zero as an actual instant; relative conditions remain durations. SQLite
regeneration is blocked if retained Track dates cannot be resolved, rather than
replacing them with missing dates. The existing zero sentinel also cannot
distinguish an ordinary missing date from exactly the Unix epoch.

Photo dates use the same local Mac conversion. Every retained date is changed only
on explicit semantic change, including when a sibling field changes. This fixes
the earlier raw-Mac-as-Unix Photo projection. Historical Photo and Smart Playlist
interpretation follows the local-date policy, with less direct capture evidence
than the Track fields.

The captured Preferences fingerprint, or verified absence, becomes a Storage
Transaction dependency. Changes, deletion, or appearance invalidate a save. An
unverifiable observation permits browsing but blocks publication. Saving adopts
the same Device Time Context; switching devices creates a new context. None of
this edits Preferences, migrates old timestamps after a timezone change, or sets
the physical device clock.
