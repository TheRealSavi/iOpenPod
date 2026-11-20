# Persistent Now Playing preview loss: capture and retention fix

The user confirmed correct behavior on **0.6.7-dev** after the drawing-mode fix.
The current **0.6.8-dev** bundle omits temporary tracing; its developer build flag
remains available. This note records the preceding investigation and captures.

The user reproduced the failure on
**0.6.5-diag**, confirming Podcasts artwork as the trigger. Its capture identified
flat source pixels without a retained artwork reference. The
**0.6.6-dev** candidate retained the current-track thumbnail through native
ownership. Its replay passed, but the user subsequently reproduced the physical
failure on 0.6.6. That capture shows retained thumbnail samples matching the file
while the renderer selects icon-mask mode. Version **0.6.7-dev** corrects
that format selection; see [drawing-mode evidence and limits](classic-now-playing-render-mode-2026-11-18.md).

## Physical capture from 0.6.4-diag

On 2026-11-18 the user reproduced the failure after extensive successful menu and
Light/Dark use, then visits to Photos and Podcasts. Which visit triggered it is
unknown. The preview disappears completely, including the usual proxy image.
Earlier feedback established that changing albums does not restore it, while
full Now Playing and ordinary menu previews remain functional.

Two read-only Storage Hardware Probes returned identical stable traces. No device
write or reboot was performed. Private captures are
`.scratch/classic-artwork-source-20261118/capture-20261118-163203.json` and
`capture-20261118-163759.json` in that directory.

- 274 paint calls, 38 shows and 39 hides, including the USB transition.
- Flags `0x02004a00`, readiness 1, view rectangle `(35,176,163,304)`.
- Model-owned bitmap at `service + 0x18c`, non-null pixels, RGB565 format.
- Image and source-context clip rectangles both `(0,0,128,128)`.
- Last show recorded readiness 0 and no context; later paint had a context.

The view still paints and rebuilds its context. Valid recorded geometry does not
prove that pixels contain artwork, the destination permits drawing, or a raster
appears. No root cause is established.

The query counter was zero because **our diagnostic hook was wrong**:
`0x08100054` queries static `BMap`; dynamic `Draw` uses **0x0810008c**. Wrapper-only
native tests missed that actual call site. Zero does not mean Apple's model
stopped receiving requests.

The complete native SysInfo was XML, but plistlib rejected a key sequence outside
the diagnostic dictionary. The private helper now extracts the named dictionaries
with an XML parser and decodes them separately as plists, without exporting full
identity XML. Its physical payload was **14,715 bytes**; this supersedes the older
size estimate based on a different 12,464-byte baseline.

## Schema 2 and ownership

`--artwork-diagnostics` remains off by default and requires both artwork and boot
reporting. Both manifests record it; enabled source hashes include the probe.
The exact-preimage patches are:

| Address | Original | Observation |
| --- | --- | --- |
| `0x08988974` | Paint `0x0810012c` | Matching BitmapView state around native paint |
| `0x0810008c` | Query `0x08268b64` | Dynamic artwork source and native model |
| `0x08100278`, `0x081002e4` | Blit `0x08259568` | Tiled/ordinary draw inputs during this preview's paint |

Delegates run exactly once with unchanged results. Other views retain their
behavior. A scoped paint pointer restores its prior value on return; unrelated
nested draws cannot inherit the outer preview identity. USB hides do not replace
paint snapshots. Before each paint, obsolete blit inputs are cleared while the
cumulative count remains, so an early return cannot look like a previous draw.

The `iOpenPodArtworkTrace` dictionary publishes `Schema=2`, `Stable=1` and these
fixed-width hexadecimal-word strings (eight characters per 32-bit word):

| Field | Words | Meaning |
| --- | --- | --- |
| Counts | 4 | Paint, show, hide, query counts |
| AfterPaint | 20 | View, flags, ready, service, context; view rectangle; bitmap, pixels, format; image rectangle; source-context clip |
| Query | 16 | Last queried service/vtable/bitmap/pixels/format/rectangle; model cached ID, retained reference, pixels and rectangle |
| Blit | 20 | Count, view, destination/source contexts, opacity, flags; destination bitmap/pixels/format/mode; destination offsets/clip; source offsets/bitmap/pixels |
| Rects | 20 | Source/target draw rectangles, source/target surface rectangles, both strides and bits per pixel |
| Pixels | 8 | Sample count, OR, AND, fingerprint, first/middle/last words, source format |
| Model | 16 | Query-shaped model/bitmap snapshot after paint, including cached views that make no new query |

Rectangles are top/left/bottom/right. Pixel sampling requires bounded aligned
DRAM, 128-square RGB565 and 256-byte stride. It reads 64 distributed words plus
first/middle/last words, not a full image; unsampled pixels remain unverified.
Known-model fields require vtable `0x089986a4`. Bounds checks do not establish
object ownership. No pixel writes occur.

