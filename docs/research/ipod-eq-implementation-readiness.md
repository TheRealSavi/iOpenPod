# iPod EQ: precise viewing and configuration in iOpenPod

Research date: 2026-11-06. This is an implementation proposal supported by native
firmware execution and current-source probes, not an accepted ADR or an application
behavior change. See [firmware findings](ipod-eq-firmware.md) for the preset catalog,
image hashes, disassembly, deobfuscation, and original native receipts.

## Where to implement it

iOpenPod already has the publication path for per-Track EQ text. It lacks a
firmware-aware interpretation and editor, a typed global EQ Preferences field,
and a device workflow for changing that preference. Two existing behaviors also
need attention: a Sync metadata merge can clear an iPod-only assignment, and
SQLite regeneration can replace a differing saved SQL assignment with the CDB
value. The following increments keep these concerns independently reviewable.
[Publication probe][publication], [Sync probe][sync], [Preferences definitions][definitions]

| User surface | Existing implementation seam | Proposed increment |
| --- | --- | --- |
| Settings > iPod Preferences | [Capture and formatting][capture], [Preferences widget][preferences-widget] | Show **Saved EQ**, its raw value when unknown, and capture provenance for individually qualified firmware. |
| Track table's Equalizer column | [Track columns][columns] | Show a preset label or **Use iPod setting**, with retained raw text/source diagnostics. Keep the stable column identifier. |
| Track metadata editor, Audio > Equalizer | [Field descriptors][fields], [metadata editor][editor], [field widget][field-widget] | Add a preset picker with an unchanged state, built-ins, explicit inheritance, and preservation of unknown values. Submit ordinary Track edits through [Library Workspace][workspace]. |
| Track EQ inspection | [Library projection][projection], [SQLite generation][sql-writer] | Distinguish configured CDB/MHOD7 text, saved SQLite text where relevant, and a conditional playback prediction. |
| Save / Sync | [Track writer][track-writer], [write preparation][preparation], [Sync merge][sync-merge] | Keep raw-byte fidelity, inspect final prepared SQL, and preserve iPod-only EQ when Host metadata has no EQ intent. |
| Global EQ configuration | [Preferences codec][codec], Application Layer device workflow, Storage publication | Add only after a firmware reload/flush contract is established; a successful file replacement is insufficient to prove that the change will take effect or persist. |

