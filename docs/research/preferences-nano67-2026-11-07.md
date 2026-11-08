# Nano 6 and Nano 7 Preferences contracts

Investigated on 2026-11-07. This pass independently qualifies updater families
36, 37, and 39 against their latest Apple catalog entries. It does not transfer
Classic offsets or a Nano 7 result to another complete firmware image.

The actionable result is a separate named settings document:
`iPod_Control/Device/iPodSettings.xml`. Its `General/Brightness` integer and
`Playback/SoundCheck` boolean have independently executed registration, setter,
and serializer evidence in all three images. The familiar binary
`iPod_Control/Device/Preferences` also exists, but its appearance does not prove
that a classic-style byte edit changes the corresponding touch UI setting.

## Sources and qualification

This investigation reads retained files and executes bounded offline instruction
probes. The firmware was acquired in the earlier, separately documented
[Nano 6 acquisition](../../../ipod-firmware-lab/notes/nano6-firmware-workspace.md)
and [Nano 7/2015 refresh acquisition](../../../ipod-firmware-lab/notes/nano7-firmware-workspace.md).
No physical device access or settings write was performed by this investigation.
Those acquisition records distinguish original Apple ciphertext signatures,
hardware-assisted plaintext acquisition, and verified runtime maps.

The retained
[Apple catalog selection](../../../ipod-firmware-lab/artifacts/preferences-latest-catalog-20261107/selected.json)
comes from Apple's version catalog, captured for this task. Its complete source
plist SHA-256 is
`5a2938b0aa28808cb738b0871e01d6e084c5f56243d69b0c6c4fabec442586b8`.
It selects the following builds; updater family and AppleFamilyID are separate
identifiers.

| Hardware target | Updater family | Latest selected firmware | AppleFamilyID | Workspace |
| --- | ---: | --- | ---: | --- |
| Nano 6 | 36 | 1.2 / 36B10147 | 17 | `Nano6FW` |
| Nano 7, original release | 37 | 1.0.4 / 37A40005 | 18 | `Nano7FW` |
| Nano 7, 2015 refresh | 39 | 1.1.2 / 39A10023 | 18 | `Nano75FW` |

| Updater | Complete plaintext `decrypted/osos.bin` SHA-256 |
| ---: | --- |
| 36 | `d529680b7e7662876543d70b6941ddfac123d96c8ed1923432e4909909e896d8` |
| 37 | `4a55fffbf58cfd04a393e9a40c0c1c42471dfb34d11847b676b85f02a8019999` |
| 39 | `ac4cf072d3c3f971b6acc03ed4f2ad1baa57d7bae20f89692bd6fb08d8a749e4` |

The inspected functions reside in each main initialized block at `0x08000000`,
mapped from file offset zero. The block lengths are `0x88D9C0`, `0x970380`, and
`0x970740`, respectively. Later SRAM relocations and BSS are distinct map
regions; the probes do not interpret their source bytes as main executable code.
The acquisition notes link the independent startup/map receipts.

Primary byte evidence and reproducible native cases:

- [Verifier](../../../ipod-firmware-lab/scripts/probe_nano67_preferences.py),
  pinned to Capstone 5.0.6, Unicorn 2.1.4, and the three complete input hashes.
- [Receipt and vectors](../../../ipod-firmware-lab/artifacts/nano67-preferences-20261107-v3/receipt.json):
  **60 native cases**, 20 per target, **27 explicit vtable/string byte guards**,
  and **33 independently hashed evidence windows** with assembly listings.
- [SoundCheck text converter probe](../../../ipod-firmware-lab/scripts/probe_nano67_soundcheck_text.py)
  and [receipt](../../../ipod-firmware-lab/artifacts/nano67-soundcheck-text-20261107-v2/receipt.json):
  **24 further native cases** with no imported-function hooks, executing the
  original Thumb converter on Nano 6 and ARM converters on both Nano 7 builds.
- Each target's `analysis/osos-corpus/functions/` provides discovery pseudocode
  and assembly. Pseudocode is not original Apple source. Missing exported
  functions were read from original bytes where needed.

Reproduction from the lab root, choosing an unused output directory:

```powershell
uv run scripts/probe_nano67_preferences.py --output-dir artifacts/nano67-preferences-20261107-rerun
```

The script refuses an existing destination. It verifies all complete input
hashes before executing that target's native cases. Native instructions execute
only in explicitly allowed spans. UI construction helpers, locks, key splitting,
string comparison, notifications, and XML writer dependencies are synthetic
hooks. Thus the probes prove the inspected control flow and data contract, not
whole-firmware execution, physical persistence, or USB-detach adoption.

