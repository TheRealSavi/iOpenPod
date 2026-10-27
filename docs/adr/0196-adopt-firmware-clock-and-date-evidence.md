# ADR-0196: Adopt firmware clock and date evidence

- Status: Accepted
- Date: 2026-10-26
- Amends: ADR-0100/0195 binary Play Counts date merging
- Extends: ADR-0097 qualified Preferences views and ADR-0098 interpretation limits
- Retains: ADR-0150's Finder date sentinel and ADR-0022/0142 Smart preservation

## Context

The [Classic clock investigation](../research/classic201-clock-semantics-2026-10-26.md)
establishes that timezone/DST adjustments shift future playback date words. A later
event can have an earlier calendar date while its counter advances. The firmware's
binary Play Counts reader replaces retained date words; iOpenPod's deliberate
newest-date policy could discard that newer event's clock reading. The same
investigation establishes a full-width Classic city ID and separate Smart date
endpoints that the previous projections could silently truncate.

## Decision

For binary Play Counts, replace a present last-played or last-skipped date with
the supplied date, including an older value or zero. Do not gate dates on count
deltas. Preserve a missing optional last-skipped field separately from a present
zero. Keep ADR-0150's exact raw Finder sentinel as no new date, checked before
timezone conversion. Stats and plist keep their existing newest/nonzero policy;
their contracts are not inferred from this Classic binary reader.

Apply the binary policy without a model gate, as an explicit shared-format
inference consistent with ADR-0195. This is not a cross-model firmware test.
Retain strict Device Time Context conversion: a gap, fold or unresolved zone
rejects the entire playback input, including otherwise valid preceding rows.
Also reject nonzero binary dates that decode to semantic Unix zero. Reject an
explicit zero clear when the retained native date is nonzero but its semantic
projection is zero: the current semantic-only writer cannot express that clear
reliably. These representational collisions preserve the whole input pending a
future explicit native-date write contract, rather than consume evidence without
applying it. Missing fields and the Finder sentinel still preserve retained dates.
Successful publication archives the original sidecar verbatim.

Project a relative Smart date condition into an editable Host duration only when
its upper displacement is zero. A nonzero upper displacement becomes an
Unsupported Smart Rule, preserving native rule data and saved membership during
automatic refresh and unrelated edits. When displacement is zero, the inactive
upper unit does not restrict interpretation. Existing rolling Host evaluation
remains a policy; it is not changed to the firmware's calendar-day window.

Add an observation-only Classic 120GB RetailOS 2.0.1 Preferences profile, requiring
the evidenced 2,956-byte extent and version word `0x3d`. It reads the full u32 city
ID, raw saved DST byte and software clock-bias pair. Automatic application use
also requires exact Classic 6.5th Gen 120GB identity and unconflicted RetailOS
2.0.1 values; a transport revision is insufficient. Other profiles retain their
existing interpretation. Language edits preserve clock fields; changes to city,
DST or bias are rejected because those edits do not implement the firmware's
complete clock-change sequence.

The Host maps known city IDs to historical IANA rules as interpretation policy.
It does not add saved DST or bias to database dates, which already reflect the
adjusted firmware calendar. Neither the epoch constant nor the bias establishes
whether the raw hardware clock is UTC or local. No clock synchronization or
historical timestamp migration follows from this work.

## Consequences and validation

Binary last-played and last-skipped can decrease or clear. This changes the
newest-date exception retained by ADR-0195; it does not reconstruct previously
discarded events. An unknown full city word cannot alias a known low halfword.
Unsupported date ranges remain preserved instead of receiving lossy reevaluation.

Authored tests cover replacement, zero/absence, Finder sentinels, multi-row failure,
semantic-zero collisions, preparation/reload and virtual selection/archive/reselect
idempotence. Smart tests cover endpoint bytes and saved membership. Preferences
tests cover qualification, full-width unknown IDs, read-only clock fields and
lossless language edits. Physical acceptance and other releases remain untested.
