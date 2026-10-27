# Classic 2.0.1 iTunesDB semantics and product corrections

Research date: **2026-10-26**. Direct firmware instructions establish that MHIT
`+0x98` is the total skip counter used by the inspected Classic's playback,
sorting, Smart rules, and Play Counts sidecar. They also establish that MHYP
`+0x28` affects repeat mode rather than counting text records. This report records
those findings, the resulting iOpenPod corrections, and the limits of applying
them beyond the one analyzed firmware image.

The product uses the corrected counter mapping in its shared binary schema,
without a firmware-version gate. **That cross-model application is an explicit
inference and compatibility decision, not evidence that other firmware has been
validated.** It replaces a historical interpretation contradicted by the examined
consumer instructions. Original iOpenPod and libgpod remain useful comparative
sources; their labels do not override this direct evidence.

## Evidence identity and method

| Item | Exact identity |
| --- | --- |
| Firmware | Apple Classic 120 GB, RetailOS **2.0.1**, updater family 33 |
| Normalized `osos.bin` | 10,513,984 bytes |
| SHA-256 | `220913cb8569af0538a7e828f1aaa08d9313bf9a5c2b0a7a7e6e2dc0bee5f16e` |
| Analysis baseline | osos-lab `d2c8e357d58591bdaa70bb6be9da191f489554a6` |
| Relevant memory mapping | ARM little-endian; runtime `.dram` begins `0x08000000`, source file offset `0xb65c` |
| Before-change iOpenPod comparison | `f93446cd01c5b4bafef66108a0d3be89a68df599` |
| Original comparison snapshot | iOpenPod v1.68.1, `de300074a25f6f327b54a7141720e5fbff9d5c5b` |
| libgpod comparison snapshot | `7982c5554f78dde47fd006afbeff659201d6db3d` |

The hash and map match the pinned [osos-lab 2.0.1 profile][osos-profile]. Its
[analysis export][osos-analysis] supplies the starting annotations. Later function
names and partial structures are analyst proposals, not recovered Apple symbols.
The local research project verified all three initialized imported regions against
the source image, inspected ARM loads/stores and branches, and exported the relevant
functions as both disassembly and reconstructed C. Decompiler signatures were
checked where saved registers or aligned 64-bit parameters produced misleading C.

Three evidence classes remain distinct:

- **Firmware static evidence:** instructions in the exact image above. This is
  stronger than an inherited field name, but does not mean the firmware was run.
- **Host reproduction:** synthetic fixtures passed through public iPodDB APIs,
  with prepared bytes reparsed or inspected at their actual offsets. This verifies
  Host behavior, not firmware acceptance.
- **Inference/product policy:** an explicit generalization or preservation choice,
  identified below. No personal database contents, identity captures, or firmware
  binaries are needed in this repository to state these findings.

## Total and secondary skip counters

Here `R` means the native Track record, not an MHIT buffer. The two coordinate
systems must not be interchanged:

| Disk MHIT offset | Native field | Established use |
| --- | --- | --- |
| `+0x50`, u32 | `R+0x90` | Total plays |
| `+0x54`, u32 | `R+0x94` | Secondary plays |
| `+0x58`, u32 | `R+0x98` | Last-played timestamp |
| Copy of `+0x50` | `R+0x9c` | Loaded total-play baseline |
| **`+0x98`, u32** | **`R+0xa0`** | **Total skips** |
| **`+0x9c`, u32** | **`R+0xa4`** | **Secondary skips** |
| `+0xa0`, u32 | `R+0xa8` | Last-skipped timestamp |
| Copy of `+0x98` | `R+0xac` | Loaded total-skip baseline |

This identification rests on several independent paths:

1. Importer **`0x08073bb8`** performs the disk-to-native stores above.
2. Skip event **`0x0824866c`** increments both `R+0xa0` and `R+0xa4`, writes
   `R+0xa8`, and emits the corresponding counter/date change mask. Play event
   `0x082485f0` has the analogous two-counter pattern.
3. Getter **`0x0827c734`** returns `R+0xa0`. Comparator **`0x08023cc8`** compares
   it for high change-mask `0x00400000`, and compares `R+0xa8` for `0x00800000`.
4. The complete Track rule helper **`0x08049778`** reads `R+0xa0` for rule field
   `0x44` and `R+0xa8` for date field `0x45`.
5. Play Counts reader **`0x080931a8`** adds row `+0x14` to `R+0xa0`, leaving
   `R+0xa4` untouched. Writer **`0x0809d024`** emits `R+0xa0 - R+0xac` at the
   same row offset.

The baseline and subtraction are especially decisive: the sidecar delta belongs
to the first counter, independently of any name assigned to the getter. The
secondary counter is independently stored and increments on skip events. A fresh
record-clone path in `0x08048d78` clears secondary counters, but that is not proof
of a reset-on-Sync or scrobbling contract. **Secondary skip count** is therefore
the appropriate conservative name; “unscrobbled skips” would overstate the evidence.