No arbitrary custom-curve editor is justified by the inspected firmware. Its
qualified playback paths select compiled built-ins. Desktop playback currently
has no EQ operation; changing an iPod assignment must not imply an audition in
the Host player. [Native DSP evidence](ipod-eq-firmware.md#dsp-implementation-and-custom-preset-boundary),
[playback interface][playback]

## What the interface should mean

The device default and a Track assignment are separate settings. In the traced
Classic, Nano 3, and Nano 5 selection paths, global Flat suppresses the Track
override; otherwise a nonzero Track byte wins, including over another non-Off
global preset. A zero Track value inherits the global setting. An unknown
nonzero Track byte can select DSP zero instead of falling back to that setting.
These statements assume a valid Track view and a media kind admitted by the
native selector. [Native selection evidence](ipod-eq-firmware.md#exact-selection-examples)

| Control / displayed fact | Meaning |
| --- | --- |
| Global **Off** | No default effect; Track assignments can still apply. |
| Global **Flat** | Neutral preset that suppresses Track overrides in the qualified selector. The executed Classic/Nano 3 loaders distinguish it from DSP bypass; Nano 5 DSP processing remains unqualified. |
| Global named preset | Default for Tracks with no override. |
| Track **Use iPod setting** | No Track override; it does not force EQ off. |
| Track **Flat** | A real Track preset; distinct from inheritance. |
| **Keep saved value** / unchanged | Preserve the original raw representation. This is editor intent, not an on-device preset. |
| **Mixed - unchanged** | Selected Tracks have different raw values; submitting the dialog must not edit them unless the user chooses a replacement. |
| **Unknown saved value** | Retained evidence that needs interpretation; never silently equate it with Off. |

For a qualified source, an optional prediction can say **Expected from saved
settings: Rock** and state that the Track override wins. If global Flat is
selected, explain that the stored Track assignment is presently ignored by that
selection rule. Missing/stale global capture, unqualified firmware, uncertain
raw parsing, conflicting SQL/CDB values, and unobserved runtime state must remain
visible limits. Saved settings do not prove what the player is processing now.

## Global Preferences: the exact Classic field is known

The follow-up [Preferences investigation][preferences-native] executes the saved
word getter, menu getter, setter, initializer, loader, player initialization,
and whole-payload saver on four separate firmware images. All four use a
little-endian u16 at **Preferences file offset `0xb60`**. Runtime context offset
`+0xb64` is four bytes later because serialization starts at context `+4`.

| Updater family / release | Existing exact Preferences profile | File extent | Format version |
| --- | --- | ---: | --- |
| 24 / 1.1.2 | Classic 1.1.2 | 2,952 | `0x3c` |
| 33 / 2.0.1 | Classic 2.0.1 | 2,956 | `0x3d` |
| 35 / 2.0.4 | Classic 2.0.4 | 2,956 | `0x3e` |
| 38 / 2.0.5 | Classic 2.0.5 | 2,960 | `0x3f` |

The product already defines these four exact framings, but **does not define
their EQ field**. Add a retained raw integer observation to the qualified
definitions and a derived interpretation. The codec's existing changed-field
validation allows unknown unchanged values to survive. Proposed new authored
global values are only 0 and 100-121. Do not expose native unchecked menu-index
lookup as a general setter or silently narrow arbitrary integers to a byte.
[Definitions][definitions], [codec][codec], [native menu probes][preferences-native]

Qualification must establish firmware identity as well as extent/version.
Follow the strongest-evidence pattern used by [Classic calendar qualification][qualification]
and [ADR-0242][adr242]; calendar eligibility itself is not EQ evidence. Do not
promote the broader existing Nano 3 Preferences profile into an EQ profile merely
because its playback routines are now evidenced. Generic fields, capacity, and
generation names cannot substitute for the inspected release.

### Saved word, menu label, and playback byte can disagree

The menu getter compares the entire saved u16 against the built-in table.
Player initialization instead passes its low byte without menu normalization.
The following examples execute identically on all four Classic builds:
[Native initialization and menu evidence][preferences-native]

| Saved u16 | Menu interpretation | Player initialization byte | Selection with a zero Track byte |
| ---: | --- | ---: | --- |
| 0 | Off | 0 | DSP bypass |
| 107 | Flat | 107 | Flat |
| 356 | Off fallback | 100 | Acoustic |
| 363 | Off fallback | 107 | Flat, also suppressing Track overrides |

Consequently, display an unknown saved word as unknown, with a diagnostic such
as **Raw 363; firmware menu fallback Off; initialization byte 107 (Flat)**.
This is a predicted initialization interpretation, not a claim that the currently
running player has reloaded the captured file. A named-preset label alone loses
important evidence.

The native reader accepts some short prefixes and zero-fills missing bytes;
invalid framing and reset paths can return EQ to zero. In particular, a nonzero
u32 at file `+0x04` makes the loader reset Preferences, including EQ. Show that
condition instead of predicting that the saved EQ word will be applied; do not
silently clear the unrelated word. The version is the first little-endian u32.
This permissiveness is not a reason to relax the product's exact-profile
validation. In particular,
partial reads can change a multi-byte unknown value into a different value.
[Loader/reset cases][preferences-native]

### A Preferences file writer needs a lifecycle contract

The native saver copies the retained Preferences context back to the file. It
does not merge a Host's intervening change. A bounded experiment patches a
mock backing file to Rock while RAM retains Jazz; a subsequent dirty flush
restores Jazz. This proves the stale-RAM overwrite mechanism, **not** its actual
ordering in disk mode, at disconnect, or during eject. [Saver experiment][preferences-native]

Before exposing a global Apply control, establish when this firmware relinquishes
ownership, reloads the file, and flushes its old context. A reboot recommendation
alone does not resolve a possible flush before reload. A physical-device
experiment should observe a controlled unrelated setting change, exit/re-entry,
reload, and persisted EQ, using the existing lab acquisition discipline.

The application workflow should separately capture fresh bytes and a file
precondition, encode the qualified change, stage and verify it through Storage,
reparse the resulting bytes, and invalidate the prior observation. It must use
the current Filesystem Session and connection generation. Those steps establish
safe Host publication; the additional firmware lifecycle evidence establishes
that the device will retain and use it. Existing read-only capture does not retain
everything required for this writer. [Capture model][capture],
[Preferences contract](../ipod-preferences.md), [ADR-0097][adr97]

## Track authoring: use the existing Library edit path

`TrackMetadata.equalizer` is currently a raw string. The shared field policy
maps it to MHOD7. Projection takes the last recognized text child; missing and
empty both project as `""`. The retained document still distinguishes absent,
empty, duplicates, and original payload bytes. A detailed inspector must get
those facts from a typed source observation, not reconstruct them from the
semantic string. [Model][track-model], [field policy][field-policy],
[projection][projection]

The new [publication probe][publication] exercises the actual Library
parse/draft/analyze/prepare path for ten source shapes: absent, empty, a normal
token, plain name, unknown ID, low-byte alias, permissive marker text, Nano-style
digit text, explicit zero, and duplicate MHOD7 values. It verifies:

- Unchanged serialization retains the original bytes; unrelated title edits
  preserve the serialized EQ chunks byte for byte.
- An explicit Jazz edit writes `#!#109#!#` to the last recognized EQ child,
  appending one if absent. Earlier duplicates remain unchanged.
- Explicit clear changes that last child to empty; it does not remove every
  MHOD7. An already absent value remains absent.
- SQLite generation publishes the semantic string verbatim, or SQL NULL for an
  empty string. No EQ-specific normalization occurs.

These are product serialization results with synthetic expanded iTunesDB
fixtures, not a complete native database import or a physical-device round trip.
The probe uses the public Library preparation path and supplies no pending
playback sidecars. It does not exercise CDB compression, device-specific SQL
postprocessing or signatures. [Probe source][publication-script]

### Canonical choices and raw preservation

For supported built-ins, the proposed encoder writes `#!#NNN#!#`, with settings
IDs 100-121. This syntax is accepted by the executed Classic/Nano 3 callback and
the independently executed Nano 5 SQL getter. A plain preset name such as `Rock`
is not the firmware encoding. Shared accepted syntax does not mean a shared
decoder: `a1b1c4` gives zero on the tested Classic callback and 114 on Nano 5.
[Track parser evidence](ipod-eq-firmware.md#findings-from-the-actual-firmware),
[Nano 5 parser](ipod-eq-firmware.md#nano-5-has-a-separate-sqlite-text-parser)

Keep the raw string as retained data. Reading an alias such as `#!#356#!#` may
explain its low-byte Acoustic result, but viewing it, editing another field,
or accepting an unchanged dialog must not rewrite it as `#!#100#!#`. Two raw
values with the same interpreted preset still count as mixed for preservation.
Do not reinterpret an arbitrary custom name as a supported custom curve.

The **inheritance encoding** needs an explicit authoring decision and acceptance
test. The current editor clears to empty; `#!#000#!#` also produces zero in the
qualified callbacks and avoids an empty text payload. Neither fact establishes
the complete firmware's duplicate/empty-MHOD7 import policy. Do not promise that
changing the last duplicate always changes playback until that import behavior
is qualified. The probe proves how iOpenPod writes, not which duplicate the
firmware ultimately accepts. A diagnostic/read-only treatment of ambiguous
duplicates can be the initial policy.

## Nano 5: CDB configuration and saved SQL input are different facts

[ADR-0150][adr150] makes iTunesCDB the sole semantic Library read authority.
`IPodLibrary` projects Track EQ from it; it does not read saved `item.eq_preset`
to construct `TrackMetadata`. By contrast, the inspected Nano 5 / family 34 /
1.0.2 firmware's playback getter consumes that SQLite column through a cached
typed row. [Library construction][library], [Nano 5 follow-up][nano-publication]

The follow-up corrects an earlier interpretation: object byte `+0x461` is a
provider mode copied from construction, **not an on-disk EQ-presence flag**.
It gates several metadata getters. The native column-24 accessor reads a typed
cell's value pointer. The new probe checks cached-cell availability, NULL string
pointers, and empty text; it does not prove SQLite NULL conversion or run a SQLite
engine, full row hydration, or a device database-refresh event. There is no
justified Host-authored `+0x461` field to
set. A file change is not proof that an existing playback object reloaded it.
[Provider and cache investigation][nano-publication]

Current preparation generates SQL `eq_preset` from the projected string.
Retention does not preserve a differing old value in that column. The publication
probe deliberately sets primary projected EQ to Acoustic and retained SQL EQ
to Rock; an unrelated title save with SQLite regeneration produces SQL Acoustic.
The same projection is authoritative for CDB devices; the probe's primary input
is the expanded fixture described above. A no-op
serialization does not regenerate SQLite. Device-supplied SQL postprocessing
also participates in preparation, so inspect the **final prepared artifact**
when reporting what a save will publish. [Reproduction][publication],
[SQL writer][sql-writer], [retention][retention], [preparation][preparation]

A precise read-only companion observation should show:

- **Configured Track EQ** from the authoritative CDB projection.
- **Saved playback input** from the captured Library.itdb row, identified by
  native persistent ID, including SQL NULL, empty, missing, or ambiguous rows.
- Any disagreement and the verified result of the next prepared save.
- Capture identity/fingerprint and refresh limits, without claiming live playback.

This observation should not silently replace CDB authority. Changing ownership
would need a new ADR. Final SQL inspection and CDB/SQL diagnostics are useful
even before live reload behavior is understood.

## Sync ownership must be fixed before promising persistent Track configuration

`METADATA_TAG_FIELDS` includes `equalizer`, and `apply_track_tags` copies it from
Host metadata. Host tag ingestion has no EQ mapping and normally leaves the
field empty. The [four-case Sync probe][sync] confirms that the merge clears
nonempty iPod EQ while applying a Host title and retaining the iPod identity.
It also confirms that an EQ-only clear changes the existing tag digest.
[Merge and digest][sync-merge], [Host tag ingestion][tags]

This occurs when the Sync planner selects a metadata update; it is not a claim
that every Sync clears every assignment. The planner's comparison/provenance
logic and execution call sites must be considered together. EQ also participates
in the comparison used to schedule optional Rockbox media-tag updates, while the
tag exporter has no EQ encoder. An EQ-only change therefore needs a focused
publication test for unintended media work. [Planner][sync-plan],
[execution][sync-execution], [tag-update comparison][tag-updates], [exporter][exporter]

The recommended ownership rule is **absence of Host EQ is not a clear request**.
Preserve iPod-only EQ through unrelated metadata updates; allow explicit user
clear through the Track editor. Make merge, comparison, and Sync Details digest
policy agree. If EQ is removed from the digest, account for existing v1 digests
instead of silently reinterpreting them. This is a proposed behavior change
requiring tests and a durable decision; the investigation did not implement it.

## Small shared module, separate observation and authoring

Put pure format/selection knowledge in a small iPodDB EQ module. Its interface
should cover three operations: inspect retained input under an explicitly
qualified consumer, encode an explicit supported choice, and predict selection
from qualified global/Track observations. It should return typed results, perform
no device I/O, and own the one built-in catalog used by Settings, the table, and
the editor. Tests and callers should use the same interface.

The result must retain enough evidence to avoid lossy shortcuts: raw text or
u16, source kind, decoder/profile, parsed value where established, playback byte,
recognized preset, and uncertainty. Model **unchanged**, **inherit**, and
**built-in** edit intent separately. Menu indices, stored IDs, and DSP indices
are different namespaces. Avoid replacing all existing raw strings with an enum
or introducing a generic provider framework for these few known consumers.

The Application Layer owns capture, qualification, freshness, editing intent,
and workflow composition. GUI widgets consume typed observations rather than
reparse strings. Storage alone publishes device files. Device Registry describes
identity/capabilities; it must not read Preferences or become a serializer.
[Architecture](../source_architecture.md), [ADR-0097][adr97], [ADR-0150][adr150]

## Implementation order and acceptance evidence

1. **Read-only precision.** Add the four qualified Classic EQ fields and typed
   observations; display saved global and Track values without normalizing raw
   bytes. Add Nano 5 SQL comparison as a separate optional observation.
2. **Reliable Track authoring.** Decide inheritance/duplicate policy and Sync
   ownership; add the shared encoder, preset picker, and comparison/digest fix.
   Reuse Library Workspace and the existing publication pipeline. Qualify the
   intended firmware's import/reload contract before promising a working device
   edit, including Nano 5 database refresh and cache invalidation.
3. **Conditional selection preview.** Explain the qualified precedence using
   captured provenance and draft Track state. Treat SQL disagreement and unknown
   inputs explicitly; do not claim a live or universal audio prediction.
4. **Global configuration.** Complete device reload/flush qualification and add
   a separate Storage-backed Preferences workflow with fresh preconditions and
   verification. This need not block Track configuration.

| Acceptance surface | Evidence required before shipping the corresponding behavior |
| --- | --- |
| Preferences codec | All four exact profiles; unknown unchanged values retained; only the two EQ bytes change; wrong type/extent/version rejected. The codec receives a caller-qualified profile, not device identity. |
| Capture/qualification/UI | Device identity mismatches rejected before selecting an EQ profile; missing, unreadable, unknown, stale, and available states; unknown word/menu/byte disagreement; no claim of current player state. |
| Track editing | Untouched mixed/unknown values preserved; cancel/reset/no-op; canonical built-ins; explicit inherit; ambiguous duplicates handled by an explicit policy. |
| Library publication | Actual prepare/read-back, unchanged EQ chunk preservation, final SQLite EQ inspected, and relevant compression/checksum paths exercised. |
| Sync | An unrelated Host title update preserves iPod EQ when Host has no EQ intent; explicit clear still works; digest compatibility; EQ-only edits do not cause unintended media retagging. |
| Native contract | Authored values accepted by the intended exact firmware; Classic and Nano 5 decoders remain separate; native duplicate/full-import gaps and Nano 5 cache invalidation/database refresh qualified before claiming a working device edit. |
| Global device publication | Current Filesystem Session, source preconditions, interruption/recovery, verification, and demonstrated device reload/flush ordering. |

Existing test homes are `tests/iPodDB/test_preferences.py`,
`tests/iPodDB/test_classic_calendar_preferences.py`, `tests/iPodDB/library/`,
`tests/iPodDB/SQLiteDB/test_retention.py`, the Preferences inspection/UI tests,
metadata editing/UI tests, and Sync metadata/execution tests. Production behavior
is unchanged in this research pass; the new scripts are evidence probes in the
sibling lab rather than tests of an unimplemented product feature.

## Reproduction and evidence limits

From iOpenPod, choose fresh output paths:

```powershell
uv run python ../ipod-firmware-lab/scripts/probe_iopenpod_eq_publication.py --output ../ipod-firmware-lab/artifacts/eq-product-publication-next.json
uv run python ../ipod-firmware-lab/scripts/probe_iopenpod_eq_sync.py --output ../ipod-firmware-lab/artifacts/eq-product-sync-next.json
```

The receipts record script hashes, relevant source hashes, and baseline commit
`0eeff3fdd19ac0e770f24b086fa63a33014643cd`. The working tree contained unrelated
changes; these were retained. Synthetic product probes and bounded native
execution do not establish complete OS startup, full database import, real audio
output, physical-device persistence, or every firmware family's support. The
linked native notes document which original instructions execute and which
services are mocked. No application behavior, firmware instruction bytes, or
device files were changed by this investigation.

[publication]: ../../../ipod-firmware-lab/artifacts/eq-product-publication-20261106-v2.json
[publication-script]: ../../../ipod-firmware-lab/scripts/probe_iopenpod_eq_publication.py
[sync]: ../../../ipod-firmware-lab/artifacts/eq-product-sync-20261106-final.json
[preferences-native]: ../../../ipod-firmware-lab/notes/eq-preferences-configuration.md
[nano-publication]: ../../../ipod-firmware-lab/notes/eq-nano5-publication.md
[definitions]: ../../src/iPodDB/preferences/definitions.py
[codec]: ../../src/iPodDB/preferences/codec.py
[capture]: ../../src/iOpenPod/app/services/ipod_preferences.py
[qualification]: ../../src/iOpenPod/app/services/classic_calendar.py
[preferences-widget]: ../../src/iOpenPod/GUI/widgets/ipod_preferences.py
[columns]: ../../src/iOpenPod/app/models/track_columns.py
[fields]: ../../src/iOpenPod/app/metadata_fields.py
[editor]: ../../src/iOpenPod/GUI/dialogs/metadata_editor.py
[field-widget]: ../../src/iOpenPod/GUI/widgets/metadata_field_editor.py
[workspace]: ../../src/iOpenPod/app/library_workspace.py
[track-model]: ../../src/iPodDB/library/models.py
[field-policy]: ../../src/iPodDB/library/_field_policy.py
[projection]: ../../src/iPodDB/library/_projection.py
[track-writer]: ../../src/iPodDB/library/_track_writing.py
[library]: ../../src/iPodDB/library/database.py
[sql-writer]: ../../src/iPodDB/SQLiteDB/database.py
[retention]: ../../src/iPodDB/SQLiteDB/retention.py
[preparation]: ../../src/iPodDB/library/_write_preparation.py
[sync-merge]: ../../src/iOpenPod/app/sync_track_details.py
[sync-plan]: ../../src/iOpenPod/app/sync_plan.py
[sync-execution]: ../../src/iOpenPod/app/sync_execution.py
[tags]: ../../src/iOpenPod/app/media/tags.py
[tag-updates]: ../../src/iOpenPod/app/library_tag_updates.py
[exporter]: ../../src/iOpenPod/app/export_tagging.py
[playback]: ../../src/iOpenPod/app/playback/backend.py
[adr97]: ../adr/0097-model-preferences-as-a-lossless-flat-document.md
[adr150]: ../adr/0150-retain-firmware-sqlite-metadata-and-dual-signatures.md
[adr242]: ../adr/0242-qualify-the-latest-classic-calendar-targets.md
