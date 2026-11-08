# Latest Classic Preferences: qualified saved-setting writes

Investigated November 7, 2026, America/New_York. Scope: updater 24 / 1.1.2,
33 / 2.0.1, 35 / 2.0.4 and 38 / 2.0.5 only. These are the four studied Classic
6, 6.5, 7 and 7.5 firmware targets; the exact qualification rules remain in
[the target report](classic-latest-firmware-targets-2026-11-05.md).
This investigation used preserved firmware, read-only Ghidra exports and bounded
ARM execution. It performed no physical-device access or publication.

Six settings have a qualified saved-file editing contract across all four:
Shuffle, Repeat, EQ, Sound Check, Brightness and Clicker Off/On. Classic 120GB
2.0.1 additionally exposes the previously qualified Alternate Audio switch.
Writing the file does **not** establish live adoption or persistence after a
later firmware flush. Backlight, menu customization and language selection need
further domain or lifecycle work; they are not filled with guessed choices.

## Primary inputs and evidence boundaries

| Family / release | Original OSOS | SHA-256 | Preferences frame |
| --- | --- | --- | --- |
| 24 / 1.1.2 | `Classic24FW/decrypted/osos.bin` | `9fc12ffc0817d481af6bcdded1a8f3c720027c85872aa13bade22cbe60913b4a` | 2,952 bytes; LE32 version `0x3c` |
| 33 / 2.0.1 | `inputs/prepared-2.0.1/osos.bin` | `220913cb8569af0538a7e828f1aaa08d9313bf9a5c2b0a7a7e6e2dc0bee5f16e` | 2,956 bytes; LE32 version `0x3d` |
| 35 / 2.0.4 | `Classic35FW/decrypted/osos.bin` | `2ca353870e84bc92ff5090024122ee0712d9bb992c6933b3b230c0ae613b0ffe` | 2,956 bytes; LE32 version `0x3e` |
| 38 / 2.0.5 | `Classic38FW/decrypted/osos.bin` | `d7669f9266e7cae15867248eeb9c34a2711f1f9a1f3cf40132ef86d9fdbf8224` | 2,960 bytes; LE32 version `0x3f` |

The [new harness][harness] pins each image before discovery or execution. The
[final v3 receipt][receipt] records map hashes, function hashes, allowlisted
executed addresses, mock targets and **260 native cases**, 65 per image. Its
SHA-256 is `fa2d61be25783e40ba8bb9fafaa98272418eaa329059b2aebd04e6618f06f704`;
the formatted harness SHA-256 is
`343b1ecf94dc932a360e98e7d811d6e6394ffc44a1fdf4c78243df3d7843c4b3`.

Relocation-normalized matches locate candidates; they are not the final proof.
Each candidate then executes its own original instructions. Player instance and
virtual query, notifications and slider property dispatch are explicit memory
mocks. Getters, scalar setters, dirty markers and brightness clamping execute
natively. The harness does not execute filesystems, USB, the complete OS or
physical display/audio output. The earlier [424-case EQ/persistence probe][eq]
separately executes the full payload reader, defaults, loader and writer for all
four. The [new export audit][export-audit] verifies 65 distinct family-33 functions
and 18,628 unique instruction bytes against the original image. Decompiled
names and types remain analyst annotations.

## File fields and supported edits

All offsets below are from byte zero of
`iPod_Control/Device/Preferences`, not from an in-memory object. Classic retained
payload starts at context `+4`. Multi-byte fields are little-endian.

