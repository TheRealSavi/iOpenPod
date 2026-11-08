# Nano 3 / Nano 4 Preferences: consumer supplement

This is the second, bounded pass for Nano 3 1.1.3 and Nano 4 1.0.4. It adds named scalar fields, native menu visibility domains, and a separate Nano 4 XML settings store. It does **not** claim every Preferences byte or every downstream consumer is understood. The first-pass report's 18 resolved representation bytes describe that earlier inventory only; they are not a coverage total for this supplement.

## Evidence and reproduction

| Target | Decrypted osos SHA-256 | Preferences extent |
|---|---|---|
| Nano 3 | `ff5980009c6720742f5b85f3e80a5c853bd0e3caa433d015e6836c209e08081a` | `0xb88` |
| Nano 4 | `a5d273ab3be00dcea90e72444bb9750ebe5d88f5f986c3e62e4fd108332ff372` | `0xb90` |

All binary offsets below are **file-relative**. The Preferences owner contains the file image at owner+4. Originals and the physical iPods were untouched. Nano 4 missing Thumb functions were recovered only in the existing isolated Ghidra copy.

The final receipt directory is `../ipod-firmware-lab/artifacts/preferences-nano34-consumers-20261107/native-final-v1/`. It contains per-target native receipts, synthetic initializer bytes, and `inventory-supplement.json`. Receipts bind firmware, runtime map, final probe script, helper script, and the static export files by SHA-256.

Reproduce from the lab with a **new output directory**:

```powershell
uv run scripts/research_preferences_nano34_consumers.py --output artifacts/preferences-nano34-consumers-reproduction-NEW
```

The probe script was Ruff-formatted and checked from the application UV environment before the final run. Both target runs passed: **258 action/state cases**, plus six captured Nano 4 native registrations and native label/catalog queries. Checks compare complete Preferences payloads, preserving unrelated bytes; menu tests also seed patterned payloads and assert unrelated mask bits survive. Photo persistence fixtures use a zeroed, internally consistent synthetic photo state.

Native instructions perform the callbacks, mask computation, stores, UI label selection, and bounded keyed setters. Recorded adapters stand in for filesystem saves, hardware, notification recipients, key splitting/string comparison, and key-service storage during UI routing probes. These are emulator observations, not physical acceptance or hot-adoption tests.

## Binary scalar fields

| File offset | Width | Meaning | UI values | Native initializer |
|---|---|---|---|---|
| `0xb39` | 1 | tv_out | 0=Off, 1=On, 2=Ask | 0 |
| `0xb3a` | 1 | tv_signal | 0=NTSC, 1=PAL | 0 |
| `0xb3c` | 1 | photo_shuffle | 0=Off, 1=On | 0 |
| `0xb3d` | 1 | photo_repeat | 0=Off, 1=On | 0 |
| `0xb84` | 1 | tv_screen | 0=Standard, 1=Widescreen | 0 |
| `0xb4d` | 1 | fit_to_screen_disabled | 0=On, 1=Off | 0 |
| `0xb85` | 1 | alternate_audio | 0=Off, 1=On | 0 |
| `0xb74` | 1 | captions | 0=Off, 1=On | 0 |
| `0xb86` | 1 | subtitles | 0=Off, 1=On | 0 |
| `0xb0c` | 2 | contact_sort | 0=First, 1=Last | 0 |
| `0xb8c` | 1 | Rotate, Nano 4 only | 0=Off, 1=On | 1 |

Initializer observations are not a claim that a live device factory reset produces no subsequent platform overrides. Generic stores accept wider raw byte/word inputs than the UI domains; preserve unlisted values.

- TV Out stores 0=Off, 1=On, 2=Ask. Nano 3 cycles 0→2→1→0; Nano 4 UI event indexes 0/1/2 map to stored 0/2/1. The Nano 4 dispatcher first changes cached UI state; `08142624` commits it to file+`0xb39`.
- TV Signal has offered 0=NTSC and 1=PAL. Nano 3 dispatcher changes its cache and video service; common persistence `0815f6dc` writes file+`0xb3a`. The Nano 3 runtime signal setter `0824f344` also has a value-2 path: its meaning and current exposure remain unresolved. Do not erase an encountered 2.
- Fit to Screen is inverted: **0 means On**, 1 means Off. This is independent of Standard/Widescreen.
- Captions and Subtitles are separate bytes. Nano 3 video runtime methods `0824f5d0` and `0824f3d4` clear the other runtime flag when enabling one and emit notifications. The persistence of that indirect notification and Nano 4 equivalent consumer still need tracing.
- Contact Sort labels are exactly First and Last. Full name/collation fallback behavior is not established.
- Photo Repeat and Shuffle are **`0xb3d` and `0xb3c`**, respectively, on each image independently. Native modern controls toggle cached photo-structure bytes+3/+2, persist, then display On/Off. Nano 3 callbacks: `081e0010`/`081e0254`; Nano 4: `081ab348`/`081ab51a`.
- **Do not label `0xb4c`/`0xb48` Photo Repeat/Shuffle.** Nano 4 legacy properties `0x9dc8`/`0x9dc9` are proven Boolean stores there, but their actual user-facing meaning remains unresolved.

