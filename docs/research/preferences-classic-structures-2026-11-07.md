# Classic Preferences: compound state, slideshow and cache checkpoint

This follow-up narrows several gaps in the [earlier inventory][previous] for the
latest Classic 6, 6.5, 7 and 7.5 firmwares. It corrects the earlier provisional
slideshow names, closes the saved Captions/Subtitles coupling under an explicit
observer-delivery adapter, and identifies a concrete artwork-cache participant.
It does **not** establish complete semantics for the entire Preferences file.

The application write qualification is unchanged by this research document.
Unknown Data, including noncanonical scalar values and clock fields, must remain
byte-exact outside explicit supported edits. Nothing here introduces a datetime
validation failure or a Host timezone conversion.

## Exact scope and evidence

All work was offline in the sibling `ipod-firmware-lab` repository. No physical
iPod I/O occurred. The images and memory maps are the same hash-pinned originals
as the earlier inventory:

| Family | Latest firmware | Original OSOS SHA-256 | Preferences extent |
| --- | --- | --- | --- |
| 24 / Classic 6 | 1.1.2 | `9fc12ffc0817d481af6bcdded1a8f3c720027c85872aa13bade22cbe60913b4a` | `0xb88` |
| 33 / Classic 6.5 | 2.0.1 | `220913cb8569af0538a7e828f1aaa08d9313bf9a5c2b0a7a7e6e2dc0bee5f16e` | `0xb8c` |
| 35 / Classic 7 | 2.0.4 | `2ca353870e84bc92ff5090024122ee0712d9bb992c6933b3b230c0ae613b0ffe` | `0xb8c` |
| 38 / Classic 7.5 | 2.0.5 | `d7669f9266e7cae15867248eeb9c34a2711f1f9a1f3cf40132ef86d9fdbf8224` | `0xb90` |

The file begins at owner-context `+4`. The Library's owner-context pointer is at
`+0xce8` on 24/33 and `+0xf00` on 35/38. Offsets below are file-relative unless
explicitly marked as object or cache offsets.

Final artifacts under the lab's `artifacts/`:

| Artifact | SHA-256 | Scope |
| --- | --- | --- |
| `preferences-classic-slideshow-20261107-final-v2/slideshow.json` | `7138f7b7584f1a33484cb0cf8eecd0d5905a881d7fcbe8addec88a91ac792c97` | 5,212 native mutations; 5,120 native duration-consumer cases; per-image menu resources |
| `preferences-classic-coupled-video-20261107-final/coupled-video.json` | `41624a6d94c8fddecdd1d4cf17ce1763e0beaa1e096e79433dfc57d66713aca3` | 8,192 native UI/live-setter/observer cases |
| `preferences-classic-track-extras-cache-20261107-final/track-extras-cache.json` | `6e55be3b9ea123eb1856567098fa4dc79d3cdd736b278580eb1b2c03cbe48615` | 3,084 saved-setter cases; 20 direct service-disable cases |
| `preferences-classic-pointer-escapes-20261107-final/escapes.json` | `59ceb08dbd7f7f68f8cf4c0070aebfe3038dc049a8fa27c4f97a9781f466a2eb` | Bounded static pointer-escape candidates on all four |
| `preferences-classic-structures-evidence-20261107-final-v2/structures-evidence.json` | `156415cf4e1baf5bf4ffcecfde0e287b21aa4c2b327a0d3c212f537f3d60033e` | Original-byte audit of 12 new Classic 33 export directories; all-four semantic overlay and transition-getter cases |

The evidence overlay uses integer offsets/sizes and half-open intervals
`[start,end_exclusive)`. Its semantic partition covers each complete file extent.
`unresolved_intervals` includes partially understood fields; a successfully
executed getter does not turn a field into a fully understood preference.

The three native harnesses import the prior `research_classic_preferences_full`
`Probe`, `find` and related helpers. Receipts pin this dependency, and the final
audit additionally pins the image/map loader, opcode normalizer and resource-bank
parsers. Relocation-normalized prefixes only locate candidates; the subsequent
execution uses the original bytes and rejects unallowlisted instructions.

