# Preferences owners, retained bytes and Video media caching

This continuation investigates why much of the binary Preferences file remains
unmapped. It distinguishes the persisted payload from the larger runtime owner,
follows owner pointers into playback and database objects, and qualifies one
previously unnamed Video flag. It does not declare the remaining leading bytes
unused, reserved or padding.

## Exact latest Video inputs

| Updater | Release | Original OSOS SHA-256 |
| --- | --- | --- |
| 13 | 1.3 | `f7b7670bafd1d6ac45effa00b4d314550c030218a953468cfc6057d6d80e6ea7` |
| 20 | 1.3 | `f7b7670bafd1d6ac45effa00b4d314550c030218a953468cfc6057d6d80e6ea7` |
| 25 | 1.3 | `784ae3d5540fd2f89e8c947b93629e97f62a06dc311d9745aab143e4db6bb251` |

13/20 share the complete image; 25 has the same executable prefix and additional
trailing bytes. Every new native case independently loads each retained input.
The [earlier Video report](preferences-video-complete-2026-11-07.md) records the
package and runtime-map baseline. No physical device access was performed.

## File coordinates versus runtime objects

The Video Preferences file is `0xB6C` bytes, version `0x39`. Its first byte is
at **owner + 8**. The outer Library object stores this owner at `+0xCA0`.
Owner `+4` points to the live playback object, whose first word points back to
the owner. These are distinct objects with different field coordinate systems.

Constructor `0xA25B4` creates the owner and calls loader `0xAF698`. Playback
constructor `0x9421C` consumes saved volume/balance and EQ fields, installs its
owner back-pointer and constructs additional runtime members. Another constructor,
`0x94988`, stores the owner in an object at `+8` and links runtime lists outside
the saved payload. `0x9B038` returns the owner to callers such as `0x208224`,
which passes it to Track/database construction `0xDE500`.

These pointer escapes are not evidence that every large buffer in a called
function belongs to Preferences. For example, the runtime list at owner `+0xB90`
and allocation state at `+0xB94` are **outside** the saved payload, which ends at
owner `+0xB74`. A matching numeric offset in another class is not a file field.
The [read-only direct export][direct] retains these constructor and call chains.

## Broader pointer-flow discovery

The new [Ghidra helper][closure-script] follows affine owner-pointer expressions
through direct calls, with optional reciprocal playback-pointer recognition and
explicit owner-parameter seeds. It emits reads/writes, call arguments, stored and
returned pointers, source C and original instruction bytes. It never saves
program changes.

The final Video discovery run reached **471 parameter states in 346 functions**.
It retained 475 access observations, including repeated observations of shared
instructions under different parameter states. The independent [audit][audit]
compared **12,021 exported instruction addresses, 48,084 bytes**, against all
three original images. This verifies the exported bytes, not every decompiler
type or inference. The raw [discovery scope][closure-scope] is retained separately.

The traversal is deliberately not described as complete firmware coverage:

- The outer-object parameter and reciprocal pointer members must be bound to
  their actual owners before treating a hit as a file access.
- Dynamic indices, partial PHI expressions, indirect calls, stored pointers and
  returned aliases can require additional manual propagation.
- Known bulk-copy, clearing and string-copy functions are recorded boundaries;
  their whole-buffer accesses do not assign meanings to individual bytes.
- Database-view aliases, missing functions and unvisited entry points remain
  gaps. The absence of a hit does not establish that a byte is unused.

The expanded run found a real consumer for forced file byte `0x91`, detailed
below. It still does not identify the large leading intervals as arrays of
preferences, inactive legacy structures or padding. Earlier exploratory runs
remain separate; one expanded run was interrupted before expression memoization
was added. Only the completed `v4` output backs this report.

## Video file `0x91`: cached media-source eligibility

This u8 field defaults to **1**. Current loader `0xAF698` forces it to **1**,
along with `0xB0A/0xB0B`, regardless of the retained input byte. The other flags
are not assigned cache meanings; a separate `0xB0B` consumer is established below.

Playback preparation `0xEB610`, at instruction `0xEB824`, reads owner `+0x99`,
which is file `+0x91`. Zero skips an optional cached-source path; nonzero checks
`0xBBB84`, which in these latest images is an original two-instruction routine
returning 1. Other Track/runtime conditions still decide whether the cached path
is actually used.

