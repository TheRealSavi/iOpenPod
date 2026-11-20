# Expanded Classic mod space

Research/build date: 2026-11-17. These results are offline binary comparisons,
native ARM execution with modeled services, and application tests. The new
Bootloader 2.1.0 / Mod Platform Version 0.3.0-dev pair has not yet been installed
on physical hardware. Earlier physical results belong to the preceding pair.

## Disk and RAM are separate limits

The stock prepared OS occupies 10,634,496 bytes in a 10,641,408-byte slot. The
previous 4,064-byte mod payload left only 2,848 disk bytes. That limit came from
the position of AUPD, not from a 4 KiB hardware restriction.

The builder keeps the resource bank and OS start fixed and expands the OS slot
to 16 MiB. The following are firmware-relative stored directory offsets:

| Entry | Original | Expanded |
| --- | --- | --- |
| OSOS start | `0x5007000` | `0x5007000` |
| AUPD start | `0x5a2d000` | `0x6007000` |
| Hash record | `0x5b4b000` | `0x6125000` |
| Complete member end | `0x5b4d000` | `0x6127000` |

Only the OS length, AUPD applied status, and the two tail offsets change in the
directory. The AUPD/hash tail is copied byte-for-byte from the pinned stock
member. Normal update retains the device's actual persistent record separately;
the [existing finalizer analysis](classic-shared-205-os-layout-2026-11-17.md#device-specific-persistent-record-remains-outside-the-shared-os)
shows that it resolves the newly written directory. The matching 2.0.5 functions
are `0x08059cb4` (record writer), `0x0806b5a8` (device/partition wrapper), and
`0x0806ec1c` (entry lookup). Their 376-, 116-, and 424-byte function bodies
respectively match 2.0.1 after masking only branch displacements; the calls
connect the corresponding new addresses. Executing the actual 2.0.5 lookup
against both directories resolves the hash sector from 23,372 to 24,870,
exactly the `0x5da000` tail displacement. Reads and allocation are modeled;
this increment does not claim a physical readback or write of that record.
Actual partition capacity remains
an installation prerequisite. The public filesystem and partition table are
outside this composition.

Mods link at `0x08b3c000`, above native BSS and downward-growing exception stacks,
and can occupy up to `0x08f3c000`: **4 MiB total**, including code, constants,
initialized data, scratch and BSS. The linker rejects overflow. Heap reservations
grow only with linked use; 0.3.0-dev still reserves two pages, as 0.2.2-dev did.
The native heap-region function at `0x0804b448` computes the heap size by
subtracting the patched lower bound from the boot-reported memory end. Both
heap-floor literals change; exception-stack literals remain original.

For low-origin loading, the appended image can overlap its final destination.
The bootstrap therefore copies backward when the destination is higher, and
forward otherwise. Its executing instructions/literals remain outside the
destination. After copying, it zeros mod scratch/BSS before returning to native
startup. Apple's subsequent BSS clear ends below the mod region.

## Bootloader change

Compared with shared 2.0.0, the compiled gate changes just two bytes in its size
constant: the schema-2 maximum becomes `0xfff800`, leaving 0x800 bytes for the
header in the 16 MiB slot. All 40 other extracted PE modules, including Bds,
FirmwareFS and SoftwareVersion, are byte-identical to 2.0.0. File positions,
SecCore, the PAD marker offset and writer packing are unchanged. The public
marker release changes to 2.1.0; schema/ABI 2 and the identifier stay unchanged.

The native Bds bridge already allocates and reads the validated declared body
size rather than the FirmwareFS virtual file's padded length. Its boundary,
short-read, CRC, legacy delegation and relocated-call tests pass with the raised
limit and a 14,760,704-byte stress image. CRCs remain corruption checks, not
signatures. Bootloader installation still uses device-specific authentication.

## Reproducible artifacts

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| Unmarked loader | 129,024 | `104c0d6453dc03e6cd8952c46855802dbbae91ffc8a1023a921ab0b474b17a32` |
| Marked 2.1.0 loader | 129,024 | `7d4e94a6a509713d92e3d54f839491e4152a2fb639fb178ad50d2aaf38abbe61` |
| Bundle manifest | See asset | `cc160a8e0077185f6abcfdf1f575046681afe29a264af30400efcd23f54113f5` |
| OSOS | 10,638,864 | `8109c0789e8bbcd04b3e1fe6e8272c35269af48d84c2df3a65b0d0e7fb26d3a0` |
| Complete firmware | 101,871,616 | `5346c62318ecc9995988afc38b28f168436cd5591aea618c602e664196ddd408` |

The source input pins are unchanged from the [2.0.5 build](classic-shared-205-os-layout-2026-11-17.md#inputs).
The release includes a 4,368-byte initialized payload, 2,560-byte scratch region,
and five Mods entries, adding **Expanded Mod Memory**. The compressed asset is
56,700,206 bytes. Maintainer output is retained under
`.scratch/classic-expanded-20261117`; no new device backup was acquired.

## Validation

- The native relocation harness executes Apple's copy and BSS-clear functions
  and the new bootstrap from both `0x08000000` and `0x09000000`. It checks every
  copied byte, heap bounds, unchanged stack literals, registers and guard bytes.
- Two synthetic builds fill the entire 4 MiB reservation: approximately 3.94 MiB
  initialized data plus 64 KiB extra BSS, and 64 KiB extra data plus approximately
  3.93 MiB BSS. Both origins pass. A build four bytes beyond capacity fails at
  link time. Synthetic data is not shipped in the normal release.
- The current release's native resource hook installs all 30 resources, with
  ordinary Mods navigation bindings and dirty-scratch handling preserved.
- The new gate/bridge passes 1,698 native cases, CRC vectors and the full large
  stress-image CRC. Thirteen qualified migrations yield the identical loader;
  27 wrong-family legacy inputs are rejected. The previous shared loader migrates
  on all four hardware families, and the new body is idempotent on all four.
- The packaged writer passes eight simulated SST25 success/failure cases.
  Hash/full scans are adapters; this is not an electrical or power-loss test.
- Application tests cover expanded composition, immutable tail bytes, size
  bounds, bundled images, required loader upgrade and previous-release receipts.

The reusable native capacity probe is
[`probe_classic_mod_capacity.py`](../../../ipod-firmware-lab/scripts/probe_classic_mod_capacity.py);
the native resource/relocation probe is
[`probe_classic_mod_menu.py`](../../../ipod-firmware-lab/scripts/probe_classic_mod_menu.py).
Neither accesses USB. This does not establish full-OS behavior under a 4 MiB
mod workload or physical compatibility on the other Classic families.

The directory probe is
[`probe_classic_expanded_directory.py`](../../../ipod-firmware-lab/scripts/probe_classic_expanded_directory.py).
Its read-only model also compares the entire preserved resource prefix and tail.
The firmware and bootloader bundle independently rebuild byte-for-byte.
