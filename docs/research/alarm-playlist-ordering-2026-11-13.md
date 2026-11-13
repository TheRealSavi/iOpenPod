# Alarm Playlist ordering in Classic and Nano firmware

The later [source projection report](alarm-playlist-source-projection-2026-11-13.md)
closes this report's binary import implementation gate, including native names,
creation-order ties, hierarchy, Smart attachment and variant media masks.
[Nano 5 SQL projection](alarm-playlist-nano5-sql-2026-11-13.md) establishes that
Nano 5 alarms use a SQL vector rather than the linked legacy comparator traced
here. The original evidence below remains useful within those corrected scopes.

The native text comparison and Playlist comparison routines are now executed
independently in all four Classic images and Nano 3, 4 and 5. They use the same
embedded weight table and produce identical results in the exercised domain.
Classic 2.0.1 additionally has an executed sorted-array builder, audio-entry
counter, import filter, selector bound and runtime-array insertion/removal path.
Its final reserved row is the current On-The-Go Playlist. The two subtractions
in its alarm setter exclude Master and this final row; they are not an unexplained
off-by-one. These results support a source-derived imported Playlist prefix,
subject to the import qualifications below. No product code changes are made by
this investigation. [Native array probe][array-probe], [native comparison probe][family-probe]

This report continues [Alarm sounds](alarm-sounds-clickwheel-2026-11-13.md) and
supersedes two statements there: the collation provider is recovered, and native
Playlist flag `+0x150 & 1` identifies an attached Smart definition, **not a Folder**.
The empty-list exception therefore concerns Smart lists. Host Folder metadata
must not substitute for this flag. [Smart attachment and hierarchy][playlist-notes]

## Exact images and reproduced evidence

All work uses original firmware instructions in Unicorn 2.1.4, with Capstone
5.0.6 for instruction inspection. The firmware bytes are hash checked before
execution. There were no physical-device mutations or physical sound tests.
Addresses are runtime addresses in the named image, not portable offsets.

| Image | OSOS SHA-256 |
| --- | --- |
| Classic family 24, 1.1.2 | `9fc12ffc0817d481af6bcdded1a8f3c720027c85872aa13bade22cbe60913b4a` |
| Classic family 33, 2.0.1 | `220913cb8569af0538a7e828f1aaa08d9313bf9a5c2b0a7a7e6e2dc0bee5f16e` |
| Classic family 35, 2.0.4 | `2ca353870e84bc92ff5090024122ee0712d9bb992c6933b3b230c0ae613b0ffe` |
| Classic family 38, 2.0.5 | `d7669f9266e7cae15867248eeb9c34a2711f1f9a1f3cf40132ef86d9fdbf8224` |
| Nano 3, family 26, 1.1.3 | `ff5980009c6720742f5b85f3e80a5c853bd0e3caa433d015e6836c209e08081a` |
| Nano 4, family 31, 1.0.4 | `a5d273ab3be00dcea90e72444bb9750ebe5d88f5f986c3e62e4fd108332ff372` |
| Nano 5, family 34, 1.0.2 | `dbd25a9279e7c8ccdc5212d94f2e1b376a73dcebe105b1b1925d9669f0cecd49` |

The family receipt includes every runtime region, initializer/consumer address,
instruction-span hash, table word and vector result. Nano 4's known uncertain
image tail is guarded against both reads and instruction fetches; no probe
touches it. Its supplied-image limitation remains in force.
[Family receipt][family-result], [Nano 4 acquisition boundary][nano4-boundary]

The retained receipts contain **4,131 nonduplicated cases**:

- Classic 33: 403 text comparisons, one 12-row native sorted-cache construction,
  21 entry-count cases, 216 paired count/fill cases, 44 selector-bound cases and
  20 runtime-array insertion/removal cases: **705** total.
- All seven images: 403 text comparisons and 144 native Playlist-comparator pairs
  per image: **3,829** total. Classic 33's 403 text cases overlap the first probe;
  the 144 comparator pairs add independent coverage.

Adapters supply cleanup registration, allocation/free, captured name-cache
outputs, a selected-alarm pointer and cache-change notification where needed.
They do not replace the comparators, sorter, traversal, count predicate, filter,
selector bounds or array insertion/removal. Count/fill predicate probes enter
the original loader's basic blocks with explicit synthetic registers; they are
not full boot or full iTunesDB-import executions. The receipts enumerate those
boundaries. [705-case receipt][array-result], [3,829-case receipt][family-result]