| Setting | Native file representation | Authored values and preservation |
| --- | --- | --- |
| Shuffle | `+0x18` u8 enabled; `+0x8a` u8 album grouping | Public 0 Off, 1 Songs, 2 Albums; native pairs `0/0`, `1/0`, `1/1`. Already-Off may retain the irrelevant album byte. Malformed boolean bytes stay exact and do not alias a normal choice. |
| Repeat | `+0x14` u32 | **0 Off, 1 All, 2 One**. These are saved values, not menu indices. Unknown words remain raw until an explicit supported choice. |
| EQ | `+0xb60` u16 | Off `0`, preset IDs `100..121`. Preserve all 16 bits when unchanged; do not reinterpret an unknown full word as its low-byte preset. |
| Sound Check | `+0xb16` u8 | `0` Off, `1` On. Other retained bytes survive unrelated edits. |
| Brightness | `+0xb54` u8 | Inclusive `0..100`, as established by the actual wheel-handler clamp. Values are native slider units; no luminance calibration is claimed. |
| Clicker | Low two bits of `+0xafc` u32 | Classic editor offers `0` Off and `3` On; preserve upper 30 bits. The code has additional individual-bit routes, but their Classic hardware routing is not qualified here. |
| Alternate Audio, **33 only** | `+0xb85` u8 | `0` Off, `1` On, reusing [the existing qualified trace][alternate]. Other families remain outside that field's authoring profile. |

The per-family scalar getter / setter entries are:

| Operation | 24 | 33 | 35 | 38 |
| --- | --- | --- | --- | --- |
| Shuffle get / set | `08032220` / `08044c60` | `08033150` / `08045e60` | `08049f08` / `0805c7a0` | `08049f28` / `0805c7dc` |
| Repeat get / set | `08031f0c` / `08044b84` | `08032e3c` / `08045d84` | `08049bf4` / `0805c6c4` | `08049c14` / `0805c700` |
| Sound Check get / set | `080323a8` / `08045040` | `080332d8` / `08046240` | `0804a090` / `0805cb80` | `0804a0b0` / `0805cbbc` |
| Brightness get / set | `0802ed08` / `08044454` | `0802fbf4` / `08045634` | `08046710` / `0805bf74` | `08046704` / `0805bfb0` |
| Brightness clamp | `081bd53c` | `081c7e9c` | `081e20c0` | `081e2ee8` |
| Clicker get / set | `0802ec00` / `08044394` | `0802faec` / `08045574` | `08046608` / `0805beb4` | `080465fc` / `0805bef0` |
| Language get, full u32 | `08030d4c` | `08031c70` | `08048948` | `08048968` |

These are runtime ARM addresses, not binary file offsets. Exact byte lengths and
SHA-256 hashes are in the [receipt][receipt]. EQ functions are tabulated in the
[separate all-four EQ note][eq], rather than rediscovered or inferred from a
uniform address displacement.

For semantic attribution, family 33's literal `ToggleSetting_Shuffle`,
`ToggleSetting_Repeat`, `ToggleSetting_SoundCheck` and `ToggleSetting_Clicker`
actions lead through Settings model property callbacks to the saved setters.
The [property setter][property-set] maps Repeat menu index `1` to saved `2`, and
index `2` to saved `1`. The [player default path][repeat-apply] calls the saved
getter and maps its result back to native playlist repeat modes. The actual
predicates [Repeat All][repeat-all] and [Repeat One][repeat-one] test playlist
values `1` and `2`, respectively. This closes the saved-versus-menu ambiguity:
saved `1` is All and saved `2` is One.

The Clicker property callback cycles only two ordinary UI states, despite
retaining additional bit-level paths. That matches Apple's 120GB guide, which
documents the ordinary Clicker Off/On control and the brightness slider.
[Apple user guide, pages 8 and 10][manual]. The restricted Classic choices do
not import Mini or Video speaker/headphone bit labels.

## Loader, reset word and persistence

The whole-payload reader first clears its destination and reads at most its
expected extent. The higher-level loader defaults again when the version at
file `+0` is zero or the second u32 at **file `+4` is nonzero**. Current versions
retain unknown scalar words. Firmware can accept short or future-version files;
that permissiveness does not qualify them for Host editing. The Host API instead
requires explicit identity-derived profile, exact version and exact extent.
A nonzero reset word is preserved and disables authoring; it is never silently
cleared. [All-four native loader cases][eq]

Native setters update retained RAM and mark it dirty; some also notify or call
the live player. Those live effects are not reproduced by a Host file patch.
The native writer copies the entire retained payload, replaces file `+8` with a
live service value and writes the full expected extent. The verified outgoing
payload has no other transformation or checksum update. This supports a pure
byte patch; it does not assign meaning to every unknown byte. [Writer cases][eq]

