# EQ evolution: Mini 2, Video 5/5.5 and four Classics

Research date: 2026-11-06. This extends the
[firmware investigation](ipod-eq-firmware.md) and
[implementation proposal](ipod-eq-implementation-readiness.md). It records
research and proposed support boundaries; it changes no application behavior
and is not an accepted architectural decision.

The subsequent [accepted Track EQ decision](../adr/0246-edit-track-eq-with-canonical-presets-and-preserve-it-during-sync.md)
implements the shared translated picker, canonical marker writer and Sync
preservation described here. Global EQ configuration and conditional playback
prediction remain separate.

The strongest finding is continuity in the built-in filters alongside a change
in control semantics. Mini 2 and Video use a localized-name registry and a
separate enable flag. The Classics use numeric preset IDs and a special global
Flat rule. Their normal compiled coefficient banks are byte-identical after
accounting for the older table layout. **One catalog is appropriate; one
unconditional decoder, Preferences layout or playback rule is not.**

## Exact targets and evidence

| Target | Inspected updater / release | Saved Preferences extent / version | Saved global EQ representation |
| --- | --- | --- | --- |
| Mini second generation | 7 / 1.4.1 | 2,876 / `0x16` | Enable byte at file `+0x8e0`; counted UTF-16 preset name at `+0x8ea` |
| Video fifth generation variants | 13 and 20 / 1.3 | 2,924 / `0x39` | Same field offsets and name representation as Mini; independently qualified framing |
| Enhanced Video, locally called 5.5 | 25 / 1.3 | 2,924 / `0x39` | Same Video contract, independently bound complete image |
| Classic | 24 / 1.1.2 | 2,952 / `0x3c` | Little-endian u16 preset ID at file `+0xb60` |
| Classic 120 GB | 33 / 2.0.1 | 2,956 / `0x3d` | Same numeric field |
| Classic updater 35 | 35 / 2.0.4 | 2,956 / `0x3e` | Same numeric field |
| Classic updater 38 | 38 / 2.0.5 | 2,960 / `0x3f` | Same numeric field |

These are file offsets. Older serialization begins at its owner object `+8`,
so the name is runtime owner `+0x8f2`; Classic serialization begins at `+4`, so
its ID is runtime owner `+0xb64`. Mixing file and owner offsets would corrupt
the wrong bytes. The exact-image notes contain hashes, maps, function addresses,
native receipts, mocks and limitations: [Mini][mini], [Video][video],
[Classic Preferences][classic-prefs], [coefficient comparison][dsp].

New checks cover 660 Mini callback/selection/Preferences case rows,
29 MHOD7 imports and 12 menu/Track sequences on each Video image, plus 230
Mini lower-DSP bank-selection/loading cases. Registry construction and Video
Preferences have additional checks. These execute original ARM instructions
with documented service adapters; none is a physical playback test.

Video 13 and 20 have identical complete OSOS images. Video 25 has the same
prefix plus 1,536 zero bytes. Keep three provenance identities and native
receipts even when sharing implementation. The four Classics also retain
separate exact Preferences profiles despite shared EQ logic. These findings
do not qualify Mini 1, earlier full-size models, another release or every nano.

## What changed over time

### Names and registry became numeric state

