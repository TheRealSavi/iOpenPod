# ADR-0166: Stage Library media replacements one at a time

- Status: Accepted
- Date: 2026-10-21
- Amends: ADR-0029 and ADR-0030

ADR-0167 supersedes this policy for application Library transactions with persistent
Host recovery. The device-retained policy remains available to other callers.

## Evidence

After the Podcast album correction in ADR-0165, Normalize Tags passed database
preparation and verification on the Nano 5 but failed transaction capacity
validation. Rockbox Metadata Support correctly requested 71 retained media-file
rewrites alongside the database changes. The ordinary transaction required
6,112,264,192 bytes with only 4,453,285,888 bytes available: every replacement was
staged while copies of all replaced originals were retained on the device.
Unchanged dependencies and stale recovery files were not the cause.

Stock firmware and Rockbox must both remain supported. Disabling file tagging or
removing recovery protection is not a solution.

## Decision

Storage Transactions gain an explicit `stage_one_at_a_time` policy. Library saves
use it when their captured resources contain media writes. Other ordinary
transactions retain their established staging policy; external recovery continues
to use its existing bounded publication path.

Before publication, Storage copies and verifies every replaced original into the
device's recovery namespace, verifies every replacement source, and rechecks all
destinations and dependencies. The application retains its private Host outputs
for the lifetime of the issued review and save. Each replacement is then staged,
hash-verified, and atomically published in order. No more than one replacement
stage is retained on the device at a time. Removals still follow verified writes.

Capacity validation reserves the originals, the peak stage plus accumulated size
growth, a restoration copy, journal replacements, and any caller reserve. It does
not assume that later removals free space. The same allocation calculation governs
review and execution; per-file writes continue to recheck actual free space.

Every original remains on the device until verified terminal cleanup. Recovery
uses the existing identity-bound Operation Journal and needs neither Host staging
files nor a Backup Snapshot. No journal-format change is needed. Cancellation
remains available before publication. If a later source changes or becomes
unreadable after publication starts, the operation stops with complete recovery
material rather than publishing unverified bytes. Disconnect, concurrent-edit,
restoration, durability-warning, and cleanup rules remain unchanged.

## Validation

A small replacement batch reproduces the former capacity rejection. Its regression
test simulates shrinking free space throughout execution and restores every original
within the lower limit. Fault tests change a later Host source before and during
publication and disconnect after every native rename. Application tests normalize
and save with Rockbox support both enabled and disabled.

A complete application save on a private Host copy of the Nano succeeds with its
original 4,453,285,888-byte free-space limit, all 98 suggested tag changes, 71 media
rewrites, and the signed database artifacts. Required space is 3,502,415,872 bytes.
This exercises publication, verification, cleanup, and reload on the Host copy;
it does not establish physical-device durability or firmware acceptance.
