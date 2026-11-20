# ADR-0289: Author Classic Genius Mixes in binary Playlist datasets

- Status: Accepted
- Date: 2026-11-18
- Amends: ADR-0176, ADR-0184, and ADR-0288's SQLite-only Mix authoring limit
- Extends: ADR-0177, ADR-0185, and ADR-0186

## Evidence

Stock Classic 2.0.4 and 2.0.5 importers accept Genius Mix MHYP records whose
distinguished-kind byte at offset `0x52` is 32. They consume the first Playlist
dataset of type 2 or 3. MHIP members refer to native Track IDs; playback obtains
their MHIT Genius IDs and generates a queue using `Extras.itdb`. These are candidate
seeds, not an ordinary fixed Playlist. The menu has twelve Mix slots.

The [firmware investigation](../research/classic-genius-mixes-2026-11-18.md)
records exact images, addresses, native execution receipts, and unresolved limits.
Actual iPodDB-authored records passed both stock importers. This does not certify
physical playback. Stock 2.0.3 capability remains established by the existing
registry policy; its importer has not been executed locally.

## Decision

Keep hardware capabilities and the binary database target unchanged. Enable Mix
management for Classics with confirmed native Genius Playlist and Mix support,
including older hardware running the qualified shared 2.0.5 OS. iOpenPod supplies
an explicit `WriteTarget.classic_genius_mixes` authoring permission. Other binary
targets cannot acquire new Mixes merely because they have an iTunesDB.

iPodDB owns the native reader and reconciler. Centralize the discriminator in the
shared MHYP definition, retaining the upper byte of its historically named
`phase_game_flag`. Keep Mixes outside the ordinary editable Playlist projection.
Read them through the retained `IPodLibrary` source into Genius Browse. Mirror
authored records across existing type-2/3 datasets; later companion creation also
carries retained Mixes. Conflicting copies, identity collisions, and unresolved
members block dependent Mix edits.

Reuse typed Genius graph and selective Mix intent. New Mixes contain a title and
ordered MHIP candidate members, with no single-seed MHOD54. Preserve unmentioned
records and Unknown Data. Track deletion, media replacement, or removal of an
assigned Genius identity prunes affected candidates and removes newly empty Mixes.
Reparse and verify prepared native records before Storage publication.

When explicitly adding a Mix, initialize zero MHBD Genius result counts from the
authored graph's single configuration. The application generates target 25 and
minimum 10; these are also observed Apple producer values. Preserve retained
nonzero counts. Native execution proved that literal zero counts otherwise accept
an empty playback queue without requesting a candidate.

The application shares manual additions, automatic rotation, removal, ownership,
and publication workflows with Nano Mixes. Capture the format selected by the
Device Profile, never a stray SQLite Library file. Publish iTunesDB, root
`Extras.itdb`, and ownership in the existing recoverable Storage transaction.
No Nano SQLite Library directory is created on a Classic.

Enforce twelve total Mixes, including externally owned collections. The Add dialog
shows remaining slots and permits promotion of an existing automatic Mix without
another slot. Automatic rotation fills only available slots and preserves unowned
Mixes. The native engine samples up to 100 candidates; this is not a file-member
limit, so the writer does not truncate larger candidate pools.

## Consequences

No new dependency, firmware patch, account service, or runtime firmware-lab
dependency is required. Existing Nano behavior remains covered by the same
publication tests. Classic coverage includes native records, byte preservation,
membership pruning, ownership rollback, explicit removal, Sync rotation, capacity,
and GUI actions. Physical menu display and playback remain an acceptance step;
the native artwork fallback is used rather than authoring custom Mix covers.

ADR-0291 subsequently adds qualified Classic and Nano 7 Mix cover publication.