Retained state is **584 bytes**, with no allocation, timer, disk write or extra
NOR access. The XML reader attempts a stable sequence at most three times,
otherwise publishing `Stable=0` and zero fields without waiting for the UI.
Schema 1 additionally published BeforePaint/Show snapshots; schema 2 omits those
redundant fields on the wire to leave room for source and drawing details.

INQUIRY VPD page `0xc0` rebuilds current SysInfo through `0x080f2e04` and
`0x08147930`. Each diagnostic string stays within Apple's formatter limit.
Native test XML grows from 1,743 to 2,000 bytes, projecting the captured device's
payload to **14,972 bytes**, below the **15,376-byte** VPD/serializer limit. This
projection is specific to the captured state, not every possible SysInfo payload.

## Validation and next capture

The retained lab `scripts/probe_classic_artwork_trace_path.py` executes native
BitmapView loading, painting and raster drawing. Against 0.6.4-diag it fails:

```text
AssertionError: Native Draw/7f05 queried 1 time(s), but diagnostics recorded 0
```

It passes on 0.6.5-diag, including real pixel output, unchanged query/allocation
counts, distinct cleared-pixel versus empty-clip captures, and clearing obsolete
inputs after an early paint return. The image provider and destination attachment
are fixtures. This reproduces the **instrumentation defect**, not the device bug.

`probe_classic_artwork_trace.py` passes delegation, pointer guards, model fields,
hide preservation, unrelated views, exact native XML, maximum-width fields,
concurrent snapshot rejection and small-buffer overflow. Native boot-report tests
pass all four hardware profiles, error cases and bootstrap/BSS relocation.
The focused application/composition/install suite passes **242 tests**; Mypy
passes all 1,598 source files. Changed Python lint/format checks, documentation
lint and decompressed bundled-image length/hash verification also pass.

1. Restart iOpenPod and install universal 2.0.5; confirm **0.6.5-diag** in About.
2. Check the preview after **Photos first**, then Podcasts if it still works.
3. At first disappearance, stay on the menu and connect USB without rebooting or
   visiting full Now Playing. Another consumer of Draw/7f05 can replace the last
   view; identify the menu preview by its rectangle and address.
4. Run `uv run .scratch/classic-artwork-source-20261118/capture_trace.py --mount <root>`.
   The helper supports schemas 1/2 and writes only an extracted Host JSON report.
   It does not mutate or eject the iPod.

## Artifact

- Build: `.scratch/classic-artwork-source-20261118/release-4`.
- Prepared OS SHA-256:
  `948c8635439672398732b3fe5d4aaf855df8a7cd3317ac336cd5e46726f77d33`.
- Payload SHA-256:
  `5bbdc8a8a45639e0ebb3ea6e2ccaf6c1809751263bf1adb04d889aeae6dd596d`.
- Complete firmware SHA-256:
  `02881e5dce2d18904b695e5551f9221eb2ce53de956e0c86317a786160aedf15`.
- Complete image: 101,871,616 bytes; compressed asset: 56,753,332 bytes.
- Initialized payload: 112,256 bytes; reserved Mod Memory Region: **118,784 bytes**
  (one additional 4 KiB page relative to 0.6.4-diag).
- Apple version **2.0.5** and bootloader **2.1.0** are unchanged.

The user subsequently installed 0.6.5-diag. The following capture and candidate
supersede that release's outstanding next-capture status.

## Physical capture from 0.6.5-diag

The user confirmed that loading podcast art in Podcasts, then returning to the
main-menu Now Playing item, makes the preview disappear. A read-only normal-USB
capture is retained at
`.scratch/classic-artwork-source-20261118/capture-20261118-172713.json`.
The agent did not write firmware, reboot or eject the device.

- Current report: 0.6.5-diag, schema 2, stable snapshot; SysInfo **14,972 bytes**.
- 57 paints, 42 model queries and 57 final blits; opacity 255, flags zero.
- Source: RGB565, 128 × 128, stride 256; source clip and draw rectangle match.
- Destination: 320 × 240, stride 1280; offsets x176/y35, matching preview clip.
- All 64 sampled words and first/middle/last words equal **0x08610861**.
  Sampling does not prove the contents of every pixel.
- The exact Now Playing model (`0x089986a4`) reports cached artwork ID **0**
  and retained reference **0**, both at query and after paint.

The failure reaches raster drawing with valid geometry and flat source samples.
That distinguishes it from a missing query, missing view or wholly clipped draw.
The capture does not identify the exact Podcasts worker that changed the buffer.

## Retained-thumbnail candidate: 0.6.6-dev

The native property getter `0x081eda2c` returns the model bitmap at `+0x18c`.
With no matching cached ID at `+0x3b4`, it clears the retained reference at `+0xcc`
and queries the transient playback provider. That provider can report success
while the sampled contents are flat; its no-art fallback is therefore bypassed.
This explains why the captured failure does not show a proxy image.