The raw setters and consumers are included in the JSON evidence. Playback eligibility, exact crop/scale behavior, alternate-audio selection, and rotation thresholds are not promoted from labels into invented implementation claims.

## Main Menu visibility

Main mask: file+`0xb2c`, little-endian u32 on both images. Nano 4 Genius is bit 0 of a **separate** u32 at file+`0xb88`. Every mapped bit has native on/off mutation tests; the native helper preserves every other bit. Unmapped bits remain unknown, so each entire mask word remains partially understood.

| Item | Mask | Nano 3 reset visible | Nano 4 reset visible |
|---|---|---|---|
| Music | `0x00000001` | 1 | 1 |
| Cover Flow | `0x20000000` | 0 | 0 |
| Playlists | `0x00008000` | 0 | 0 |
| Artists | `0x00000002` | 0 | 0 |
| Albums | `0x00000004` | 0 | 0 |
| Compilations | `0x00200000` | 0 | 0 |
| Songs | `0x00000008` | 0 | 0 |
| Radio | `0x02000000` | 1 | 1 |
| Genres | `0x00000010` | 0 | 0 |
| Composers | `0x00000020` | 0 | 0 |
| Audiobooks | `0x00040000` | 0 | 0 |
| Search | `0x10000000` | 0 | 0 |
| Photos | `0x00100000` | 1 | 1 |
| Podcasts | `0x01000000` | 0 | 0 |
| Videos | `0x04000000` | 1 | 1 |
| Video Playlists | `0x00008000` | 0 | 0 |
| Movies | `0x40000000` | 0 | 0 |
| TV Shows | `0x80000000` | 0 | 0 |
| Music Videos | `0x00001000` | 0 | 0 |
| Rentals | `0x00000000` | 0 | 0 |
| Extras | `0x00000200` | 1 | 1 |
| Clocks | `0x00000040` | 0 | 0 |
| Alarms | `0x00004000` | 0 | 0 |
| Calendars | `0x00000100` | 0 | 0 |
| Contacts | `0x00000080` | 0 | 0 |
| Games | `0x00000800` | 0 | 0 |
| Notes | `0x00000400` | 0 | 0 |
| Screen Lock | `0x00800000` | 0 | 0 |
| Stopwatch | `0x00400000` | 0 | 0 |
| Nike+iPod | `0x08000000` | 1 | 1 |
| Shuffle Songs | `0x00080000` | 1 | 1 |
| Sleep | `0x00002000` | 0 | 0 |
| Genius, Nano 4 extension word | `0x00000001` | — | 0 |

These are **row initializer / Reset Menu defaults**, not a claim that the current on-disk word equals their union. Reset Menu itself is an action, not a visibility bit. Playlists and Video Playlists intentionally use the same property and mask. Rentals maps to zero in this helper; its actual independent visibility mechanism remains unresolved. Search returns `0x10000000` only when the native search capability check succeeds, otherwise zero. Radio also has higher-level Main/Music propagation that is not closed by this lower-level setter pass.

## Music Menu visibility

Music mask: file+`0xb80`, little-endian u32 on each image. The Nano 4 Genius bit here differs from its Main Menu extension bit.

| Item | Mask | Nano 3 reset visible | Nano 4 reset visible |
|---|---|---|---|
| Cover Flow | `0x00000001` | 1 | 1 |
| Playlists | `0x00000002` | 1 | 1 |
| Artists | `0x00000004` | 1 | 1 |
| Albums | `0x00000008` | 1 | 1 |
| Compilations | `0x00000010` | 1 | 0 |
| Songs | `0x00000020` | 1 | 1 |
| Radio | `0x00000080` | 1 | 1 |
| Genres | `0x00000100` | 1 | 1 |
| Composers | `0x00000200` | 1 | 1 |
| Audiobooks | `0x00000400` | 1 | 1 |
| Search | `0x00000800` | 1 | 1 |
| Genius, Nano 4 | `0x00001000` | — | 1 |

The unused bit positions are **not padding or reserved-by-proof**. Full property IDs, resource labels, defaults, selected word, and mutation receipts are in `inventory-supplement.json` and the native receipts.

## Nano 4: separate iPodSettings XML store

**Exact pathname: `iPod_Control/Device/iPodSettings`, without `.xml`.** This is distinct from binary Preferences and from another model's similarly named file. Its XML root is `iPodSettings`, attribute `version="1.0"`. Registered `Category.Key` names become category and key elements. Bool and integer scalar text is unsigned decimal (`%lu` at `08116bdc`); the writer uses XML element serialization, not a binary Preferences tail.

