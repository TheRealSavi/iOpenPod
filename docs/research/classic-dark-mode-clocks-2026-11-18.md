# Classic dark-mode clock rows, 2026-11-18

The user reported white highlights behind unselected clocks. The clock-row
backdrop was missing from the explicit dark-mode bitmap roles. Firmware
**0.6.1-dev**, appearance mod **0.1.4-dev**, adds this one resource to the existing
surface treatment. No drawing hook, controller or bootloader changes are needed.

## Reproduction and resource identity

Use the same qualified prepared Apple 2.0.5 image, SHA-256
`660eb6ff5f498bb1a75e85f1f9921bf0c753525a8bca9b4fa47ed260e5ad0f1e`.
Clock item template SIEM `0x0dad04da` has native item type 31 and binds SORC
`0x17c`. That source binds the static `WorldClock_Graybar_Image` (`0x0dad0489`)
to destination 13. Its BMap is a 5 × 80 indexed image with 67 palette entries,
including partial alpha. The resource is 700 bytes at prepared offset 5,123,448.

The regression command is:

```shell
uv run pytest tests/iOpenPod/app/test_classic_appearance.py -k world_clock_row -q
```

Before the fix, it reports `White clock row at y=0: (234, 234, 234)`.
The ordinary fill hook cannot change this embedded bitmap. The missing role
leaves the same light palette in both appearance modes.

The correction retains the direction of the gradient, palette alpha, index plane
and geometry, using the existing dark surface palette. Primary and secondary text
meet 7:1 contrast after RGB565 quantization. The map, day/night clock faces, center
cap, shadows and hands remain untouched. The regression verifies these exclusions.

## Native switching evidence

The ignored reproduction harness is
`.scratch/classic-clock-dark-20261118/probe_clock_backdrop.py`. It executes the
compiled `iop_appearance_apply`, Apple's BMap cache loader `0x0828fdc0`, cached
draw `0x0828fe10`, and native 32-bit compositing into a 5 × 80 destination.
As recorded in the earlier palette investigation, a direct indexed8-to-RGB565
mode-0 probe selects Apple's grayscale path; this test qualifies ARGB32
composition and separately checks color contrast after RGB565 quantization.
Only resource lookup, initial graphics-context allocation and mutex construction
are stubbed. The same harness fails against 0.6.0-dev with a rendered white pixel
`(234, 234, 234)` and passes against 0.6.1-dev.

Light → Dark → Light uses one cache load and no allocations or resource reloads
during switching/drawing. Every rendered center-column pixel remains dark and
readable in Dark. The second Light image exactly matches the first. The cached
object, source header, palette alpha and index plane remain byte-identical.

The new initialized payload is 109,776 bytes, 280 bytes more than 0.6.0-dev.
Reserved Mod Memory remains 114,688 bytes (28 pages). The complete firmware is
101,871,616 bytes, SHA-256
`8138f36d6b2a9ad16e3329fffb2fbf6c31e80d1b979ecb68f024d0eb31620f61`.
Bootloader 2.1.0 and the Bootloader Report mod remain included and unchanged.

These are resource and native-emulation checks, not a physical LCD observation.
The fix has been bundled into iOpenPod; no device was flashed during this work.
