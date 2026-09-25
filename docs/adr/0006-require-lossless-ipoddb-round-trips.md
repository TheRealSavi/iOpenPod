# ADR-0006: Require lossless iPodDB round trips

- Status: Accepted
- Date: 2026-08-20

## Context

Real iPod databases contain fields, Chunks, flags, padding, ordering, and
version-specific data that iOpenPod may not fully understand. Treating unknown bytes
as disposable would allow a harmless read and write to damage information or device
behavior.

iPodDB must also remain independent from device persistence so its format behavior
can be tested with captured database fixtures.

## Decision

- iPodDB accepts bytes or generic binary streams and returns structured database data
  or serialized bytes.
- iPodDB does not import or use Storage and does not import iOpenPod. iOpenPod decides
  when to read or persist database bytes through Storage.
- Parsing and serializing a database without application edits must reproduce the
  original bytes exactly.
- Lossless reproduction includes Unknown Data such as unknown fields, unknown Chunks,
  flags, record ordering, padding, and other retained bytes.
- Encountering Unknown Data is normal and does not by itself make a database invalid.
- Structurally malformed or truncated data remains distinct from Unknown Data and may
  produce a typed parse error.
- iPodDB must not normalize, clean up, reorder, or replace retained data merely as a
  side effect of reading and writing it.

## Consequences

- Parsed representations must retain enough original encoding information for exact
  serialization; understood semantic values alone are insufficient.
- Writers and parsers share one lossless format contract rather than evolving as
  unrelated implementations.
- Golden fixtures must verify complete byte equality for unchanged round trips,
  including databases with Unknown Data.
- Convenience transformations that discard original representation cannot be the
  default iPodDB path.
