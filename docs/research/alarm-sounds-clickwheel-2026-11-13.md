# Clock Alarm sounds in Classic and Nano 3–5 firmware

Research date: 2026-11-13. This follow-up resolves the sound fields that the
[initial seven-image investigation](alarms-clickwheel-firmware-2026-11-13.md)
preserved without authoring. Sound selection is now qualified from native
consumers, setters, resource banks and original-instruction probes. No physical
iPod or mounted device was written, and audible playback was not tested.

The later [Playlist ordering investigation](alarm-playlist-ordering-2026-11-13.md)
resolves the collation provider and final On-The-Go row. It also corrects the
initial empty-folder interpretation: the native exception applies to an attached
Smart Playlist with no child Playlists.

## Scope and primary evidence

The exact OSOS inputs and runtime maps are the seven hash-bound images in the
initial report: Classic updater 24/33/35/38, Nano 3 updater 26, Nano 4 updater 31,
and Nano 5 updater 34. The additional probe executes each image's original tone
parser and line reader with 12 vectors: **84 native parser cases**. Native number
conversion also runs unchanged. File reads and string allocation/copy/substring
operations are bounded in-memory adapters; Nano 4/5 string count/search helpers
are adapted as well. These are parser executions, not device audio tests.
[Probe source][parser-probe], [hash-bound results][parser-results]

The language pass extracts 21 default names independently from each Classic and
Nano 3 image, 22 from Nano 4's packaged language catalog/resources, and 30 Nano 5
locale defaults. Nano 5's original locale-to-resource-filename switch executes
for all **29 external language resources**; US English is embedded in OSOS.
Together this follow-up adds 113 original-instruction cases. Resource extraction
and the following static call-chain traces are separate forms of evidence.
[Localized resources][locales], [native filename switch][locale-switch]

The complete tone setter, playback dispatcher, name lookup, default constructor,
directory scan, collection initializer and note-queue bodies each uniquely match
across all four Classic images and Nano 3 after normalizing branch operands and
PC-relative literal displacements. Their individual byte hashes are retained.
This supplies cross-image static support in addition to the seven independently
executed parsers; it does not replace checking each image's resource contents.
[Matched native sound spans][sound-spans]

Nano 4's RSRC is a FAT16 filesystem within its preserved `Firmware.MSE`; the
locale probe checks the MSE against its acquisition receipt. Nano 5's 29 extracted
files are compared byte-for-byte with the FAT16 payload of the original RSRC
component, SHA-256
`643564c222bfcdd2276cf2eff6079da78d9a0f6adb60f8f9a747b6fb0bac28af`.
Each locale file has its own retained hash. Resources are primary firmware
contents, not translations supplied by the Host. [Extraction probe][locale-probe]

The parser probe is repeatable from the sibling firmware lab with a new output:

```powershell
uv run scripts/probe_alarm_tone_parser_20261113.py --output artifacts/alarm-tone-new.json
```

## Two independent saved sound fields

| Persisted field | Native object member | Meaning |
| --- | --- | --- |
| Token 8, unsigned word | `+0x1c` | Native Playlist menu selector; `0xffffffff` means none |
| Token `0x3c`, UTF-8 plus NUL | string object `+0x20` | Tone collection name, taken from file contents or localized default |

The tone setter copies the selected collection item's **name**, not its filename,
path, array position, or resource ID. A negative tone-menu selection assigns an
empty string. The Playlist setter writes only the scalar selector. Neither
setter clears the other field, changes the saved enable gate, or imposes mutual
exclusion. Nano 4 and Nano 5 independently have these same stores.
[Classic tone setter][tone-setter], [Classic Playlist setter][playlist-setter],
[Nano 4 tone setter][nano4-setter], [Nano 5 tone setter][nano5-setter]

Classic playback first considers the Playlist selector when invoked normally.
A non-sentinel selector starts the selected Playlist. Independently, a nonempty
tone name is resolved and played. Therefore a malformed or deliberately authored
record can request both. The application expresses an exclusive sound choice by
explicitly clearing the other field; this is application behavior, not a claim
that the native setters do so. [Playback dispatcher][playback]

Control 4 with no Playlist and a nonempty tone name still takes the tone path.
The tone branch does not distinguish control 4 from 8. Both are nonzero scheduler
gates. A separate legacy default-beep branch requires `(control & 0x0c) == 0x0c`
and no Playlist. Consequently the constructor's control 8 plus empty tone name
and no Playlist is **not proof of an audible default**. A new Host alarm should
explicitly select a qualified tone. Changing an existing sound need not force
an off/on transition merely to normalize the gate. [Playback instructions][playback-asm]

## Tone collection and file format