## Two separate stores

The named settings owner contains its store name at `owner + 0x9C`, typed
collections for settings, and a dirty byte at `owner + 0xAC`. This owner is
different from the retained binary Preferences owner.

| Surface | Family 36 | Family 37 | Family 39 |
| --- | --- | --- | --- |
| Named settings constructor | `0803CB5C` | `080277A0` | `080277A0` |
| Installed settings vtable | `086ECA58` | `087ECED8` | `087ECF48` |
| Named settings XML loader | `08083488` | `081C37F0` | `081C37F4` |
| Named settings XML saver | `081DAE64` | `081C3A28` | `081C3A2C` |
| Binary default initializer | `0818FB64` | `081685D8` | `081685DC` |
| Binary raw loader | `08027B90` | `081545D8` | `081545DC` |
| Binary saver | `08136EBC` | `0810CFD0` | `0810CFD0` |

All three named loaders/savers construct the path from
`iPod_Control\Device\` and `%s%s.xml`, with store name `iPodSettings`. The name,
both path literals, both format strings, and the binary Preferences path are
explicit guards. The constructors install the listed vtables; the serializer
is vtable slot `+0x78`.

The binary initializers clear `0xB90` bytes and write format version `0x3E`.
Their raw loaders read at most `0xB90` bytes into the blob, clearing the blob
first on the successful length/read path. Their savers copy exactly `0xB90`
bytes beginning at **owner + 4**, refresh the copied word at file offset `+8`,
and write that copy. Binary dirty state is at **owner + 0xB94**. Those are static
byte/code observations, not emulated file-load/save acceptance tests.

No reset-request meaning is established for binary file offset `+4` in these
three targets. A Classic reset-request diagnostic must not be applied to that
word. Similarly, recognized extent/version do not qualify the legacy binary
language, clock, city, DST, or playback offsets for authoring.

## Named XML contract

The native serializer opens a root named `iPodSettings`, sets attribute
`version="1.0"`, emits a section element for each group, and emits child elements
for each setting in that group. It obtains those two names by splitting the
registered key at its first dot. This conceptual example illustrates the native
structure; it is not a captured device file or a default document to create:

```xml
<iPodSettings version="1.0">
  <General><Brightness>40</Brightness></General>
  <Playback><SoundCheck>0</SoundCheck></Playback>
