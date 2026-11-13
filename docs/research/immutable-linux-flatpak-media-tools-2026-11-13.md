# Immutable Linux and Flatpak without bundled media executables

Investigated 2026-11-13 against checkout
`5bf610338da188c79d8a93486de229b8335309c1`.
This is a proposed direction, not an accepted ADR or a
declaration of platform support. No application or packaging behavior changed.
It supplements the [2026-11-06 investigation](immutable-linux-flatpak-2026-11-06.md),
with a more concrete answer to its external-media-tool question.

A subsequent owner-requested experiment built fpcalc against Qt's existing
FFmpeg libraries and executed it successfully on Windows. See
[the measured result](#executed-windows-experiment-reusing-qts-ffmpeg-libraries).
Linux/Flatpak execution remains unverified.

## Finding

The strongest Flatpak route is to use **FFmpeg and FFprobe supplied by the
Freedesktop runtime**, keeping both out of iOpenPod's `/app` payload. The existing
25.08 candidate already selects that runtime. Its `codecs-extra` extension
supplies additional codec libraries. Neither requires iOpenPod to build or
maintain its own FFmpeg executable distribution. Source evidence and an existing
Flathub application support this approach; installed iOpenPod acceptance remains
unverified. The detailed evidence appears below.

**fpcalc is required and its installation route remains unresolved.** The owner
explicitly corrected the earlier optional-dependency recommendation; see
[ADR-0264](../adr/0264-require-fpcalc-in-supported-installations.md).
No maintained general-purpose runtime extension providing fpcalc was established
by this investigation. Qualify a user-installed upstream binary or independently
maintained extension as part of the complete solution. The runtime FFmpeg/FFprobe
finding alone does not establish support. Current reduced-operation behavior
under [ADR-0084](../adr/0084-keep-optional-media-analysis-out-of-sync-gates.md)
does not satisfy this requirement.

For native immutable Linux installations, use externally managed tools from an
appropriate user-space package manager, or run the application and tools together
inside a supported Distrobox/Toolbx environment. Automatically selecting ordinary
Fedora DNF installation from `ID_LIKE` is insufficient for an Atomic Host.
The current [Host observations](../../src/storage/host_tools.py) and
[installation planner](../../src/iOpenPod/app/services/media_tools.py) have no
separate immutable-distribution policy.

## What “without bundling” means here

[ADR-0081](../adr/0081-require-user-installed-media-tools.md) requires separately
installed command-line executables and explicitly retains Qt's FFmpeg playback
libraries. [ADR-0103](../adr/0103-offer-native-media-tool-installation.md) permits
user-initiated native package-manager installation;
[ADR-0140](../adr/0140-restore-host-media-tool-path-overrides.md) permits executable
path overrides, not shell-command strings.

There are two different distribution promises:

- **No command-line executables in iOpenPod, and no iOpenPod-owned tool builds:**
  consuming an independently maintained Flatpak runtime fits this requirement.
- **Users must perform a separate manual installation for every tool:** runtime
  dependencies installed by Flatpak do not follow that exact workflow. Record the
  Flatpak-specific interpretation of ADR-0081 before implementation. Do not
  silently rewrite the accepted policy.

An iOpenPod-owned `MediaTools` extension would keep binaries out of the main app
payload, but iOpenPod would still redistribute and maintain them. It is not a
solution to a requirement that the project never distributes those executables.
The existing Qt playback-library decision also means this is not a promise of an
entirely FFmpeg-free application distribution.

## Freedesktop 25.08 already provides the useful foundation

The source chain is specific to the candidate's `org.freedesktop.Platform//25.08`:

1. The runtime's [platform dependency list](https://gitlab.com/freedesktop-sdk/freedesktop-sdk/-/blob/release/25.08/elements/platform.bst)
   includes `components/ffmpeg.bst`.
2. Its [base FFmpeg element](https://gitlab.com/freedesktop-sdk/freedesktop-sdk/-/blob/release/25.08/elements/components/ffmpeg.bst)
   and [shared build settings](https://gitlab.com/freedesktop-sdk/freedesktop-sdk/-/blob/release/25.08/elements/include/ffmpeg.yml)
   do not disable programs. FFmpeg's [configure defaults](https://github.com/FFmpeg/FFmpeg/blob/n7.1.3/configure)
   enable its program list. The runtime's [composition exclusions](https://gitlab.com/freedesktop-sdk/freedesktop-sdk/-/blob/release/25.08/elements/platform-image.bst)
   and [split rules](https://gitlab.com/freedesktop-sdk/freedesktop-sdk/-/blob/release/25.08/include/_private/split-rules.yml)
   do not remove those executables.
3. The [codecs-extra FFmpeg element](https://gitlab.com/freedesktop-sdk/freedesktop-sdk/-/blob/release/25.08/elements/extensions/codecs-extra/ffmpeg.bst)
   explicitly disables programs, enables encoders/decoders and adds x264/x265.
   It supplies libraries, not a second CLI installation.
4. The [runtime manifest](https://gitlab.com/freedesktop-sdk/freedesktop-sdk/-/blob/release/25.08/elements/flatpak-images/platform.bst)
   mounts `codecs-extra` and adds its `lib` directory to library lookup.

This supports using `/usr/bin/ffmpeg` and `/usr/bin/ffprobe` inside the sandbox.
It would be incorrect to conclude that a codec extension lacking executables
means the base runtime also lacks them.

There is a concrete downstream precedent: [Frame's upstream documentation](https://github.com/66HEX/frame#flathub-linux)
states that its Flathub build uses runtime FFmpeg, FFprobe and codec libraries.
Its [published Flathub manifest](https://github.com/flathub/io.github._66HEX.Frame/blob/master/io.github._66HEX.Frame.yml)
selects Freedesktop 25.08 and system media tools without an FFmpeg build module.
This corroborates the source interpretation, but does not test iOpenPod.

The [Flatpak extension documentation](https://docs.flatpak.org/en/latest/extension.html)
identifies `codecs-extra` as the replacement for `ffmpeg-full` from 25.08 onward.
It is installed automatically with the runtime unless blocked, and uses a branch
such as `25.08-extra`. Users and distributors can mask it. Therefore version
checks alone are insufficient: inspect actual codecs and run representative
conversions, including when the extension is absent. Do not add the obsolete
`ffmpeg-full//25.08` as the supposed solution.

The current base configuration explicitly disables H.264/HEVC/VC-1/VVC decoding;
the extra extension is significant for common video inputs. Optional audio
encoders such as `libfdk_aac` also cannot be inferred merely from runtime presence.
Use the existing per-operation capability checks and clear missing-codec outcomes.
Sources: [base configuration](https://gitlab.com/freedesktop-sdk/freedesktop-sdk/-/blob/release/25.08/elements/components/ffmpeg.bst)
and [extra configuration](https://gitlab.com/freedesktop-sdk/freedesktop-sdk/-/blob/release/25.08/elements/extensions/codecs-extra/ffmpeg.bst).

The frozen application's external-process environment must retain the runtime's
library configuration while removing incompatible private PyInstaller libraries.
The existing behavior is documented in [Media-tool setup](../media-tools.md);
verify it in the installed Flatpak before changing it. Runtime paths can use the
existing direct-executable runner, without a Host-command bridge or a general
execution-provider refactor.

## fpcalc options

[AcoustID publishes Linux x86-64 and ARM64 fpcalc downloads](https://acoustid.org/chromaprint).
A user-installed copy in an accessible user-data location, selected with the
existing override, is the smallest candidate to test. Confirm its ELF loader,
shared dependencies, architecture, codecs, output and seekable descriptor support
inside the chosen runtime. A Linux download is not automatically a compatible
Flatpak executable; this investigation did not run those binaries. Leave updates
with the upstream installation channel rather than introducing an automatic tool
downloader contrary to the current setup decision.

Because fpcalc is required, manual post-installation setup must also be evaluated
against the Flathub core-functionality requirements discussed below. Proving that
a downloaded executable can run does not establish an accepted Flathub route.

A separately installed extension is technically possible. Flatpak can mount
declared [application extensions](https://docs.flatpak.org/en/latest/extension.html)
with matching branch and architecture. The app would need an explicit discovery
location, and the extension needs a maintainer and update policy. If an independent
provider maintains it, iOpenPod can consume it without its own tool builds.
If iOpenPod builds it, the redistribution responsibility remains with iOpenPod.
No ready-to-use shared fpcalc extension was verified here.

Replacing fpcalc with an arbitrary FFmpeg invocation is not an existing solution.
FFmpeg's [Chromaprint muxer](https://ffmpeg.org/ffmpeg-all.html#chromaprint)
requires `--enable-chromaprint`; that flag and dependency are absent from the
audited runtime build. Its defaults and raw output format also differ from the
current fpcalc contract. Any replacement would require algorithm-2 compatibility
fixtures, cache-identity review, proportionate tests and an explicit decision.
Likewise, adding a library or Python wrapper that bundles its own binary only
moves the dependency into another package.

## Native immutable Linux

[Fedora Atomic documentation](https://github.com/fedora-silverblue/silverblue-docs/blob/master/modules/ROOT/pages/getting-started.adoc)
recommends Flatpak for graphical applications and Toolbx for CLI tools. Package
layering changes the system deployment and normally needs a reboot; it should
not be confused with ordinary mutable-Fedora DNF installation.
[Bazzite](https://docs.bazzite.gg/Installing_and_Managing_Software/software-intro/)
prefers Flatpak for GUI apps, Homebrew for CLI tools, then containers, with
`rpm-ostree` layering a last resort.

For a native iOpenPod launch on Bazzite, Homebrew is a promising external-tool
source. Its [FFmpeg formula](https://formulae.brew.sh/formula/ffmpeg) includes
FFmpeg and FFprobe, and [Chromaprint](https://formulae.brew.sh/formula/chromaprint)
includes fpcalc; both list Linux bottles. Bazzite documents its
[Linuxbrew prefix](https://docs.bazzite.gg/Installing_and_Managing_Software/Homebrew/).
Detect existing executable locations outside the desktop launcher's PATH and
verify them. This does not make the same Host installation runnable inside a
Flatpak; the sandbox has its own libraries and filesystem view.

Alternatively, install iOpenPod and its tools **together** in a Distrobox/Toolbx
container. [Distrobox exports GUI launchers](https://distrobox.it/usage/distrobox-export/)
that continue to execute inside that container. This avoids crossing a container
boundary for every media subprocess. Mount discovery, UDisks2, physical backing,
device reconnect and recovery still require acceptance in that environment.
Exporting only an FFmpeg wrapper is a different, more complex integration:
Distrobox's exported binaries are wrapper scripts, not native Host binaries.

Native application paths also need the alias/recovery work identified in the
[earlier investigation](immutable-linux-flatpak-2026-11-06.md). Media-tool
availability alone does not resolve that report's `/home` aliases or Flatpak
visibility of `/sys/fs/btrfs`.

Optional Phase analysis has a separate private Python/dependency/model setup;
runtime FFmpeg availability does not validate that environment inside Flatpak.
Retain its acoustic fallback and qualify optional execution separately, as
described in [the earlier investigation](immutable-linux-flatpak-2026-11-06.md)
and [ADR-0225](../adr/0225-install-optional-phase-analysis-with-safe-fallbacks.md).

## Why a Host-command bridge should not be the default

[`flatpak-spawn --host`](https://docs.flatpak.org/en/latest/flatpak-command-reference.html#flatpak-spawn)
can execute installed Host tools but needs access to `org.freedesktop.Flatpak`.
It grants arbitrary Host-command execution, not permission restricted to three
media programs. The documented `--forward-fd` and `--watch-bus` options help with
descriptor transport and lifetime, but are not evidence that existing runners
work unchanged.

Local [Storage media execution](../../src/storage/media_processing.py) passes
pinned POSIX inputs through `/dev/fd/N` and `pass_fds`, bounds output, and kills
the immediate process on cancellation. A bridge must preserve those descriptors,
seekability, source identity and cancellation of the real worker. It must also
map temporary files and outputs between the sandbox and Host; a sandbox `/tmp`
path is not automatically a Host path. Container grandchildren need additional
lifetime validation. [Synesthesia](../../src/iOpenPod/app/synesthesia/audio.py)
also has a streaming FFmpeg launch path to cover.

If this route is pursued later, use a typed execution adapter in Storage, with
Application Layer provider selection and diagnostics. Do not store shell snippets
in the existing executable override fields. Tools should produce Host staging
outputs; verified device publication remains within Storage Transactions.

It is also a poor default Flathub proposal. Current
[Flathub requirements](https://docs.flathub.org/docs/for-app-authors/requirements#host-dependent-applications)
reject apps dependent on Host components or complicated post-installation setup
for core functionality, except case by case. The
[Flatpak D-Bus permission exception policy](https://docs.flathub.org/docs/for-app-authors/linter#finish-args-flatpak-talk-name)
is restricted to Flatpak clients or development apps. Technical feasibility in a
self-distributed Flatpak is distinct from Flathub acceptance.

## Options compared

| Route | iOpenPod distributes tool binaries? | Main consequence |
| --- | --- | --- |
| Runtime FFmpeg/FFprobe plus `codecs-extra` | No, runtime maintainers supply them | Partial solution; required fpcalc remains unresolved. |
| User-installed compatible fpcalc inside sandbox | No | Candidate to complete the required tool set; validate artifacts and distribution acceptance. |
| Independently maintained tool extension | No | Good sandbox integration if a suitable maintained provider exists. |
| iOpenPod-maintained tool extension | Yes, in another artifact | Does not satisfy a strict no-redistribution requirement. |
| Native application plus Linuxbrew tools | No | Promising Bazzite route; needs discovery and native acceptance. |
| Application and tools together in Distrobox/Toolbx | No | Uses container packages; validate Storage and desktop integration. |
| Flatpak calling Host/container tools | No | Broad permission, descriptor/lifetime work and Flathub policy obstacles. |

## Proposed next increment

1. Apply the settled requirement: FFmpeg, FFprobe and fpcalc must all work without
   iOpenPod bundling their executables. Record the selected runtime/provider
   arrangement; a route missing fpcalc is incomplete.
2. On an installed candidate, record runtime/extension versions and actual
   executable paths. Run FFmpeg/FFprobe capability checks and representative
   audio/video inspection, conversion and verification through iOpenPod's runner.
   Repeat with `codecs-extra` masked and ensure missing features fail clearly.
3. Qualify one upstream fpcalc build per supported architecture using ordinary
   paths and Storage's pinned seekable inputs. Exercise missing tools, bad
   overrides, cancellation and retained matching data. Require successful
   fingerprint generation for installation acceptance; missing-tool fallback is
   not a passing result.
4. Add immutable-Host observations and appropriate setup guidance; keep native
   Linuxbrew and same-container execution distinct from Flatpak discovery.
5. Complete the earlier investigation's installed Storage acceptance: Btrfs
   backing visibility, aliases, identity, disconnect/reconnect, recovery and eject.
6. Address reproducible packaging separately. The current
   [manifest](../../packaging/linux/flatpak.json) copies a locally frozen tree;
   [packaging documentation](../packaging.md) already records that it is not a
   complete Flathub submission. Re-audit the latest runtime at submission time.

This investigation used repository source, Context7 and primary upstream
documentation on Windows. It did not execute Linux media binaries, install a
Flatpak candidate or mutate an iPod. Source-level feasibility and another app's
use of the runtime do not establish installed iOpenPod platform support.

## Executed Windows experiment: reusing Qt's FFmpeg libraries

The owner subsequently asked whether fpcalc could be bundled, identified the
existing Qt FFmpeg libraries, and requested an actual build and test. This
experiment evaluates that alternative to the original no-bundling constraint.
It does not change application discovery, package manifests, release policies or
the requirement that fpcalc work in every supported installation.

**Result: reuse works on this Windows x64 installation.** Chromaprint/fpcalc
1.6.2 was built against the exact FFmpeg 7.1.5 DLLs already supplied by PySide6
6.11.2. No second FFmpeg implementation was built. The two added release binaries
total **98,304 bytes (96 KiB)** before license/source materials:

| Added binary | Bytes | SHA-256 |
| --- | ---: | --- |
| `fpcalc.exe` | 40,448 | `6dfe136766dee619d612cff95737f74e09bb90b0de444aaa57764c0e2df58112` |
| `chromaprint.dll` | 57,856 | `b4456d219194b6d27f48c7b2505e6d7f1c0eb5d2d07c9ac7f9044cc1ac72afd3` |

### Build inputs and method

- [Chromaprint 1.6.2 source](https://github.com/acoustid/chromaprint/releases/tag/v1.6.2),
  archive SHA-256
  `d54ada62c16b2db396d3251ec54fc7a58909c163131a1cfcf7fa6407dbc14360`.
- FFmpeg 7.1.5 headers from the repository's already hash-pinned source archive,
  SHA-256 `de668509caf9e35e3cd162473441fdb29538c6d96ed080292b3cf9e6fc5d558f`.
  The public `avconfig.h` describes the Windows x64 target's little-endian and
  unaligned-access properties; it does not enable codecs or rebuild FFmpeg.
- MSVC 19.44.35229, CMake 4.1.3 and Ninja 1.13.0. Import libraries were generated
  from the existing Qt DLL exports. The PySide6 installation was not modified.
- `BUILD_TOOLS=ON`, `BUILD_SHARED_LIBS=ON`, `BUILD_TESTS=OFF`,
  `FFT_LIB=avtx`, `AUDIO_PROCESSOR_LIB=swresample`. Chromaprint source was unpatched.
  The existing internal fingerprint resampler remained enabled.

### What was executed

All media was generated locally for this experiment. A separately installed
FFmpeg executable produced the fixture encodings; it was then excluded from the
fingerprinting process's PATH. Process-module enumeration confirmed that fpcalc
loaded `avutil-59.dll`, `avcodec-61.dll`, `avformat-61.dll` and `swresample-5.dll`
from the existing PySide6 directory. The recorded DLL hashes identify the exact
inputs. No user media or physical iPod was used.

The Application Layer's real `FpcalcFingerprinter` and Storage runner produced
identical raw algorithm-2 fingerprints to the previously installed fpcalc 1.6.1
for all ten cases:

| Case | Fingerprint words | Exact reference match |
| --- | ---: | --- |
| WAV | 237 | Yes |
| FLAC | 237 | Yes |
| MP3 | 237 | Yes |
| AAC in M4A | 237 | Yes |
| ALAC in M4A | 237 | Yes |
| Opus | 237 | Yes |
| Vorbis | 237 | Yes |
| H.264/AAC MP4 | 237 | Yes |
| WAV with spaces and accented/Japanese filename characters | 237 | Yes |
| 130-second WAV analyzed with the 120-second limit | 948 | Yes |

The reference executable reports FFmpeg library versions `Lavc62.11.100`,
`Lavf62.3.100` and `SwR6.1.100`; the new build reports `Lavc61.19.101`,
`Lavf61.7.103` and `SwR5.3.100`. Exact equality across this fixture set is useful
compatibility evidence, not proof for every recording or decoder version.

Repeated fingerprints were identical and source hashes remained unchanged.
A Virtual Filesystem Session produced the same result as the Host input.
Malformed audio was rejected. Real blocked fpcalc children were cancelled or
timed out through Storage and reaped before the runner returned.

A separate PyInstaller one-file proof bundle placed fpcalc and Chromaprint beside
the shared DLLs in `PySide6/`. All ten cases passed with the child PATH restricted
to Windows System32. Archive inspection found exactly one copy of each of Qt's
five FFmpeg DLLs, including `swscale`, and no `ffmpeg.exe` or `ffprobe.exe`.
This proves the tested frozen loading arrangement, not MSIX installation.

Focused repository validation passed **96 tests**, with **one POSIX descriptor
inheritance test skipped** on Windows. Coverage included media fingerprinting,
Storage execution/environment/lifetime, cancellation checkpoints and Qt playback.
The new fpcalc was selected for the real-tool fingerprint test. The full suite
was not run because application behavior was unchanged and unrelated work was
present in the shared checkout.

### Local artifacts and remaining work

The executable, shared library, input hashes, build configuration, generated
fixtures and machine-readable verification records are under the ignored
`build/native-libs/fpcalc-qt-experiment/` directory. Local reproduction scripts
and instructions are under `.scratch/fpcalc-qt-reuse-20261113/`. These are
experimental artifacts, not a production packaging recipe or public release.

Production integration needs explicit bundled-tool discovery, the tested
same-directory loading arrangement, matching source/notices and dependency
inventory, an updated package-content checker, and installed-package acceptance.
Reuse must be checked again when Qt's FFmpeg ABI changes. Linux/Flatpak and macOS
require their own builds and execution tests; this machine has no installed
Linux environment. The earlier Btrfs and Host path-alias work remains separate.
