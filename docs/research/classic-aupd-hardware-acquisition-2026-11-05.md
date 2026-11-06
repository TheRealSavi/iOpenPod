# Latest Classic AUPD acquisition using the supplied Classic 6.5

Research date: **2026-11-05**. The user supplied a connected Classic 6.5 and
entered DFU. This acquisition closes the missing plaintext-input boundary for
latest updater families 24 / 1.1.2, 35 / 2.0.4 and 38 / 2.0.5. Family 33 / 2.0.1
was already available from the earlier acquisition. It does not establish any
clock semantics by itself. [Validated acquisition receipt][receipt]

## Device and operation

The single detected device used Apple's Windows DFU backend. The checked
identity was MB565, hardware revision `0x00130100`, with BootROM SHA-256
`69c087afc5753d7f0f11f09b141b372af753a854bc526673ea444c486d6003e4`.
Every required check passed, compatibility was true, and initial cleanup returned
DFU idle. The serial and complete hardware identifier stay in private acquisition
reports. The public summary intentionally omits them. [Receipt][receipt]

The executable was built from `lgreitis/osos-lab` revision
`d2c8e357d58591bdaa70bb6be9da191f489554a6`; its SHA-256 was
`e73fff8cd109d08e7910cfb950a1f07e3033e3121436d075a94a55d89785dcee`.
The previously audited `decrypt` path executes temporary RAM payloads and uses
the hardware AES engine on Host-supplied ciphertext. It creates a new Host file,
returns DFU to idle, and does not install the supplied firmware or invoke NOR
erase/program operations. This is active temporary device execution, not passive
enumeration. [Procedure and source audit][procedure], [pinned command][decrypt]

One process at a time ran these commands, using the selector from that session:

```text
reprise devices --json
reprise dfu-state --device 1:18 --json
reprise check --device 1:18 --json
reprise decrypt --input <qualified-AUPD-IMG1> --output <new-body-file> --device 1:18 --json
reprise dfu-state --device 1:18 --json
```

The decrypt command ran separately for each of the three inputs. Each repeated
the compatibility checks. All three outputs contain **1,164,368 bytes including
AES padding**. Decryption took approximately 74 seconds per image, and every
decryption report recorded idle cleanup. The final independent GETSTATE returned
`2`, DFU idle. The user then restarted with Menu + Center and confirmed the normal
menu. Subsequent enumeration found no DFU device and Windows observed normal USB
ID `05ac:1261`. Its Windows device node reported problem Code 10, so normal Host
USB I/O was not validated. There is no normal-mode pre-acquisition baseline to
attribute that condition; no drivers were changed. [Receipt][receipt]

## Exact inputs and outputs

| Latest target | Encrypted IMG1 SHA-256 | Captured plaintext body SHA-256 |
| --- | --- | --- |
| Classic 6 / 1.1.2 (24) | `8a975cadbeb93d89a919e4a8d10a38b282149791a2ce2986aec40b5527b35878` | `98f66b2a8af0bb8a6c27cc27630ff4b54d159fa485dae0fa0a67dfbf112942e4` |
| Classic 7 / 2.0.4 (35) | `c3252a3a4921e49e44f4d37aa56be7af07e53489ce11d9a66e44da634716f3d5` | `34d5fa37dbc3ad9e3fa818021263064244a37274b95a5680072b8a7f33c17f2d` |
| Classic 7.5 / 2.0.5 (38) | `c49b4796d9370b80713b3eaaa0c8053388a6efd568a1f2cce9631c276c817d27` | `9fdd2f354eb345ef0ff65dbc5ac7479720232e52d02e36b53cf1c711aa1a6095` |

The 38 plaintext matches the independently pinned whole-body hash. The 24 and
35 whole-body hashes are newly measured, not pre-existing references. The CLI's
`reference_matched=false` reflects that no `--reference` file was supplied; it is
not a failed comparison. Subsequent loader and embedded-image validation are
documented separately in the [early boot report][early] and [later boot report][later].

## Reproducibility and interpretation

The offline [receipt builder][validator] rehashes the exact encrypted inputs,
captured outputs and executable, checks saved compatibility/cleanup results, and
verifies final DFU state. It performs no USB access. The acquisition artifacts
remain ignored in the sibling firmware lab; no Apple firmware binaries or private
identity reports become application fixtures or runtime dependencies.

This result demonstrates that the supplied Classic 6.5 can decrypt these three
specific latest AUPD images. It does not prove that every Apple image shares a
key, that every Classic has identical boot behavior, or that decrypted firmware
is appropriate to install on this device. The firmware analyses retain separate
target hashes, address maps and bounded test receipts.

[receipt]: ../../../ipod-firmware-lab/artifacts/classic-aupd-dfu-20261105-v1/acquisition-receipt.json
[validator]: ../../../ipod-firmware-lab/scripts/record_classic_aupd_acquisition.py
[procedure]: ../../../ipod-firmware-lab/notes/dfu-acquisition-procedure.md
[decrypt]: https://github.com/lgreitis/osos-lab/blob/d2c8e357d58591bdaa70bb6be9da191f489554a6/host/crates/reprise-cli/src/decrypt.rs
[early]: classic-early-boot-rtc-2026-11-05.md
[later]: classic-later-boot-rtc-2026-11-05.md
