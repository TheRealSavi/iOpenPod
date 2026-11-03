# ADR-0231: Avoid Phase captures for content-checked cache hits

- Status: Superseded by [ADR-0232](0232-cache-phase-input-metadata-across-library-saves.md) for unchanged-input verification
- Date: 2026-11-03
- Extends: ADR-0210 and ADR-0227
- Supersedes: ADR-0227's capture and second full preparation hash on chart reuse

Fully cached Phase preparations previously copied every compressed Track to Host
staging and then hashed the device file again, despite doing no decoding or
analysis. The prefetch measurements already recorded this regression. An unchanged
Playlist must avoid those unnecessary copies without treating matching file size
and modification time as proof of unchanged content.

The preparation reader first hashes device audio whose saved provenance matches
the candidate analyzer identity and Track duration. A matching SHA-256 supplies
the input fingerprint without a Host capture. The coordinator still validates the
chart's size, signature and content hash against its provenance. Only when the
chart is reused does preparation replace the second full audio hash with a
lightweight source-identity check. The complete content fingerprint remains a
mandatory dependency of the recoverable Storage Transaction. A later content
change invalidates publication even if file size and modification time agree.

Untracked audio, duration changes and analyzer upgrades retain bounded prefetch.
An audio-content mismatch adds a hash before the existing capture/analysis path.
If audio matches but its chart needs regeneration, direct device analysis retains
the full post-analysis fingerprint check. Incoming prepared Host sources keep
their existing verification. Reader ownership, cancellation, Connection Generation
checks and queue bounds are unchanged. Chart bytes, analysis parameters, cache
format and algorithm identity are unchanged; no dependency or setting is added.

The virtual-device regression failed with two unnecessary Host copies for an
unchanged two-Track Playlist and now passes with zero copies and one audio hash
per Track. Regressions cover changed audio with preserved size/time, changed or
missing charts, changed duration, cancellation, disconnection, and transaction
rejection of later content changes. Three alternating local eight-Track runs
(128 MiB total compressed input) reduce mean preparation time from 0.4441 to
0.1950 seconds, with zero temporary audio writes instead of 128 MiB. The private
harness and results are under `.scratch/phase-cache/`. These warmed synthetic
local-file measurements do not establish physical iPod or cold USB performance.