The earlier stale-Host-edit native case proves that a subsequent dirty flush can
overwrite a newer disk value with an older RAM value. Family-33 construction
calls the file loader, but Library reconstruction reuses the existing Preferences
context. A database reload therefore does not establish a Preferences reload.
The normal USB/disk-mode detach ordering, reboot requirements and retained-state
adoption remain unresolved. This bounded pass does not claim all direct and
indirect lifecycle paths have been exhausted. The application can report saved
and verified file bytes; it must not promise live adoption or a required restart
without further evidence. [Lifecycle boundary and acceptance proposal][eq]

## Codec consequences and remaining questions

The public [qualified edit API][native-codec] exposes typed keys and domains,
reads unnormalized values, and records explicit edits while retaining original
source bytes. Serialization patches only those fields. Scalar unknowns, clock
words and malformed dates do not block unrelated supported edits. A malformed
compound Shuffle value is reported as unrepresentable, not silently converted
to Songs or Off. Storage publication remains an application workflow.

All four qualified Classic language getters read **LE32 at file `+0xaf8`**.
Native vectors include `0x100`, `0xa5a50000` and `0xffffffff`; none is English
zero. Qualified models now retain the full word; historical generic byte
projections remain available for backward compatibility. Language is absent
from the new authoring catalog pending its resource-dependent menu domain.
The older inverse `write_preferences` contract still permits explicitly replaced
known language integers within their binary width; that low-level capability is
not a qualified application language editor.

Remaining questions are the same on the four targets unless specified:

- Backlight selector get/set is proven at file `+0xaf0` u32. Native vectors
  establish byte behavior, not a complete code-to-duration/menu catalog.
  The adjacent word at `+0xaec` is **not** established here as a second timeout;
  no coupled write is invented. Resolve actual duration consumption and menu
  choices before exposing it.
- Resolve the full Main/Music menu bit catalog and dependent refresh behavior;
  neighboring fields or defaults are not sufficient labels.
- Bind every offered language code to the actual per-build resource catalog,
  locale/resource reload and persistence path. The word width is now closed.
- Determine exact USB disconnect, disk-mode exit and restart load/flush ordering;
  distinguish saved-file readback, menu adoption and later retention.
- Qualify any extra fields, including Alternate Audio on 24/35/38, through their
  own callers and on-disk framing. Do not copy the 33-only field merely because
  another payload has enough bytes.

The [codec regressions][tests] check six qualified formats, exact unknown-byte
preservation, unknown values, low-bit overlays, typed domains, no-op/reverted
edits and refusal of unqualified/reset frames. Native and application tests have
different scopes: authored test bytes validate the Host contract; pinned ARM
execution supplies the firmware evidence.

[harness]: ../../../ipod-firmware-lab/scripts/check_classic_preferences_settings.py
[receipt]: ../../../ipod-firmware-lab/artifacts/preferences-classic-native-20261107-v3/receipt.json
[export-audit]: ../../../ipod-firmware-lab/artifacts/preferences-classic-export-audit-20261107.json
[eq]: ../../../ipod-firmware-lab/notes/eq-preferences-configuration.md
[alternate]: ../../../ipod-firmware-lab/notes/itunesdb/video-alternate-audio.md
[property-set]: ../../../ipod-firmware-lab/artifacts/preferences-classic-discovery4-20261107/0814df14-FUN_0814df14.c
[repeat-apply]: ../../../ipod-firmware-lab/artifacts/preferences-classic-discovery11-20261107/0815a728-FUN_0815a728.c
[repeat-all]: ../../../ipod-firmware-lab/artifacts/preferences-classic-discovery11-20261107/0815a5e8-MediaPlayer_IsRepeatAll.c
[repeat-one]: ../../../ipod-firmware-lab/artifacts/preferences-classic-discovery11-20261107/0815a61c-MediaPlayer_IsRepeatOne.c
[manual]: https://cdsassets.apple.com/live/6GJYWVAV/user/ma630_ipod_classic_120gb_en.pdf
[native-codec]: ../../src/iPodDB/preferences/native.py
[tests]: ../../tests/iPodDB/test_native_preferences.py
