# Classic family 33: independent version row in About

Research date: 2026-11-17. Initial scope: offline inspection of Apple 2.0.1
resource loading, About layout, and startup memory placement. The native
integration findings below are distinct from the subsequent physical upload
and complete firmware readback recorded at the end. The user has now confirmed
the added row displays correctly on the physical iPod.

## Result

Use Apple's existing resource override map to install two strings, two string
sources, and an eight-child replacement for the existing six-child About View.
Keep Apple's version provider and all six original children. The added value
comes from the separately named `iop_platform_version` constant, initially
`0.1.0-dev`, as required by ADR-0275. This needs neither a new top-level screen nor
a rewritten resource bank. The same View is used by the basic About page with
and without an accessory attached. [Override implementation][set],
[About resource evidence][layout], [identity decision][adr]

A small appended payload can be copied above the native BSS before BSS clearing,
then protected by advancing the two actual heap-base literals. This avoids
materializing the approximately 1.2 MiB BSS gap inside the firmware image. The
entry stub must remain position independent until it has copied the payload.
This integration is supported by the exact native startup instructions and
implemented in the appended payload described below. [Startup copy][copy],
[BSS clearing][zero], [heap references][heap]

## Exact input and address qualification

All addresses below are for the prepared family-33 Apple 2.0.1 OSOS, not the
2.0.5 image used by the upstream modding project:

- Input: `Classic33FW/firmware/analysis-inputs/osos.bin` in the lab.
- Size: `0xa06e40` bytes, including the `0x800`-byte IMG1 header.
- SHA-256: `220913cb8569af0538a7e828f1aaa08d9313bf9a5c2b0a7a7e6e2dc0bee5f16e`.
- The read-only Ghidra export verified all three initialized runtime regions
  byte for byte against that input. Pseudocode names and inferred types are
  research annotations, not Apple's original C source. [Export qualification][qualified]

| Prepared file start | Runtime start | Size | Purpose |
| --- | --- | --- | --- |
| `0x800` | `0x22000000` | `0xae5c` | IRAM code/data |
| `0xb65c` | `0x08000000` | `0x9fad50` | Main DRAM image |
| `0xa063ac` | `0x089fad50` | `0xa84` | Initialized DRAM data |
| No file bytes | `0x089fb7d4` | `0x12665c` | Zeroed DRAM BSS |

BSS ends at `0x08b21e30`. Sixteen trailing bytes follow the initialized image in
the prepared file. The proposed payload begins at file offset `0xa06e40` and
runtime address `0x08b22000`, subject to the parent build's complete size and
image-container checks. [Startup copy][copy], [BSS clearing][zero]

## Bank format and native API

The primary English bank starts at file offset `0x3fbaf8`; its data starts
`0x17178` bytes later. Its 27 kind records and 7,845 resource records consume
exactly that metadata span: `12 + 27 * 16 + 7845 * 12 = 0x17178`. There is no
unused index gap into which new records can simply be inserted. Twenty further
banks contain language resources (`LDTm` and `Str `), while shared View resources
are in the main bank. [Existing bank catalog][catalog]

`ResourceIndex_Find` binary-searches kind IDs. Normal kinds binary-search sorted
resource IDs; kind flag 1 instead assumes a contiguous ID range and computes
`requestedID - firstID`. The returned pointer is the stored data-base pointer
plus the resource's offset. This lookup does not separately enforce a bank-end
boundary. That permits theoretical relocation of metadata/data, but does not
prove that arbitrary appended file offsets are initialized RAM or safe from BSS
and heap use. The native override route avoids these complications. [Lookup][lookup]

| Native operation | Apple 2.0.1 address |
| --- | --- |
| `ResourceBank_GetResource` | `0x080fa7e4` |
| `ResourceBank_SetResource` | `0x080fa890` |
| `ResourceBank_InitOverrides` | `0x080fa970` |
| `ResourceBank_NextResource` | `0x080faa70` |
| `ResourceBank_FirstResource` | `0x080fab64` |
| `ResourceBlockList_Load` | `0x08161fd4` |
| `ResourceBlockList_Construct` | `0x08162058` |
| `MenuItems_RegisterResourceType` | `0x0817bbc4` |
| `ResourceBank_GetDefaultBank` | `0x0817c540` |
| `UI_InitResourceProviders` | `0x081ad30c` |

