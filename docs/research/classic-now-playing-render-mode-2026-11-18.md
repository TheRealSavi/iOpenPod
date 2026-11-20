# Now Playing preview: select the actual bitmap's drawing mode

The user subsequently confirmed correct behavior on **0.6.7-dev**. The current
**0.6.8-dev** bundle keeps the fix with temporary artwork tracing disabled.
The evidence below records the investigation; the final section records cleanup.

## Physical evidence

The user reproduced the same completely blank main-menu Now Playing artwork on
**0.6.6-dev**: the preview initially works, Podcasts loads its artwork, then the
preview disappears on return. The 0.6.6 retention change did not resolve this.

A read-only normal-USB capture is retained in
`.scratch/classic-artwork-source-20261118/capture-20261118-175046.json`:

- Mod report 0.6.6-dev, stable schema 2; SysInfo **14,971 bytes**.
- 25 paints and blits, 22 source queries; source and destination geometry valid.
- Current model cached artwork ID **221**, retained reference nonzero.
- RGB565 source, 128 × 128, 256-byte stride; nonuniform sampled image data.
- Destination ARGB8888, 320 × 240; preview clip `(35,176,163,304)`.
- Opacity 255, flags zero, native drawing mode **0x21**.

A separate read-only Storage Filesystem Session parsed ArtworkDB and read only
image 221's format-1055 thumbnail range. Its 64-word sample fingerprint and
first/middle/last words match the firmware capture exactly. The private comparison
is `physical-066-pixel-match.json` in the same directory. This is strong evidence
for retained artwork being intact; it is not a comparison of every RAM pixel.
No device writes, reboot or eject occurred during this investigation.

## Native mismatch

BitmapView's loader `0x08100020` handles two sources:

- Static `BMap`: initialize the view's embedded bitmap at `+0xa4`.
- Dynamic `Draw`: attach a context to the model's bitmap without populating that
  embedded static bitmap.

Paint `0x0810012c` nevertheless reads the embedded bitmap format at `view+0xb8`
to select color versus mask rendering. At `0x081001f0` it loads that halfword;
formats 2, 4 or 8 select a tint and mode **0x21**. The base geometry callback at
`0x08100364` adjusts rectangles, not the drawing mode. The raster call ultimately
receives the actual model's RGB565 source paired with the incompatible mask mode.

The capture and native code establish the format-selection mismatch. They do
not record which Podcasts operation last wrote the embedded bitmap field. It
may be stale state; do not present a traced Podcasts allocator/worker as evidence.
The earlier raster tests initialized the view to zero and missed this state.

## Correction and scope

**0.6.7-dev** replaces only the format-read instruction with
`classic_about/artwork.S`'s `iop_artwork_format`. For `Draw/0x7f05`, it reads the
format from the current context's actual bitmap (`context+0x1c`, then `+0x14`).
Other properties and static sources execute the original embedded-format read.
Null context/bitmap takes the original fallback; genuine dynamic mask formats
still select Apple's mask path. No view, image or context fields are changed.

The hook preserves r1–r12 and stack alignment. The following native comparison
overwrites condition flags, so it does not depend on the replaced instruction's
flags. The builder verifies the exact `b80bd4e1` preimage before replacing it.
This composes independently of appearance and diagnostic hooks. Existing
retained-thumbnail ownership, fallback selection and cold loading are unchanged.

## Regression evidence

The retained lab script exercises native loading, property dispatch, bitmap
construction and raster drawing. The new argument supplies an embedded mask
format alongside the real dynamic RGB565 source:

```powershell
uv run ../ipod-firmware-lab/scripts/probe_classic_retained_preview.py `
  --cold-preview-only --embedded-format 4 `
  --build .scratch/classic-artwork-source-20261118/retained-1 `
  --capture .scratch/classic-artwork-source-20261118/capture-20261118-175046.json `
  --out .scratch/classic-artwork-render-20261118/native-mode-old.json
```