| Contract | Established behavior |
| --- | --- |
| Stored representation | One unsigned byte at file `0x91`; all 256 patterns can be retained in an input file. |
| Current load | Every input `0..255` becomes 1 in the retained native owner. The source file is not rewritten by this loader probe. |
| Runtime gate | 0 disables eligibility; `1..255` enable eligibility at the tested branch. |
| Default | 1. |
| Native saved-file authoring | Editing this byte to zero does not establish a persistent disable setting: the current loader overwrites it. |
| Menu exposure | No ordinary menu control is qualified by this investigation. |

The downstream conversion is explicit. `0x92750` searches a runtime cache entry
using `0x87B94`; an existing entry makes it replace the source identifier with
**`0x4D46494C`, `MFIL`**, put the cache pointer and length at source `+0x110` and
`+0x114`, and retain the entry at playback `+0x29D0`. On a miss, it can construct
an entry through `0x87CEC`. That constructor links the runtime owner list and
calls `0x1153D4` to obtain buffer capacity. These are runtime source/entry fields,
not additional offsets in Preferences. See the [consumer export][consumers].

The broader cache implementation, its scheduler, physical I/O and every Track
eligibility condition remain outside this field-level qualification. The separate
Track-extras service reached during construction must not be collapsed into
this media-source gate merely because both concern caching.

## Native validation and reproduction

The [native probe][probe] passed **1,539 cases**, 513 per exact input:

- All 256 current-loader input bytes, with a patterned entire Preferences file.
  Only the three forced flags change; every other retained byte and the original
  source file remain unchanged.
- All 256 runtime gate inputs through the original `0xEB824..0xEB848` fragment
  and original `0xBBB84`. The result is exactly zero/nonzero, without modifying
  Preferences.
- One original `0x92750` existing-entry conversion per input, proving the `MFIL`
  source identifier, pointer, length and retained runtime reference. Only the
  cache lookup is replaced with an explicit synthetic existing entry.

The imported harness provides disclosed filesystem/platform adapters. These
tests do not run a complete boot or claim physical cache acceptance. The
[native receipt][receipt] pins source images, final script/helper hashes, adapter
addresses and executed original instruction hashes. The probe passed Ruff
formatting and lint checks before this receipt was generated.

From `ipod-firmware-lab`, use a fresh directory:

```powershell
uv run scripts/probe_video_forced_cache_flag.py --output artifacts/NEW-video-cache-flag
```

The read-only discovery command is retained in
`logs/preferences-video-pointer-closure-20261107-v4.log`. Its script arguments
are the new output directory, `scripts/preferences-video-pointer-seeds-20261107.tsv`,
owner member `ca0`, owner getter `9b038`, bulk boundaries
`a8098 a7ed0 7ccd0 9359c`, and reciprocal pointer option `playback:4:0`.
It processes `Video13FW/ghidra/Video13`, program `osos.bin`, with `-readOnly`
and `-noanalysis`. Separate comparison against 20/25 verifies instruction equality;
their independent native cases provide the per-image execution evidence.

## Video file `0xB0B`: prefix-normalized artist selection

A separate direct ARM-instruction scan found reads that the owner-pointer closure
missed. Getter `0x9FAA8` follows TrackData `+0` to its Library, then Library `+8`
to the Preferences owner, and reads owner `+0xB13`, or file `+0xB0B`. Classifier
`0x90850` follows the same selection. This is a concrete example of why missing
alias propagation must not be treated as proof that a field is unused.

| Condition | Selected token | Selected string pool |
| --- | --- | --- |
| Saved byte is zero | TrackData `+0x2C` | Library `+0xE0` |
| Saved byte is nonzero and alternate token is zero | TrackData `+0x2C` | Library `+0xE0` |
| Saved byte is nonzero and alternate token is nonzero | TrackData `+0x30` | Library `+0x10C` |

The original fallback is `0x9F904`. The getter converts the returned byte length
to a UTF-16 code-unit count by shifting right once. Sorting dispatch `0x91D44`
uses this alternate getter for selector `0x08000000`, while selector 4 uses the
ordinary getter. There is no newly qualified ordinary menu switch or persistent
disable contract: current startup forces the byte to 1.