The collection uses `iPod_Control/Tones`, with reserved default filename
`Beep.tone`. It inserts the default first, then enumerates regular directory
entries until the collection contains 20 tones. Directory entries, empty names,
leading-dot names and the exact reserved filename are skipped. There is **no
extension filter**. At most 19 custom tones fit, and membership above that limit
depends on filesystem enumeration order. [Classic initialization][tone-init],
[Classic directory scan][tone-scan], [Nano 5 directory scan][nano5-scan]

A tone file is a small text sequence:

```text
Tone name
540 200
676 400
```

The first nonblank CR/LF-delimited line supplies the native name. Subsequent
nonempty lines supply frequency and duration, separated at the **first ASCII
space**. Each note occupies two unsigned 16-bit values; the native object holds
up to 1000 notes. Native playback queues those pairs without interpreting the
file's name as a path. [Classic parser][classic-parser], [Nano 4 parser][nano4-parser],
[Nano 5 parser][nano5-parser], [tone playback][tone-play]

The executed edge cases establish details that a generic text parser would miss:

- CR and LF blank lines are skipped; NUL ends one line, not the whole file.
- A line can hold 253 bytes before CR/LF. A 254-byte line is returned only when
  the next read is EOF or NUL; a delimiter after 254 bytes makes that read fail.
- Firmware ignores the first line-read status. Thus an overlong header can
  produce a native-valid empty name. Empty files and named files with no notes
  can also be native-valid but produce no audible notes.
- A note with no ASCII space invalidates the tone. A tab is not a separator.
  An extra space at the beginning of the second operand produces zero.
- Decimal prefixes are accepted; trailing text is ignored, and values truncate
  to unsigned 16-bit storage. The 1001st note is not added.
- Classic/Nano 3 convert a leading sign to zero. Nano 4/5 consume leading signs;
  `-3 +4` becomes frequency 65533, duration 4. This is independently executed,
  not inferred from the shared token format.

[All seven native case sets][parser-results]

iPodDB reproduces these bounded rules, retains the original bytes, and exposes
name, notes, native validity and interpretation issues. Invalid UTF-8 is not
guessed. Its 1 MiB capture limit is a Host bound, not a firmware file-size claim.
Without an exact profile, signed note operands remain unqualified. The optional
profile distinguishes the verified numeric routines.
[Pure parser](../../src/iPodDB/alarms/tones.py), [native-derived tests](../../tests/iPodDB/test_alarm_sounds.py)

## Default Beep identity and localization

Firmware first tries to parse `Beep.tone`. If valid, it **overwrites its internal
name with the current localized Beep resource**. If unavailable/invalid, it
synthesizes eight alternating notes: 540 Hz for 200 ms, then 676 Hz for 400 ms,
repeated four times. The default name is still the localized resource. Native
code can also save that default file when its directory is available; iOpenPod
does not need to create it merely to choose the default.
[Classic default constructor][tone-default], [Nano 5 default constructor][nano5-default]

Name lookup is exact and case-sensitive, using native decoded-character equality.
The first matching collection item wins. Failed nonempty-name lookup falls back
to the default object. Display additionally translates the literal name `Beep`.
The saved string `Beep` therefore cannot universally stand for the default: on
a non-English device a custom tone literally named `Beep` can match that string,
while the default object's actual name is localized. [Lookup][tone-lookup],
[fallback playback][tone-fallback], [Nano 5 display][nano5-display]

The mapping is exposed by `default_alarm_tone_name(profile, language)` and the
framing-aware `saved_alarm_tone_name(data, profile)`. Unknown language, unsupported
profile, ambiguous XML scalar or mismatched binary framing yields `None`; no
Host language or presumed English value is substituted.

| Image | Language source | Qualified profile |
| --- | --- | --- |
| Classic 24 | `Device/Preferences`, full word `+0xaf8` | `PreferencesProfile.CLASSIC_6_1_1_2` |
| Classic 33 | same | `PreferencesProfile.CLASSIC_120GB_2_0_1` |
| Classic 35 | same | `PreferencesProfile.CLASSIC_UPDATER_35_2_0_4` |
| Classic 38 | same | `PreferencesProfile.CLASSIC_UPDATER_38_2_0_5` |
| Nano 3 | same | `PreferencesProfile.NANO_3_1_1_3` |
| Nano 4 | same; distinct numeric catalog | `PreferencesProfile.NANO_4_1_0_4` |
| Nano 5 | `Device/iPodSettings.xml`, `General.Language` | `NamedPreferencesProfile.NANO_5_1_0_2` |

Paths above are relative to `iPod_Control`. Nano 4's language remains in the
binary Preferences store, not its separate extensionless named-settings store.
Nano 5 uses exact locale spelling such as `en-US` and `de-DE`; the resource
filenames use underscores. The native switch independently maps four-character
locale identities to those filenames. [Language resource joins][locales],
[Nano 5 registered language default][named-registration], [resource file selection][resource-selection]

