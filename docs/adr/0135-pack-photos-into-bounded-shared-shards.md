# ADR-0135: Pack Photos into bounded shared shards

- Status: Accepted
- Date: 2026-10-08
- Amends: ADR-0076's fresh Photo thumbnail shard policy
- Extends: ADR-0053, ADR-0059, ADR-0117, ADR-0129

## Context

Photo Sync assigned a fresh iTHMB filename to every Photo and format. This caused
file counts to grow with the number of Photos even though PhotosDB already
identifies each representation by a filename, byte offset, and size. Primary
implementations pack many Photo representations into each format's files.
The [research](../research/photo-sharding-2026-10-08.md) supports decimal
256,000,000 bytes as a historical compatibility default, without establishing a
universal firmware maximum.

ADR-0076 avoided rewriting retained Photo thumbnail files to reduce USB traffic
and preserve existing data. Packing within one batch fixes only part of the
problem: successive small Syncs would still create a new file for each format.
Extending a verified shard reduces that growth while preserving recoverability.

## Decision

Prepared Photo thumbnails share bounded iTHMB shards per format, within a Sync and
across successive Syncs. Before appending a complete allocation, its resulting
file size must fit the configured compatibility bound, defaulting to 256,000,000
bytes, and applicable filesystem limits. A format rolls to another shard when its
next allocation would exceed the bound. Formats allocate independently. A
representation is never split between files; full-resolution originals remain
standalone, verified image files.

An existing shard may be extended only when its entire prefix is captured and
fingerprinted, its retained references and allocations are understood and bounded,
and the unchanged prefix is verified in the candidate output. Append after its
captured length. Preserve all existing bytes, including unreferenced ranges,
allocation padding, auxiliary raster data, and Unknown Data. Retained MHNI offsets
and size fields remain unchanged. Do not infer the append point from the last
semantic representation or rewrite a legacy zero secondary size.

Missing, damaged, unreadable, or uncertain files and their recorded names remain
reserved. Names observed on the device, including case-insensitive collisions,
cannot be silently reused. When an existing shard is ineligible, allocate fresh
output for the valid incoming Photos. An existing file exceeding the default is
ineligible for extension; the bound alone does not make its retained contents
corrupt. This decision does not authorize compaction, filling old holes, truncating
unreferenced tails, or rebuilding unrelated Photos.

The Application Layer owns shard allocation and packing policy. It captures
resources through Storage, supplies their evidence, and reconciles only
successfully prepared Photos. iPodDB owns the binary representation and verifies
formats, bounded ranges, and supplied resource evidence. Storage owns device
capture, staging, and publication. Shared outputs are published once per path, with
consistent whole-file evidence; conflicting duplicates fail validation. Thumbnail
representations validate their own ranges against that evidence. Original images
retain whole-file requirements. Host preparation remains bounded and can use the
private spill storage established by ADR-0117.

Extending a shard is implemented as a staged complete replacement, not an in-place
device append. Storage verifies the captured original fingerprint, stages and
verifies the candidate, and publishes it before PhotosDB references are committed.
The existing Storage Transaction retains originals and can restore both the shard
and PhotosDB after interruption. Concurrent changes invalidate publication.

Photo IDs, Photo Album membership, dates, ratings, and untouched database bytes
remain retained. MHIF continues to declare one format's frame size rather than
the size or number of its shard files. MHII child counts describe representation
children, including an optional original-image container. Shared files remain
while any surviving Photo references them; supported cleanup may reclaim a wholly
unreferenced file only with the required captured evidence. Unverifiable obsolete
files are preserved rather than preventing publication of valid replacements.

## Consequences

Normal additions fill each format's available shard capacity, avoiding per-Photo
file proliferation. Extending an old shard costs a read and a staged rewrite of
its retained prefix; that cost buys verified reuse and transactional rollback.
Uncertain shards may cause fresh-file allocation, and unused old ranges continue
to consume space until a separately designed compaction workflow exists.

Tests must cover both batch packing and later Sync append, capacity boundaries,
raw allocation preservation, multiple owners, unavailable files, filename
collisions, stale-prefix rejection, and restoration. The compatibility bound is a
writer policy, not a reason to reject an otherwise bounded retained database.