The exported implementations and call sites qualify these addresses against the
exact input. [Native resource exports][qualified], [UI initialization][init]

At `0x081ad34c`, the original instruction is `BL 0x080fa970`, encoded as bytes
`87 35 fd eb`. Register `r0` contains the default bank, also retained in `r5`.
The original result is unused: `0x081ad350` immediately replaces `r0` with an
allocation size. A hook can call the original initializer and then install its
overrides, preserving callee-saved registers and an eight-byte-aligned stack.
`SetResource` receives bank, kind, resource ID, and data pointer in `r0`–`r3`,
with byte length at stack offset zero. Bank type 2 requires its override map at
bank offset `0x18` to have been initialized first. [Call-site assembly][initasm],
[initializer][overrides], [setter][set]

The five resources are:

| Kind | ID | Contents |
| --- | --- | --- |
| `Str` (`0x53747220`) | `0x0cf00000` | `Mod Version` plus NUL |
| `Str` (`0x53747220`) | `0x0cf00001` | Independent `0.1.0-dev` plus NUL |
| `SORC` | `0x0cf00002` | Static source for the label string |
| `SORC` | `0x0cf00003` | Static source for the version string |
| `View` | Existing `0x0dad0ac3` | Six retained children plus two cloned text children |

Use `0x0cf00004` and `0x0cf00005` as the new child IDs. Static string sources
match the existing SORC block structure: one block, body length 12, block kind
`0x534f5243`, and body words `0x80`, string ID, `1`. Existing About strings use
that same representation. [Resource evidence][layout]

Re-register the `View` resource kind (`0x56696577`) after installing the
replacement. The registration code enumerates stock resource IDs, then resolves
each through `ResourceBlockList_Construct` and `GetResource`, and stores each
child's payload pointer under its ID at payload offset `0x30`. Reusing the
existing View ID therefore admits the two new children without changing the
resource enumeration routine. Adding an entirely new top-level View ID would
need separate treatment. [Registration][register], [block loading][load]

The service used by registration is already initialized at this hook: the same
service is required for `GetDefaultBank` at the beginning of
`UI_InitResourceProviders`. The later language-provider initialization is not a
prerequisite for direct View lookup. [Default bank][default], [block loading][load],
[UI initialization][init]

The existing TMLT is a container descriptor, not a fixed list of six children.
`UI_CreateTemplateFromResource` constructs that container; its virtual method
at `0x081c4a1c` loads the View for the template's ID. The resulting block list is
passed to the child-construction method. Keeping the original TMLT therefore
retains the container while supplying eight View blocks. [Template construction][template],
[View loading][viewload]

## About layout

The global name table stores pairs of **string pointer, resource ID**. The ID is
the word after the pointer. Treating the preceding word as its ID incorrectly
swaps nearby template and field identities. The resource extractor retains
numeric IDs and raw block words independently of names. [Resource evidence][layout]

| About screen | SLyt ID | SSin ID | Shared View | Named layout ID |
| --- | --- | --- | --- | --- |
| Basic | `0x0dad0b06` | `0x177` | `0x0dad0ac3` | `0x0dad0aca` |
| Basic with accessory | `0x0dad0b0a` | `0x17a` | `0x0dad0ac3` | `0x0dad0aca` |

The paired layout ID is a four-byte **TEVT** resource with zero blocks, not a
VLyt resource. The instance IDs are `0x350` and `0x35f`, respectively. Both
screens can be covered by the one shared View replacement. [Resource evidence][layout]

The stock View is at file offset `0x807f5c`, length 892: six 140-byte text
payloads, each with an eight-byte block header, plus the four-byte block count.
Labels use X=18; values use X=192. Both columns have row origins Y=153,171,189.
Within each text payload, Y is at offset `0x0c`, child ID at `0x30`, and SORC ID
at `0x64`. Cloning the relevant label/value payload retains the native fonts,
alignment flags, clipping behavior and rendering properties. The three original
value sources remain unchanged, including Apple's version source.
[Resource evidence][layout]

Use row origins **144,162,180,198**, preserving 18-pixel spacing. This is a
source-derived placement recommendation: the band occupies Y=61 through 99,
the logo occupies Y=40 through 111, and the three/four page-dot templates begin
at Y=220. A native accessory-information template already places its final row
at Y=200. A new row at Y=207 would leave only 13 pixels before the dots; shifting
the existing rows up nine pixels gives 22 pixels from the final row origin to
the dots. Actual font extents and visual balance still require a physical
display check. [Resource evidence][layout]