Before this correction, iOpenPod called `+0x98` `genius_category_id` and projected
`+0x9c` as common `skip_count`. A synthetic fixture with values `7 / 11` and a
sidecar skip delta of `2` prepared disk values `7 / 13`. The inspected firmware
merge instead changes the total to `9`, retaining secondary `11`.

The corrected [MHIT definition][mhit] places `skip_count` at `+0x98` and
`secondary_skip_count` at `+0x9c`; [Library projection][projection] exposes the
former as common Track metadata and retains the latter as iPod-specific evidence.
Semantic writes and sidecar addition use that same shared definition. The false
Genius diagnostic is removed. This does not invalidate the separately represented
Genius identity at MHIT `+0x1e4`, Genius graph records, or native Genius features.

For comparison, the pinned [libgpod Track reader][libgpod-tracks] retains offset
152 (`0x98`) as `unk152` and reads `skipcount` at offset 156 (`0x9c`). Its
[sidecar merge][libgpod-merge] then adds skip deltas to that value. This documents
the competing historical convention; it does not establish that the examined
Classic uses that convention. Applying the corrected shared mapping to other
models remains an inference until their firmware or equally strong evidence is
examined. SQLite columns retain their existing format-specific offsets and names;
the inference is about the common semantic total, not a claim that SQLite has
MHIT offsets.

## Preserve MHYP `+0x28` across metadata edits

The Playlist importer **`0x08072f30`**, specifically `0x08073240..0x08073278`,
reads this 16-bit value and maps it to native Playlist `+0x128`:

| Serialized value | Native value | Behavior in this firmware |
| --- | --- | --- |
| `0` | No store | Keep existing/default repeat state |
| `1` | `0` | Repeat off |
| `2` | `2` | Repeat one |
| `3` | `1` | Repeat all |
| Other nonzero | `0` | Repeat off fallback |

The interpretation is independently supported by next/previous helpers
**`0x08032070` / `0x08032b30`**: mode one wraps at list ends and mode two retains
the current entry unless the applicable advance flags override it. Predicates
`0x0815a5e8` / `0x0815a61c` test those same values. This is more than inferring an
enum from the importer's switch.

The old Host field `string_mhod_child_count` was adjusted when text children
changed. A synthetic description addition changed disk `+0x28` from `3` to `4`:
repeat-all becomes repeat-off in the examined importer. A title rename with the
same string count happened to preserve it. Actual MHOD/MHIP child counts are
separate fields at `+0x0c/+0x10`.

The correction uses the neutral raw [field `unk_mhyp_0x28`][mhyp], preserves its
value during text edits and companion-dataset construction, and stops deriving it
from text-child counts. The existing authored default `1` is retained for new
Playlists. That default is a compatibility choice; it means repeat-off here, but
is not presented as a validated universal enum. This pass does not expose a new
cross-model repeat-control property or normalize unfamiliar retained values.

## Binary Play Counts: bookmark and played state

For this firmware, reader **`0x080931a8`** reads a `0x60`-byte `mhdp` header and
fixed `0x1c`-byte positional rows after checking count against native Tracks.
There is no persistent-ID lookup in this path. The inspected fields are:

| Row offset | Native effect |
| --- | --- |
| `+0x00`, u32 | Add total plays at `R+0x90` |
| `+0x04`, u32 | Replace last-played value at `R+0x98` |
| `+0x08`, u32 | Replace bookmark milliseconds at `R+0x68`, **including zero** |
| `+0x0c`, u32 | Low byte replaces rating at `R+0x7e` |
| `+0x10`, byte | Nonzero sets record dirty mask `0x4000` in `R+0x1c` |
| `+0x11`, byte | `1` sets played/status mask `0x08` in `R+0x8f`; every other value clears it |
| `+0x14`, u32 | Add total skips at `R+0xa0` |
| `+0x18`, u32 | Replace last-skipped value at `R+0xa8` |

Writer **`0x0809d024`** emits marker `1` or `2`. Its floating-point path sets
marker one if the retained native played flag is set, the play delta is nonzero,
or bookmark progress is strictly above a threshold imported from MHBD byte
`+0x21`. For finite nonnegative inputs and nonzero duration, the calculation is:

```text
percent = float64(float32(bookmark_ms) / float32(duration_ms)) * 100.0
played_marker = 1 if (
    percent > float64(mhbd_byte_21)
    or native_played_flag
    or total_plays != imported_play_baseline
) else 2
```

