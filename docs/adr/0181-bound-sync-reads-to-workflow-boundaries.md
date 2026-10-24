# ADR-0181: Bound Sync reads to workflow boundaries

- Status: Accepted
- Date: 2026-10-24
- Amends: ADR-0129 and ADR-0167
- Extends: ADR-0180

## Context

The cleanup investigation prompted an audit of the rest of Sync. The Host recovery
implementation repeated source verification both before and after its prepared
callback. It also hashed originals immediately before a copy that independently
hashes and validates them. Podcast preparation validated the Library transaction
before appending Podcast state, then validated the entire combined transaction.
Retained Podcast artwork extraction hashed the device file before and after a
copy that already computes a source fingerprint.

Timestamp-preserving publication performed two extra content reads around a
metadata-only change. Ordinary Sync additions do not request preserved timestamps;
this extra cost primarily affected retagging and Host recovery restoration.

## Decision

Host transaction execution validates plan shape and capacity first, then captures
each original to the Host. The copy's complete source fingerprint must equal the
reviewed fingerprint, including file identity and modification time, rather than
only matching content. This replaces the separate initial device hash. Explicit
`validate_transaction` calls still check all device preconditions.

After staging copies and reporting PREPARED, execution runs the final preparation
callback. It then verifies Host recovery copies, incoming Host content, and the
complete device precondition set once before entering PUBLISHING. PREPARED remains
nonterminal: its journal does not authorize cleanup or imply that the final
publication checks have passed. No reviewed target is removed or overwritten
before those checks succeed. Each destructive deletion still checks its immediate
target; a long batch cannot reuse an earlier observation as deletion authority.

When a Host transaction specifies a modification time, Storage sets it on the
private staged file. The existing post-publication content read verifies both the
bytes and actual filesystem timestamp. The complete transaction's final content,
dependency, and timestamp checks remain required before commit. Public timestamp
mutation retains its independent content-precondition contract.

Library transaction composition does not perform an early validation itself. The
coordinator appends optional Podcast state before validating the complete plan
once. A review with no transaction still validates the captured resources.

Retained Podcast cover extraction receives the fingerprint computed during its
single device-to-Host copy. The extracted cover keeps that content as an explicit
Library dependency, rechecked during review and publication. Changes during capture
or later before publication are still rejected at those boundaries.

## Measured read budgets

These are full content passes, independent of OS caching and USB throughput. The
Storage rows cover execution after review; they exclude earlier Library capture
and review. The original-copy row includes the copy itself. Confirmed cleanup adds
no media reads after ADR-0180.

| Operation | Before | After |
| --- | ---: | ---: |
| Each original replaced or removed, including capture | 5 | 3 |
| Each unchanged transaction dependency during execution | 4 | 2 |
| Each incoming Host source verified before device copying | 2 | 1 |
| Each Host recovery copy verified before publication | 2 | 1 |
| Published file with an explicit preserved timestamp | 4 | 2 |
| Ordinary published Sync file without a timestamp override | 2 | 2 |
| Retained Podcast cover extraction from device media | 3 | 1 |
| Source database preparation when Podcast state is appended | 3 | 2 |

## Other audited stages

- Host and iPod Media Scans reuse their existing caches. Missing or stale acoustic
  evidence still requires decoding; cached entries do not need another full decode.
- Sync source checks use file metadata for selected changes and explicit matching
  associations. They do not hash unchanged media across the whole Library.
- Genius reuses cached audio profiles. Retained device sources use file identities
  for validation. Incoming Host sources are checked against their captured content
  before analysis/cache lookup; this is a separate consumer of that source.
- Library preparation already reuses fingerprints from retained-media capture.
  Its review validation and later publication validation span separate workflows.
- Sync Details publication uses committed file metadata and prepared matching
  evidence. It does not reread media for acoustic fingerprints or full hashes.
- Independent recovery inspection and restoration retain their complete checks.
  An interrupted transaction cannot reuse successful-commit evidence it never had.

## Consequences and validation

The remaining original reads provide capture evidence, validate the complete plan
before publication, and protect each immediate deletion. The remaining output reads
verify an individual write and then the complete result after the rest of the batch.
They detect edits that retain size and modification time. These checks, file and
Volume flushing, journals, connection invalidation, capacity limits, and recovery
copies remain part of the safety contract.

Regression tests count full reads and Host verification passes, including requested
timestamps and combined Podcast plans. Mutation tests cover changed source identity,
changed inputs/dependencies/recovery copies at PREPARED, and later edits before
commit. Existing disconnect and restoration tests exercise the changed publication
path. Tests use virtual Volumes; no new physical-device timing claim is made.