Read-only Ghidra exports are discovery aids. The final audit compares every
exported instruction byte with the original Classic 33 OSOS. Ghidra's executable
hash for this project identifies the wrapped ELF, not the raw OSOS. Some Ghidra
functions absorb disjoint tail-call bodies, and exploratory recovery included
unhelpful mid-function/data candidates. Verified bytes do not validate those
function boundaries or inferred C prototypes. Native receipts, explicit call
sites and literal references carry the behavioral claims below.

## Large prefix: what the owner-pointer escapes establish

The renewed pass deliberately started with whole-owner pointers and their
callees. On Classic 33, constructor `08036b34` loads Preferences into owner `+4`,
then initializes runtime lists and pointers beyond the serialized extent.
Library constructor `08036878` stores this owner at Library `+0xce8`.

`080263b0` constructs a TrackData object, stores the owner pointer at TrackData
`+8`, and manipulates owner `+0xb98` and `+0xbac`. These are outside the serialized
Preferences bytes. `0802f0fc` obtains the current TrackData object through
`0802f248` and returns its runtime `+0x3c` member. The reset path `080431a0`
initializes owner `+4`, clears file `0xb00`, and marks the owner dirty. These
escapes therefore cannot be counted as reads of an imagined giant Preferences
array merely because their first argument is the same owner pointer.

The all-four straight-line candidate ledger also finds collation paths that the
initial P-code closure missed. On 33, `08023c00` receives the owner from Browser
flows at `0806bb70`, `080afe44`, `080aff58` and `08203b0c`. The owner identity is
not necessarily function parameter zero. Its deeper text-comparison use is an
explicit remaining lead, including possible language/sort relationships.

The exploratory parent helper `PreferencesPointerClosure.java` produced 161
states/159 functions for the initial 33 pass. It exposes the returned pointer at
`0802f8f8` and stored pointer at `080263d8`; it does not propagate all returned,
stored, dynamic or indirect flows. That helper subsequently changed, so its
current source hash is **not** claimed to reproduce the earlier exploratory
closure. The immutable all-four candidate ledger uses this agent's separately
pinned straight-line scanner.

The large leading region remains unresolved. There is no new claim that it is
padding, a resume record, or unused legacy state. In particular, cross-family
evidence that Video's second word is a balance coordinate has not yet been
independently established for Classic file `+0x0c`.

## Slideshow: corrected field model

The earlier names `slideshow_timing_candidate` at `0xb3b`,
`slideshow_transition_candidate` at `0xb3e`, and `slideshow_timing_auxiliary` at
`0xb49` are superseded by this evidence. The actual timing byte is `0xb3e`;
`0xb3b` and `0xb49` encode transition selection.

Classic 33's legacy settings cache begins at object `+0x60`. Its native compound
commit `0814f718` reads the following members and invokes the individual saved
setters. The same mapping and original compound commit execute on all four.

| File offset | Size | Cache-relative offset | Meaning / current UI values |
| --- | --- | --- | --- |
| `0xb39` | 1 | `+0` | TV Out, retained as part of the shared block |
| `0xb3a` | 1 | `+1` | TV Signal, retained as part of the shared block |
| `0xb3c` | 1 | `+2` | Shuffle Photos: canonical 0 Off / 1 On |
| `0xb3d` | 1 | `+3` | Repeat: canonical 0 Off / 1 On |
| `0xb3e` | 1 | `+4` | Time Per Slide: 0 Manual, 2, 3, 5, 10 or 20 seconds |
| `0xb3f` | 1 | `+5` | Slideshow music selection mode |
| `0xb3b` | 1 | `+6` | Signed transition mode; current writer emits -1 or -2 |
| `0xb40` | 8 | `+8` | Music identity, little-endian unsigned 64-bit |
| `0xb49` | 1 | `+0x10` | Transition effect identifier |

The cache commit writes all these fields, not just the control being edited.
The harness begins with a coherent cache/file pair and verifies the entire
surrounding context, including dirty marking. A Host writer must not copy a
stale firmware-style cache over unrelated file bytes.

The native Repeat and Shuffle Photos actions XOR the existing byte with one.
They do not normalize arbitrary values: `2 -> 3`, `255 -> 254`. Their display
property handles exact 0/1; an arbitrary raw byte is not a legitimate third menu
choice. Both getters and rendering/end-of-album consumers must remain distinct
questions.