Classic and Nano 3 have 21 entries. For example saved codes 3, 10, 17 and 22
produce `Signalton`, `ビープ音`, `嘟嘟声` and `sygnał`. Nano 4 adds UK English at
code 1 and shifts the other nonzero codes by one. Nano 5 includes additional
resources such as `pt-BR` → `Bipe`, `ar-SA` → `صفير`, and `th-TH` → `บี๊บ`.
UK English lacks its own Beep entry and resolves through the English provider.
All spellings come from the per-image resource join, including capitalization.
[Complete locale catalog][locales], [provider fallback][resource-fallback]

For deterministic Host custom-tone choices, the application can require at most
19 eligible regular-file candidates, readable and interpretable captured files,
unique nonempty names, and exclusion of the current default name and literal
`Beep`. Under those conditions every custom entry fits, and filesystem ordering
does not change exact-name resolution. Counting only successfully parsed entries
while ignoring unreadable candidates would not establish this condition. The
language source and relevant tone captures must remain part of publication's
source evidence. These are application qualification rules derived from the
native cap and lookup, not an additional native restriction. [Scan][tone-scan],
[lookup][tone-lookup]

## Playlist selector identity and remaining projection work

Token 8 is **not a Playlist persistent ID**. The Alarm menu callback stores
the selected row minus one, with its none row becoming `0xffffffff`. Playback
passes the scalar to `080ef888`, which selects native library array element
`selector + 1` through `08045088`. The name getter uses the same offset. The
browser count wrapper subtracts one from native owner `+0xd4c`; the Alarm setter
subtracts one again before validating. These are positional dependencies, not
a stable identity lookup. [Menu selection][playlist-menu], [player selection][playlist-player],
[name wrapper][playlist-name], [array lookup][playlist-array], [setter][playlist-setter]

That array is owner `+0xd48`, assembled by `08046cd8`. It excludes native
`flags130 & 0x80` and podcast flag `flags150 & 0x10`. Native `flags130 & 0x40`
bypasses the subsequent count/media checks. Otherwise the importer evaluates
an entry-tree predicate, retains attached Smart leaves even when empty, and filters nonzero aggregate
media kinds against mask `0x12d`. The count predicate walks native entry trees;
it is not simply the Host snapshot's track-count property. [Library finalizer][library-finalizer],
[count predicate][playlist-count]

Crucially the fill loop calls `08030ca0(..., 1)`, whose cached array builder
copies preorder and **sorts** it. Comparator `080893d0` puts `flags130 & 0x40`
entries first, compares native names through `080243b8` mode `0x1b`, then uses
native unsigned member `+0x2c` as a tie-break. The
[later investigation](alarm-playlist-ordering-2026-11-13.md) executes the provider
and comparators across all seven images and resolves the final On-The-Go row,
Smart-leaf inclusion and Classic 2.0.1 entry predicate. Complete source import
projection and variant array consumers remain the implementation gate.
[Array builder][playlist-sort], [comparator][playlist-comparator],
[comparison model][collation]

Consequently neither raw MHYP order nor `LibrarySnapshot.playlists` order may
be substituted for this selector. The raw scalar codec can preserve or explicitly
patch a qualified value, but this pass does not claim a complete Host-generated
Classic Playlist menu projection. A future projection must return native
positions and stable Playlist identity together and bind explicit sound selection
to captured iTunesDB evidence. Library writes leave saved Alarm selectors alone,
as directed in [ADR-0262](../adr/0262-leave-alarm-selections-unchanged-during-library-writes.md).
No preservation across Sync reorderings is planned. The sound projection is a
specific remaining native dependency, not evidence that Host sound selection is
inherently impossible.

## Implemented byte contract and adoption limits

`update_alarm` and `add_alarm` accept `tone_name` and `playlist_selector`.
For updates, `None` retains a field, `""` clears the tone, and `0xffffffff` clears
the Playlist selector. The legacy `AlarmRecord.label` attribute remains a
compatibility alias; `tone_name` states its meaning. Tone names are authored as
valid UTF-8 plus NUL, bounded to 254 name bytes. Replacing a variable-length name
changes only that field's length/payload; unknown fields, sibling containers and
all other record bytes remain preserved. Malformed/ambiguous source fields and
forged edit capabilities cannot authorize writes.
[Codec](../../src/iPodDB/alarms/codec.py), [tests](../../tests/iPodDB/test_alarm_sounds.py)

Mounted-file publication and active firmware adoption remain different events.
The saved language and tone directory can differ from objects retained in RAM.
Native services may later save their retained alarm collection over a Host edit.
These results qualify persisted encodings and deterministic catalog construction;
they do not establish immediate reload, actual speaker routing, wake delivery or
physical playback. Storage capture/fingerprint checks protect the specific Host
publication. Device lifecycle verification remains separate.