## Small appended payload and startup

At the end of `retailos_copy_image_to_runtime_regions`, `r4` retains the original
staging address of the DRAM image whose prepared-file offset is `0xb65c`.
The relocated IRAM routine's last three instructions are:

```text
2200474c  ldr r0,[22004758]       ; original entry 22000000
22004750  pop {r4,r5,r6,lr}
22004754  bx r0
```

An appended position-independent stub can be reached without assuming a fixed
staging base by replacing those instructions with three ARM-encodable additions:

```text
add r0,r4,#0x009f0000
add r0,r0,#0x0000b700
add pc,r0,#0x000000e4
```

The summed delta is `0xa06e40 - 0xb65c = 0x009fb7e4`. The stub can find its
current source address with `ADR`, copy its complete linked payload to
`0x08b22000` using native IRAM memcpy at `0x220000d4`, then replay the original
entry-load/pop/branch sequence. The payload's compiled code and data addresses
must refer to the destination; only the copy stub executes at its staging
address. Exact instruction encoding, copied length, non-overlap, and preserved
registers remain builder/harness obligations. [Startup copy][copy]

Four literal words equal the native BSS end `0x08b21e30`, but only two are heap
starts. For a payload strictly below `0x08b23000`, reserve that aligned limit:

| Literal address | Role | Treatment |
| --- | --- | --- |
| `0x08034648` | `Platform_GetHeapRegion` lower bound | Advance to `0x08b23000` |
| `0x080657dc` | Runtime heap initialization lower bound | Advance to `0x08b23000` |
| `0x080172f8` | Exception stack top loaded into SP | Retain `0x08b21e30` |
| `0x220030cc` | IRQ stack top loaded into SP | Retain `0x08b21e30` |

Both exception stacks grow downwards. They must not be moved into the new
payload. Native BSS clearing stops at the old end, below the proposed payload
base. If the complete payload does not fit the reserved interval, the builder
must reject or recompute a qualified larger reservation; silently truncating or
overwriting the heap is invalid. [Heap references][heap], [BSS clearing][zero]

After relocation and BSS clearing, startup invokes `0x22004504`. It disables
MMU/D-cache/I-cache, invalidates I-cache and drains the write buffer through
`0x22003190`, invalidates D-cache and drains again through `0x220031a4`, builds
the memory mappings, and enables caches and MMU. The copied payload is therefore
covered by native cache initialization before the much later resource hook.
Initial execution of the staging stub retains the same incoming cache-coherence
assumption as native IRAM relocation: Apple's original copy routine does not
perform extra cache maintenance before its own jump into relocated IRAM.
[Startup entry][entry], [cache initialization exports][cache]

## Verification boundary

Static analysis alone establishes exact addresses, resource contracts and
placement constraints. It cannot establish that a boot chain accepts a modified
IMG1, that every loader transfers additional prepared-file bytes, or that a
physical screen renders the new text correctly. Those need separate boot-path,
container, native-emulation and device-verification evidence. The physical
result below qualifies only this exact Classic33 build and device.

The evidence extractor is offline and reproduces its layout JSON from the
hash-pinned stock bytes and existing resource catalog. No product dependency or
device access was added. [Extractor][extractor]

## Implemented candidate and physical readback

The compiled payload adds a 32-byte `iop_platform_version` constant containing
`0.1.0-dev` and a separately identifiable `IOPOD.MOD.VER1` record. The resource
hook calls the original initializer, installs five resource overrides, and
registers the replacement View. Apple's version provider remains unchanged.
The appended position-independent entry copies 1,608 payload bytes to
`0x08b23000`; both heap lower bounds advance to `0x08b24000`, preserving the
original stack tops. Native-copy/BSS emulation tests both load origins, canaries,
ABI and resources, including changing the version constant independently.
[Payload](../../../ipod-firmware-lab/scripts/classic33_mod/payload.c),
[Builder](../../../ipod-firmware-lab/scripts/build_classic33_about.py),
[Native tests](../../../ipod-firmware-lab/scripts/test_classic33_about.py)

