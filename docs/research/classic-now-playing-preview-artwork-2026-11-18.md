# Classic Now Playing preview artwork

Date: 2026-11-18. Scope: the main-menu Now Playing hover preview in shared
Classic 2.0.5. No device was accessed.

Two resource overrides are sufficient: connect the existing image child to the
native current-artwork property, then give it a 128 × 128 rectangle. Preserve the
existing title, artist and album bindings. The native model already supplies
fallback art and change notifications; no new decoder, timer or pixel cache is
needed.

This describes the original 0.5.0-dev implementation. The subsequent physical
report of missing menu previews after Cover Flow exposed a gap in the provider-
stubbed tests below. Version 0.6.2-dev adds a native visibility/lifetime hook;
see the [cache lifetime investigation](classic-menu-artwork-lifetime-2026-11-18.md)
for its narrower reproduced case and the outstanding hardware verification.

## Evidence and pins

The primary source is the exact Apple executable and its embedded resource bank.
Existing lab artwork notes and the pinned
[osos-lab annotations](https://github.com/lgreitis/osos-lab/tree/d2c8e357d58591bdaa70bb6be9da191f489554a6)
provided discovery coordinates; the contracts below were checked on 2.0.5.

| Input | SHA-256 |
| --- | --- |
| Lab `Classic38FW/decrypted/osos.bin` | `d7669f9266e7cae15867248eeb9c34a2711f1f9a1f3cf40132ef86d9fdbf8224` |
| Prepared stock 2.0.5 | `660eb6ff5f498bb1a75e85f1f9921bf0c753525a8bca9b4fa47ed260e5ad0f1e` |
| 0.5.0-dev build-2 OS | `d636c36ca3334d1f8549f313b02606edf0d9e27056e01045c7fb12f5f8cf7477` |
| 0.5.0-dev build-2 payload, 105116 bytes | `3a29270d31952405e881fe1e1f6d5adeb64f3e0d139b055956737abdc6a272c9` |
| Stock `VCvs 0x162`, 100 bytes | `56007c9a53160b8d981ee24c637d74435423fd734e8f24dde57e7e9ecbf0278d` |
| Replacement `VCvs 0x162` | `152368ebd0358539f2c4b17f9e454f32b3b9db9b005e24939fd932ea421904b7` |
| Stock `VLyt 0x0dad01c0`, 160 bytes | `d179dbe61b2a84cbf2ac0f553453b35b9919fcd4e6483c179407554eb8021238` |
| Replacement `VLyt 0x0dad01c0`, 220 bytes | `57c3fee00aaf2748c05423221c93d593518e69dc4fb0e47a8ee57a3eb10ba1cd` |

Raw file offset `0xaf98` maps to DRAM `0x08000000`; prepared images use
`0xb798`. Addresses below are runtime addresses in these pinned images.

## Resource recipe and native dimensions

The main-menu handler `0x08226474` always emits `NoArtNowPlayingHilited`, without
testing artwork availability. That event selects
`MainMenus_Main_Screen_NoNowPlayingArt`: `SLyt 0x0dad07a7`, `SSin 0x74`, instance
`0x162`, `View 0x0dad01b9`, layout `0x0dad01c0`. Its image child is `0x0dad01ba`.
Changing the separate art-present layout would miss this actual route.

In `VCvs 0x162`, replace the little-endian source ID at byte 24 from `0x3b1`
to `0x4a9`. The former selects static `BMap 0x0dad0136`; the latter already
describes service `0x7f00`, property `0x7f05`, flags `1`. Exact `SORC 0x4a9`:

```text
010000000c00000043524f53007f0000057f000001000000
```

Native image parser `0x082670f0` selects category `Draw` (`0x44726177`). The
title/artist/album children keep properties `0x7f01`, `0x7f06`, `0x7f02`.

The native primary selector is **15**, format **1055**, **128 × 128 RGB565**,
row stride 256. These values were returned by actual calls to
`0x080fac14(15)` and `0x080fad18(out, 15)`. Static playback setup confirms the
default selector: `0x08170238` configures primary 15 through `0x082167f0`;
`0x082168f0` resolves requested `0xffffffff` to the stored primary. Selector 16
instead produces format 1029, 200 × 200, and is unsuitable for this preview.

The original proxy is 119 × 119. The native image view centers intrinsic pixels;
it does **not** resize them. Keep visibility property 1005 and replace/add these
image-child layout properties in `VLyt 0x0dad01c0`:

| Property | Serialized tuple `(offset, reference, type)` | Meaning |
| --- | --- | --- |
| 1000 | `(35, 0, 0)` | Top, relative to parent top |
| 1001 | `(176, 0, 0)` | Left, relative to parent left |
| 1002 | `(-77, 0, 0)` | Bottom, relative to parent bottom |
| 1003 | `(-16, 0, 0)` | Right, relative to parent right |

Type zero is parent-edge relative, not an absolute coordinate. Native constraint
decoder `0x0826797c` and layout calculation `0x08264f9c`, with the screen parent
`(top,left,bottom,right) = (0,0,240,320)`, return `(35,176,163,304)`.
Native image rectangle preparation `0x08100364` preserves this exact rectangle
for 128 × 128 art. The unchanged title starts at top 170, left 164, leaving a
seven-pixel gap; artist and album retain their original positions.

`VLyt 0x0dad01c0` has only this `SSin` reference in the pinned resource bank,
so overriding it does not alter other uses of shared `View 0x0dad01b9`. Preserve
the other three layout child blocks byte-for-byte. Static drawing analysis
shows `0x08264bdc` intersects the view bounds with the enclosing clip before
drawing. Unexpected source dimensions retain native centering/clipping, not
custom resampling.

## Model ownership, fallback and refresh

`0x081eda2c(model, category, property, out)` handles `Draw/0x7f05` at
`0x081ee04c`. It calls the player's vtable entry `+0x148` with selector
`0xffffffff`, tests the returned availability byte, and fills the existing
bitmap at `model + 0x18c`. Unavailable art falls back through native resource
loading to `BMap 0x0dad0128` or `0x0dad0129`, both 128 × 128. A matching cached
image ID at `model + 0x3b4` reuses that model bitmap without another provider
request. The getter has no pause-state check that substitutes a placeholder.

`BitmapView_LoadBitmap`, `0x08100020`, queries the bound property and borrows
its bitmap. Its only new allocation is a 68-byte graphics context, retained at
`view + 0x15c`; repeated draws reuse it. Invalidator `0x081000bc` destroys/frees
that context and clears readiness, without taking ownership of the model bitmap.

Property binding flag 1 follows `0x08175b7c` → `0x08265914` → `0x08119e10` to
register the view with its service. Native view event handler `0x08265a2c`
matches event type `0x13`, category `Draw`, property `0x7f05`, and invokes the
image invalidator through vtable `+0xd4`. A `Draw/0x7f19` event does not invalidate
this view. These matching/nonmatching event cases were instruction-executed
against a constructed, already cached view.

Native Now Playing event handler `0x081efe74` publishes `Draw/0x7f05` on artwork
completion event `0x8000d`. Track refresh `0x081ef48c` publishes it along with
the existing title, artist and album properties. Both notification paths were
instruction-executed. No added polling or manual repaint event is required.

## Reproduction and limits

Ignored probes execute the pinned ARM instructions with synthetic player and
graphics/service boundaries:

```shell
uv run .scratch/classic-dark-native-20261117/probe_preview_artwork.py --build .scratch/classic-preview-artwork-20261118/build-2
uv run .scratch/classic-dark-native-20261117/probe_preview_bounds.py --build .scratch/classic-preview-artwork-20261118/build-2
```

Both probes load the candidate DRAM image, its compiled payload at the linked
address, and zeroed payload BSS before executing the native code. The first
verifies the actual candidate binding embedded in the built payload,
hover routing, descriptor category, both fallbacks, cached-image reuse, bounded
context lifetime, property-event invalidation, and model notifications. The
second finds the exact embedded replacement layout, verifies unchanged metadata
children, and feeds its actual property bytes into native constraint decoding.
It also executes format selection and intrinsic alignment. All seven artwork
contract groups and four geometry/format contract groups pass on build-2. The
adjacent reports are `native-preview-artwork-report.json` and
`native-preview-bounds-report.json`.

Provider data and availability are supplied by the probe; actual ArtworkDB disk
reads and decoding are outside its coverage. Model notifications and receiving
view dispatch are tested separately, rather than through a complete booted GUI
queue. Screen-parent geometry is a fixture, and unexpected-size clipping has
static rather than final-raster coverage. Physical track changes, paused tracks,
no-art transitions and LCD composition still need an on-device check.
