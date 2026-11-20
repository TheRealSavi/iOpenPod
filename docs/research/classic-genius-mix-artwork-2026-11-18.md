# Classic Genius Mix artwork

Classic RetailOS 2.0.5 supports a dedicated cover for each Genius Mix. Its proxy
image is a fallback, not the required appearance. The native browser looks up an
ArtworkDB image by the Mix's persistent Playlist ID, then preloads its **F1069**
thumbnail. At the start of this investigation, iOpenPod Mix creation supplied
the Mix and its members but did not author this image. No firmware patch is
needed to use the existing cover path. The later Nano 7 qualification below
establishes its separate F1010 route. [Mix browser][browser], [Mix writer][writer]

## Scope and exact source

The initial execution evidence in this report uses the original Classic family-38
RetailOS **2.0.5** logical OSOS, SHA-256
`d7669f9266e7cae15867248eeb9c34a2711f1f9a1f3cf40132ef86d9fdbf8224`, with its
independently recovered [runtime map][map]. Addresses are runtime addresses in
that image. This investigation did not install firmware, modify a device, or
visually test an authored cover. It extends the earlier
[Classic Mix format investigation][mixes].

## Lookup, preload, and fallback

1. Browser initialization at `0x081aaf1c` acquires the `GeniusMixArtwork` allocator
   and invokes preload `0x081ab23c` for up to twelve Mixes.
2. Preload gets the full 64-bit persistent Playlist ID through `0x0829cf34`.
   Wrapper `0x0815e298` passes it through `0x08046474` to `0x08045668`, using the
   device's existing artwork library at context `+0xf9c`.
3. The lookup compares both ID words against native image `+0x10/+0x14`. The
   MHII importer `0x08074db8` obtains these from serialized MHII `+0x14/+0x18`.
   iPodDB currently calls this field `db_track_id_ref`, but this consumer also
   uses it for a **Mix identity**. It does not ask for the first candidate
   Track's artwork or automatically assemble a collage.
4. Preload calls `0x082664d8` with format **1069**, from literal `0x081ab36c`.
   That thumbnail-reference constructor finds the requested format using
   `0x08048c5c`. `0x080f33a4` loads its pixels; `0x080f36a4` returns the bitmap.
   Only a successfully obtained bitmap enters the browser's cover cache.
5. The selected-Mix artwork getter `0x081ab6cc` repeats the identity lookup.
   It initially constructs an F1055 reference, but replaces that reference with
   the preloaded cache entry before drawing. **F1055 alone does not supply this
   browser's cover.** If there is no usable cache entry, it requests built-in
   bitmap resource `0x0dad0128` in resource class `BMap` (`0x424d6170`).

These branches are visible in the [exact decompiler export][artwork-export] and
[browser initialization][browser]. The displayed image is independent of the
currently playing Track's cover on the full Now Playing screen.

The image lookup uses the full 64-bit identity, but preload inserts the cover
into its local map using only the **low 32 bits** (`0x081ab31c`–`0x081ab334`).
Selection uses the same truncated key (`0x081ab74c`–`0x081ab7ac`). A future
producer should avoid lower-word collisions among its Mix IDs. This is a
native implementation constraint, not evidence that such a collision caused
the user's missing covers. [Preload and selection][artwork-export]

## Native artwork representation

The original descriptor routine `0x080fad38`, executed with format 1069, returns:

| Property | Value |
| --- | --- |
| Width and height | 142 × 142 |
| Row stride | 284 bytes |
| Pixel representation | 16-bit RGB565, native tag `0x565` |
| Rotation | 0 |
| Pixel payload size | 40,328 bytes |

The descriptor bytes are
`8e0000008e0000001c0100000000000000000000000000001000000065050000`.
The [execution receipt][display-receipt] records these independently of the
decompiler. The firmware's existing SysInfo emitter also advertises F1069 with
association `0x20000`; the concrete browser call above now establishes its Mix
use. [Descriptor source][descriptor], [earlier format evidence][formats]