Both eras expose the same 22 built-in presets, with external marked IDs
100..121; Flat is 107 and Rock is 116. Off is a separate global menu entry.
Use the [full catalog](ipod-eq-firmware.md#built-in-presets), subject to
the evidence for each exact target.

In the older firmware, MHOD7's marked text passes through a `resm` callback.
It parses the marked number, obtains a localized resource string, and stores
that name in the Track's string pool. Playback resolves the name against the
runtime registry. Global Preferences also store a counted name. The Mini
callback maps ID 100 to resource 10305; Video uses a different resource range.
Consequently, resource IDs and localized strings are firmware data, not a
universal Host-side encoding. Plain MHOD7 `Rock` is not equivalent to the
canonical marked string `#!#116#!#`. [Mini import trace][mini], [Video import trace][video]

The Classics' `rsid` callback instead produces a numeric Track value. Import
stores a u16 and playback consumes its low byte. Global Preferences store a
u16, while menu display and initial playback do not always interpret unknown
values identically. Classic legacy-name migration is not its current Track
importer. [Classic import and selection](ipod-eq-firmware.md),
[saved-word distinctions][classic-prefs]

Canonical `#!#100#!#` through `#!#121#!#` strings therefore provide a shared
authoring vocabulary. Reading arbitrary existing values remains target-specific:
Mini's native decimal conversion accepts signs/whitespace that Classic's
parser does not, and Classic has byte-narrowing behavior that must not be
invented for the older name path. Preserve raw text; do not normalize malformed
or unknown strings merely because their displayed label is unclear.

### Flat and unknown assignments changed selection semantics

The following older results are from native menu/selection paths with controlled
services. They describe those paths, not a full boot or physical listening test.

| Configuration | Mini 2 / Video tested path | Four Classics tested selector |
| --- | --- | --- |
| Global Acoustic, Track Rock | Select Rock | Select Rock |
| Global Flat, Track Rock | Select Rock; global Flat has no override veto | Select Flat; Track override suppressed |
| Enabled global Rock, Track has no usable override | Restore global Rock | Zero Track value inherits Rock |
| Unresolved runtime Track name / unsupported numeric byte | Name lookup failure restores global in the older selector | Nonzero unsupported byte replaces the global ID, then maps to DSP bypass |
| Global Off, Track Rock | Tested menu-Off path retains disabled state when selecting Rock; complete playback behavior unresolved | Select Rock |
| Track Flat under an enabled non-Flat global | Select zero filter slots | Select the explicit neutral Flat section |

**The Off row conflicts with the documented Mini behavior.** Apple's
[Mini 2 User Guide, printed page 34][mini-manual] says per-song iTunes EQ applies
when global EQ is Off. The native tests execute the actual Off menu path and
subsequent Track selection; this is not merely a manually forced disable bit.
They still do not prove that no later event re-enables processing in the complete
player. Keep the discrepancy open. iOpenPod should show the saved Off setting
and Track assignment separately, and withhold a definitive older-model
effective-EQ prediction for that case. [Mini evidence][mini], [Video evidence][video]

### The normal filters were retained, but their packaging changed

Mini and Video store 55 records containing two five-coefficient sets each;
record zero is empty. Deinterleave records 1..54 and both resulting banks are
byte-for-byte identical to the Classic 44.1/48 kHz banks across all four builds.
For 21 of 22 presets, older one-based section selectors map exactly to Classic
zero-based section indices. Flat differs: older Flat selects no sections;
Classic Flat explicitly selects a neutral section. [Hash-pinned comparison][dsp]

The older ten-float/ten-short intermediate representation is misleading if read
as a graphic equalizer. The numbers become integer filter selectors, with only
three nonzero slots used by built-ins and five transported to the lower engine.
They are not ten user-adjustable dB bands. A Mini hardware-dependent alternate
bank also exists; its downstream control behavior and physical bank selection
are not fully qualified. Shared normal coefficients alone do not prove equal
rounding, clipping, headroom, rate conversion or audible output. [Native DSP trace][dsp]

The subsequent [preset-values investigation](../../../ipod-firmware-lab/notes/eq-preset-values.md)
exports every coefficient and calculated frequency-response gains for both
banks. Its recurrence is checked against native Classic sample processing;
those linear gain curves are not stored ten-band slider settings or physical
audio measurements.

No inspected import/selection chain establishes an arbitrary custom curve or
external `EQPresets` consumer. That is a bounded negative finding, not proof
that every possible firmware path rejects every custom file. Offer supported
built-ins and retain unknown data; do not infer a custom-curve editor from a
registry node or a ten-slot structure.

## How iOpenPod should support these devices

### Share the editor and publication path

Keep a semantic built-in catalog separate from retained raw
`TrackMetadata.equalizer`. One picker can offer unchanged, **Use iPod setting**,
and the 22 named presets. Explicit preset selection emits the canonical marker;
explicit inheritance is separate from unchanged/unknown data. Continue through
the existing Library Workspace and iPodDB MHOD7 publication path.

Mini 2, Video and Classics already use iTunesDB under the accepted publication
policy. Mini/Video need no new database backend, CDB path or SQLite workaround.
Their registry profiles use baseline `0x30` with no database checksum; the
Classics use HASH58. Preserve [ADR-0171's existing older-device authoring policy][adr171].
An EQ edit does not justify unrelated Track-header changes.

The existing [Sync ownership problem](ipod-eq-implementation-readiness.md#sync-ownership-must-be-fixed-before-promising-persistent-track-configuration)
must be fixed for every target: missing Host EQ metadata is not an explicit
request to clear an iPod-only assignment. Unknown raw values, duplicate MHOD7
children and unrelated edits need lossless preservation. Native duplicate-entry
ordering is still an independent gap; an existing writer policy is not proof
of firmware precedence.

### Keep target-specific interpretation small and explicit

Use an Application Layer table keyed by qualified updater, release and compatible
Device Profile. Associate each target with a Track decoder/selection policy and
an exact Preferences profile. Share implementations only where independently
verified. Do not add one generation-wide `supports_eq` boolean or infer EQ
support from calendar qualification.

USB identification alone is insufficient: `0x1205` spans both Mini generations
and `0x1209` spans Video 5/5.5. Use the repository's strongest-authority evidence
pattern and retain conflicts. Unknown EQ qualification must not prevent ordinary
Library use. [USB identity mappings][catalog], [registry metadata][registry],
[calendar qualification pattern][qualification]

In iPodDB, the Preferences codec should remain a pure, lossless byte codec.
Add exact Mini/Video framing and a counted-text observation with raw enable
state, count and retained bytes. Preserve unknown/localized names rather than
guessing English equivalence. Do not put EQ into the existing generic
2,924-byte Video layout based only on matching length. Mini 2's 2,876-byte
layout is also not the generic 2,892-byte fourth-generation layout.
[Definitions][definitions], [codec][codec], [ADR-0097][adr97]

Current implementation traps need deliberate treatment: format-version checks
are tied to `ClassicClockPreferences`; base-field editing assumes integers;
non-Classic extension writing currently assumes Nano DST or volume-limit units.
A name-bearing EQ profile cannot safely be added by copying a Classic field
definition. The Application Layer owns identity qualification, while Storage
owns any future device-file mutation. [Preferences capture service][capture]

### Separate saved configuration from playback predictions

Show **Saved EQ** with capture provenance. On older targets display the saved
name and enable state independently when inconsistent or unknown. On Classics
retain the full saved word and distinguish it from menu interpretation and the
initial low-byte playback value. Do not label a saved-file observation as live EQ.

A conditional prediction can explain that global Flat suppresses a Track on a
qualified Classic, while an enabled older Flat permits the Track override.
Unknown localization, malformed input, missing/stale capture, or the unresolved
older Off case should produce an explicit unknown prediction, preserving the
underlying settings. This is a model-specific explanation within one UI, not
different editors for each generation.

Global writes remain a later increment. Both eras save a retained RAM payload;
older saves also distinguish the global remembered name from a temporary Track
override. A Host patch may be overwritten or may not reload. Establish the
physical reload/flush sequence before offering Apply, even after pure codec
editing passes. Desktop playback still does not audition iPod EQ.

## Next acceptance work

1. Implement exact, read-only saved EQ observations and target qualification;
   test unknown versions, conflicting identity, localized/unknown names and
   byte-preserving unchanged serialization.
2. Add the shared preset picker/canonical encoder and fix Sync ownership;
   validate prepared MHOD7 bytes and explicit unchanged/clear semantics.
3. Physically resolve Mini/Video Off versus Track behavior, global Flat versus
   Track behavior, malformed assignments, and language changes. Record exact
   updater/release and independent Track/global settings.
4. Test Preferences reload and stale-RAM flush before global Apply. Only after
   those results should an ADR authorize the complete device workflow.

Hardware chronology and final software chronology differ. Mini 2 launched in
2005, Video in 2005, enhanced Video in 2006 and Classic in 2007; this comparison
uses the retained final/selected software builds, not snapshots of every launch
firmware. Family 38's package date does not establish a new marketed hardware
generation. [Apple Mini launch][mini-launch], [Video launch][video-launch],
[enhanced Video launch][enhanced-launch], [Classic launch][classic-launch]

[mini]: ../../../ipod-firmware-lab/notes/eq-mini2.md
[video]: ../../../ipod-firmware-lab/notes/eq-video.md
[dsp]: ../../../ipod-firmware-lab/notes/eq-legacy-dsp.md
[classic-prefs]: ../../../ipod-firmware-lab/notes/eq-preferences-configuration.md
[definitions]: ../../src/iPodDB/preferences/definitions.py
[codec]: ../../src/iPodDB/preferences/codec.py
[capture]: ../../src/iOpenPod/app/services/ipod_preferences.py
[registry]: ../../src/device_registry/metadata.py
[catalog]: ../../src/device_registry/data/catalog.py
[qualification]: ../../src/iOpenPod/app/services/classic_calendar.py
[adr97]: ../adr/0097-model-preferences-as-a-lossless-flat-document.md
[adr171]: ../adr/0171-use-standard-track-headers-on-mini-2-and-ipod-video.md
[mini-manual]: https://cdsassets.apple.com/live/6GJYWVAV/user/ma96_ipod_mini_2nd_gen_userguide.pdf
[mini-launch]: https://www.apple.com/newsroom/2005/02/23Apple-Unveils-New-iPod-mini-Starting-at-Just-199/
[video-launch]: https://www.apple.com/newsroom/2005/10/12Apple-Unveils-the-New-iPod/
[enhanced-launch]: https://www.apple.com/newsroom/2006/09/12Apple-Introduces-the-New-iPod/
[classic-launch]: https://www.apple.com/newsroom/2007/09/05Apple-Introduces-New-iPod-classic/
