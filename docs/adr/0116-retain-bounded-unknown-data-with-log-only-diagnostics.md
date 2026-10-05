# ADR-0116: Retain bounded Unknown Data with log-only diagnostics

- Status: Accepted
- Date: 2026-10-05

ADR-0006 requires lossless Unknown Data retention. A captured fifth-generation
iTunesDB exposed stricter MHOD parsing that rejected an extra 60 bytes in each
Smart Playlist preferences payload. The same assumption appeared in playlist
positions, chapter atoms, playback sidecars, and compressed database framing.

Unknown Data within validated boundaries must not prevent Library loading or
unrelated edits. Readers retain extra payload bytes, opaque Chunks, and physical
framing extensions; writers carry them forward without interpretation. For a
recognized MHOD whose encoding or layout signature is unsupported, the shared
reader records an explicit opaque payload. The shared writer validates that its
bytes, MHOD type, and parent context are unchanged before emitting it. This
extends ADR-0008's single definition-driven path without a permissive alternate
parser or a blanket exception handler.

Readers report retained extensions through Python logging at WARNING level.
Each complete read emits one bounded summary with the artifact, number and total
size of reported regions, and representative types, offsets, and sizes. Repeated
types do not crowd out other examples. Logs contain no payload dumps or decoded
Library metadata. Unknown Data does not produce a user-facing warning, dialog,
or approval step. Established reserved fields remain retained; these diagnostics
identify opaque payloads and newly encountered extensions, rather than logging
every reserved field on every read.

Structurally truncated records, impossible lengths, inconsistent counts, and
ambiguous sidecar layouts remain errors. Unsupported semantic edits or format
conversions must fail explicitly if they would discard Unknown Data. Unchanged
serialization and unrelated edits remain available. Regression tests must cover
exact round trips and preservation after known-field edits, including sidecar
remapping and physical iTunesCDB framing.
