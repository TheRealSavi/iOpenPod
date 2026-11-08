# Latest firmware Preferences model coverage

Research date: 2026-11-07. The Application Layer now selects an explicit model
for every requested family. This is a model of verified saved settings, not a
claim that every native setting is understood or that a running iPod immediately
adopts a Host file edit. Unknown bytes and clock metadata remain preserved.

The subsequent [whole-file inventory](preferences-complete-inventory-2026-11-07.md)
extends the research beyond this implemented edit surface. Its five group reports
are the current source for newly decoded value domains and exact remaining gaps.

## Latest release qualification

The [official Apple update catalog][apple-catalog] was retrieved again for this
pass. Its retained [catalog][retained-catalog] has SHA-256
`5a2938b0aa28808cb738b0871e01d6e084c5f56243d69b0c6c4fabec442586b8`.
The [manifest audit][manifest-audit] compares all **18 retained IPSW packages**
against their offered filenames, updater families and release/build identities.
Its SHA-256 is `0af2493dac58a82c7e59181612c94ff9f4b2f165b9ecdce67443787e60a90a49`.
This establishes the latest package offered per updater family, not cross-family
upgrade compatibility. Hardware generation, updater family and internal build
numbers remain separate identifiers.

| Device | Latest RetailOS | Updater families | Edited artifact | Verified editable fields |
| --- | --- | --- | --- | --- |
| Mini 1 | 1.4.1 | 3, 6 | Binary Preferences | Shuffle, Repeat, Sound Check, Clicker |
| Mini 2 | 1.4.1 | 7 | Binary Preferences | Shuffle, Repeat, Sound Check, Clicker |
| Nano 1 | 1.3.1 | 14, 17 | Binary Preferences | Shuffle, Repeat, Sound Check, Clicker |
| Nano 3 | 1.1.3 | 26 | Binary Preferences | Shuffle, Repeat, Sound Check, EQ, Brightness |
| Nano 4 | 1.0.4 | 31 | Binary Preferences | Shuffle, Repeat, Sound Check, EQ, Brightness |
| Nano 5 | 1.0.2 / 34A20020 | 34 | iPodSettings.xml | Brightness, Sound Check |
| Nano 6 | 1.2 / 36B10147 | 36 | iPodSettings.xml | Brightness, Sound Check |
| Nano 7 | 1.0.4 / 37A40005 | 37 | iPodSettings.xml | Brightness, Sound Check |
| Nano 7 refresh | 1.1.2 / 39A10023 | 39 | iPodSettings.xml | Brightness, Sound Check |
| Video 5 | 1.3 | 13, 20 | Binary Preferences | Shuffle, Repeat, Sound Check, Clicker |
| Video 5.5 | 1.3 | 25 | Binary Preferences | Shuffle, Repeat, Sound Check, Clicker |
| Classic 6 | 1.1.2 | 24 | Binary Preferences | Shuffle, Repeat, Sound Check, EQ, Brightness, Clicker |
| Classic 6.5 | 2.0.1 | 33 | Binary Preferences | Shuffle, Repeat, Sound Check, EQ, Brightness, Clicker, Alternate Audio |
| Classic 7 | 2.0.4 | 35 | Binary Preferences | Shuffle, Repeat, Sound Check, EQ, Brightness, Clicker |
| Classic 7.5 | 2.0.5 | 38 | Binary Preferences | Shuffle, Repeat, Sound Check, EQ, Brightness, Clicker |

All paths are under `iPod_Control/Device/`. A latest release is not inferred from
the connected device's age, capacity or transport revision. Conflicting strongest
evidence leaves editing unavailable. Later Classic and both Nano 7 branches require
explicit updater-family evidence. The other studied model/release pairs can qualify
without an updater observation; a present contradictory family still rejects them.
The codec independently validates the captured artifact before offering fields.

## Important differences established by this pass

- Mini 1 and Nano 1 independently use Clicker `1` Speaker / `2` Headphones,
  whereas Video uses the reverse labels. These are not portable bit meanings.
- Mini 1 independently qualifies its 50-choice, full-u32 fixed-offset selector.
  It does not supply IANA geography or historical timezone rules. Invalid words
  remain unknown rather than falling back to a firmware UI default.
- Nano 3/4's UI callbacks directly reach the traced binary setters and serializer.
  Their language word is observed as u32, but the new profiles deliberately do not
  inherit a Classic city or the historical Nano 3 `0x6BC` DST interpretation.
- Nano 5 is a click-wheel device with a named XML settings store. The presence of
  its legacy binary Preferences file does not make that file the UI's authority.
- Nano 5/6/7 retain separate 2,960-byte binary blobs. A familiar extent and version
  do not qualify Classic fields or reset semantics. These blobs remain opaque in
  the Application Layer while verified XML settings are independently editable.
- Named settings retain XML bytes and replace only explicit scalar text. They do
  not rebuild a tree, manufacture missing files/nodes, normalize dates, or copy
  defaults from another firmware. Brightness uses 0 through 100; Sound Check uses
  canonical numeric 0/1. Unknown settings and unedited lexical forms survive.