The instructions and software floating-point helpers establish a **status marker**,
not proof that the Track finished playing. Equality does not satisfy the threshold
arm. Zero duration, NaNs, infinities, and all exceptional floating-point cases have
not been modeled exhaustively. This pass consumes the recorded marker; it does
not reproduce this calculation or split every version's MHBD `platform` field.

Before the correction, Host projection used `new_bookmark or previous_bookmark`
and inferred played state from retained state or positive total plays. A fixture
with marker `1`, zero plays, sidecar bookmark zero, and prior bookmark `500`
therefore remained unplayed with bookmark `500`. The firmware merge sets the
flag and clears the bookmark.

The corrected [codec][sidecar-codec] exposes the optional raw played marker when
the row contains that byte. [Projection][sidecar-projection] treats binary
Play Counts bookmark zero as an explicit reset. Known markers `1` and `2`
override played state with true and false respectively. An absent or unknown
marker retains the existing Host fallback, rather than generalizing the firmware's
“every value other than one clears” behavior to legacy inputs. That fallback is
an intentional policy difference. Raw sidecar serialization remains byte-exact.
The zero-bookmark correction is specific to binary Play Counts; iTunesStats and
plist retain their existing missing/zero policies.

The pinned [libgpod merge][libgpod-merge] updates a bookmark only when nonzero and
sets played status from a nonzero play delta; it does not decode this byte's
meaning. Its [sidecar parser][libgpod-playcounts] groups bytes `+0x10..+0x13` into
an unknown word. These are comparison points, not a reason to retain a demonstrated
loss of a reset or known status marker.

Not every firmware behavior is copied. Current bounds validation, historical
rating/date policies, the captured Device Time Context, duplicate-source
protection, and transactional publication remain distinct Host contracts.
In particular, firmware readers can partially apply a prefix on later read failure;
iOpenPod should not imitate that failure mode. See [playback sidecars][sidecars].

## Empty base OTG file

The base filename `OTGPlaylistInfo` acts as the presence gate for numbered OTG
files. The stronger new static evidence concerns its representation:

- `0x0804d2c0(owner, NULL)` calls **`0x08088bdc` before** testing the OTG count.
  The helper checks/replaces the path, opens it with mode two, then closes it
  without writing payload. A zero count skips writing an `mhpo` header.
- Numbered save **`0x0809d2fc`** writes the numbered file, then on its successful
  path calls the same helper for the base filename at `0x0809d3c0`.

This strongly supports a zero-byte base marker after saving an archive. Exact
filesystem virtual-method semantics are inferred from the call sequence; no
controlled firmware execution or physical empty-marker capture was performed.
libgpod also [gates numbered loading on base-file presence][libgpod-otg], providing
an independent Host convention consistent with the semaphore interpretation.

Previously iPodDB recognized the presence gate but sent a zero-byte base through
the strict `mhpo` parser, yielding an error and blocking reconciliation even with
a valid numbered Playlist. The correction accepts **only the empty base file**
as a consumed marker without creating a Playlist. Nonempty base files and all
numbered files still require valid structured content; an empty numbered file
does not gain an exemption. Existing preservation and publication safeguards apply.

## Smart Playlist findings retained as research

The investigation follows the real route from refresh wrapper `0x0804bf18`
through `plsu` command dispatch to membership updater **`0x0804bfa0`**, group
evaluator **`0x0803b8f8`**, leaf callback **`0x08040068`**, and Track field helper
**`0x08049778`**. All 31 bounded jump-table branch slots in the latter were
checked before recovering its full 976-byte body. `0x080c06bc` is a serialized
criteria conversion callback, not the rule predicate evaluator.

| Topic | Firmware 2.0.1 static behavior | Retained iOpenPod behavior |
| --- | --- | --- |
| References | Validate dependencies and recursively refresh referenced Smart Playlists first; detected cycles become non-ready. | Read the same completed saved-membership snapshot for every refreshed Playlist; no cascade. |
| Folder reference | Track leaf walks actual occurrence owners; no descendant traversal inside that leaf. | Include Playlist Folder descendants in saved membership. |
| Budget overrun | First overrun exhausts selection; later smaller candidates cannot fill the remainder. | Skip an oversized candidate and consider later Tracks. |
| Time budgets | Sum each Track's truncated whole seconds. | Sum exact milliseconds. |
| Random limited selection | Eligible existing membership consumes budget before remaining random candidates. | Recompute deterministic preview selection using a fixed seed. |
| Empty active group | Empty/all-disabled group yields false, including AND. | Empty root disables filtering; nested ALL uses the usual empty-true rule. |
| Date bounds | Relative sentinel uses start/end-of-day plus delta-times-units, then inclusive range comparison. | Evaluate relative recency against one captured instant. |
| Text | UTF-16 operands; strips leading code units `0..31`; lower collation modes remain unresolved. | Python case folding and supported string operations. |
| Skip rule `0x44` | Uses the total at native `+0xa0` / MHIT `+0x98`. | Uses common metadata `skip_count`, now corrected by the shared field mapping. |