### Time Per Slide

The selector maps row indices 0 through 5 to `[0,2,3,5,10,20]`; out-of-range
indices leave the saved state unchanged. Each image's native English ITEM menu
has `Manual`, `2 Seconds`, `3 Seconds`, `5 Seconds`, `10 Seconds`, `20 Seconds`
in that order. The resource rows and their hashes are retained independently;
the full event-registration/router is not emulated.

The runtime consumer reads the byte with sign extension. Zero returns before
scheduling any automatic slide duration. Otherwise it multiplies the effective
seconds value by 1000. If the slideshow controller's album-duration override is
enabled, it uses that runtime album value with a minimum of two seconds. A saved
zero still returns before the override. All 256 raw bytes and five override
conditions execute on every target. Negative signed bytes consequently reach
the arithmetic as negative values, producing wrapped 32-bit millisecond
arguments; the harness does not call those supported durations.

The model lookup and downstream timer operations are explicit adapters. Native
duration selection, sign extension, override, multiplication, and both outgoing
timer arguments execute; actual OS timer scheduling does not.

| Family | Compound commit | Duration selector | Duration consumer |
| --- | --- | --- | --- |
| 24 | `08148e5c` | `081f4210` | `080e75b4` |
| 33 | `0814f718` | `082034ac` | `080eb6c4` |
| 35 | `081671c4` | `0821db30` | `08102804` |
| 38 | `081679cc` | `0821f1a8` | `081029a8` |

### Transitions

The native seven-element selector table is `[0,-1,14,5,24,1,3]`. Each target's
English resource menu binds these ordered choices:

| UI choice | Writer argument | Saved `0xb3b` | Saved `0xb49` |
| --- | --- | --- | --- |
| None | 0 | `0xfe` (-2) | 0 |
| Random | -1 | `0xff` (-1) | 25 |
| Cross Fade | 14 | `0xfe` | 14 |
| Fade To Black | 5 | `0xfe` | 5 |
| Zoom Out | 24 | `0xfe` | 24 |
| Wipe Across | 1 | `0xfe` | 1 |
| Wipe Center | 3 | `0xfe` | 3 |

The getter returns -1 only when the mode byte is `0xff`; every other raw mode
returns the unsigned effect byte. The final audit executes 1,024 getter vectors
per target across every mode byte and four effect bytes. The writer special
case tests the full 32-bit argument for -1; all other integers select mode -2 and
store the low effect byte. Thus a directly supplied 255 is different from -1.
The raw effect domain is not the seven-choice UI domain.

The downstream transition renderer, its random-selection distribution and
effects for noncatalog IDs remain open. The table establishes menu meaning and
storage encoding without claiming that every byte is a usable animation.

### Music

All-four native special-row actions establish `Now Playing -> mode 4` and
`Off -> mode 1`; both clear the eight-byte identity. The exact native vtable slot
used to translate that row is `0x128` on 24 and `0x12c` on the later three, rather
than an assumed uniform layout. Each native resource menu contains those two
fixed rows followed by the dynamic playlist row.

Additional semantics below are **Classic 33 static instruction evidence**.
Selection callback `08210d90`, initialization `08210a28`, and runtime consumer
`080ea66c` form a connected path:

| Mode | Identity / selection and runtime handling |
| --- | --- |
| 0 | Legacy/album-provided path: obtain album-associated playlist/track identities through `08026480`, `080301a0` and `080301c8`; menu highlights Now Playing. Current special-row writer emits 4 instead. |
| 1 | Off; zero identity. Runtime invokes player-side virtual slot `+0xa8` and leaves the local mode at 1; the full player-side effect needs its own closure. |
| 2 | Dynamic playlist selection: full 64-bit playlist member `+0x30`, obtained by `0827e5ec`; runtime reconstructs the selection with `0811b02c`. |
| 3 | Special current On-The-Go playlist selection; identity zero. Predicate `0827e6ac` compares the selected playlist with Library `+0xd28`; runtime selects the last playlist entry. |
| 4 | Now Playing; zero identity. Runtime returns before replacing the current player selection. |
| 5 | Zero-extended playlist member `+0x1b0`; selected when that member is nonzero and the `+0x1b8/+0x1bc` predicate is false. Runtime matches that same identity and predicate. The human meaning of this playlist class is not yet proved. |
| 6 | Same 32-bit identity member, with the `+0x1b8/+0x1bc` predicate true. Runtime matches the true variant. Its human playlist-class label remains open. |
| 7..255 | Accepted by the low-level byte writer but not emitted by the traced current UI; runtime falls through to its Off handling on 33. Preserve unchanged raw values. |