Authoring therefore needs an ordinary ArtworkDB MHII image with a unique image
ID and its reverse identity set to the Mix persistent Playlist ID. Its MHOD-2 /
MHNI child must describe F1069 pixels, with valid dimensions, filename, offset,
and length. The pixels belong in an Artwork-directory ithmb file, for example
`F1069_1.ithmb`, referenced through the usual `:F1069_1.ithmb` filename token.
The filename's digits do not select the format; the MHNI format ID does. The
normal [ArtworkDB file contract][file-contract] and
[2.0.5 native bitmap loader][formats] apply. This is a concrete format route,
not yet a qualified complete Mix-image writer.

## Offline execution evidence

The [identity probe][identity-probe] serializes two images with iPodDB's actual
low-level ArtworkDB builder and executes the original MHLI/MHII importer. Their
identities are `0x123456789abcdef0` and `0x234567899abcdef0`. Both import exactly,
and the original lookup returns the corresponding image for each. It rejects
`0x3456789a9abcdef0`, which shares their low word, and zero. This confirms full
64-bit matching before the browser's separate cache. The fixture intentionally
has no thumbnail children: it isolates identity rather than claiming raster
qualification. File services, allocation, readiness and progress notifications
are explicit adapters. [Identity receipt][identity-receipt]

The [display probe][display-probe] executes original preload `0x081ab23c` followed
by selected-image getter `0x081ab6cc` in six cases:

| Supplied artwork | Native controller outcome |
| --- | --- |
| No matching MHII | Built-in proxy |
| Matching image without thumbnails | Built-in proxy |
| F1055 only | Built-in proxy |
| F1069 only, successful load | Preloaded Mix bitmap |
| Both F1055 and F1069, successful load | Preloaded F1069 Mix bitmap |
| F1069 whose pixel load fails | Built-in proxy |

The controller's branch logic, format constants, bitmap-pointer getter, and
descriptor execute unmodified. The display probe adapts image lookup, thumbnail
construction, pixel loading, smart references, map storage and final drawing.
Thus it establishes the format selection and fallback contract, not complete
filesystem loading, cache lifetime, rendered pixels, or physical display.
All six cases and the descriptor assertions pass. [Display receipt][display-receipt]

## iOpenPod implementation implications

Current `GeniusMix` is an alias of `SQLiteGeniusMix`, carrying `container_id`,
`name`, `track_ids`, and optional `seed_track_id`; it has no cover intent.
The Classic writer authors the native Mix title and members. Existing artwork
reconciliation creates artwork through Track changes, and returns early when
there are no changed or deleted Tracks. The proxy is therefore consistent with
the data currently authored. [Mix data][mix-data], [Mix writer][writer],
[artwork writer][artwork-writer]

A proper addition should express Mix-owned artwork explicitly, preserve
unrelated and unknown images, allocate collision-free identities, publish
ArtworkDB and pixel slices through the existing Storage workflow, and remove
only owned unused assets when a Mix is removed. It should not invent a fake
Track solely to drive the Track artwork writer. Because the artwork lookup has
no Track/Mix type discriminator, identity allocation also needs to account for
existing artwork reverse identities. The browser's low-word cache constraint
is an additional distinct check.

Cover design is a Host decision: a four-album collage, one representative cover,
or dedicated artwork can all be encoded as the required raster. The firmware
does not choose or compose those source images in this path. Physical validation
of an authored image and complete publication/cleanup remain implementation
work; no product behavior changed in this investigation.

## Device qualification follow-up

The cover writer must have its own capability gate, separate from native Mix
playback. A positive result for the Classic F1069 route does not qualify another
device's cover representation. Conversely, an unqualified writer must not be
reported as evidence that the device can never display Mix artwork.

| Target | Native cover evidence | Initial F1069 writer qualification |
| --- | --- | --- |
| Classic 2.0.4 | Six native preload/selection cases and descriptor execution | Qualified format path |
| Classic 2.0.5, including qualified shared OS on older Classic hardware | Six native preload/selection cases, descriptor and identity import/lookup execution | Qualified format path |
| Classic 2.0.3 | No exact mapped image tested in this investigation | Unknown |
| nano 4 | Existing registry marks native Mix playback unsupported | Not qualified |
| nano 5 1.0.2 | Mix playback known; cover producer/consumer not qualified here | Unknown |
| nano 6 1.2 | Static Mix-image lookup and F1073 load/fallback path | Different path; not qualified |
| nano 7 1.0.4 and 1.1.2 | Native image import, identity, descriptor and UI selection tests | Different F1010 path, qualified below |