The path is verified past the literal: `08116ea8` initializes a string with `082343c0`, inserts the exact literal through `082320b2`→`08231932` (length)→`082319de` (copy), and calls `08216476`. That writer passes it to `082340b4`; `082343b0`→`08232710` copies it unchanged into file object+0xc. `082333d0` passes that same path object to filesystem-provider virtual+0x14. No extension is appended in this chain. Reader `08116c40` independently constructs the identical pathname. The static trace is retained under `nano4-static11-direct/`.

| Key | Type / UI domain | Registered default |
|---|---|---|
| `NowPlaying.EnergySaver` | Boolean: 0=Off, 1=On | 1 |
| `NowPlaying.Crossfade` | Boolean: 0=Off, 1=On | 0 |
| `Settings.FontSize` | integer: 0=Standard, 1=Large | 0 |
| `Settings.ShakeSetting` | Boolean: 0=Off, 1=On | 1 |
| `Settings.VoiceFeedback` | Boolean: 0=Off, 1=On | 1 |
| `Settings.PreviewPanel` | Boolean: 0=Off, 1=On | 1 |

Native registration tail `0814282c` registers all six; `082092a8` stores Boolean current/default bytes and type 3, while `08209354` stores integer current/default/minimum/maximum and type 1. Font Size registers inclusive bounds 0..1 and default 0. Those exact arguments were captured from original instructions. The callback route and serialized store are separate from binary byte coverage.

- Boolean UI callbacks toggle 0/1. Lower service `08208fbc` stores the low byte as supplied: native probes distinguish 2, 255, 256 and `0xffffffff`. This wider service domain does **not** imply additional supported UI states.
- Integer setter `08209030` checks signed registered bounds. Native probes for 0, 1, 2, `0x7fffffff`, and `0xffffffff` confirm only 0 and 1 can replace the Font Size value.
- Loader `08116c40` resolves the registered type by category/key. Boolean text is parsed then normalized to 0/1; integer text goes through the bounded setter. Load uses no-save flag 1. Unknown type 0 has no setter branch. Exact malformed XML and version-repair edges are still open.
- On an ordinary changed value, setters notify by registered ID and invoke save `08116ea8` when no-save flag is 0. The integer setter can also request save after rejecting a differing out-of-range input. Reset method `08208ed0` restores registered defaults, not arbitrary zeroes, and notifies/saves.
- Save `08208d04` reconstructs the registered-key XML tree, then `08216476`/`08216594` serializes it. A host editor should preserve unknown XML content; this research does not authorize copying native rebuilding behavior into a lossy host writer.

These six settings now have native names, store, type, registered defaults, UI domains, and persistence routes. Remaining effect details are concrete: Energy Saver timing, crossfade duration/track eligibility, shake thresholds, voice-asset/language availability, Large font metrics, and view-specific Preview Panel/rotation conditions. Those require downstream consumers rather than guessing from their names.

## Remaining questions and exact next entrypoints

- Nano 3 `0824f344` signal value 2; notifications from `0824f5d0` and `0824f3d4`. Nano 4 video runtime equivalents and caption/subtitle persisted coupling.
- Nano 3 photo persistence `0815f6dc`; Nano 4 `08142624`: timing, transition selector, music selector and playlist identifier fields surrounding the now-proven photo Boolean fields. Nano 4 transition callback `081ab4ee` uses -1 versus -2 and byte+0x10; its full menu is still open.
- Main/Music higher-level customization handlers and Radio propagation: Nano 3 `081dfb98`; Nano 4 `081aa930` and adjacent callbacks. Rentals zero-mask handling and all unassigned mask bits remain open.
- Nano 4 legacy Bool properties `0x9dc8` / `0x9dc9`, setters `08059794` / `08059a60`, file+`0xb4c` / `0xb48`: values known, meanings not yet named.
- Nano 4 XML loader `08116c40`, registered reset `08208ed0`, and serializer `08208d04`: malformed input, duplicate/unknown key policy, version recovery, and whether all registry categories have been found.
- First-pass open fields remain open: Clicker upper bits, language-dependent behavior, Backlight current versus latent entries, playback state, clocks/cities/DST, structured blocks, and other byte ranges. Zero initialization is never used as padding evidence.

This supplement contributes 19 named binary bytes on Nano 3 and 24 on Nano 4 (including partly understood mask words), plus six named Nano 4 XML keys. These are **named-byte counts only**, not additional resolved semantic coverage. The previous inventory remains a frozen first-pass artifact. Application integration must reconcile fields individually and preserve Unknown Data. No datetime parsing or device loading policy was changed; datetime issues remain non-blocking.
