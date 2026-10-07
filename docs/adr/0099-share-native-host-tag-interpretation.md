# ADR-0099: Share native Host tag interpretation

- Status: Accepted
- Date: 2026-09-30
- Extends: ADR-0031, ADR-0063, ADR-0075, ADR-0084
- Amended by: ADR-0123 for seekable scan metadata probes without private captures

Host Media Scan retained a small metadata subset, while music import and Sync
interpreted different names. ID3 PCST was read as text instead of an integer, and
non-ID3/MP4 lyrics were lost. Correct parsing alone was insufficient: the Host
snapshot and cache also needed to retain the fields.

Use one Application Layer adapter for native decoding and common Track projection.
It normalizes recognized tags into immutable `MediaTag` values, handles native
value semantics, and exposes no filesystem operations. Tags and artwork share one
Mutagen parse. Cache v9 retains normalized values in its strict, checksummed
envelope and invalidates older interpretations.

When native reading yields neither useful tags nor timing for video, reuse bounded
FFprobe inspection over a Storage capture. Unsupported containers incur a temporary-file
cost; readable native tags need no additional tool. Failure retains basic facts
and a diagnostic. Unreadable audio retains its existing basic-facts fallback;
scanning does not start a second decoder for malformed audio. Classification
remains separate from codec compatibility.

Music import prefers native fields over FFprobe fallbacks; Sync enrichment retains
reviewed values. Descriptive tags do not invent listening history or codec timing.
Lyrics remain unsynchronized text under the existing verified publication contract.

The [coverage contract](../host-media-tags.md) records mappings, precedence, date
precision, scalar limits, and regression evidence. New semantic fields still need
an explicit common Library design rather than an untyped extras bag.