Reproduce from the firmware lab with unused output paths:

```powershell
uv run scripts/probe_alarm_playlist_ordering_20261113.py --output artifacts/alarm-order-new.json
uv run scripts/probe_alarm_playlist_collation_family_20261113.py --output artifacts/alarm-order-family-new.json
```

## Actual collation provider and ordering

Classic 33 initializer `082890a8` constructs object `08acfe98` from 256 embedded
words at `088d1b94`, with threshold `0x596`. The constructor writes the pointer,
count and threshold directly. Its registered destructor is a no-op. The existing
startup-table trace identifies its invocation. The only aligned absolute
references found to this object are the initializer and slow comparison wrapper;
this is a static reference audit, not a live-memory capture.
[Startup/provider trace][provider-notes]

Each image independently constructs the same provider layout, count and threshold,
with a pointer to its own copy of the identical 1,024 table bytes. The constructor
writes ten bytes. No locale parameter or external resource enters these
executed comparisons. This qualifies the initialized/default provider; it does
not claim to have observed every possible later memory write.
[Family execution receipt][family-result]

| Image | Initializer | Counted UTF-16 compare | Playlist compare | Master flag member |
| --- | --- | --- | --- | --- |
| Classic 24 | `08272afc` | `0802354c` | `08086c98` | `+0x130` |
| Classic 33 | `082890a8` | `080243b8` | `080893d0` | `+0x130` |
| Classic 35 | `082a60a0` | `0803ad2c` | `0809fee4` | `+0x18c` |
| Classic 38 | `082a79a0` | `0803ad2c` | `0809ff90` | `+0x18c` |
| Nano 3 | `082aa0b0` | `0802487c` | `080903f8` | `+0x130` |
| Nano 4, Thumb | `0826594c` | `080390dc` | `0809c778` | `+0x130` |
| Nano 5, Thumb | `08017bfc` | `080e3b04` | `080e4e88` | `+0x130` |

The binary Playlist comparator ranks the Master flag first, reads each counted UTF-16
name into a 512-byte buffer, compares with mode `0x1b`, and breaks a comparison
tie using unsigned native Playlist ID at `+0x2c`. That ID is allocated in memory;
it is not the on-disk persistent ID. The 144 pairs per image exercise Master
priority, accents, leading space, punctuation, digits, equal primary names and
native-ID ties. [Classic comparator][classic-comparator],
[Nano 4 comparator][nano4-comparator], [all-image execution][family-result]

Mode `0x1b` trims leading UTF-16 units at or below ASCII space. Its fast path
accepts space, `!`, `.`, ASCII letters and digits, folds ASCII letter case and can
return on an early unequal pair. Encountering a digit under this mode, another
character or a non-ASCII unit enters the slow path for the entire trimmed pair.
The slow path compares nonzero primary weights from the fixed table; units at
or above 256 use their unchanged UTF-16 code-unit value. It does not implement
general Unicode normalization, Unicode case folding or natural number sorting.
[Native comparison trace and model][comparison-notes], [executed cases][family-result]

Examples include `Echo == écho` before the native-ID tie break, `2 > 10`,
`Ā < A`, and a single `ß` having zero primary weight. Composed `é` and `e` plus
combining acute differ. These examples are not a replacement for the fast-path
rules: applying only the slow weight sequence everywhere is also incorrect.
[Complete native vectors and weight table][family-result]

Classic 33's `080ac908` builds the cache by traversing all native Playlists,
then invokes original sorter `08040690` with comparator `080893d0`. Names sort
globally; a child Playlist need not remain next to its parent. The executed
12-row hierarchy places `Z child` after the unrelated `Smart` row even though
its parent is `Folder`. Cache building does not use a Host locale or semantic
snapshot tuple order. [Cache builder][cache-builder], [native sorted cache][array-result]

## Imported array membership and Smart lists

Classic 33 selects the first type-2 or type-3 dataset encountered in file order.
It imports Tracks from preceding type-1 datasets; it does not prefer type 3
unconditionally or combine duplicate Playlist datasets. One unambiguous Master
and source-qualified membership/identity records are necessary for a Host
projection. [Root importer instructions and dataset dispatch][lifecycle]

The imported audio array is owner `+0xd48`, with count `+0xd4c`. Its count and fill
blocks apply the same predicate. Native `+0x130 & 0x80` and `+0x150 & 0x10` exclude
a row. The latter is imported from MHYP `+0x2a` bit 0. A surviving Master is
included. For another row:

1. Count recursively visited leaf occurrences whose resolved native Track has
   `u16(+0xba) & 0x12d != 0`.
2. If that count is zero, include only an attached Smart list with no direct
   child Playlists (`+0x150 & 1`, `+0x20 == 0`).
3. For a non-Smart row, also reject a nonzero membership-media aggregate at
   `+0x14c` that has no `0x12d` bit.

The original count callback skips group nodes and null Track pointers. Checked
status, persistent IDs, Folder labeling and Host visibility are not consulted
by this predicate. The 216 cases execute both loader blocks and require their
results and filled pointer to agree. [Native loader][loader],
[native audio predicate][audio-predicate], [count/fill receipt][array-result]

Do not equate raw `MHIT.media_type` mechanically with every native media member.
The Track importer initially copies the low 16 bits from disk `+0xd0` and has
additional classification/mutation branches. In particular it clears video bit
1 in its `0x8000` branch. That bit is outside `0x12d`, but a complete general
import projection must account for its own qualified Track layouts and branches.
[Track import evidence][track-import]

Before the audio array is counted, `080a8a78` invokes Smart refresh and recomputes
membership aggregates. `0804bf18` requires attachment, no descendant Playlists
and ready state `+0x152 == 1`. `080b18c8` then gates ordinary refresh on live-update
byte `+0x154` and `+0x150 & 2`, dispatching an update event under a reentrancy guard.
Thus saved Smart membership is not universally the final runtime membership.
However, the audio-array predicate includes an attached Smart **leaf** even when
its audio count is zero and exempts it from the non-Smart aggregate rejection.
That bounded inclusion fact does not require predicting the rule evaluator.
The continuation qualifies Smart lists with children through the no-descendants
refresh gate and captured occurrence membership.
[Preparation pass][smart-preparation], [refresh gate][smart-gate],
[refresh request][smart-request], [native filter cases][array-result]

## Final On-The-Go row and generated Playlists

The imported array is followed by a separate runtime initialization path.
`080f1670` calls `0803b4a8`, which creates owner `+0xd28` through `0804033c`.
Creation inserts it into the audio array with `0801a854`. It can then load saved
membership through `0808958c`; the default filename is **OTGPlaylistInfo**,
literal `083d90dc` referenced at `080726c4`, under `iPod_Control/iTunes`.
This establishes the final row as the current On-The-Go collection.
[Initialization caller][otg-init], [create/load wrapper][otg-wrapper],
[row construction][otg-create], [OTG reader][otg-reader], [path helper][otg-path]

`0801a854` appends this distinguished row at the existing count. When inserting
any other generated Playlist it copies the preceding array, inserts the new
row just before the distinguished row, then places the distinguished row last.
It increments the count and notifies the browser cache. `0803e1f4` removes a
matching pointer, preserves the order of other rows and decrements the count.
The 20 original-instruction cases cover four imported-prefix sizes, final-row
creation, two generated insertions, removal and absent removal. The imported
prefix stays unchanged in each case. [Insert][runtime-insert],
[remove][runtime-remove], [executed lifecycle cases][array-result]

Saved/generated collection readers and Genius saving call the same insertion
routine. Those rows are an appended suffix, not a reason to treat all native
indices as unknown. Their identities still need their own source evidence for
explicit sound selection. [Saved collection import][saved-import],
[Genius/save caller][genius-save]

## Alarm selector and public API consequences

With total native count `N`, browser method `0811a398` returns `max(N-1, 0)`.
Alarm setter `080e867c` subtracts another one when nonzero and accepts a signed
selector smaller than `max(N-2, 0)`. `-1` is accepted as no Playlist. Display and
playback resolve nonnegative selector `s` to raw array index `s+1`. With Master
first and current On-The-Go last, the normal range selects every intervening
imported/generated row. [Count wrapper][browser-count], [setter][alarm-setter],
[playback selection][playback-selection], [44 executed bound cases][array-result]

A public binary projection exposes the raw imported array index, persistent
Playlist ID and source title. The alarm codec uses `index-1` as its stored selector.
The ordinary Library snapshot is insufficient: it removes Master, merges source
datasets and does not carry this firmware comparator/import filter. A generated
suffix or final On-The-Go row must not be fabricated from an absent captured PID.
Existing selectors outside the proven imported prefix remain unchanged unless
the user explicitly selects a qualified replacement sound. Library publication
leaves all Alarm selections unchanged under
[ADR-0262](../adr/0262-leave-alarm-selections-unchanged-during-library-writes.md),
including when Playlist positions change or selected Playlists are deleted.