The metadata binding is independently established on Video. Importer `0xD7888`
reads the 24-byte MHOD header, compares its tag with the literal `mhod` at
`0xD8284`, and dispatches type **4 (Artist)** to `0x10DB84` with Library `+0xE0`
and TrackData `+0x2C`. It then invokes
`0x907F4 -> 0x1114DC -> 0x90D88`. That path builds the alternate token in
TrackData `+0x30` using Library's `+0x10C` pool. This closes the connection
between the saved flag, the metadata field and the generated alternate key;
it does not rely on transferring a Mini/Nano field name.

Normalizer `0x90D88` compares counted UTF-16 prefixes, bounds the input to 255
code units, and substitutes the matched prefix with its table replacement.
The table pointer/count at owner `+0xB88/+0xB8C` are outside Preferences. Each
runtime table record occupies 256 bytes, with its replacement half beginning
128 bytes into the record. Exact multilingual entries, their loading lifecycle
and all collation behavior remain open.

The [alternate-text probe][text-probe] passed **1,536 additional native cases**:
all 256 raw flag values with an absent and present alternate token, independently
on 13/20/25. Original getter/fallback instructions run unchanged; the shared
string-pool service `0x10A650` is an explicit adapter that records the requested
pool/token and supplies a synthetic pointer and length. Every case preserves the
entire patterned Preferences payload. The [receipt][text-receipt] pins the final
script/helpers, original executed instruction hashes, four static export trees,
and an instruction-byte comparison against all three images.

The MHOD importer and normalization chain above are original static instruction
evidence, separately byte-audited; those functions are not emulated by the getter
cases. The [Mini/Nano 1 investigation][mini-followup] independently establishes
the related behavior on its exact targets. The flag remains partially understood
because the full normalization and adoption contracts are still open. File
`0xB0A` remains unresolved.

Reproduce with a fresh directory from the lab:

```powershell
uv run scripts/probe_video_alternate_text_preference.py --output artifacts/NEW-video-alternate-text
```

## Consequences for iOpenPod

The [consolidated Video inventory][combined] integrates both fields above with
the [volume, Photo, Radio and lock-file follow-up][video-followup]. Its
[combiner][combine-script] checks all three image identities and retains every
unrelated field and unresolved interval. Both newly named flags remain partial;
the conservative byte counts do not increase merely because their names improve.
The derived artifact pins its script and all three input inventories/receipts.

The file contains a mixture of user choices, firmware-forced controls, retained
state, migration inputs and unresolved bytes. A complete model must distinguish
these roles rather than offer an editor for every recovered scalar.

This report does not expand the application write surface. Unchanged bytes remain
authoritative, and no host normalization to the firmware's three forced values
is introduced. Unknown preferences and datetime values remain nonblocking for
Library loading, Calendar work and Sync. Further work should follow the explicit
stored/returned aliases and database-view owners, not infer unused space from
the current discovery gaps.

[direct]: ../../../ipod-firmware-lab/artifacts/preferences-video-prefix-deep-20261107-export-v1/index.tsv
[closure-script]: ../../../ipod-firmware-lab/scripts/ghidra/PreferencesPointerClosure.java
[closure-scope]: ../../../ipod-firmware-lab/artifacts/preferences-video-pointer-closure-20261107-v4/scope.txt
[audit]: ../../../ipod-firmware-lab/artifacts/preferences-owner-pointer-audit-20261107-v1/receipt.json
[consumers]: ../../../ipod-firmware-lab/artifacts/preferences-video-forced-flags-20261107-export-v1/index.tsv
[probe]: ../../../ipod-firmware-lab/scripts/probe_video_forced_cache_flag.py
[receipt]: ../../../ipod-firmware-lab/artifacts/preferences-video-forced-cache-20261107-v1/receipt.json
[text-probe]: ../../../ipod-firmware-lab/scripts/probe_video_alternate_text_preference.py
[text-receipt]: ../../../ipod-firmware-lab/artifacts/preferences-video-alternate-text-20261107-final-v3/receipt.json
[mini-followup]: preferences-mini-nano1-deep-followup-2026-11-07.md
[combined]: ../../../ipod-firmware-lab/artifacts/preferences-video-consolidated-20261107-final-v3/field-inventory.json
[combine-script]: ../../../ipod-firmware-lab/scripts/combine_video_preferences_evidence.py
[video-followup]: preferences-video-deep-followup-2026-11-07.md
