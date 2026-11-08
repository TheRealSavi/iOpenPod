# ADR-0240: Treat calendar dates as best-effort metadata

- Status: Accepted
- Date: 2026-11-05
- Supersedes: ADR-0098, ADR-0100 and ADR-0196 date rejection and timezone preconditions
- Retains: lossless native preservation, ADR-0150 Finder sentinel, Storage safety

## Context

Issue [312](https://github.com/TheRealSavi/iOpenPod/issues/312) exposes a selection
failure when a Play Counts date lies in a repeated or skipped local hour. The
same failure in Distrobox is independent of the reported Flatpak storage-access
failure. A valid playback counter must not become unusable because its date cannot
identify one exact UTC instant. The product policy explicitly prefers approximate
dates to blocked loading, editing, saving or Sync.

The [firmware inspection](../research/nonblocking-ipod-dates-2026-11-05.md) confirms
that Classic 120GB 2.0.1 copies raw playback date words, including backward and zero
values. Its adjusted calendar, current bias and annual DST rules cannot recover
historical timezone choices or distinguish the occurrences of a repeated hour.
Modern IANA rules remain a useful Host estimate, not proof of device chronology.

## Decision

Calendar metadata is best effort throughout the Library workflow. Date ambiguity,
unknown timezone evidence, unsupported calendar ranges and malformed optional date
values produce an estimate, a missing date or a retained prior value. They must
not produce a blocking issue. Ordinary input syntax validation remains appropriate;
this policy does not relax identities, counters, binary framing, media positions,
filesystem safety or cryptographic/security checks.

Use recognized city rules first, a valid captured fixed offset second, and UTC
when neither is usable. Never consult the Host timezone or current date to decode
native dates. In a repeated hour, prefer the occurrence matching the retained
database header offset; otherwise use the earlier UTC occurrence. For a skipped
hour, use the pre-transition offset. Report approximation as a warning. Do not
add saved DST or clock bias again and do not rewrite the header offset to endorse
the interpretation.

Preserve unchanged native date words. Carry binary Play Counts played/skipped
words separately from their semantic projection through resolution, writing and
verification. This includes explicit zero and nonzero words that project to Unix
zero; optional absence and the exact Finder sentinel still mean no date update.
An explicit subsequent semantic edit wins over captured playback data. Archive
the original consumed sidecar verbatim through the normal Storage transaction.
For plist dates, bound integer Mac words and treat non-integers as absent while
retaining valid counters and original document bytes.

Resolve newly authored Track, Photo and supported Smart dates before validation
and verification. Bound native dates to the unsigned 32-bit range, reserving zero
for missing values except absolute Smart operands. Bound relative Smart periods
to their supported positive range; order range endpoints in native calendar order.
Retain the prior value when a Track layout cannot store a date. A Prepared Library
describes these resolved values, so verification proves the chosen representation
rather than rejecting the original unrepresentable intent. Unsupported untouched
Smart rules retain their bytes and saved membership.

SQLite regeneration uses the same best-effort dates. Preferences remain captured
read-only evidence, but their readability and later fingerprint are not Library
save preconditions. Database, sidecar, resource and device-session preconditions
remain enforced. Explicit Preferences editing remains a separate workflow;
ADR-0248 subsequently qualifies its source-checked publication.

Podcast models accept signed Unix dates; malformed persisted optional dates become
missing without discarding listening counts. Date display must handle pre-1970
values on Windows and unsupported calendar ranges. Scrobble queue date defects
must not block Sync: preserve identities, capture cursors and integer date
evidence, use missing values for malformed dates, and defer delivery when the
Host calendar or service date limits do not permit it. Existing Last.fm date
adjustment remains a delivery policy, separate from native playback evidence.

## Consequences and validation

Displayed event times, SQLite dates and Smart membership can be approximate, most
visibly within DST transitions. This is an explicit availability tradeoff. Native
binary playback dates retain exact evidence even when their displayed instant
cannot be exact. A date cannot be used as proof of chronological event order.

Regressions cover virtual selection/archive/reselection at folds and gaps,
zero/count-independent dates, semantic-zero collisions, exact raw preservation,
unknown or changing Preferences, SQLite regeneration, extreme Track/Photo/Smart
dates, missing layout fields, Podcast history and portable date display. Firmware
verification is static instruction checking plus reconstructed arithmetic; it is
not execution on ARM or physical-device acceptance across all iPod generations.

## Clarification: qualified named Nano clock evidence, 2026-11-07

The same optional clock-evidence policy now includes `DateTime.TimeZone` from
`iPod_Control/Device/iPodSettings.xml` for exact latest Nano 5/6/7 and updater-39
refresh targets. Capture the bounded, verified source before Library projection.
iPodDB interprets the named setting into typed evidence; the Application Layer
resolves an audited geographical IANA key with Whenever and retains it in the
existing Device Time Context. This extends the existing boundary and precedence,
without introducing a clock writer or reproducing the firmware's DST evaluator.

Nano 5's geographical mapping is explicit Host policy. Nano 6/7 use their exact
packaged timezone record names only where the audit supports the mapping.
Contradictory, unsupported, missing, malformed or duplicate evidence falls back
to the retained database header offset, then UTC. A packaged base offset is not
a captured effective offset, and saved bias/DST is never added again. Qualified
Mini effective offsets and Classic city rules retain their existing policies;
Video and Nano 1/3/4 gain no inferred clock source. Binary Preferences requesting
a reset withhold their saved clock evidence because firmware discards that state.

Reads and explicit new date writes share the captured context for that Library
source; unchanged native words retain their bytes. The XML capture fingerprint
verifies the observation but is not a later Library write precondition. Explicit
Preferences publication remains a separate, source-checked workflow (ADR-0248),
and neither it nor a later external settings change reinterprets a loaded Library.
Saved city state and Host historical rules remain estimates of the Firmware
Calendar, not proof of live adoption, Raw Hardware Clock origin or past location.