The full-width `0xb40` writer and all 256 mode-byte values execute on all four.
That storage proof does not promote 33's dynamic playlist semantics to the
other firmwares. For 5/6, the precise field predicates are useful durable
knowledge even before the final human labels are established.
The album association in mode 0 is a static interpretation of the slideshow
context calls, not a newly bound UI label; the three identity-provider functions
listed in the table remain the next points for confirming that interpretation.

## Captions and Subtitles are coupled saved preferences

The current UI's toggle rule for either byte is zero to one, every nonzero value
to zero. Enabling Captions (`0xb74`) clears Subtitles (`0xb86`); enabling
Subtitles clears Captions. This clears even malformed other bytes such as 2 or
255. Disabling either leaves the other byte unchanged.

The saved effect is indirect: the first UI path saves its own byte, updates the
media object, and explicitly disables the other media setting on enable. The
media notification reaches the legacy settings observer, which reads the live
getter, compares its cached value, and saves the second byte when needed. The
native live setters themselves also enforce exclusion when their full argument
equals 1 and the other live byte equals 1. That narrower rule alone would not
explain the UI's malformed-other-byte behavior.

| Family | Live Captions / Subtitles member | Caption / Subtitle event |
| --- | --- | --- |
| 24 | `+0x44` / `+0x46` | `0x5000d` / `0x5000f` |
| 33, 35, 38 | `+0x63` / `+0x65` | `0x50011` / `0x50013` |

The harness executes the actual UI handler, saved setters, dirty helper, media
getters/setters and observer. A FIFO adapter delivers emitted events after the
UI call. Classic 33's subject dispatcher `08231040` statically traverses its
subscriber list and invokes callbacks synchronously; registration, lock behavior
and the complete OS dispatch graph are not emulated. Movie subtitle/caption
rendering remains a separate consumer question.

## `0xb4c`: Track Extras Cache, with a concrete artwork participant

All four constructor instruction streams bind the literal
`TTrackExtrasCache`. The actual saved setter and service control loops execute
with a synthetic two-participant collection:

- Equal current raw byte and full requested argument cause no service call or
  dirty change.
- Requested zero disables the service with mode 1, invokes each participant's
  virtual slot `+0x14`, and disables the aggregate allocation service.
- Requested nonzero enables the service, sums registered budgets, updates the
  aggregate allocation service and invokes each participant's slot `+0x10`.
- Direct service disable with low-byte mode zero additionally invokes slot
  `+0x24`; the preference setter uses mode 1, so it does not request that extra
  clear operation.

The collection iterator, concrete callbacks and aggregate allocator are explicit
adapters. The native loops, budget sum, service flags, file byte and dirty marker
execute. Wider callers are a separate raw contract: argument 256 enables the
service but stores byte zero; ordinary UI boolean inputs do not do this.

Concrete payload discovery is currently qualified on **Classic 33 only**:

1. The only direct call found to registration `081957c0` is at `080637c4` in
   initialization `08063704`. It creates participant ID 0 with constructor
   `081ecdf4`, installing vtable `08969318`, if that participant is absent.
   This is a direct-call census, not a proof that indirect registration cannot
   exist.
2. Worker entry `081ec0e0` repeatedly calls `081ecb00` and `081ec538`.
   Preparation `081ec18c` uses artwork browser `08146310`, then
   `08146218 -> 0802f960` to resolve a persistent track ID into the Library
   `+0xd78` artwork database using the track's artwork identifier, with a
   persistent-track-ID fallback.
3. It enumerates image entries with `0824824c -> 08031f64`, builds a native
   filename plus location/size descriptor through
   `080dc564 -> 0802fa7c / 0802fa2c`, and schedules descriptors through
   `081ec944 -> 083841fc`. Filename resolution reaches the artwork entry's
   string-cache token via `080309bc`; colon-prefixed names use that database's
   directory prefix. It is not a guessed fixed filename.
