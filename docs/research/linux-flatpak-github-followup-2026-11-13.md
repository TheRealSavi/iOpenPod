# Linux and Flatpak: GitHub follow-up

Investigated 2026-11-13 through GitHub's connected read-only API and the working
checkout at `5bf610338da188c79d8a93486de229b8335309c1`. This follows the
[media-tool research and Windows fpcalc experiment](immutable-linux-flatpak-media-tools-2026-11-13.md)
and the [earlier Bazzite investigation](immutable-linux-flatpak-2026-11-06.md).
It records findings and remaining acceptance work, not an implementation decision.
Existing unrelated working-tree edits were left untouched.

## Finding

There is already an **open Flatpak repair PR, #266**, but its current approach
bundles a new FFmpeg build. It is useful evidence and a source of packaging fixes,
not a complete answer to the requested distribution strategy. Required fpcalc
support, the runtime/library arrangement and installed Linux testing still need
an explicit resolution.

The broader GitHub history adds important acceptance requirements: FAT identity
stability, old UDisks versions, large-library staging, aliased paths, reconnects,
desktop input and migration from community builds. Several earlier Linux Storage
defects already have merged fixes; repeating those diagnoses would obscure what
is actually outstanding.

Current direction requires FFmpeg, FFprobe **and fpcalc** in every supported
installation. The current missing-fpcalc fallback does not satisfy support
acceptance; see [ADR-0264](../adr/0264-require-fpcalc-in-supported-installations.md).
The later Windows experiment demonstrates fpcalc reuse of Qt's existing FFmpeg
libraries, not Linux/Flatpak compatibility or production bundling approval.

## Open PR #266: useful work, conflicting tool strategy