Classic **2.0.4** OSOS SHA-256 is
`2ca353870e84bc92ff5090024122ee0712d9bb992c6933b3b230c0ae613b0ffe`.
The follow-up independently located preload `0x081aa8b8` and selected-image
getter `0x081aad48` by normalized instruction matching, then executed the same
six cases against the original 2.0.4 instructions. Its descriptor routine
`0x080fac80` returns exactly the same F1069 descriptor. Its fallback resource ID
differs from 2.0.5; the probe reads the actual per-image literal rather than
assuming equal resource numbering. All six cases and the descriptor pass with
the same explicitly bounded adapters as the 2.0.5 probe.
[2.0.4 probe][probe204], [2.0.4 receipt][receipt204]

The assumption that Nanos are always proxy-only is incorrect. In the saved nano
6 **1.2** image, SHA-256
`d529680b7e7662876543d70b6941ddfac123d96c8ed1923432e4909909e896d8`,
Mix artwork routine `0x082c8b50` obtains a Mix identity with `0x081bd8f6` and
looks up its image through `0x08150c88` → `0x0815389c` → `0x08156d08`.
The loader receives format **1073** from the literal at `0x082c8d10`. The
routine has explicit successful-image and fallback paths, and separate
prefetch behavior. This is static consumer evidence, not a qualified Nano
ArtworkDB writer. [Nano 6 Mix artwork][nano6-art], [Nano 6 identity lookup][nano6-id]

Nano 7 **1.0.4**, SHA-256
`4a55fffbf58cfd04a393e9a40c0c1c42471dfb34d11847b676b85f02a8019999`,
uses Mix-image property `0x0822ace6` → `0x083a7c7c`. The latter obtains the
Mix identity through `0x08410a04`, looks it up through `0x081ed5a4` →
`0x080de498` → `0x080dc330`, and requests format **1010** (`0x3f2`) through
`0x083fb890`. It displays the resulting image or falls back, while the property
method also prefetches neighboring Mixes. Nano 7 **1.1.2**, SHA-256
`ac4cf072d3c3f971b6acc03ed4f2ad1baa57d7bae20f89692bd6fb08d8a749e4`,
contains the corresponding flow at `0x083a7c9c`, again requesting F1010.
These initial static traces are supplemented by the Nano 7 native execution
evidence below. No physical Nano display test was performed.
[Nano 7 image property][nano7-property], [1.0.4 artwork flow][nano7-art],
[1.1.2 artwork flow][nano75-art]

The Nano paths use their own provider/cache implementations. Different native
image layouts alone do not establish disk-field compatibility; the Nano 7
importer and format are now qualified below, while Nano 5 and 6 remain
unqualified. Cover publication should require a qualified target/format pair,
independent of playback capability. [Native Genius capability policy][capabilities]

## Nano 7 and 2015 refresh qualification

Both saved Nano 7 images support dedicated Mix covers using **F1010**, through
the ordinary binary ArtworkDB. The 2015 refresh is represented here by
`Nano75FW` release **1.1.2**; the earlier model is `Nano7FW` **1.0.4**. The hashes
above pin the exact images. This qualification does not generalize to an
uninspected Nano release.

### Identity and file contract

The Mix identity is the full 64-bit SQLite **`container.pid`**, not a Track ID,
SQLite row number, thumbnail ID, or alternate artwork identifier:

1. The container query at `0x087f4e69` selects `container.pid` as column zero.
   Reader `0x0848c410` loads that query. Its vtable at `0x087f139c`, slot `+0x3c`,
   points to `0x084b16da`, which calls the 64-bit column getter `0x084005de` with
   column zero.
2. Container construction `0x0848d3fc` reads that PID and passes both words into
   `0x0848da80` → `0x0848f03c`, which stores them at object `+0x10/+0x14`.
   Distinguished kind `0x20` routes the object into the Mix vector at root
   `+0x6c`. The displayed Mix handle retrieves those same words through
   `0x08410a04` in 1.0.4, or `0x08410a08` in 1.1.2.