4. The preparation table at `083d9814` contains kinds 8 and 9. Native format
   lookup `080e3a40` returns 1061 for kind 8 and `0xffffffff` for kind 9. The
   second value is not evidence of a second supported artwork format; its
   sentinel/filter consequences need further tracing.

This proves an artwork-caching purpose for the discovered participant. It does
not prove that disabling the preference hides artwork, nor that there are
lyrics/chapter participants. Actual file-read completion, eviction/fallback
behavior, and the concrete participant implementations on 24/35/38 remain
separate questions. In particular, initialization `08063704` explicitly enables
the service, so a saved zero is not yet a proved persistent startup-disable
contract.

## Remaining questions and next entry points

The four current firmwares now share native evidence for compound slideshow
storage, the fixed duration/transition/music choices, caption/subtitle mutation
and observer persistence, and the cache-service preference route. They do not
have identical completeness for the deeper consumers.

| Target | Remaining work after this checkpoint |
| --- | --- |
| 24 / 1.1.2 | Classify leading owner-pointer consumers and possible retained legacy structures; trace dynamic slideshow music modes independently; bind artwork participant and timer/transition end behavior; resolve legacy settings and volume/lock consumers. |
| 33 / 2.0.1 | Follow `08023c00` collation escape and stored TrackData owner pointers; identify playlist classes 5/6, image kind-9 sentinel, actual cache read/eviction and startup adoption; close transition renderer, Repeat/Shuffle playback behavior and observer registration. |
| 35 / 2.0.4 | All 24 questions using its own owner `+0xf00`, plus dynamic menu/tail identity distinctions; do not import 33 playlist/cache-consumer semantics solely from the shared field layout. |
| 38 / 2.0.5 | All 35 questions plus EU limit byte `0xb8c`, regional providers, confirmation/lock interaction and trailing `0xb8d..0xb90`; no new EU write qualification in this pass. |

Other explicit gaps remain from the earlier inventory: legacy `0xaf4`, `0xb02`,
date-format and display flags, `0xb20`, `0xb22`, `0xb48`, `0xb4b`, `0xb62`,
regional radio values, volume/PIN/limit relationships, unnamed menu-mask bits,
and persisted state/unused-byte distinctions. Defaults are still those proved
by the previous all-four defaults/frame harness; this pass does not claim a new
startup-adoption test for every field. “No observed reader” is not “unused.”

## Reproduction and handoff

From `ipod-firmware-lab`, use new output directories; the scripts reject reuse:

```text
uv run --script scripts/research_classic_slideshow_preferences.py --output artifacts/NEW-slideshow
uv run --script scripts/research_classic_coupled_video.py --output artifacts/NEW-coupled-video
uv run --script scripts/research_classic_track_extras_cache.py --output artifacts/NEW-track-cache
uv run --script scripts/inventory_classic_preferences_pointer_escapes.py --output artifacts/NEW-escapes
uv run --script scripts/audit_classic_preferences_structures_evidence.py --output artifacts/NEW-evidence
```

The last script audits the pinned final paths named in its source; the earlier
commands demonstrate fresh reproduction, not automatic retargeting of that
audit. The PEP 723 environments pin Python 3.12, Capstone 5.0.7 and Unicorn
2.1.4. Format the research scripts before producing final receipts.

The new Classic 33 export directories are named
`preferences-classic33-{structures,coupled,cache,photo,photo-runtime,cache-payload,cache-io,cache-source,cache-files,cache-path,music-model,music-label}-export-20261107`.
Each retains C, original-byte assembly and references. The corresponding
`scripts/preferences-classic-*-targets-20261107.txt` files retain seed addresses.
Use Ghidra 12.1.4 in `-readOnly -noanalysis` mode with
`PreferencesClassicRecoverExport.java`; its in-memory recovery changes are
discarded. `structures` and `photo` used the existing read-only
`PreferencesNanoExport.java` with zero expansion depth. No Ghidra project
mutation or firmware edit is required.

This is a bounded checkpoint for the continuing five-group investigation, not
completion of the requested exhaustive Preferences model.

[previous]: preferences-classic-complete-2026-11-07.md