[parser-probe]: ../../../ipod-firmware-lab/scripts/probe_alarm_tone_parser_20261113.py
[sound-spans]: ../../../ipod-firmware-lab/artifacts/alarm-sounds-20261113-classic-span-matches.json
[parser-results]: ../../../ipod-firmware-lab/artifacts/alarm-sounds-20261113-parser-native-v3.json
[locales]: ../../../ipod-firmware-lab/artifacts/alarm-sounds-20261113-localized-defaults-v2.json
[locale-probe]: ../../../ipod-firmware-lab/.scratch/alarm-tone-locales-20261113.py
[locale-switch]: ../../../ipod-firmware-lab/artifacts/alarm-sounds-20261113-native-locale-file.json
[tone-setter]: ../../../ipod-firmware-lab/artifacts/alarm-sounds-20261113-classic-core/080e7e40.c
[playlist-setter]: ../../../ipod-firmware-lab/artifacts/alarm-sounds-20261113-classic-core/080e867c.c
[nano4-setter]: ../../../ipod-firmware-lab/artifacts/alarm-sounds-20261113-nano4/080f3f08.c
[nano5-setter]: ../../../ipod-firmware-lab/artifacts/alarm-sounds-20261113-nano5b/080b2b00.c
[playback]: ../../../ipod-firmware-lab/artifacts/alarm-sounds-20261113-classic-identity/080e7f3c.c
[playback-asm]: ../../../ipod-firmware-lab/artifacts/alarm-sounds-20261113-classic-identity/080e7f3c.asm.txt
[tone-init]: ../../../ipod-firmware-lab/artifacts/alarm-sounds-20261113-classic-tone-init/0817f0c0.c
[tone-scan]: ../../../ipod-firmware-lab/artifacts/alarm-sounds-20261113-classic-identity/0817f34c.c
[nano5-scan]: ../../../ipod-firmware-lab/artifacts/alarm-sounds-20261113-nano5deep/0804ea40.c
[classic-parser]: ../../../ipod-firmware-lab/artifacts/alarm-sounds-20261113-classic-tone-parser/08244ec4.c
[nano4-parser]: ../../../ipod-firmware-lab/artifacts/alarm-sounds-20261113-nano4deep/08222dec.c
[nano5-parser]: ../../../ipod-firmware-lab/artifacts/alarm-sounds-20261113-nano5deep/082bd9e4.c
[tone-play]: ../../../ipod-firmware-lab/artifacts/alarm-sounds-20261113-classic-tone-init/08245034.c
[tone-default]: ../../../ipod-firmware-lab/artifacts/alarm-sounds-20261113-classic-core/0817f12c.c
[nano5-default]: ../../../ipod-firmware-lab/artifacts/alarm-sounds-20261113-nano5deep/08271f90.c
[tone-lookup]: ../../../ipod-firmware-lab/artifacts/alarm-sounds-20261113-classic-core/0817efb4.c
[tone-fallback]: ../../../ipod-firmware-lab/artifacts/alarm-sounds-20261113-classic-core/0817f2b8.c
[nano5-display]: ../../../ipod-firmware-lab/artifacts/alarm-sounds-20261113-nano5b/08264864.c
[named-registration]: ../../../ipod-firmware-lab/artifacts/nano567-preferences-complete-20261107-final-inventory-v3/inventory.json
[resource-selection]: ../../../ipod-firmware-lab/artifacts/alarm-sounds-20261113-nano5language/081a7514.c
[resource-fallback]: ../../../ipod-firmware-lab/artifacts/alarm-sounds-20261113-nano5b/081a3f86.c
[playlist-menu]: ../../../ipod-firmware-lab/artifacts/alarm-sounds-20261113-classic-alarm-ui/081f0e74.c
[playlist-player]: ../../../ipod-firmware-lab/artifacts/alarm-sounds-20261113-classic-identity/080ef888.c
[playlist-name]: ../../../ipod-firmware-lab/artifacts/alarm-sounds-20261113-classic-library2/0811b1d0.c
[playlist-array]: ../../../ipod-firmware-lab/artifacts/alarm-sounds-20261113-classic-identity/0811af40.c
[library-finalizer]: ../../../ipod-firmware-lab/artifacts/mhii-unknown-fields-20261028/08046cd8-Research_Library_LoadAndFinalize.c
[playlist-count]: ../../../ipod-firmware-lab/artifacts/alarm-sounds-20261113-library-comparator/080c4974.c
[playlist-sort]: ../../../ipod-firmware-lab/artifacts/alarm-sounds-20261113-library-extra/080ac908.c
[playlist-comparator]: ../../../ipod-firmware-lab/artifacts/alarm-sounds-20261113-library-comparator/080893d0.c
[collation]: ../../../ipod-firmware-lab/notes/itunesdb/string-comparison-and-collation.md