3. ArtworkDB MHII import `0x08136a20` / `0x08136a24` copies disk MHII
   **`+0x14/+0x18`** into native image **`+0x38/+0x3c`**. The same serialized
   `db_track_id_ref` field used by the Classic therefore also carries the
   Nano Mix identity, despite the different in-memory layout.
4. The Mix image lookup reaches `0x080dc330`, comparing both words. No
   additional SQLite artwork column is read by this Mix cover lookup.

The query, container and importer sources establish these steps; the native
probe additionally executes the actual handle getter and full-word image
lookup for two imported Mix IDs with identical low words.
[Query export][nano7-query], [container construction][nano7-container],
[PID storage][nano7-container-pid], [MHII import][nano7-import],
[native probe][nano7-probe]

The required representation is:

| Field | Nano 7 value |
| --- | --- |
| MHII image ID | Unique image identity; distinct from Mix persistent ID |
| MHII reverse identity at `+0x14` | Full 64-bit Mix `container.pid` |
| MHOD-2 / MHNI format | **1010** |
| Width and height | **240 × 240** |
| Stride | **480 bytes** |
| Pixel encoding | **RGB565 little-endian**, 16 bits, native tag `0x565` |
| Rotation | 0 |
| Payload size | **115,200 bytes** |
| MHOD-3 filename example | UTF-16LE `:F1010_1.ithmb` |
| Pixel file example | `iPod_Control/Artwork/F1010_1.ithmb` |

Original descriptor `0x08402a10(1010)` returns
`f0000000f0000000e00100000000000000000000000000001000000065050000`
in both releases. MHNI importer `0x0814ee2c` / `0x0814ee30` retains the file
offset and payload length at native thumbnail `+0x18/+0x1c`, and decodes the
MHOD-3 filename through `0x081689f8` / `0x081689fc`.

Artwork library loader `0x080e0f2c` roots the library at
`iPod_Control/Artwork` and reads `ArtworkDB`. Path resolver `0x080deb38`
prefixes that library directory when the filename starts with `:`.
Bitmap loader `0x0819cfa0` / `0x0819cfa4` obtains the format descriptor, opens
that resolved file, seeks to the MHNI offset, and reads its length. F1010 uses
the ordinary raw bitmap branch; the loader's special decode branch is for
format `0x3fa`, not F1010 (`0x3f2`).
[ArtworkDB loader][nano7-library], [path resolver][nano7-path],
[bitmap loader][nano7-bitmap], [refresh bitmap loader][nano75-bitmap]

### Selection, fallback, limits, and evidence

The native Mix UI prefers this Mix-owned image. When that identity has no
image, it can try the first member Track's image before using a proxy. This
differs from the Classic preload behavior. Both selection and neighboring-Mix
prefetch request F1010 through the existing asynchronous loader/cache.
Initialization `0x0822a82c` caps the displayed Mix count at **18**; image
property `0x0822ace6` prefetches indices **−1, −2, +1, +2** around the selected
Mix. The native cache owns the retained representation. These observations do
not establish a complete memory budget or validate cache eviction/lifetime.
[Nano 7 initialization][nano7-init], [image property][nano7-property],
[image selection][nano7-art]

The [reproducible probe][nano7-probe] uses actual iPodDB low-level builder output
and the original instructions of both firmware images. Its
[combined execution receipt][nano7-receipt] records:

- Four MHII imports with native MHOD-2, MHNI and MHOD-3 parsing, preserving
  full Mix IDs, F1010, dimensions, offsets, sizes and filename text.
- Eight original full-ID lookups, including successful IDs with the same low
  word and rejection of a different high word and zero.
- Two original F1010 descriptor calls.
- Eight original UI selection cases: each of the two authored Mix IDs draws
  the adapted image, an unknown ID falls back to the proxy, and prefetch
  requests F1010 without performing the selected-image draw.