</iPodSettings>
```

| Native field | Registration | Serialized form | Qualified authored values |
| --- | --- | --- | --- |
| `General.Brightness` | Signed integer, minimum 0, maximum 100, default 40 | Unsigned decimal scalar text | 0 through 100 inclusive |
| `Playback.SoundCheck` | Boolean, default false | Unsigned decimal scalar text | 0 or 1 |

The general constructors are `08023E08`, `08279444`, and `08279464` for
families 36/37/39. The playback constructors are `0802F45C`, `082885E4`, and
`08288604`. Executing each constructor with a synthetic registration interface
captures the exact keys, types, bounds, and defaults listed above. These are
registration defaults, not justification for silently replacing missing fields
in an existing document.

| Operation | Family 36 | Family 37 | Family 39 |
| --- | --- | --- | --- |
| Integer setter, vtable `+0x34` | `0816EAA8` | `08454020` | `08454020` |
| Boolean setter, vtable `+0x3C` | `0813ECD8` | `08453F9C` | `08453F9C` |
| XML serializer, vtable `+0x78` | `08064CB0` | `08453C18` | `08453C18` |
| Decimal element helper | `081DAC0C` | `083D6024` | `083D6040` |

Equal function addresses in the two Nano 7 images do not imply identical bytes
or callees. In particular, the scalar helper and XML writer addresses differ.
The verifier independently executes and hashes every target.

Integer setters search the typed collection by group/name and enforce the
registered signed bounds. An in-range changed value updates the current value
and notifies observers. An out-of-range changed request leaves the value
unchanged but still marks the store dirty. Unknown names return 1; missing dot
returns 2. The public writer rejects out-of-range input locally rather than
depending on those native fallback side effects.

The Nano 6 scalar setter ABI receives a pointer to the value in `r2`, plus a
flush flag in `r3`. The Nano 7 versions receive the scalar value directly in
`r2`. The XML loader dispatch differs accordingly; this is a real interface
difference even though the document contract agrees.

The original serializer and numeric helper produce `%u` for both fields. Native
vectors cover brightness 0, 40, and 100 paired with SoundCheck 0/1, preserving
section/key identity and root version in captured XML writer calls. Setter
vectors include negative/out-of-range integers, unchanged values, boundary
values, missing keys, and missing separators. They do not assert that calling
the boolean setter with arbitrary non-boolean integers is supported.

Static loader control flow iterates root children and their children, joins
their names as `%s.%s`, checks registered-key eligibility and type, then calls
the corresponding setter. Type 1 consumes unsigned decimal digits with an
optional leading plus and limited leading whitespace; a leading minus yields
zero. Type 3 converts decimal input to boolean. Type 5 passes string content.
These parser fallbacks are not a Host validation policy or permission to
normalize retained unusual input. Raw XML tokenization and complete malformed
file acceptance were not executed in the native probes.

The boolean conversion leaves are `0817A250`, `0841B33C`, and `0841B340`.
Unlike the integer loader's explicit whitespace loop, they do **not** skip
leading whitespace. The 24 native converter vectors prove `1` and `+1` produce
one, while a leading space, tab, or newline before `1` produces zero. A trailing
space does not change the result. Therefore an explicit SoundCheck edit writes
canonical `0` or `1` over its complete scalar text; retaining leading padding
would change the device interpretation. Unedited padded text is still retained.

## Application model and lossless editing

The separate pure [named settings codec](../../src/iPodDB/preferences/named.py)
retains captured source bytes, an explicit
firmware profile, parse observations, and explicit scalar edits. It does not
derive the device profile from the XML root, and it does not use a binary
Preferences datetime projection as a prerequisite for XML edits.

The editor offers the two evidenced scalar fields only when their exact nodes
can be safely located. It writes only explicitly selected scalar text spans,
keeping unrelated bytes, comments, ordering, Unicode, line endings, other
settings, and unknown datetime content. An unchanged parse/write is exact;
setting an already equal decimal value retains its original spelling.

The supported Host edit envelope is intentionally narrower than all documents
the firmware might read:

- UTF-8 XML with root `iPodSettings` and exactly the qualified `version="1.0"`
  attribute. DTD/entity declarations and other encodings remain read-only.
- Duplicate sections or duplicate/complex setting nodes disable the affected
  field. An unaffected, unambiguous scalar field remains available.
- Missing files, sections, and keys are never synthesized. Unknown scalar
  values remain unchanged unless the user explicitly replaces that field.
- Source bytes are immutable snapshots. Update and publication both validate
  key/value types and domains; forged edits cannot bypass the publication gate.

The [codec tests](../../tests/iPodDB/test_named_preferences.py)
cover all three profiles, exact-byte no-ops, unrelated bad
dates, UTF-16/NUL ambiguity, DTD/entities, duplicates, complex nodes, oversized
integer text, mutable captures, whitespace-only values, SoundCheck's distinct
leading-whitespace contract, and forged edit types. The final scoped run has
**56 passing tests**, including the separate Nano 5 profile added by the sibling
investigation, with scoped Mypy and Ruff passing. Application Storage transaction
behavior is owned by the separate Preferences workflow integration.

## Remaining questions by target

| Target | Qualified in this pass | Remaining boundaries |
| --- | --- | --- |
| Nano 6 / 1.2 | Both stores and framing; XML path, root/type contract; Brightness and SoundCheck registration, native setters, serializer | USB exit/reload timing; whether retained settings can supersede a Host patch; authority/bridges of remaining binary fields; clock and reset semantics; broader string-valued controls |
| Nano 7 / 1.0.4 | Independently qualified same document contract with different scalar setter ABI | Same lifecycle and remaining-field questions; no broad Nano 6 layout assumption |
| Nano 7 refresh / 1.1.2 | Independent complete image, pointers, domains, native setters and serializer | Same questions; explicit updater 39 identity is required, not merely the generic Nano 7 generation name |

`General.Clicker`, `Playback.Repeat`, and `Playback.Shuffle` are registered
strings, unlike the old binary numeric encodings. The captured registration
records preserve their defaults, but this pass does not qualify the complete
user-choice-to-string-to-runtime contract for new public editors. EQ and other
settings likewise remain outside this narrow authoring model.

The firmware stores and serializes live settings. That establishes a possible
later overwrite of a Host-patched file, but this pass does not trace USB detach
or restart all the way through reload/save scheduling. The UI must describe a
saved preferences **file**, not confirmed live adoption. No actual
`iPodSettings.xml` sample was present in the retained normal-mode capture
inventory examined for this pass; native serializer events and test fixtures
must not be described as physical captures.

Raw clock initialization, timezone/city mapping, DST policy, and the legacy
blob's timestamp validity are still separate research questions. Unsupported
or invalid datetime content remains preserved and cannot block otherwise
qualified Preferences edits.