On 0.6.6 this selects **0x21** and produces **00000000**, leaving the destination
unchanged instead of drawing the blue fixture artwork. With `--build` changed to
`.scratch/classic-artwork-render-20261118/candidate-1`, 0.6.7 selects **0x20** and
draws **ff0000ff**. Embedded formats 2, 4 and 8 all pass. The `--no-art` case also
draws the native fallback correctly with no thumbnail allocation.

`probe_classic_artwork_format.py` passes 29 format/scope/null/register cases,
including genuine masks and zero writes to view/context/image data. The combined
retention/cold-load regression passes. Existing diagnostic, actual raster-path,
512 visibility-cycle, 16 appearance-cycle and four-profile boot-report probes
also pass. The focused application/composition/installation suite passes **223
tests** against the new bundle.

ArtworkDB/file reads, allocation and GUI attachment remain explicit fixture
boundaries. These tests reproduce a matching blank draw, not an entire Podcasts
visit or LCD presentation. Physical resolution was unverified at build time;
the user subsequently confirmed correct behavior on 0.6.7-dev.

## Release and next check

- Build: `.scratch/classic-artwork-render-20261118/candidate-1`.
- Prepared OS: `b7e25056cfc153935830b5ede078599cfc26c3a00175468e6760686d4787a100`.
- Payload: `9ae870ed3e7552fb537eddbf11f3345a4ac14fc1e029ccaba7372d574e21a441`.
- Complete firmware: `18f850b017fecc6862ab05eecf09b8129c7ef18db0d61c14fa37220f6156cc13`.
- Complete image **101,871,616 bytes**; compressed asset **56,753,781 bytes**.
- Initialized payload **112,920 bytes**, up 84; reserved Mod Memory Region remains
  **118,784 bytes**. The hook adds no BSS, heap allocation or pixel copy.
- Preview mod **0.1.3-dev**; Apple 2.0.5 and bootloader 2.1.0 unchanged.

Restart iOpenPod and install 0.6.7-dev through Device Summary. Check the preview,
visit Podcasts until artwork loads, then return. Diagnostics remain enabled; if
the image still disappears, reconnect USB without rebooting for another capture.

## Physical confirmation and diagnostic removal

On 2026-11-18 the user reported that everything appeared to work correctly after
installing 0.6.7-dev. Version **0.6.8-dev** therefore builds without
`--artwork-diagnostics`. It retains the same eight functional mods, including
the three artwork fixes and the Bootloader Report used for normal-USB updates.
The diagnostic source and optional flag remain available for future investigation.

The release omits all trace callbacks, 584 bytes of retained trace state and the
`iOpenPodArtworkTrace` USB dictionary. The original paint, query and blit call
sites are restored. No per-paint snapshot or pixel sampling executes. The linked
payload shrinks by 2,352 bytes, and its page-rounded reservation falls from
118,784 to **114,688 bytes**, returning one 4 KiB page to Apple's heap.

A new bundled-image regression checks those original call sites, absence of the
diagnostic dictionary and presence of the three artwork fixes and Bootloader
Report. It failed on the diagnostic bundle and passes on 0.6.8. The native replay
now observes the blit directly, so it runs without depending on firmware tracing.
Retention, cold loading, stale-mask drawing, fallback drawing, 29 format/register
cases, 512 visibility cycles, 16 appearance cycles and boot-report/bootstrap
checks pass. The focused application suite passes **224 tests**.

- Build: `.scratch/classic-artwork-release-20261118/release-1`.
- Prepared OS: `6bafe2849ff10d0aeccc0198e59afc23c5d34f98f94118aad24763a636d51c5e`.
- Payload: `26bb8ce43e35372656b782f81b5078ec10be7446985150cbd5db18108718a33b`.
- Complete firmware: `b3ea06db84b792375e1467b0364af046bebb8befb97c135b0348eef98404a1e6`.
- Initialized payload **110,568 bytes**; compressed asset **56,752,710 bytes**.
- Complete image **101,871,616 bytes**; Apple 2.0.5 and bootloader 2.1.0 unchanged.

The agent packaged this cleanup for installation through iOpenPod, without
flashing the device. Hardware confirmation belongs to 0.6.7; the clean 0.6.8
artifact has the offline validation above.