Apple also has a retained-thumbnail path at `0x081eefc0`: look up the current
track in ArtworkDB, load format **1055**, retain its native reference, initialize
the model bitmap and cache its artwork ID. The new `iop_artwork_property` follows
that recipe before delegating to the original getter. It patches only the exact
model getter entry at **0x08998708**, with an original-value check.

The implementation checks both wrapper and pixel resource before bitmap setup;
a failed file load can leave a non-null wrapper with no resource. Missing/failed
art falls through to the native provider and its fallback selection. Video
retains native live-frame semantics. Repeated queries with a valid matching
reference perform no new file load. Native reference assignment/release handles
replacement; there is no independent accumulating image cache or global flush.

The lab's `scripts/probe_classic_retained_preview.py` executes the compiled hook,
native getter/vtable dispatch, thumbnail wrapper creation, shared-reference
counters and bitmap setup. ArtworkDB lookup, file reads, allocator and resource
destruction are explicit fixtures. It supplies the captured flat pixel word
through the successful transient-provider boundary, plus distinct current-track
artwork through the retained-file boundary. It **does not execute the complete
Podcasts GUI or background workers**.

```powershell
uv run ../ipod-firmware-lab/scripts/probe_classic_retained_preview.py `
  --build .scratch/classic-artwork-source-20261118/release-4 `
  --capture .scratch/classic-artwork-source-20261118/capture-20261118-172713.json `
  --out .scratch/classic-artwork-source-20261118/native-retained-old.json
```

The 0.6.5 build fails with:

```text
AssertionError: Preview returned captured flat playback pixels 61086108 instead of current-track artwork
```

Changing `--build` to `retained-1` passes on 0.6.6-dev, including 128 repeated
queries after changing the transient buffer, 32 artwork-ID changes, recovery
after a native reference release, unrelated property delegation, missing art,
failed-file retry and video provider/fallback behavior. Tracked thumbnail
allocations settle at **32,836 bytes**, peak at **65,672 bytes** during replacement,
and return to zero on fallback/video. Those figures cover fixture pixel resources,
wrapper and reference counter, not the entire filesystem/database heap.

Existing native diagnostic, real raster-path, 512 visibility-cycle,
16 appearance-cycle and four-profile boot-report probes also pass. The complete
Podcasts sequence and physical memory behavior remain unverified.
The focused application, firmware composition and installation suite passes
**223 tests** against the new bundle. Mypy passes all 1,598 source files; changed
Python lint/format and documentation checks pass. Runtime bundled-image validation
confirms the complete length/hash, including the new release's resource hooks.

The candidate's build is `.scratch/classic-artwork-source-20261118/retained-1`:

- Prepared OS: `fc21f44eab3acf347c3a6e17e5bc74d185b696de797946d6f24c705ec72f5387`.
- Payload: `ba05cac3e8bfb726e78105122c12086e79a7e83439a1f094ee3e92be305187ea`.
- Complete firmware: `7f4d74b4baed56bc22bb29cdac3a08c36d95a48ecf2ca5eed9ce5b38ae50a900`.
- Complete image 101,871,616 bytes; compressed asset **56,753,749 bytes**.
- Initialized payload **112,836 bytes**, up 580; fixed reservation remains
  **118,784 bytes**. Dynamic thumbnail ownership is separate from this reservation.
- Apple version 2.0.5 and bootloader 2.1.0 remain unchanged. Diagnostics stay enabled.

Next: install 0.6.6-dev through Device Summary, let Podcasts load artwork, then
return to the main-menu Now Playing preview. Repeat with another album and an
appearance change. If it disappears, connect USB without rebooting for another
capture. This turn only reads the device and packages the candidate on the Host.

## Loading artwork from a cold menu preview

The user also reported an earlier-version symptom: a proxy remains until opening
full Now Playing causes artwork to load. This was not yet tested on 0.6.6-dev.
Its retained-thumbnail hook already performs an explicit load, independently of
the playback provider's readiness; this does not require another firmware change.

The separate `--cold-preview-only` case in `probe_classic_retained_preview.py`
starts with no model reference or cached artwork ID and an unavailable playback
image. It runs native BitmapView load, property dispatch, the real current-track
ID lookup, the patched getter, thumbnail wrapper creation and raster drawing.
Metadata/file I/O, repaint scheduling and destination attachment are fixtures;
the test does not enter the full Now Playing controller or run a physical disk.

With the earlier capture/build arguments and `--cold-preview-only`, 0.6.5 fails:

```text
AssertionError: Cold menu preview rendered 00ff00ff instead of blue artwork
```

The green output pixel is the fixture's proxy; blue is its track artwork.
The identical test passes on the bundled 0.6.6-dev with **one thumbnail load,
zero playback-image queries**, and no further loads on repeated paints. The
native context and retained reference clean up to zero tracked allocations.
The combined retention regression also passes with this cold-view case added.
This establishes the direct request/render path, not every physical disk-read
timing or a retry after a failed read while the same proxy remains attached.
