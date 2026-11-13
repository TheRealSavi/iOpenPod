# Source projection for Classic and Nano alarm Playlists

The binary iTunesDB projection is now defined for Classic families 24, 33, 35 and
38, Nano 3 and Nano 4. It follows native import order, membership and Smart
attachment, imported names, firmware collation and native creation-order ties.
It supports ordinary, grouped and hierarchical imported catalogs, including
Smart leaves, without evaluating Smart rules. Nano 5 uses a different SQL route;
the linked legacy comparator in that image is **not** its alarm catalog source.
Its separate [SQL investigation](alarm-playlist-nano5-sql-2026-11-13.md) defines
the `Library.itdb`/`Dynamic.itdb` projection.

This continues and supersedes the source-import implementation gate in
[Playlist ordering](alarm-playlist-ordering-2026-11-13.md). Automatic Playlist
selection preservation during Library writes was declined and is outside this
work. No physical device was mutated, and no physical alarm playback or adoption
claim follows from these instruction executions.

## Evidence and reproduction

The exact firmware hashes and runtime maps are those in the
[ordering report](alarm-playlist-ordering-2026-11-13.md#exact-images-and-reproduced-evidence).
The new producers verify those original image bytes before execution with Unicorn
2.1.4 and Capstone 5.0.6. Every receipt includes its producer hash; the earlier
705-case and seven-image comparison receipts remain unchanged.

| Producer and receipt | New executed coverage |
| --- | --- |
| [Name composition producer][names-probe], [receipt][names-result] | 917 embedded composition pairs; 11,172 Hangul pairs; nine sequence vectors on five ARM images; matching composition-table bytes in all six binary images |
| [Name edge producer][edges-probe], [receipt][edges-result] | 35 counted-cache copy cases across five ARM images; seven UTF-8 decoder cases; ten full UTF-8 title-reader cases |
| [Import metadata producer][import-probe], [receipt][import-result] | 44 full Classic 33 MHLP/MHYP/MHOD inputs exercising metadata-order Smart attachment and imported Podcast flag |
| [Source-family producer][source-probe], [receipt][source-result] | 228 original audio predicates across six images; 30 original native-ID allocations; nine Nano 4 composition vectors and seven counted-cache copies; five original hierarchy links |
| [Empty-title producer][empty-probe], [receipt][empty-result] | Eight full Classic 33 UTF-16 reader cases varying composition bypass and reused scratch contents |

The retained vectors represent 12,517 new cases in these categories, excluding
the composition producer's repeated Classic 33 sequence run. They do not imply
12,517 full database imports. Adapters replace file I/O, allocation, final cache
storage, selected pointer getters and notifications where the individual receipt
says so. The original parser dispatch, attachment decision, comparison, audio
predicate, composition, decoder, native ID increment and hierarchy linker execute
from firmware. The full imported-source algorithm additionally uses static
instruction evidence for the entry construction and variant loaders.

Run each producer from the firmware lab with a new output path, for example:

```powershell
uv run --script scripts/probe_alarm_playlist_source_family_20261113.py --output artifacts/alarm-source-new.json
uv run --script scripts/probe_alarm_playlist_import_20261113.py --output artifacts/alarm-import-new.json
```

The application-side [native name fixture][name-fixture] contains receipt hashes,
composition pairs, sequence outputs, cache limits and unsafe-reader examples. It
contains no firmware bytes and is usable without the firmware lab.

## Binary dataset and occurrence projection

Process datasets in file order. Track datasets encountered before the selected
Playlist dataset supply its Track lookup. Select the first type 2 or type 3
Playlist dataset; later duplicate Playlist datasets do not merge into this
catalog. The native importer accepts Track classes 1, 2 and 3. It zeroes fields
absent from a short supported header; unresolved or zero Track references cannot
produce an audio occurrence. [Classic dataset dispatch][root33],
[Classic Track importer][track33], [Nano 4 Track importer][track31]

MHYP records create native Playlists in source order. A nonzero Master byte
reuses an existing Master when one exists. An ordinary row's parent PID is looked
up among already imported native Playlists: an absent or later parent is not
retroactively linked. The serialized `is_folder` field does not control this
native hierarchy. The native linker increments the immediate parent's direct
child count at `+0x20` and every ancestor's descendant count at `+0x1c`. Five
original linker executions produce direct counts `[2,1,0,0,0]` and descendant
counts `[3,1,0,0,0]`. [Playlist importer][import33], [linker][linker],
[hierarchy receipt][source-result]

For MHIP entries, a nonzero group-marker byte creates a group. A nonzero parent
group reference must resolve an already inserted group; zero means the root.
An ordinary entry must resolve an imported Track. Unresolved entries are skipped;
duplicate Track occurrences remain separate entries. Audio counting walks leaf
occurrences recursively, skipping group nodes. It does not test the checked byte.
Ambiguous duplicate source identities or malformed entry structures must prevent
qualification of the whole catalog, because dropping a potentially earlier row
would change saved selectors. [MHIP import and entry semantics][entry-notes],
[original count tests][array-result]

## Native eligibility by binary layout

| Images | Native Track media member | Audio mask | Additional imported exclusions |
| --- | --- | --- | --- |
| Classic 24/33, Nano 3 | `u16(+0xba)` | `0x12d` | Podcast flag |
| Classic 35/38 | `u32(+0xbc)` | `0x20012d` | Podcast flag; MHYP distinguished-kind byte `+0x52` equal to `0x20` or `0x22` |
| Nano 4 | `u16(+0xbe)` | `0x12d` | Podcast flag |

The media member is copied from disk MHIT `+0xd0`, truncated only for the 16-bit
layouts. The `0x8000` classification branch clears video bit 1; that bit is outside
the relevant audio masks. The 228 original predicate cases independently exercise
every input bit and mixed masks in all six images. [Track import][track33],
[late Classic Track import][track35], [Nano 4 import][track31],
[cross-image predicate receipt][source-result]

Podcast exclusion is MHYP `+0x2a & 1`, imported as native flags `+0x150 & 0x10`
or late Classic `+0x1ac & 0x10`. Classic 35/38 additionally set native bits `0x40`
and `0x20` for distinguished kinds `0x20` and `0x22` respectively. Their count and
fill blocks both exclude all three bits. Nano 4's count and fill exclude only
Podcast among these imported flags; its original Thumb predicate `08053e5a`
loads `u16(+0xbe)` and tests `0x12d`.
[Late Classic import][import35], [Classic 38 import][import38],
[late Classic loader][loader35], [Nano 4 loader][loader31],
[Nano 4 predicate][predicate31]

After those exclusions, include Master. Include another row when it has at least
one audio leaf occurrence, or when it has an attached Smart definition and zero
direct child Playlists. The non-Smart aggregate-media gate agrees with the same
audio mask; a qualifying audio occurrence necessarily supplies such a bit to
the aggregate. Native generated flags have their own paths and are not invented
from an unrelated source visibility field.

Smart attachment is a metadata-order state machine, not the existence of a
Smart metadata chunk. Start with `inhibit=0` and no attachment. MHOD 50 replaces
the inhibit byte from payload `+0x0e` (chunk `+0x26`). MHOD 51 leaves that byte
unchanged. After either type, native code attaches when the current inhibit byte
is zero; attachment remains present after later metadata. Thus `[51,50(inhibit=1)]`
attaches, whereas `[50(inhibit=1),51]` does not. The 44 complete original inputs
exercise eleven sequences against four disk flag values. [Import receipt][import-result],
[Classic importer][import33], [Nano 4 importer][import31]

The later Smart refresh cannot invalidate this projection: an attached Smart
leaf is included regardless of its resulting membership. A Smart row with
descendants fails the native refresh gate and uses captured membership for the
audio predicate. In the imported acyclic hierarchy, zero direct children is
equivalent to zero descendants. No Host Smart-rule evaluator is needed for this
catalog. [Refresh gate][smart-gate], [refresh request][smart-request]

## Names, composition and creation-order ties

Use the last Title metadata for an ordinary Playlist. Missing Title has an empty
native cache token. UTF-16 Title payloads are sequences of 16-bit units, including
embedded NULs and surrogate units. When `bypass_pair_composition` is zero, apply
the firmware's left-to-right adjacent-unit composition before caching. A successful
pair replaces the pending unit; a failed pair flushes the previous unit. This is
not general Unicode normalization or canonical reordering.
[Title reader][name-reader], [composition receipt][names-result]

The firmware has 917 embedded pair mappings, plus algorithmic Hangul composition:
`L=1100..1112` and `V=1161..1175` form
`AC00+(L-1100)*588+(V-1161)*28`; an LV base with zero trailing index combines
with `T=11a8..11c2` by adding `T-11a7`. Every table pair and every Hangul combination
was executed. The table bytes match all six binary images, and the sequence
routine was independently executed in each image, including Nano 4 Thumb
`080392a0`. [Composition producer][names-probe], [Nano 4 execution][source-result]

The name getter copies at most 510 cache bytes and stores the copied unit count.
Comparison therefore sees the first 255 **UTF-16 units**, after composition; it
may split a surrogate pair. Embedded NUL units remain in this counted string.
Forty-two native copy cases cover all six images. Missing or placeholder Master
names can be generated during import, but Master priority is checked before text,
so its localized fallback does not reorder ordinary rows. [Counted cache copy][cache-copy],
[Nano 4 cache copy][cache-copy31], [copy receipts][edges-result]

Two source forms cannot safely be projected as ordinary deterministic text:

- Encoding 2 follows a faulty UTF-8 title path in Classic 33. It passes raw decoded
  units to a counted-string cache insertion, using the first character as length.
  `ABC` supplies count 65 and starts the cached data with `B,C`, followed by stack
  contents. Changing only initial stack fill changes those contents. The decoder
  supports only one-, two- and three-byte forms; a four-byte lead returns zero.
  Refuse an encoding-2 binary Title catalog instead of substituting Host decoding.
- An explicit zero-length UTF-16 Title with composition enabled leaves the scratch
  count unchanged. A reused scratch name `Old` is consequently cached as `Old`.
  Empty Titles with composition bypassed are deterministic, as are missing Titles.
  Refuse the empty composition-enabled form rather than assume scratch is zero.

These are original-reader observations with captured cache calls, not deductions
from a desktop Unicode library. The eight UTF-16 cases also confirm nonempty
`e + combining acute` becomes `é` only when composition is enabled.
[UTF-8 reader receipt][edges-result], [UTF-16 reader receipt][empty-result]

Finally apply the exact native mode-`0x1b` comparison from the ordering report.
Master comes first. Text ties compare unsigned native ID at `+0x2c`, allocated
by a monotonic counter when each Playlist is created. Original allocation runs
in all six images return consecutive IDs; constructor code performs this once
per newly created Playlist. Hence relative source creation order supplies the
tie order for an unambiguous imported catalog. Persistent PIDs, hierarchy traversal
order and Host locale are not substitutes. [Constructor][constructor],
[ID executions][source-result], [comparison evidence][family-result]

## Selectors and explicit sound edits

The six binary layouts expose an imported prefix with Master at raw index zero.
The persisted alarm selector is `raw_index - 1`. The current On-The-Go row is
created after import, and other generated rows are inserted before that reserved
tail. They do not shift the qualified imported prefix. Preserve an unknown stored
selector until the user chooses a qualified replacement; do not fabricate a PID
for a generated row absent from the captured source. Nano 5 instead selects
directly from its SQL eligible vector, as its separate report documents.
[Binary array lifecycle](alarm-playlist-ordering-2026-11-13.md#final-on-the-go-row-and-generated-playlists)

Native tone-menu handler `081f0c38` changes only the tone selection, and Playlist
handler `081f0e74` changes only the Playlist selector. Both then send UI event
`0x10`. The setters preserve the other sound field and the enable gate. Playback
starts the selected Playlist and independently plays a nonempty tone name, so
an existing mixed record is meaningful. An exclusive Host Sound choice may
deliberately clear the other field while preserving the saved enable gate.
Control 4 and control 8 both reach either sound branch; toggling off and on is
unnecessary. A newly enabled Playlist alarm uses the qualified enable transition
control 4, while a tone-only alarm uses control 8.
[Tone handler][tone-handler], [Playlist handler][playlist-handler],
[sound and gate evidence](alarm-sounds-clickwheel-2026-11-13.md#two-independent-saved-sound-fields)

[names-probe]: ../../../ipod-firmware-lab/scripts/probe_alarm_playlist_names_20261113.py
[names-result]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-name-composition-20261113-v1.json
[edges-probe]: ../../../ipod-firmware-lab/scripts/probe_alarm_playlist_name_edges_20261113.py
[edges-result]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-name-edges-20261113-v1.json
[import-probe]: ../../../ipod-firmware-lab/scripts/probe_alarm_playlist_import_20261113.py
[import-result]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-import-metadata-20261113-v1.json
[source-probe]: ../../../ipod-firmware-lab/scripts/probe_alarm_playlist_source_family_20261113.py
[source-result]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-source-family-20261113-v1.json
[empty-probe]: ../../../ipod-firmware-lab/scripts/probe_alarm_playlist_empty_name_20261113.py
[empty-result]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-empty-name-20261113-v1.json
[name-fixture]: ../../tests/fixtures/alarms/native_name_import.json
[root33]: ../../../ipod-firmware-lab/artifacts/itunesdb201-pass1/080422e0-FUN_080422e0.c
[track33]: ../../../ipod-firmware-lab/artifacts/itunesdb201-pass1/08073bb8-ITunesDB_ImportTrackDataset.c
[track35]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-track35-20261113/0808a3ec.c
[track31]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-track-nano4-body-20261113/0808a0ec.c
[import33]: ../../../ipod-firmware-lab/artifacts/itunesdb201-pass1/08072f30-FUN_08072f30.c
[import35]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-import-classic35-20261113/08089700.c
[import38]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-import-classic38-20261113/0808979c.c
[import31]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-import-nano4-seed-20261113/08089884.c
[linker]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-source33-final-20261113/0803a4ac.c
[entry-notes]: ../../../ipod-firmware-lab/notes/itunesdb/playlist-record-semantics.md
[loader35]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-count-classic35-followup-20261113/0805d62c.c
[loader31]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-source-nano4-loader-20261113/0805b790.c
[predicate31]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-track-nano4-20261113/08053e5a.c
[smart-gate]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-20261113-seeds/0804bf18.c
[smart-request]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-20261113-more/080b18c8.c
[name-reader]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-name-source-20261113/0809c7c8.c
[cache-copy]: ../../../ipod-firmware-lab/artifacts/eq201-import-20261106/0809bdf0-StringCache_CopyCountedUtf16.c
[cache-copy31]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-source-nano4-loader-20261113/080ad7d4.c
[constructor]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-source33-final-20261113/0803cfac.c
[tone-handler]: ../../../ipod-firmware-lab/artifacts/alarm-sounds-20261113-classic-alarm-ui/081f0c38.c
[playlist-handler]: ../../../ipod-firmware-lab/artifacts/alarm-sounds-20261113-classic-alarm-ui/081f0e74.c
[array-result]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-ordering-20261113-native-v3.json
[family-result]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-ordering-20261113-cross-family-native-v3.json