The first two Host policies are explicit in [ADR-0035][adr35] and
[ADR-0142][adr142]; the others are covered by the current evaluator and fixtures.
They are not silently replaced in this correction pass. The budget behavior also
appears in the [Original evaluator][original-smart] and
[libgpod evaluator][libgpod-smart], so the difference has a traceable origin, but
that provenance is not proof of Apple firmware equivalence. A later compatibility
decision needs separate fixtures, version scope, and preview/publication agreement.
See the current [evaluator][smart-preview].

## Portable evidence and validation

The separate, ignored firmware lab retains the following evidence. These names are
relative to the lab root and contain no machine-specific paths or private Library
data. A reader with the matching image can reproduce the address-level checks:

| Evidence | Contents |
| --- | --- |
| `artifacts/itunesdb201-corpus-index.json` | Function export corpus inventory and provenance |
| `artifacts/itunesdb201-pass1/` | Importers, Play Counts reader/writer, OTG writer; paired `.c` and `.asm.txt` exports keyed by address |
| `artifacts/itunesdb201-semantics-events/` | Playback event setters and surrounding callers |
| `artifacts/itunesdb201-lifecycle-readable-v3/` | Reviewed readable functions with proposed types/names |
| `artifacts/itunesdb201-smart-track-rule/dispatch-slots.tsv` | All 31 checked field-switch branch slots |
| `artifacts/itunesdb201-rule-operator-exploration/` | Numeric/boolean comparison and date-context instructions |
| `artifacts/itunesdb201-rule-boundaries/` | Text dispatcher, bound arithmetic, calendar conversion adapters |
| `artifacts/host-contract-probes.json` | Synthetic pre-correction counter, repeat-field, bookmark, and played-marker comparisons |
| `artifacts/otg-empty-semaphore-host-probe.json` | Synthetic empty-base plus numbered-Playlist failure before correction |
| `notes/itunesdb/` | Track, Playlist, persistence, counter, Smart, and Host-contract analysis with per-function citations |

These exports are supporting research artifacts, not product dependencies. The
public [osos-lab profile][osos-profile] identifies the exact image and memory map;
the address tables here state the important deductions without requiring a
reader's access to the private lab. The public source links below identify the
comparison implementations; they do not purport to publish Apple's firmware.

Regression verification should inspect serialized offsets, not merely reproject
through the same schema that introduced the old interpretation. The correction's
fixtures cover independent total/secondary values, sidecar addition at `+0x98`,
retained MHYP `+0x28` across text edits, known and unknown played markers, explicit
bookmark zero, and empty-base versus empty-numbered OTG files. Lossless parse/
serialize remains necessary but cannot alone prove field meaning.

No altered database or firmware was run on a physical iPod for this correction.
Other Classic releases, older full-size iPods, and nano firmware have not acquired
new firmware-validation status from the shared schema change. Missing evidence
about secondary-counter resets, collation, timezone handling, and cross-version
reuse remains explicit rather than being replaced with familiar historical labels.

[osos-profile]: https://github.com/lgreitis/osos-lab/blob/d2c8e357d58591bdaa70bb6be9da191f489554a6/ghidra/profiles/classic6g-reva-2.0.1.json
[osos-analysis]: https://github.com/lgreitis/osos-lab/tree/d2c8e357d58591bdaa70bb6be9da191f489554a6/ghidra/analysis/2.0.1/osos
[original-smart]: https://github.com/TheRealSavi/iOpenPod/blob/de300074a25f6f327b54a7141720e5fbff9d5c5b/src/iopenpod/sync/spl_evaluator.py#L415-L483
[libgpod-tracks]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_itunesdb.c#L2547-L2557
[libgpod-merge]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_itunesdb.c#L2739-L2753
[libgpod-playcounts]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_itunesdb.c#L980-L1017
[libgpod-otg]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_itunesdb.c#L2866-L2899
[libgpod-smart]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_playlist.c#L891-L936
[mhit]: ../../src/iPodDB/iTunesDB/shared/chunk_defs/mhit.py
[mhyp]: ../../src/iPodDB/iTunesDB/shared/chunk_defs/mhyp.py
[projection]: ../../src/iPodDB/library/_projection.py
[sidecar-codec]: ../../src/iPodDB/sidecars/codec.py
[sidecar-projection]: ../../src/iPodDB/library/_sidecar_projection.py
[sidecars]: ../playback-sidecars.md
[smart-preview]: ../../src/iOpenPod/app/smart_playlist_preview.py
[adr35]: ../adr/0035-author-evidence-backed-smart-playlist-choices.md
[adr142]: ../adr/0142-refresh-smart-playlists-before-library-publication.md
