# Classic unsigned eapp manifests

Date: 2026-11-17. This is the first bundled Firmware Mod beyond the About row.
The user requested unsigned homebrew eapps, beginning with Parachute Fixed.
Mod Platform Version is **0.2.1-dev**; the existing Universal Unlocked Bootloader
**2.0.0** requires no change. This increment did not flash a device.

## Exact change

The prepared Apple 2.0.5 input is 10,634,496 bytes with SHA-256
`660eb6ff5f498bb1a75e85f1f9921bf0c753525a8bca9b4fa47ed260e5ad0f1e`.
Its raw decrypted body has SHA-256
`d7669f9266e7cae15867248eeb9c34a2711f1f9a1f3cf40132ef86d9fdbf8224`.
These are different containers; the prepared image has an extra 0x800-byte header.

At ARM address `0x080f9414`, prepared-file offset `0x104bac`, replace
`05 30 a0 e1` (`mov r3,r5`) with `00 30 a0 e3` (`mov r3,#0`).
The game manifest loader then passes a null detached-signature pathname into
Apple's reader constructor at `0x0825e510`. The existing reader supports this
mode and continues to XML parsing without opening `Manifest.plist.p7b`.

This applies to all manifests using this game-loader call site, not exclusively
Parachute. It does not patch the shared cryptographic verifier, executable
Verify/DRM checks, IC-Info, module-interface validation or XML parsing. Homebrew
manifests describe their own unprotected files with Verify and DRM false.
The change neither decrypts protected executables nor supplies authorization.
It adds no executable payload, allocation or persistent setting.

The maintainer build's explicit `--homebrew-eapps` option records
`org.iopenpod.homebrew` version `0.1.0-dev` in its provenance. This fixed release
includes the mod; the parked checkbox UI and native Firmware Mod Registry are
not enabled by this increment.

## Evidence

The earlier Parachute manifest and import probes are retained under
`iPodClickWheelRecomps/Parachute/tools/prepare_dev_loader.py` and
`verify_eapp_loader.py`. The lab's new
`scripts/probe_classic_homebrew_release.py` runs those native paths from the
actual release and compares it with an otherwise identical control build.

| Check | Result |
| --- | --- |
| Control without mod; Parachute manifest without signature | Returns `0xffffffff`; requests the missing signature before XML parsing. |
| Release with mod; same manifest | Returns zero; reaches the XML parser without a signature-file request. |
| Paired OS bodies at the same platform version | Only the one four-byte instruction differs; two of its bytes change. |
| Complete firmware outside the OS slot | Identical to the control, including resources and AUPD. |
| Native eapp import resolver | Accepts Parachute, binds all 188 imports across four modules and copies all five entry vectors. |
| Eight malformed eapp cases | All rejected by native code. |
| Cross-compiled game tests | Five tests pass, including gameplay equivalence, input/timing, exit and framebuffer bounds. |

The gate probe adapts file buffers, the XML parser and cleanup. The import probe
adapts memcpy/memcmp/strncmp. These tests do not establish the complete XML
parser, Games-menu discovery, full game lifecycle or physical launch.
Parachute is still silent and does not persist its best score.

### Follow-up: immediate game exit

The first physical launch returned to Games without drawing. The game's original
512 KiB translated-heap backing vector requested 524,296 bytes after adding its
malloc header. Classic's native `MemoryAlloc[0]` at `0x082c0e38` rejects requests
above 524,288 bytes. Reproducing that limit in the cross-compiled game tests gives
`std::bad_alloc` during initialization and an exit before the first rendered frame.
The fix backs each translated allocation separately. All five runtime tests pass
with the real limit enforced. The corrected package was installed and read-back
verified; the user confirmed game launch and wheel/Center input on the Classic
120 GB running universal 2.0.5.
No additional firmware patch is needed for this fix.

The new game-side `tools/probe_eapp_launch.py` also executes the native XML parser,
package loader, file validation and import resolver together. It accepts the
corrected package and rejects missing-signature stock, malformed XML, missing
artwork and wrong artwork-size controls. The native allocator separately accepts
524,288 and rejects 524,296 bytes with its initialized block-size field. File I/O,
task state and low-level libc primitives are adapted. This extends the earlier
probes; it does not establish complete hardware lifecycle behavior.

Private evidence is in `.scratch/classic-homebrew-20261117/`. Reproduce the native
probe with `uv run` and its required `--build`, `--control`, `--parachute` and
`--out` paths. Build both directories using the same version/compiler/input;
include `--homebrew-eapps` only for the candidate. No device is opened.

## Bundled release and upgrade behavior

The complete 95,735,808-byte image has SHA-256
`2dc8b94f0fff21c1fb70f6d9748c95890fed35de8fdd72d187ffd605742ce5dd`.
The common OS SHA-256 is
`cf294da39489a23f2dcc1d912adc883d8529c28754eb042490e23b1cd34ba75c`.
The compressed application asset is 56,692,478 bytes. Preparation uses the
existing offline cache at `shared/0.2.1-dev/firmware.bin`.

Installer receipts now recognize the exact 0.2.0-dev and 0.2.1-dev version/hash
pairs. Completed older receipts permit the next release. Pending older receipts
remain verification-only; the dialog displays their saved Mod Platform Version.
A new upload still uses only the currently pinned release. Mixed or unknown
version/hash pairs are rejected. No previous write is replayed.

To try this release, restart the source application, install universal 2.0.5
through Device Summary, and complete its normal boot/About confirmation. Use
the Parachute package's `iPod_Control/games_RO/F0001/` folder on the public
filesystem. Its manifest has no `.p7b` companion. The subsequent corrected game
build successfully launched on the Classic 120 GB as recorded above; broader
hardware and lifecycle validation remains outstanding.