See the independent [Mini 1/Nano 1 investigation][mini1-nano1],
[Nano 3/4/5 investigation][nano345], [Nano 6/7 investigation][nano67],
[Mini 2/Video investigation][mini-video] and [Classic investigation][classics].
Those reports pin firmware hashes, addresses, execution adapters and limits.
Native execution means original instructions in bounded offline harnesses;
it does not mean a complete boot or physical device acceptance test.

This expansion adds **652 bounded native cases**: 250 Mini 1/Nano 1, 304 Nano
3/4/5, 84 Nano 6/7, and a separate [14-case Nano 5 boolean conversion check][nano5-bool].
That last check independently confirms why Sound Check edits must use canonical
numeric text instead of preserving leading whitespace around a changed value.
The earlier Mini 2/Video and Classic evidence remains separately scoped in its
original reports; these counts do not describe a rerun of those images.

## Questions recorded at the editing-expansion checkpoint

This table records the open questions when the editing expansion above finished.
The subsequent whole-file investigation closes some of these and records further
field-level questions; consult its group reports for the latest evidence.

| Model | Important remaining preference questions |
| --- | --- |
| Mini 1 | Localized EQ-name/capacity contract; Backlight selector and Contrast domains; complete language-change dependencies; live clock arbitration and Host-edit reload ordering. |
| Mini 2 | Localized EQ-name contract; Backlight and Contrast UI domains; language-change dependencies; live settings reload ordering. |
| Nano 1 | Clock/timezone/Alarm representation; full Brightness save/apply route; localized EQ names; Backlight/Contrast domains and live adoption. |
| Nano 3 | Clicker route labels for its four raw states; saved city/DST semantics; Backlight/menu configuration; language dependencies and live adoption. |
| Nano 4 | Clicker route labels for its four raw states; saved clock/city/DST semantics; Backlight/menu configuration; language dependencies and live adoption. |
| Nano 5 | Exact named Repeat/Shuffle/Clicker string domains; EQ and remaining named settings; legacy binary consumers versus XML authority; clock settings and reload/dirty-save order. |
| Nano 6 | Named enum domains and remaining UI settings; language/date/time consumers; legacy blob relationship; mounted-file reload and retained-RAM overwrite order. |
| Nano 7 / updater 37 | Named enum domains and remaining UI settings; clock/timezone consumers; legacy blob relationship; live reload/dirty-save order. |
| Nano 7 refresh / updater 39 | Independently qualify remaining named settings and clock consumers; differences outside the proved two-field store; live adoption. |
| Video 5 | Localized EQ-name serialization; complete Brightness and Volume Limit workflows; Backlight/language dependencies; clock and live-adoption gaps. |
| Video 5.5 | Same open settings require this target's own evidence; do not infer native menu labels or coupled changes from Mini/Nano similarity. |
| Classic 6 | Backlight/menu/language workflows; Raw Hardware Clock initialization and callback gaps; live adoption of edited Preferences. |
| Classic 6.5 | Backlight/menu/language workflows; Alternate Audio's link to movie language selection; Raw Hardware Clock and live-adoption gaps. |
| Classic 7 | Backlight/menu/language workflows; remaining saved DST prefix consumers and Raw Hardware Clock gaps; live adoption. |
| Classic 7.5 | Same unresolved areas require its own firmware evidence, especially remaining DST prefix consumers and live adoption. |

No unsupported setting is authored merely to fill a coverage cell. Saved bytes
can differ from retained live settings: later firmware saves may overwrite a Host
edit. The current UI reports verified file publication and asks the user to check
the device after ejecting; it does not promise a particular reboot sequence.

Datetime uncertainty never becomes a Library load/Sync blocker. Nano clocks whose
meaning is unqualified use the established database-offset/UTC estimate. Explicit
preference changes still require an unchanged source and valid Storage transaction;
that is file-integrity validation, not calendar validation. XML edits depend on
their own captured file, not the separate optional binary clock blob.

[apple-catalog]: https://itunes.apple.com/WebObjects/MZStore.woa/wa/com.apple.jingle.appserver.client.MZITunesClientCheck/version
[retained-catalog]: ../../../ipod-firmware-lab/artifacts/preferences-latest-catalog-20261107/apple-version-catalog.plist
[manifest-audit]: ../../../ipod-firmware-lab/artifacts/preferences-latest-catalog-20261107/manifest-audit.json
[mini1-nano1]: preferences-mini1-nano1-2026-11-07.md
[nano345]: preferences-nano345-2026-11-07.md
[nano67]: preferences-nano67-2026-11-07.md
[mini-video]: preferences-mini-video-writes-2026-11-07.md
[classics]: preferences-classic-writes-2026-11-07.md
[nano5-bool]: ../../../ipod-firmware-lab/artifacts/nano5-named-bool-20261107-v1.json