The [source continuation](alarm-playlist-source-projection-2026-11-13.md) defines
the entire imported-catalog qualification, including hierarchy and Smart rows.
Long UTF-16 names are composed and truncated at the native 255-unit boundary;
ties use native creation order. Its two unsafe name-reader forms and ambiguous
source identities prevent catalog qualification. Dropping an unknown row is
unsafe because it could change every later selector.

## Coverage boundary and completed continuation

The shared comparator and its provider are executed in **all seven** images.
Classic 24 and Nano 3 also have unique normalized instruction matches for the
Classic 33 cache builder, count/fill blocks, selector setter and browser count.
Classic 35/38 retain the same comparator/setter semantics with relocated fields
or virtual slots. The source continuation establishes their additional imported
exclusions and 32-bit media mask, and independently executes the six binary audio
predicates and name routines. Nano 5's comparator execution demonstrates linked
code behavior; the separate SQL report identifies the actual alarm array route.
[Static span-match inventory][span-matches],
[all-image comparator receipt][family-result]

Source-to-native projection for explicit sound selection is now qualified by the
linked continuation reports. Automatic preservation through Library rewrites was
declined by the user and is not remaining work. These are original-instruction
and static import results; physical adoption and wake/sound output are not
claimed or required by this investigation.

[array-probe]: ../../../ipod-firmware-lab/scripts/probe_alarm_playlist_ordering_20261113.py
[family-probe]: ../../../ipod-firmware-lab/scripts/probe_alarm_playlist_collation_family_20261113.py
[array-result]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-ordering-20261113-native-v3.json
[family-result]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-ordering-20261113-cross-family-native-v3.json
[span-matches]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-ordering-20261113-span-matches-v1.json
[nano4-boundary]: ../../../ipod-firmware-lab/notes/games/nano4-independent-verification.md
[provider-notes]: ../../../ipod-firmware-lab/notes/itunesdb/collation-runtime-initialization.md
[comparison-notes]: ../../../ipod-firmware-lab/notes/itunesdb/string-comparison-and-collation.md
[playlist-notes]: ../../../ipod-firmware-lab/notes/itunesdb/playlist-record-semantics.md
[classic-comparator]: ../../../ipod-firmware-lab/artifacts/alarm-sounds-20261113-library-comparator/080893d0.c
[nano4-comparator]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-20261113-nano4-listcompare/0809c778.c
[cache-builder]: ../../../ipod-firmware-lab/artifacts/alarm-sounds-20261113-library-extra/080ac908.c
[lifecycle]: ../../../ipod-firmware-lab/notes/itunesdb/lifecycle.md
[loader]: ../../../ipod-firmware-lab/artifacts/mhii-unknown-fields-20261028/08046cd8-Research_Library_LoadAndFinalize.asm.txt
[audio-predicate]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-20261113-seeds/08040184.c
[track-import]: ../../../ipod-firmware-lab/notes/itunesdb/track-import.md
[smart-preparation]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-20261113-seeds/080a8a78.c
[smart-gate]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-20261113-seeds/0804bf18.c
[smart-request]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-20261113-more/080b18c8.c
[otg-init]: ../../../ipod-firmware-lab/artifacts/preferences-classic33-full-export-20261107/080f1670.c
[otg-wrapper]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-20261113-finalrow/0803b4a8.c
[otg-create]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-20261113-runtime2/0804033c.c
[otg-reader]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-20261113-runtime2/0808958c.c
[otg-path]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-20261113-finalrow/080726bc.c
[runtime-insert]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-20261113-runtime/0801a854.c
[runtime-remove]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-20261113-runtime/0803e1f4.c
[saved-import]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-20261113-runtime2/08041e00.c
[genius-save]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-20261113-runtime2/0810a930.c
[browser-count]: ../../../ipod-firmware-lab/artifacts/alarm-sounds-20261113-classic-library2/0811a398.c
[alarm-setter]: ../../../ipod-firmware-lab/artifacts/alarm-sounds-20261113-classic-core/080e867c.c
[playback-selection]: ../../../ipod-firmware-lab/artifacts/alarm-sounds-20261113-classic-identity/080ef888.c