The device-authenticated OSOS has SHA-256
`6172eace399f46a4822642b0d13787c78861bcb805805fc6d11babd281bf2581`.
The assembled 93,515,776-byte firmware has SHA-256
`ee39d4d4d2553da48c7126123d8bc8ba7998daf3725866fc3b709590e6adac3f`.
Only the OSOS length word and existing OSOS slot differ from the saved preimage;
the used AUPD flag, hash sector, resources and other entries are preserved.
[Composition evidence](C:/Users/JohnG/AppData/Local/iOpenPod/firmware/recovery/8P840FN62C7/2026-11-17-mod-images/manifest.json)

After installing the conditional loader and verifying a normal stock boot, the
Host sent this exact candidate through Storage in 2,856 acknowledged commands.
The update reboot request completed and the iPod returned to normal USB mode,
still reporting Apple `2.0.1`. A subsequent independent DFU acquisition matched
all firmware bytes across 23 two-read/hash ranges and confirmed the original
raw partition table. A second full NOR read confirmed the modified loader
persisted. After another normal boot, library files and the disk layout still
matched; Storage safely ejected the device. The user opened About and confirmed
that Apple `2.0.1` and `Mod Version: 0.1.0-dev` both appear and look correct.
That final display evidence is user observation, not an inspected screenshot.
[Upload journal](C:/Users/JohnG/AppData/Local/iOpenPod/firmware/recovery/8P840FN62C7/2026-11-17-mod-upload/upload.json),
[Complete readback](C:/Users/JohnG/AppData/Local/iOpenPod/firmware/recovery/8P840FN62C7/2026-11-17-mod-readback/verified-written-span.json),
[Boot-path evidence](classic33-modified-boot-path-2026-11-17.md)
[Final installation and display confirmation](C:/Users/JohnG/AppData/Local/iOpenPod/firmware/recovery/8P840FN62C7/2026-11-17-mod-final/installation-verification.json)

[adr]: ../adr/0275-compose-firmware-mods-with-independent-platform-identity.md
[catalog]: ../../../ipod-firmware-lab/artifacts/preferences-classic-resource-banks-20261107/banks.json
[layout]: ../../../ipod-firmware-lab/artifacts/classic33-about-layout-20261117.json
[extractor]: ../../../ipod-firmware-lab/artifacts/classic33-about-layout-20261117.py
[qualified]: ../../../ipod-firmware-lab/artifacts/classic33-about-reader-20261117/summary.txt
[lookup]: ../../../ipod-firmware-lab/artifacts/classic33-about-reader-20261117/081395d0-ResourceIndex_Find.c
[set]: ../../../ipod-firmware-lab/artifacts/classic33-about-reader-20261117/080fa890-ResourceBank_SetResource.c
[overrides]: ../../../ipod-firmware-lab/artifacts/classic33-about-reader-20261117/080fa970-ResourceBank_InitOverrides.c
[register]: ../../../ipod-firmware-lab/artifacts/classic33-about-reader-20261117/0817bbc4-MenuItems_RegisterResourceType.c
[load]: ../../../ipod-firmware-lab/artifacts/classic33-about-reader-20261117/08161fd4-ResourceBlockList_Load.c
[default]: ../../../ipod-firmware-lab/artifacts/classic33-about-reader-20261117/0817c540-ResourceBank_GetDefaultBank.c
[init]: ../../../ipod-firmware-lab/artifacts/classic33-about-init-20261117/081ad30c-UI_InitResourceProviders.c
[initasm]: ../../../ipod-firmware-lab/artifacts/classic33-about-init-20261117/081ad30c-UI_InitResourceProviders.asm.txt
[template]: ../../../ipod-firmware-lab/artifacts/classic33-about-template-20261117/081c4594-UI_CreateTemplateFromResource.c
[viewload]: ../../../ipod-firmware-lab/artifacts/classic33-about-template-20261117/081c4a1c-FUN_081c4a1c.c
[copy]: ../../../ipod-firmware-lab/Classic33FW/artifacts/stock201-research/220046b0-retailos_copy_image_to_runtime_regions.asm.txt
[zero]: ../../../ipod-firmware-lab/Classic33FW/artifacts/stock201-research/220047b8-retailos_zero_runtime_bss.asm.txt
[entry]: ../../../ipod-firmware-lab/Classic33FW/artifacts/stock201-research/22000000-retailos_image_entry.asm.txt
[heap]: ../../../ipod-firmware-lab/artifacts/classic33-about-heap-refs-20261117.txt
[cache]: ../../../ipod-firmware-lab/artifacts/classic33-about-cache-20261117/summary.txt