Stream, allocation, filename storage, bitmap cache, drawing, and reference
lifetime have explicit adapters. The native selector, PID getter, image
provider, full identity lookup and presence branch execute unmodified.
The probe does not execute physical file I/O, raster rendering, asynchronous
cache scheduling or a real display. The first-member fallback is statically
traced but not exercised in these eight UI cases. Physical Sync/rendering and
production publication/cleanup still require application-level validation.

[map]: ../../../ipod-firmware-lab/Classic38FW/evidence/runtime-map.json
[mixes]: classic-genius-mixes-2026-11-18.md
[browser]: ../../../ipod-firmware-lab/artifacts/classic-genius-mixes-20261118/seed/081aaf1c.c
[artwork-export]: ../../../ipod-firmware-lab/artifacts/classic-genius-mix-artwork-20261118.c
[descriptor]: ../../../ipod-firmware-lab/artifacts/issue178-classic7/38-verified/080fad38.c
[formats]: classic7-artwork-firmware-178.md
[file-contract]: ../../../ipod-firmware-lab/notes/itunesdb/artwork-import-and-file-contract.md
[identity-probe]: ../../../ipod-firmware-lab/scripts/probe_classic_mix_artwork_identity_20261118.py
[identity-receipt]: ../../../ipod-firmware-lab/artifacts/classic-genius-mix-artwork-20261118/identity-receipt.json
[display-probe]: ../../../ipod-firmware-lab/scripts/probe_classic_mix_artwork_20261118.py
[display-receipt]: ../../../ipod-firmware-lab/artifacts/classic-genius-mix-artwork-20261118/display-receipt.json
[mix-data]: ../../src/iPodDB/SQLiteDB/inputs.py
[writer]: ../../src/iPodDB/library/_classic_genius_mixes.py
[artwork-writer]: ../../src/iPodDB/library/_artwork_writing.py
[probe204]: ../../../ipod-firmware-lab/scripts/probe_classic204_mix_artwork_20261118.py
[receipt204]: ../../../ipod-firmware-lab/artifacts/classic-genius-mix-artwork-20261118/classic204-receipt.json
[nano6-art]: ../../../ipod-firmware-lab/Nano6FW/analysis/osos-corpus/functions/082c8b50.c
[nano6-id]: ../../../ipod-firmware-lab/Nano6FW/analysis/osos-corpus/functions/08156d08.c
[nano7-property]: ../../../ipod-firmware-lab/Nano7FW/analysis/osos-corpus/functions/0822ace6.c
[nano7-art]: ../../../ipod-firmware-lab/Nano7FW/analysis/osos-corpus/functions/083a7c7c.c
[nano75-art]: ../../../ipod-firmware-lab/Nano75FW/analysis/osos-corpus/functions/083a7c9c.c
[nano7-query]: ../../../ipod-firmware-lab/artifacts/nano7-genius-art-query-20261118/0848c410.c
[nano7-container]: ../../../ipod-firmware-lab/Nano7FW/analysis/osos-corpus/functions/0848d3fc.c
[nano7-container-pid]: ../../../ipod-firmware-lab/Nano7FW/analysis/osos-corpus/functions/0848f03c.c
[nano7-import]: ../../../ipod-firmware-lab/Nano7FW/analysis/osos-corpus/functions/08136a20.c
[nano7-probe]: ../../../ipod-firmware-lab/scripts/probe_nano7_mix_artwork_20261118.py
[nano7-receipt]: ../../../ipod-firmware-lab/artifacts/nano7-genius-mix-artwork-20261118/final-receipt.json
[nano7-library]: ../../../ipod-firmware-lab/Nano7FW/analysis/osos-corpus/functions/080e0f2c.c
[nano7-path]: ../../../ipod-firmware-lab/Nano7FW/analysis/osos-corpus/functions/080deb38.c
[nano7-bitmap]: ../../../ipod-firmware-lab/Nano7FW/analysis/osos-corpus/functions/0819cfa0.c
[nano75-bitmap]: ../../../ipod-firmware-lab/Nano75FW/analysis/osos-corpus/functions/0819cfa4.c
[nano7-init]: ../../../ipod-firmware-lab/Nano7FW/analysis/osos-corpus/functions/0822a82c.c
[capabilities]: ../genius-capabilities.md