[#266, “Fix Flatpak builds”](https://github.com/TheRealSavi/iOpenPod/pull/266), is
open at head `dcaab22aa8154a69fa26c89cc2932aab8ab0d8d6`, last updated November 7.
The [12-file diff](https://github.com/TheRealSavi/iOpenPod/pull/266/files) contains:

| Change | Relevance now |
| --- | --- |
| Freedesktop 25.08 to 26.08 and an app-ID-named manifest | Evaluate against the chosen supported runtime; the previous media-tool source audit covered 25.08, so repeat it for 26.08. |
| Builds x264, FFmpeg 7.1.5 and Chromaprint 1.6.2 into `/app` | Supplies all tools, but includes a second FFmpeg distribution instead of qualifying runtime/Qt reuse. Does not meet the original no-bundled-FFmpeg/FFprobe requirement. |
| fpcalc links static Chromaprint and uses FFmpeg's `avtx` FFT | A relevant build configuration to compare with the Windows reuse experiment, not evidence that Linux reuse was tested. |
| AppStream release entry, desktop category cleanup, manifest assertions | Useful packaging work to review independently. The release is hardcoded to `2.0.13`; this checkout declares `2.1.3`, so metadata needs generation or updating. |
| Copies the existing locally frozen application tree | Still not an offline, reproducible Flathub source build. |
| Retains current permissions | Still lacks `/sys/fs/btrfs`; does not resolve the reported Bazzite recovery observation failure. |

The PR adds a branch-only document labelled accepted `ADR-0247`, claiming a
Flatpak bundling exception. It is not a merged decision. Main already uses that
number for [Extras editing](../adr/0247-manage-extras-through-qualified-lossless-file-edits.md).
Its policy, numbering and documentation must be reconciled before any integration;
the branch's assertion that the owner chose bundling is not current authorization.

Its packaging prose also claims that freezing inside the SDK encounters a
missing Kerberos dependency of QtNetwork, and that a newer Host glibc can make the
frozen tree unusable in the runtime. Treat these as concrete build-reproduction
targets. The PR does not provide Linux execution logs demonstrating those claims
or an installed end-to-end result.

At the inspected head, GitHub returned no submitted reviews, check runs or commit
statuses. The sole [discussion comment](https://github.com/TheRealSavi/iOpenPod/pull/266#issuecomment-6257428139)
attributes an `hdiutil` failure to unrelated infrastructure. That is not evidence
of a successful Linux build or Sync. A subsequent metadata refresh reported
`mergeable=false` and `mergeable_state=dirty`; the branch needs conflict resolution
as well as policy review. Current-code comparisons in this note refer to the
local checkout, not a claim that all fixes have shipped in a public package.

## Historical PRs and what has already landed

| PR and state | Established change | Present implication |
| --- | --- | --- |
| [#70](https://github.com/TheRealSavi/iOpenPod/pull/70), merged | Original Flatpak wrapper, metadata and workflow for a prebuilt application. | Historical baseline, not proof of v2 support. Its old `--device=all` permission should not be restored. |
| [#171](https://github.com/TheRealSavi/iOpenPod/pull/171/files), merged | Adds the missing PulseAudio socket permission. | Already present in the current manifest; preserve and test audio. |
| [#179](https://github.com/TheRealSavi/iOpenPod/pull/179/files), merged | Disables UPX for Linux after crashes under load. | Current application and update-helper specs already use `upx=False`. |
| [#283](https://github.com/TheRealSavi/iOpenPod/pull/283), merged | eCryptfs recovery resolution, actionable device diagnostics, safe native desktop-helper environment. | Keep the improved diagnostics. Its native helper path deliberately excludes Flatpak/Snap, which retain Qt/portal integration. |
| [#284](https://github.com/TheRealSavi/iOpenPod/pull/284), merged | Traverses physical backing through supported device-mapper and MD RAID relationships. | The old logical-device separation defect is fixed in source; actual target-system acceptance remains distinct. |
| [#285](https://github.com/TheRealSavi/iOpenPod/pull/285), merged | Uses Linux `O_PATH` for search-only ancestors with pinning and no-follow protections. | Do not report the original directory-read-permission defect as still unfixed. udev remains a prerequisite. |
| [#286](https://github.com/TheRealSavi/iOpenPod/pull/286), merged | Adds Btrfs member verification after #284 initially rejected Btrfs. | Btrfs is no longer generically unsupported. Sandbox visibility and complete physical backing are still required. |
| [#318](https://github.com/TheRealSavi/iOpenPod/pull/318), merged | Fixes Windows-specific assumptions in tests and stale translations after a Fedora run. | Useful real Linux test evidence, but its reported remaining GUI/font failures and offscreen execution do not establish installed desktop acceptance. |

For #286, Ubuntu tests exercised a real two-member Btrfs fixture, subvolume and
bind alias. The fixture uses loop devices and expects final recovery rejection
of those unsupported leaves. It validates kernel interfaces, not successful
recovery on physical Btrfs hardware. See
[ADR-0193](../adr/0193-resolve-btrfs-recovery-through-all-member-devices.md).

The original #70 review raised source-build, metadata and library-path concerns;
these are historical review suggestions, not runtime test results. Its
[contributor discussion](https://github.com/TheRealSavi/iOpenPod/pull/70#issuecomment-4229260649)
explains the intention to use a common runtime and generate release metadata.
Current [Flatpak CI](../../.github/workflows/flatpak.yml) is manual and retains a
candidate artifact, so the old automatic-release race is not the current setup.
Likewise, merged [AppImage #65](https://github.com/TheRealSavi/iOpenPod/pull/65)
and [AUR #61](https://github.com/TheRealSavi/iOpenPod/pull/61) establish earlier
distribution work, not current support commitments. Native archive publication
is governed by [ADR-0107](../adr/0107-publish-only-native-release-archives.md).

## Issues that change acceptance work

Issue state below is the state observed during this investigation. A closed issue
does not by itself prove a reproduced fix, released fix or completed workflow.

| Evidence | What to account for |
| --- | --- |
| [#103](https://github.com/TheRealSavi/iOpenPod/issues/103), open | Flatpak remains a requested/planned channel. The [latest report](https://github.com/TheRealSavi/iOpenPod/issues/103#issuecomment-6842644645) says a workflow build works after extra filesystem access; it spells the path `btfs`, so use #312's exact Btrfs evidence rather than copying that typo. |
| [#312](https://github.com/TheRealSavi/iOpenPod/issues/312), closed | Separates three failures: native installation-lease path validation, Flatpak Btrfs visibility, and a date error. The [Flatseal workaround](https://github.com/TheRealSavi/iOpenPod/issues/312#issuecomment-6685202865) confirms `/sys/fs/btrfs` access helped; the [date-fix confirmation](https://github.com/TheRealSavi/iOpenPod/issues/312#issuecomment-6686219809) is a different outcome. |
| [#326](https://github.com/TheRealSavi/iOpenPod/issues/326), open | Linux Mint 21/vfat report: ArtworkDB inode changes despite unchanged size, modification time and SHA. Cause remains unestablished; the report's experimental copies/simulations are not a physical-device fix. Investigate FAT identity behavior without globally deleting identity checks. |
| [#313](https://github.com/TheRealSavi/iOpenPod/issues/313), closed | [Maintainer comment](https://github.com/TheRealSavi/iOpenPod/issues/313#issuecomment-6855538294) identifies `GetDrives` incompatibility before UDisks 2.11 and says the next release fixes it. Current code uses drive-subtree introspection; the reporter has not confirmed a successful retest. |
| [#270](https://github.com/TheRealSavi/iOpenPod/issues/270), closed | Reporter [confirms Classic/Nano 3 detection](https://github.com/TheRealSavi/iOpenPod/issues/270#issuecomment-6401990680), then reports eject trouble. Treat detection and eject as separate acceptance checks. |
| [#241](https://github.com/TheRealSavi/iOpenPod/issues/241), closed | [Path overrides are confirmed](https://github.com/TheRealSavi/iOpenPod/issues/241#issuecomment-6172205981), but the [following comment](https://github.com/TheRealSavi/iOpenPod/issues/241#issuecomment-6179759353) reports Sync trouble with details elsewhere. Preserve overrides and require a clean installation to discover its supported tools without manual repair. |
| [#247](https://github.com/TheRealSavi/iOpenPod/issues/247), closed; [#295](https://github.com/TheRealSavi/iOpenPod/issues/295), open | Large-library reports include temporary-storage growth and too many files. Verify staging location, free space, descriptor/lease use, stale cleanup and cancellation inside Flatpak, not just short media fixtures. |
| [#230](https://github.com/TheRealSavi/iOpenPod/issues/230), closed; [#85](https://github.com/TheRealSavi/iOpenPod/issues/85), closed | Authorized symlink sources and network/mounted media are real workflows. Test saved paths, sandbox grants, external Playlists and NAS sources across restart. |
| [#105](https://github.com/TheRealSavi/iOpenPod/issues/105), closed; [#228](https://github.com/TheRealSavi/iOpenPod/issues/228), closed | Kinoite duplicate-device reports and Fedora stale Connection Generations require alias deduplication and remount/reconnect tests. Closure supplies no general proof that every topology works. |
| [#82](https://github.com/TheRealSavi/iOpenPod/issues/82), closed | Historical modifier-key crashes include Flatpak. No confirmed fix was established from the comments; exercise actual Wayland/X11 keyboard selection and playback. An offscreen smoke test cannot cover this. |
| [#232](https://github.com/TheRealSavi/iOpenPod/issues/232), open | Linux ARM64 is a separate requested target; the present candidate workflow builds only x86-64. Do not imply ARM64 support from upstream fpcalc download availability. |

Current code supports several of these directions without proving the reporter's
environment is repaired:

- [FileFingerprint](../../src/storage/models.py) includes inode identity, and
  device revision checks consume it. #326 needs a filesystem-specific diagnosis
  that preserves stale-input rejection and transaction safety.
- [Linux eject](../../src/storage/platform/linux_eject.py) and its
  [regression tests](../../tests/storage/test_linux_eject.py) now cover the absence
  of `Manager.GetDrives`. Test the packaged app against an older Host UDisks and
  real authorization/busy-device outcomes.
- [Host staging](../../src/storage/host_staging.py) uses an explicit
  `TMPDIR`/`TEMP`/`TMP` before application cache storage. A Flatpak-provided temp
  setting can therefore matter. [ADR-0117](../adr/0117-spill-prepared-library-content-to-host-storage.md)
  and [ADR-0212](../adr/0212-share-host-staging-ownership-across-workspaces.md)
  address prior storage/lease issues; they do not promise bounded disk use
  independent of batch size or verified Linux/NAS Sync.
- [ADR-0132](../adr/0132-follow-explicitly-authorized-host-symbolic-links.md)
  and [ADR-0136](../adr/0136-allow-network-filesystems-as-host-media-sources.md)
  support authorized Host aliases and mounted network sources. They do not
  automatically authorize updater/recovery aliases or missing sandbox grants.

## Distribution continuity and next checks

[#103's community-distribution offer](https://github.com/TheRealSavi/iOpenPod/issues/103#issuecomment-5260188992)
means some users may already have unofficial packages. Before an official release,
identify actual installed app IDs, remotes and data paths; test settings and
Backup Archive continuity. Do not assume a community remote is still maintained
or silently replace its update ownership. The older
[#115 updater report](https://github.com/TheRealSavi/iOpenPod/issues/115) concerns
an implementation the [maintainer says was replaced](https://github.com/TheRealSavi/iOpenPod/issues/115#issuecomment-5826136212).
Flatpak updates should remain with its distribution channel.

The next evidence should come from a real installed Linux candidate:

1. Resolve all three media tools and the selected library set. Verify Linux
   fpcalc fingerprints and loading independently of the successful Windows proof.
   The [external-process environment](../../src/storage/host_tools.py) removes
   PyInstaller's private library path on Linux; Qt-library reuse needs an explicit
   loader/RPATH design compatible with that policy.
2. Reproduce native cache-path aliases and validate the read-only Btrfs grant;
   retain complete physical-backing and recovery checks.
3. Diagnose #326 on disposable FAT media, then test a complete reviewed Sync,
   disconnect/recovery and old-UDisks eject on an explicitly selected test iPod.
4. Exercise large batches, full staging volumes, clean cancellation, symlink/NAS
   sources, desktop file selection and actual keyboard input on Wayland/X11.
5. Rework #266's useful packaging pieces around the selected tool policy,
   generated metadata and reproducible build. Validate fresh install and upgrade
   from identified existing channels before calling it supported.

The PR survey covered all 67 open/closed PR metadata records returned by GitHub,
plus focused searches and relevant diffs, discussion and review/status records.
Issue evidence was reconciled with current source rather than inferred from
labels. No external comments were posted and no Linux environment or physical
iPod was exercised by this investigation.
