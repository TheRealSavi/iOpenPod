# Immutable Linux and Flatpak support

Investigated 2026-11-06 against checkout
`9039e6b090b3228f681607272d8eb64f814b83fa` and
[issue #312](https://github.com/TheRealSavi/iOpenPod/issues/312).
This is research and a proposed direction, not an accepted ADR or a declaration
of platform support. No application or packaging behavior changed.

## Finding

Support is feasible without relaxing Storage's recovery guarantees. Two small,
separate compatibility changes deserve investigation first:

1. Expose `/sys/fs/btrfs` read-only to the Flatpak candidate. The reporter already
   confirmed that granting this directory through Flatseal fixed their Flatpak
   access failure. The proposed read-only variant still needs installed-package
   testing.
2. Handle legitimate Host filesystem aliases at the native application's path
   entry points. The reported launcher failure occurs while validating the
   installation lease's **cache lock path**, not merely the executable path.

A supported Flatpak distribution also needs a workable command-line media-tool
strategy, installed-package acceptance, and reproducible packaging. Flathub
publication is a further gate. The existing candidate is useful starting work;
it does not establish those outcomes.

## What issue #312 establishes

| Observation | Interpretation and confidence |
| --- | --- |
| A custom Flatpak on Bazzite 44 cannot read `/sys/fs/btrfs/<uuid>/exclusive_operation` while checking Host `TransactionRecovery` storage. | The log identifies the missing Btrfs observation, before device access is prepared. This is separate from permission to read the iPod's files. |
| Adding `/sys/fs/btrfs` in Flatseal resolves that failure. | Reporter-confirmed workaround; the comment does not specify read-only access or provide a complete workflow test. |
| The native tarball launcher raises `Installation path traverses a link or special file` from `HostInstallationLease.__init__`. | The traceback points to validation of the cache lock path. `/home` aliasing is a strong explanation, but the reporter's actual path/environment were not captured. |
| Distrobox gets past startup and reaches the older playback-sidecar date error. | Evidence that another environment can load further, not evidence of complete Distrobox support. |
| The reporter confirms commit `dd4e40399cc96da3811562cf9054f181e5812ce2` fixes the DST error. | Separate date-handling issue, already confirmed fixed in the discussion. Do not conflate it with Linux packaging. |

Sources: [initial report](https://github.com/TheRealSavi/iOpenPod/issues/312),
[native traceback](https://github.com/TheRealSavi/iOpenPod/issues/312#issuecomment-6673871036),
[Distrobox observation](https://github.com/TheRealSavi/iOpenPod/issues/312#issuecomment-6673968682),
[Flatseal result](https://github.com/TheRealSavi/iOpenPod/issues/312#issuecomment-6685202865),
and [DST confirmation](https://github.com/TheRealSavi/iOpenPod/issues/312#issuecomment-6686219809).
The issue was closed when inspected. That does not close the broader support work.

## Immutable Linux: fix Host path entry points

Immutable distributions can run user-installed applications. Fedora's documented
Atomic layout keeps `/etc` and `/var` writable and maps `/home` to `/var/home`,
`/opt` to `/var/opt`, and `/mnt` to `/var/mnt`. Consequently, a normal writable
user directory can have a symlink in its ancestors. See the
[Fedora filesystem-layout source](https://github.com/fedora-silverblue/silverblue-docs/blob/master/modules/ROOT/pages/technical-information.adoc).
Bazzite recommends Flatpak for graphical applications and treats package layering
as a last resort; see its [software guide](https://docs.bazzite.gg/Installing_and_Managing_Software/software-intro/).

The native failure follows this chain:

- [`iopenpod_update_helper.py`](../../src/iopenpod_update_helper.py) passes the
  executable's parent to `launch_managed`.
- [`launch_managed`](../../src/iOpenPod/app/updates/helper.py) validates that root,
  then obtains a shared `HostInstallationLease` before starting the selected
  version.
- [`HostInstallationLease`](../../src/storage/host_usage.py) constructs its lock
  through `application_cache_file`, creates the parent, and calls
  `require_plain_path` on the lock path.
- [`application_cache_file`](../../src/storage/host_files.py) uses
  `XDG_CACHE_HOME`, or `Path.home() / ".cache"`, without canonicalizing that base.
- [`require_plain_path`](../../src/storage/host_installation.py) rejects every
  symlink/reparse ancestor. An alias through `/home` is sufficient to fail.

This explains why launching an executable through `/var/home/...` alone is not a
complete solution: the cache location can still use `/home/...`. Configuration,
recovery, optional analysis, and updater paths need the same audit. The reported
Host Python 3.15 does not establish the packaged interpreter version; this project
pins Python 3.12 and freezes its own runtime. See
[`pyproject.toml`](../../pyproject.toml) and [packaging](../packaging.md).

Proposed design, requiring a focused ADR before changing the shared contract:

1. Resolve an authorized installation root and existing application-location base
   into a canonical Host location at their entry points. Define which aliases
   are accepted: OS-owned layout aliases and explicit user selections should not
   implicitly authorize arbitrary links supplied by an update archive or journal.
2. Validate and pin the resulting directory, then keep no-follow checks on child
   paths, payloads, lock files, and publication operations. Resolve an existing
   base before creating missing application subdirectories beneath it.
3. Use the same canonical installation identity for the application and update
   helper's shared/exclusive lease. Alternate spellings must not produce separate
   locks for the same installation. Account for existing processes and persisted
   update records when introducing this normalization.
4. Audit startup, settings, cache, Host recovery, download staging, updates,
   rollback, and optional Phase analysis. An app that opens but cannot safely
   update or recover is not accepted support.

The existing [`HostSelectionResolver`](../../src/storage/host_input.py) already
distinguishes explicit selection from indirect references and requires normal
Storage observations afterward. It is a useful precedent, not automatic
authorization to apply it to updater-controlled paths. Do not replace
`require_plain_path` globally with `Path.resolve()` or disable link checks.

Native media-tool setup also needs an immutable-distribution capability check.
[`_linux_plan`](../../src/iOpenPod/app/services/media_tools.py) currently selects
package managers from distribution IDs, including `dnf` for Fedora, without a
separate Atomic-host policy. Prefer a verified user-installed executable route
and accurate setup guidance; do not infer that ordinary Fedora package
installation is appropriate because the Host identifies as Fedora-derived.

## Flatpak: restore the missing Btrfs observation

[`packaging/linux/flatpak.json`](../../packaging/linux/flatpak.json) currently
uses Freedesktop 25.08, a staged frozen application, home and removable-mount
access, `/run/udev:ro`, UDisks2 access, audio, graphics, networking, and MPRIS.
It does not expose `/sys/fs/btrfs`.

Storage's Btrfs recovery proof intentionally combines a read-only filesystem
ioctl, descriptor mount identity, complete Btrfs membership, and the live block
graph. It rejects active reconfiguration, missing members, and physical backing
shared with the selected iPod. The first missing field in this report is
`exclusive_operation`, but allowing just that file would leave membership checks
unsatisfied. See [`linux_btrfs.py`](../../src/storage/platform/linux_btrfs.py),
[`linux_backing.py`](../../src/storage/platform/linux_backing.py), and
[ADR-0193](../adr/0193-resolve-btrfs-recovery-through-all-member-devices.md).

Flatpak exposes several sysfs subtrees read-only by default, including
`/sys/class` and `/sys/devices`; `/sys/fs/btrfs` needs an explicit filesystem
permission. `/sys` is not a reserved filesystem path in the current documentation.
Read-only directory access is supported. See
[Flatpak filesystem permissions](https://docs.flatpak.org/en/latest/sandbox-permissions.html#reserved-paths).

For a local installed candidate, the proposed one-launch diagnostic is:

```shell
flatpak run --filesystem=/sys/fs/btrfs:ro io.github.therealsavi.iOpenPod
```

This adds access only for that invocation; it does not persist an override.
See the [Flatpak run reference](https://docs.flatpak.org/en/latest/flatpak-command-reference.html#flatpak-run).
If acceptance confirms it, the same permission belongs in the candidate's
`finish-args`. This note does not apply it or claim it was executed.

Keep recovery validation mandatory. Missing observations must still prevent
unsafe work, with a diagnostic that distinguishes hidden sandbox information from
an unsupported or changing Host storage topology. No evidence here requires
`--device=all`, broad system-bus access, a host-shell escape, or a new privileged
helper.

### Remaining device integration checks

- **Discovery and reconnect:** verify the actual sandbox's mount table, udev
  properties, block graph, bind aliases, and new Connection Generations. The
  current adapter reads `/proc/self/mountinfo`, `/run/udev/data`, and
  `/sys/class/block`; see [`linux.py`](../../src/storage/platform/linux.py).
- **Eject and rename:** retain the named UDisks2 permission. The existing
  [`linux_eject.py`](../../src/storage/platform/linux_eject.py) uses D-Bus to
  resolve a device, unmount its filesystems, and confirm power-off. Bus visibility
  alone does not guarantee Host authorization; test busy, denied, and partial
  outcomes. See [UDisks authorization](https://storaged.org/doc/udisks2-api/latest/udisks-polkit-actions.html).
- **Identity setup:** the optional application udev rule publishes identity
  evidence without granting raw-device access. It remains a Host setup operation;
  the Flatpak cannot infer whether Host `/etc/udev/rules.d` contains it by checking
  sandbox `/etc`. Audit the startup status message and setup guidance in
  [`linux_identity.py`](../../src/iOpenPod/app/services/linux_identity.py).
- **Portals:** user-selected Host media folders can benefit from portal grants,
  but a document-portal path is not proof of physical recovery backing. The USB
  portal provides access to USB device nodes, not this Btrfs evidence or a
  mounted-filesystem session. See the [USB portal API](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.Usb.html).

## The main product decision: command-line media tools

[ADR-0081](../adr/0081-require-user-installed-media-tools.md) explicitly requires
user-installed FFmpeg, FFprobe, and fpcalc executables; Qt playback libraries are
separate. FFmpeg/FFprobe gate incoming Track preparation, while missing fpcalc
limits acoustic matching. The current Flatpak workflow intentionally does not
bundle those executables. Host installation alone does not make them usable in
the sandbox; the packaging guide already records this unresolved gate.

| Approach | Consequence |
| --- | --- |
| User-installed tools compatible with the Flatpak runtime, accessible inside the sandbox | Closest to the existing decision. Needs a concrete, maintained installation route and tests of paths, dependent libraries, codecs, subprocess cancellation, and updates. A readable Host binary is not necessarily runnable against the sandbox runtime. |
| A separately installed Flatpak extension containing the tools | A possible distribution design, not an already available solution. Requires compatible builds, lifecycle ownership, discovery, licensing work, and review of whether it meets the intent of ADR-0081. |
| Package tools with the app | Simplifies integration but changes the owner's explicit distribution policy and dependency/license responsibilities. Requires an accepted superseding ADR. |

Flatpak supports application extension points, but a codec extension is not
evidence that the required command-line executables are present. In particular,
Freedesktop replaced `ffmpeg-full` with `codecs-extra` starting at 25.08; do not
assume adding the former supplies FFmpeg/FFprobe for this candidate. See
[Flatpak extensions](https://docs.flatpak.org/en/latest/extension.html).

Recommendation: resolve this policy before calling Flatpak a supported Sync
channel. Avoid using a general Host command bridge as the default solution.
The current setup service already refuses to install Host packages from a
confined application; preserve that behavior while adding a real supported route.
See [`media_tools.py`](../../src/iOpenPod/app/services/media_tools.py).

Optional Phase analysis also downloads UV, Python, dependencies, and model data
into a private Host environment. Its Linux runtime, sandbox execution, GPU/CPU
fallback, and distribution acceptance remain separate checks; the existing
acoustic fallback is the baseline. See
[ADR-0225](../adr/0225-install-optional-phase-analysis-with-safe-fallbacks.md) and
[`phase_runtime_install.py`](../../src/iOpenPod/app/phase_runtime_install.py).
Do not assume native success establishes Flatpak or Flathub acceptance.

## Packaging and publication

The manual [Flatpak workflow](../../.github/workflows/flatpak.yml) freezes on
Ubuntu 24.04, copies `build/linux-root` into `/app`, and runs an offscreen smoke
test. It produces a candidate artifact. A frozen-app smoke test does not exercise
the reported Btrfs recovery path, safe removal, or incoming media preparation.
Flatpak detection already routes updates away from the native GitHub installer;
retain that in [`updates/platform.py`](../../src/iOpenPod/app/updates/platform.py).

For Flathub, replace the local-directory input with pinned upstream sources and
offline dependency inputs. Build/test against the chosen SDK and runtime, and
explicitly provide Python 3.12 rather than assuming the runtime's Python matches
the project. Native wheels/extensions, Qt plugins, Wasmtime, numerical analysis,
and the frozen helper require runtime compatibility checks. UV remains the
repository's Python toolchain; no dependency change is proposed here.

Flathub's current requirements include source builds where available, offline
builds, permission review, and validated application metadata. Recheck its
runtime-version requirement rather than assuming the candidate's 25.08 remains
acceptable for a new submission. Its current AI
policy additionally prohibits AI-assisted manifests and agent-generated
submission interactions, and requires disclosure of included generated material.
A future Flathub submission needs human authorship and maintenance under that
policy; this research does not submit anything. See
[Flathub requirements](https://docs.flathub.org/docs/for-app-authors/requirements).
Keep this publication gate distinct from testing or distributing a local candidate.

## Recommended acceptance order

1. **Confirm the permission fix:** reproduce with and without the Btrfs grant on
   Bazzite and Fedora Atomic, using a clean candidate without unrelated Flatseal
   overrides. Record kernel, Flatpak, runtime, filesystem, and mount facts.
2. **Fix native path handling:** add Linux regressions for OS-style aliases,
   canonical cache/config locations, alias-equivalent installation leases,
   malicious child links, ancestor replacement, and update/rollback behavior.
3. **Validate Storage inside Flatpak:** exercise single- and multi-member Btrfs,
   encrypted backing, subvolumes/binds, ordinary ext4, missing sysfs evidence,
   same-Physical-Device recovery refusal, reconnect, and interrupted recovery.
4. **Resolve tools and complete workflows:** test media preparation and Sync,
   playback, Backup Snapshots, restore, export, identity evidence, eject, and
   updates from the installed package. Test optional analysis separately.
5. **Prepare a distribution release:** finish reproducible packaging and metadata,
   then evaluate Flathub submission against its current requirements.

Use disposable virtual Volumes for automated mutation tests and an explicitly
selected test iPod for physical acceptance. Existing synthetic backing tests in
[`test_linux_btrfs_backing.py`](../../tests/storage/test_linux_btrfs_backing.py)
cover many rejection cases. The native fixture in
[`test_linux_btrfs_native.py`](../../tests/storage/test_linux_btrfs_native.py)
tests real Btrfs inspection but deliberately rejects its loop-backed leaves;
passing it cannot establish successful physical recovery-storage acceptance.

This investigation ran on Windows and inspected source, tests, issue evidence,
and current primary documentation. It did not run a Linux/Flatpak candidate,
reproduce the reporter's environment, or mutate an iPod. The research document's
Markdown validation is separate from all platform acceptance above.
