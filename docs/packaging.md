# Packaging and distribution

iOpenPod targets the Mac App Store, Microsoft Store, and Linux software stores
through Flatpak/Flathub and Snap. Version tags publish native downloads through
GitHub Releases; branch builds produce **packaging candidates**. These are not
approved store submissions. Store accounts, production signing, and sandbox/device
acceptance testing remain separate gates. See ADR-0104 for the GitHub release policy.

iOpenPod is GPL-3.0-or-later. Complete the [distribution licensing requirements](licensing.md),
including corresponding source and third-party notices, before public release.

## Build inputs

Run from a clean checkout using Python 3.12 and UV. On Windows and Linux:

```shell
uv sync --locked --group packaging
uv build --no-build-isolation
uv run --locked --group packaging python scripts/check_wheel.py
# Windows: build the audited native audio dependency before freeze (see below).
uv run --locked --group packaging python scripts/package_app.py freeze
uv run --locked --group packaging python scripts/package_app.py archive
```

On macOS, use the [controlled Mac environment](#macos--mac-app-store) below so a
newer builder selects wheels compatible with the declared minimum OS.

The `packaging` dependency group locks PyInstaller and Hatchling separately from
runtime dependencies. Build on each target OS and architecture; PyInstaller does
not cross-compile. Use a fresh environment without the optional `synesthesia-gpu`
extra. The native baseline includes ordinary analysis but excludes Demucs, Torch,
and Torchaudio; optional GPU analysis needs a separate packaging/size decision.

On Windows the builder limits DLL discovery to Python and Windows system paths.
Before `freeze`, run `uv run --locked python -m scripts.build_windows_sndfile` to
build the pinned, audited native audio library. Portable build tools are verified
and stored under `build/`; the command does not install system software.
This prevents unrelated installed tools from contributing incompatible DLLs (for
example, a third-party `icuuc.dll` with symbols different from Windows' ICU API).
The executable explicitly declares PerMonitorV2 DPI awareness and runs as the
current user. The bundle omits unused Tcl/Tk and scikit-learn sample/test datasets;
the analysis runtime remains included. Windows CI checks the embedded executable
manifest and collected payload with `scripts/check_windows_bundle.py`.
Windows uses PyInstaller one-file mode: `dist/iOpenPod.exe` embeds its Python
runtime, libraries, resources, and notices (ADR-0108). The checker reads the
embedded archive as well as the executable manifest. Launch extracts the runtime
to a temporary directory, adding startup time, and cleans it up on normal exit.

`pyproject.toml` owns the version. Native versions currently require three numeric
components; MSIX appends `.0` as required for Store uploads. Tags must exactly match
`v<version>`. The macOS bundle retains Original iOpenPod's `com.iopenpod.app`;
Linux retains `io.github.therealsavi.iOpenPod`. Confirm ownership of those identities
in the store accounts before reserving a new listing. The Windows identity is
supplied from Partner Center and saved in `packaging/windows/store-identity.toml`,
never invented by the build script.

The copied Original iOpenPod icon is used in the application, executable, bundle,
desktop entry, and Store tiles. See its [provenance](../src/iOpenPod/assets/icons/README.md).
The available master is 256 pixels. ICNS includes larger converted representations;
the original high-resolution artwork is still needed for final store art review.

Outputs are under ignored `build/` and `dist/`. Store staging refuses to overwrite
an existing staging directory so obsolete files cannot silently enter a package.
Remove that specific generated directory before staging again. Windows archives
contain only `iOpenPod.exe`; MSIX staging copies that same executable to `app/`.
macOS ZIPs preserve `.app` symlinks using `ditto`. Each macOS DMG copies that same
signed app with `ditto` into a read-only image beside an `/Applications` shortcut.
Finder can lag behind a successful mount. Layout retries its object-not-found
error (`-1728`) up to ten attempts, two seconds apart, with a 60-second timeout per
script invocation. Other failures stop immediately; the image is detached before
the error propagates, and conversion and checksum generation require a saved layout.
The ZIP stays available for Sparkle's signed appcast; the DMG is for a first manual
drag to Applications. Linux archives preserve
executable modes and dereference bundled library symlinks. Their managed root has
the stable `iOpenPod` launcher, `installation.json`, `current.json`, and
`versions/<version>/` containing the onedir runtime. Start the root launcher.
Store staging continues to use the ordinary onedir build. Each archive gets SHA-256.

Native download names use `x86_64` consistently, including Windows:

- `iOpenPod-<version>-Windows-x86_64.zip`
- `iOpenPod-<version>-Linux-x86_64.tar.gz`
- `iOpenPod-<version>-macOS-<architecture>.dmg` for manual installation
- `iOpenPod-<version>-sparkle-update-macOS-<architecture>.zip` for Sparkle only

Mac architectures are `arm64` and `x86_64`. Publish only the new names, without
legacy aliases. Signed update metadata uses updater protocol 2 to select these
names; protocol-1 clients need one manual upgrade. See
[ADR-0114](adr/0114-distinguish-install-downloads-from-update-archives.md).

Standalone builds embed update identity and public trust keys from
`packaging/update-keys.json`. Windows embeds a separately frozen helper; Linux
ships it as the stable launcher and within each runtime for installation/recovery.
The helper is independent of Qt and uses its own onefile extraction lifetime.
Do not clean a user's installation directory when upgrading.

macOS packaging downloads the SHA-256-pinned Sparkle 2.10.0 SDK, preserves framework
symlinks and full notices, compiles the Objective-C bridge, and signs the nested
components before the app. Ad-hoc signing is the default. A configured
`IOPENPOD_CODESIGN_IDENTITY` is optional; notarization is still a separate release
step. Sparkle signing does not require Apple Developer ID. See
[Application updates](app-updates.md#signing-and-first-release-setup) for key custody,
the first manual upgrade, feed publication and expiry renewal. Native updater
acceptance does not change ADR-0106's manual-only Health policy.

## User-installed media tools and bundled libraries

Users install **FFmpeg**, **FFprobe** (provided with FFmpeg), and **Chromaprint's
fpcalc** separately. iOpenPod does not bundle these executables. Its opt-in setup
helper invokes native package managers to download and install missing tools.
Normal native builds do not require them on the build machine and need no special
preview flag. The earlier `--media-tools` and `--preview` options have been removed.
See [ADR-0103](adr/0103-offer-native-media-tool-installation.md) and
[Media-tool setup](media-tools.md) for channels and prerequisites.

The frozen app preserves the user's PATH. Shared discovery also finds standard
WinGet aliases and Homebrew prefixes, allowing setup without a restart. Media
inspection requires FFprobe; incoming Track preparation checks FFmpeg/FFprobe and
needed encoders before device changes. fpcalc supports optional acoustic matching.
Startup checks tools and offers setup without requiring installation to browse.
Some Synesthesia decoding also uses external FFmpeg. Store descriptions and setup
help must disclose the affected features, external installation, and opt-in network
access through package managers. Confined builds do not offer Host installation.

Qt's FFmpeg **playback libraries remain bundled**, as explicitly selected by the
owner. They are distinct from `ffmpeg.exe`/`ffprobe.exe` and do not satisfy the Sync
tool requirement. Keep their applicable licenses, attribution, and corresponding
source in the distribution review. See [Qt Multimedia deployment](https://doc.qt.io/qt-6/qtmultimedia-index.html#the-ffmpeg-backend).

Windows startup loads these bundled libraries by absolute path before Qt selects
its Playback Backend. [MSIX's DLL search](https://learn.microsoft.com/en-us/windows/win32/dlls/dynamic-link-library-search-order#search-order-for-packaged-apps)
does not use PySide6's PATH additions;
without this step, Qt can silently fall back to Windows Media Foundation and
reject Apple Lossless Tracks despite the FFmpeg DLLs being present. This applies
to both directory bundles and the extracted one-file runtime. The smoke test now
decodes a generated in-memory audio sample through Qt's FFmpeg buffer output,
without playing sound or requiring an audio endpoint. Installed-package validation
must run that same smoke test under the package identity; a portable launch alone
does not exercise the Store's loader rules.

Frozen analysis code uses Numba's per-user compilation cache, keeping installed
bundles read-only; this cache contains compiled code, not Track Analysis results.
Windows CI rejects bundled FFmpeg/FFprobe/fpcalc executables and obsolete private
`media-tools` directories while permitting Qt's playback DLLs.

`build/packaging/licenses/` contains the application license and grant,
acknowledgements, icon permission, HASHAB notice, installed
runtime dependency inventory, and dependency license files. `licenses/upstream/`
adds the full source-derived notices, source manifest, and native-library audit
materials. The native bundle excludes unused Qt PDF and Virtual Keyboard plugins.
Notice collection excludes Python code, native binaries, and dSYM debug bundles,
including PyObjC's copying tests whose names otherwise match license filenames.
Wasmtime's native library is collected with an explicit `*.so` pattern on Linux
because its `_libwasmtime.so` name does not match PyInstaller's default `lib*.so`.
The bundle preserves the package-relative platform directory used by its loader.
Windows libsndfile is rebuilt from pinned source with external codecs disabled;
the package includes its exact build record. See
[`packaging/third-party`](../packaging/third-party) for regeneration instructions.
FFmpeg codec/build options can change redistribution terms, so future dependency
updates require refreshing this evidence.
See [Qt licensing](https://doc.qt.io/qtforpython-6/) and
[FFmpeg legal information](https://ffmpeg.org/legal.html).

## Windows / Microsoft Store

The prepared listing, six authentic screenshots with synthetic data, privacy,
support, license pages, and certification notes are in
[`packaging/windows/store`](../packaging/windows/store). The Store-kit assembler
produces a package-specific release record, matching source archives, checksums,
and a deployable static site. It records pending account/publication and installed
validation fields explicitly; it does not invent an IARC rating or publish an app.

`packaging/windows/test-installed-package.ps1` verifies locally signed, hash-pinned
packages through installation, real app activation, upgrade, uninstallation, and
the Windows App Certification Kit. It refuses an existing user installation and
removes only its own temporary installation and added certificate trust. Test
certificates are not production credentials or Store upload requirements.

Put the external-tool requirement at the **beginning** of the Store description,
as required by [Store policy 10.2.4](https://learn.microsoft.com/en-us/windows/apps/publish/store-policies#102-security).
Suggested opening text:

> Media inspection and conversion require separately installed FFmpeg (including
> FFprobe); Chromaprint's fpcalc enables optional acoustic matching. These tools
> are not bundled. The setup helper can install missing packages through WinGet
> after you choose Install, or you can use your own installation on PATH.

Include the setup steps in certification notes so reviewers can test Sync.

Build on Windows. The public identity supplied by the listing owner is saved in
[`store-identity.toml`](../packaging/windows/store-identity.toml):

| Partner Center field | Value |
| --- | --- |
| Package/Identity/Name | `TheRealSavi.iOpenPod` |
| Package/Identity/Publisher | `CN=FB5CD908-9397-4B6A-B014-49E83AB6CE1A` |
| Package/Properties/PublisherDisplayName | `TheRealSavi` |
| Store ID | `9P2LXCHHWLG9` |
| Package Family Name (PFN) | `TheRealSavi.iOpenPod_gncxjke9mmtsj` |
| Package SID | `S-1-15-2-3217256207-1113745441-394109889-2428521660-2671115195-2036667267-1488106813` |

These values are not credentials. Signing keys remain outside the repository. The
Store ID identifies the listing; it, the PFN, and the Package SID are reference
metadata rather than MSIX manifest fields. Stage the native bundle with the saved
identity:

```powershell
uv run --locked --group packaging python scripts/package_app.py msix-stage
```

Explicit overrides remain available for a separately reserved listing:

```powershell
uv run --locked --group packaging python scripts/package_app.py msix-stage --identity 'PARTNER_CENTER_PACKAGE_NAME' --publisher 'CN=PARTNER_CENTER_PUBLISHER_ID' --publisher-display-name 'YOUR_PUBLISHER_DISPLAY_NAME'
```

Run Windows SDK `MakeAppx.exe` in a developer shell:

```powershell
MakeAppx.exe pack /d build\msix /p dist\iOpenPod.msix
```

When the SDK is not installed, Microsoft's standalone
[`Microsoft.Windows.SDK.BuildTools` NuGet package](https://www.nuget.org/packages/Microsoft.Windows.SDK.BuildTools/10.0.28000.2705)
also supplies MakeAppx. Extract that build-only package outside the application
payload; version `10.0.28000.2705` places the x64 tool at
`bin/10.0.28000.0/x64/makeappx.exe`. This does not install the Windows App
Certification Kit. Leave MakeAppx validation enabled. A successful pack checks
manifest structure and referenced assets, but does not establish installed-app or
Store compatibility.

The template declares a full-trust desktop application (`runFullTrust`) and does not
request administrator execution. The version and architecture come from the build.
Sign sideload test packages using a certificate matching the manifest Publisher;
keep keys and certificates outside this repository. Use Partner Center's package
identity and submission process for the Store-signed release. Validate with the
Windows App Certification Kit and test install, update, uninstall, settings
retention, media keys, device discovery, safe eject, and recovery under package
identity. The manifest does not prove Store approval for a restricted capability.
See [Microsoft's desktop MSIX guide](https://learn.microsoft.com/en-us/windows/msix/desktop/desktop-to-uwp-manual-conversion).

Always inspect the Certification Kit's XML `OVERALL_RESULT` and individual `TEST`
results. A successful process exit and successful task execution do not mean every
test passed. For Desktop Bridge packages, optional archive and blocked-executable
tests are informational. Review their actual findings; do not strip required Python,
Qt, or analysis libraries merely because an API or string was flagged. The current
Windows media subprocess calls pass argument lists to user-installed
FFmpeg/FFprobe/Chromaprint without a command shell. Test the installed MSIX with the
tools present and absent, including discovery through the user's PATH, actionable
failure messages, and an unchanged iPod after a missing-tool failure.
See [Microsoft's Desktop Bridge tests](https://learn.microsoft.com/en-us/windows/uwp/debug-test-perf/windows-desktop-bridge-app-tests).
A report run without application deployment does not cover installed-app behavior.

## macOS / Mac App Store

The native build produces `dist/iOpenPod.app`. The default is an ad-hoc signed
development candidate, not a Gatekeeper-ready public release or App Store package.
The archive command also produces an architecture-specific DMG containing
`iOpenPod.app` and an Applications shortcut. Users open the DMG and drag the app
onto that shortcut. The matching ZIP remains the Sparkle update archive. Native CI
mounts each image, checks its layout and app signature, and compares its executable
with the frozen app. A DMG does not replace Developer ID signing or notarization.
The standard native candidate targets **macOS 12.3 or later**. The workflow builds
separate Apple Silicon (`macos-14`) and Intel (`macos-15-intel`) candidates. These
newer runners establish buildability and launch on their own OS; **execution on
macOS 12.3 on each architecture remains pending acceptance**.

### Build for macOS 12.3

Use UV **0.12.7**, whose managed Python manifest supplies the inspected runtime.
`tool.iopenpod.packaging` in `pyproject.toml` owns the minimum OS and packaging
Python version. Prepare the environment on the architecture being built:

```shell
uv run --no-project --managed-python --python 3.12 python scripts/sync_macos_build.py
uv build --no-build-isolation
uv run --no-sync python scripts/check_wheel.py
uv run --no-sync python scripts/package_app.py freeze
uv run --no-sync python scripts/check_macos_bundle.py
uv run --no-sync python scripts/package_app.py archive
```

The preparation script selects UV-managed Python 3.12.14 and explicit
`aarch64-apple-darwin` or `x86_64-apple-darwin` tags with
`MACOSX_DEPLOYMENT_TARGET=12.3`. It installs locked third-party wheels, the editable
application, and the packaging group without dev tools or optional extras.
Setting the deployment environment variable alone does not constrain UV's host
wheel selection. Subsequent commands use **`--no-sync`** to retain the selected
artifacts. Re-run the preparation script after any ordinary project sync or run
that changes the environment.

macOS pins PySide **6.9.3**; Windows and Linux retain the existing 6.11.2 minimum.
Intel macOS selects Numba **0.62.1**, llvmlite **0.45.1**, and NumPy **2.3.5**.
Apple Silicon retains the newer numerical stack. Small Qt adaptations preserve
row filtering and QRhi buffer uploads with either binding line. The existing
compiled shaders are retained. These choices preserve the standard app's feature
set; the optional `synesthesia-gpu` extra is outside this compatibility target.
See [ADR-0094](adr/0094-target-macos-12-3-with-platform-specific-native-dependencies.md)
and the [binary investigation](research/macos-compatibility.md).

CI prepares the same environment with `--with-checks` for the full test suite in
Health. The separate native build installs it without check tools before freezing. The
`packaging-checks` group supplies Pytest without the other dev tools, including
Mypy, whose locked version lacks an Intel macOS wheel.

Development type checking has a separate limitation: Qt 6.9's generated stubs omit
public fields and misdescribe decorators and nullable results used by existing
code. Mypy passes with the current Windows bindings but reports errors against the
older stubs. Correcting those annotations remains work for a Mac development
environment; the native build does not disable the project's type-checking rules.
Health runs the authoritative Mypy check on Windows and independently runs runtime
tests on all four native targets, including both Mac architectures.

The bundle check compares `Info.plist` with the configured target and reads every
unique Mach-O file, including all universal slices. It rejects a missing build
architecture, non-macOS platform, missing deployment declaration, or minimum newer
than 12.3. `build/packaging/macos-compatibility.json` records hashes and deployment
targets and is retained with the CI candidate. No binary headers are rewritten.

Before claiming verified 12.3 support, exercise both native candidates on 12.3:
launch, playback, standard analysis, Synesthesia rendering through Metal, system
media integration, device discovery, and safe Storage workflows. The binary check
does not prove that all imported system symbols exist on that OS. User-installed
FFmpeg, FFprobe, and fpcalc must also support the user's OS. Complete corresponding
source and source-derived notices for Qt 6.9.3 and Intel's older numerical versions
before public distribution; the existing native evidence is for Windows.

### Signing and App Store acceptance

`packaging/macos/app-store.entitlements.plist` is a starting entitlement set for
sandbox investigation. `helper.entitlements.plist` is the inherited sandbox profile
for bundled executable helpers. Neither is automatically applied to every binary:
main app and helper roles need separate inside-out signing. The build accepts
`IOPENPOD_CODESIGN_IDENTITY` and `IOPENPOD_ENTITLEMENTS` for controlled signing
experiments; these do not implement an App Store signing pipeline. `CFBundleVersion`
now matches the numeric project version so Sparkle and signed JSON select the
same release.

Before an App Store submission:

- Implement native user-selected folder grants and security-scoped bookmark lifetime
  management in Storage, including Host Media Library folders, Backup Archives,
  export locations, and the selected iPod. Saved paths and Volume Identity alone do
  not preserve sandbox authorization across launches.
- Verify native discovery/IOKit observations and safe removal within App Sandbox.
  The current `diskutil` subprocess adapter cannot be assumed to work there. Do not
  bypass Storage checks or silently claim successful eject on a denied operation.
- Validate Wasmtime and Numba executable-memory requirements under the actual
  signed sandbox/hardened-runtime configuration. Determine supported entitlement
  or non-JIT alternatives before claiming HASHAB and analysis support.
- Sign every bundled native extension/library. Audit the Qt plugins for App Store
  compatibility and use the current Apple SDK. Determine a permitted way to invoke
  user-installed media tools within App Sandbox; Host PATH alone does not establish
  executable access or App Store acceptance.
- Configure the real Team ID, App ID, provisioning profile and distribution and
  installer certificates; validate the signed sandboxed `.app`, then produce the
  submission `.pkg` with Apple's distribution tooling. Complete privacy, export
  compliance, age-rating, screenshots, and support information in App Store Connect.

App Sandbox is mandatory for this target. The current application has path-based
access and no persistent sandbox grants, so enabling the entitlement alone is not
a supported release. See [Apple's sandbox overview](https://developer.apple.com/documentation/security/protecting-user-data-with-app-sandbox),
[persistent file access](https://developer.apple.com/documentation/security/accessing-files-from-the-macos-app-sandbox),
and [Qt macOS deployment](https://doc.qt.io/qt-6/macos-deployment.html).

## Linux stores

Build on Linux, then create the shared install tree:

```shell
uv run --locked --group packaging python scripts/package_app.py linux-stage
desktop-file-validate packaging/linux/io.github.therealsavi.iOpenPod.desktop
appstreamcli validate --no-net packaging/linux/io.github.therealsavi.iOpenPod.metainfo.xml
```

The tree includes the launcher, native bundle, desktop entry, AppStream metadata,
and icon. Native distribution maintainers can reuse these files for DEB/RPM packages,
but this repository does not yet claim Debian/Fedora repository acceptance.

### Flatpak / Flathub

The local candidate uses Freedesktop 25.08 and the generated native tree:

```shell
flatpak remote-add --user --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
flatpak install --user flathub org.freedesktop.Sdk//25.08 org.freedesktop.Platform//25.08
flatpak-builder --user --install --force-clean --repo=build/flatpak-repo build/flatpak packaging/linux/flatpak.json
flatpak run --env=QT_QPA_PLATFORM=offscreen io.github.therealsavi.iOpenPod --smoke-test
flatpak build-bundle build/flatpak-repo dist/iOpenPod.flatpak io.github.therealsavi.iOpenPod
```

Permissions explicitly cover audio, graphics, network Podcast feeds, home media and
Backup Archives, standard removable mount locations, read-only udev observations,
UDisks2 eject, and MPRIS. They do not grant raw devices or a host-shell escape.
The Host mounts the iPod. Verify discovery's mount/device correlation inside the
sandbox; bind-mounted paths and hidden block devices may require a Storage adapter.
The native Linux identity setup remains a separately explained Host operation.

This local-directory manifest is not a Flathub submission. Replace generated local
sources with a reproducible, pinned upstream-source build and offline dependency
inputs, including UV/Python 3.12. Add release metadata,
Linux screenshots and stable source URLs, verify app-ID ownership, and pass Flathub
manifest/AppStream lint and permissions review. The manual CI workflow produces a
preview `.flatpak` without bundled media tools and never uploads it to a store.
Host-installed executables are not automatically available inside Flatpak. Resolve
and test a permitted user-installed tool integration before advertising Sync in a
Flathub release; the current manifest does not implement one.
See [Flatpak permissions](https://docs.flatpak.org/en/latest/sandbox-permissions.html)
and [Flathub requirements](https://docs.flathub.org/docs/for-app-authors/requirements).

### Snap Store

Copy `packaging/linux/snapcraft.yaml` to `snap/snapcraft.yaml` in a disposable build
checkout after `linux-stage`, then run `snapcraft` on an amd64 Linux builder. It
stages the app and desktop runtime on core24, without FFmpeg/Chromaprint executable
packages. This is a
strict-confinement development candidate; it is not marked stable.

As with Flatpak, installing tools on the Host does not automatically make them
executable from a confined Snap. User-installed tool integration remains unresolved
for this channel. Do not add the tools back as staged packages to conceal that gap.

Test `home`, `removable-media`, `hardware-observe`, and `udisks2` connections and
read-only udev identity access. The latter three are not automatically connected by
default; Store auto-connection review may be required. Check audio, graphics,
identity correlation, disconnect/reconnect, and eject on real installed packages.
Do not switch to classic confinement merely to hide permission failures. Record any
needed Storage adaptation first. See [Snap removable media](https://snapcraft.io/docs/reference/interfaces/removable-media-interface/),
[hardware observation](https://snapcraft.io/docs/reference/interfaces/hardware-observe-interface/),
and [UDisks2](https://snapcraft.io/docs/reference/interfaces/udisks2-interface/).

## Verification and publication

Both source and installed launchers support `--version` and `--smoke-test`. The latter
imports the GUI startup graph (including scrobbling and its credential-vault
adapter), and checks Qt icon/image/SVG/multimedia loading, compiled shaders, the
udev resource, native HASHAB execution, lazy audio-analysis imports, and the
platform's dynamically loaded system-media bindings. It does not create settings,
discover devices, or write to an iPod. `--smoke-test-report /absolute/file.txt` writes
diagnostics even for a Windows executable without a console.

Run the frozen smoke test outside the checkout on a machine without Python.
Health checks the lockfile, formatting, linting, typing, and the complete test suite.
It runs only through explicit dispatch: **Actions → Health → Run workflow**.
Pushes, pull requests, releases, and Flatpak builds never start Health automatically.
Release and Flatpak workflows do not call or wait for Health; maintainers choose
when to run it separately (ADR-0106). The native CI jobs
exercise Windows x64, macOS arm64 and x86_64, and Linux x64 and validate wheel
contents. Native environments exclude dev tools and optional GPU dependencies.

Pushing a tag that exactly matches `v<version>` in `pyproject.toml` automatically
builds and publishes a public GitHub Release, then publishes the same version to
PyPI. A manual Build and release run on a version tag does the same. To create the
tag through GitHub, open **Actions → Build and release → Run workflow**, select
**main**, and enable **Publish to GitHub and PyPI**.
The workflow reads the version from `pyproject.toml`, builds that exact commit,
and creates its tag only after native builds and release assembly pass.
An existing tag must already point at that commit; tags are never moved. A manual
branch run with publication unchecked only retains candidate artifacts, as do pull
requests. Other branches cannot request publication. No workflow publishes to a
Store.

Publication waits for all four builds and their frozen smoke tests. It verifies
each native archive and macOS disk image checksum, collects dependency inventories
and Mac compatibility reports, and assembles the wheel and sdist from the Windows
build, application source snapshot, hash-verified pinned third-party sources,
`release.json`, and `SHA256SUMS`. These supporting files are retained in the
producing Actions run's `release-supporting-files` artifact, subject to Actions
artifact retention, rather than attached to the GitHub Release (ADR-0107).
Only the Windows ZIP, two macOS ZIPs, two macOS DMGs, and Linux binary tar.gz are
uploaded to the release (ADR-0110). Bundled license files remain inside the app.
The source snapshot excludes the private fixtures listed in
`scripts/prepare_store_kit.py`; the Python sdist excludes them too, and the
publication assembler rejects their presence. The six native downloads upload to
a draft before the workflow makes it public. Release notes combine
`packaging/github-release.md` with GitHub's generated change list. Publication
receives `contents: write`; the build and test jobs only receive read access.

The separate `publish-pypi` job waits for the GitHub Release to succeed, then
downloads the `pypi-distributions` artifact from that same run. It contains only
the assembled Windows wheel and sdist, already checked by the native build and
release assembler. The job uses UV with PyPI Trusted Publishing and receives only
`id-token: write`; it does not check out or rebuild application code. PyPI and the
signed update feed publish independently after the GitHub Release (ADR-0112).

### PyPI setup and recovery

Before the first PyPI-enabled release, configure the existing `iOpenPod` project's
[Trusted Publisher](https://pypi.org/manage/project/iopenpod/settings/publishing/)
with these GitHub values:

| Field | Value |
| --- | --- |
| Owner | `TheRealSavi` |
| Repository | `iOpenPod` |
| Workflow filename | `release.yml` |
| Environment | `pypi` |

Create the matching `pypi` environment in GitHub repository settings. If deployment
branch/tag restrictions are enabled, allow both `main` (manual publication) and
version tags matching `v*`. No PyPI API-token secret is needed. See
[PyPI's setup guide](https://docs.pypi.org/trusted-publishers/adding-a-publisher/).

If PyPI publication fails after GitHub succeeds, fix the publisher configuration
or upload problem and rerun only the failed `publish-pypi` job while its artifact
is retained. Do not rerun successful builds or recreate the GitHub Release. UV
skips files already on PyPI only when their contents match exactly, so a partial
upload can resume with the original artifact. Changed files require a new version;
see [UV's publishing guide](https://docs.astral.sh/uv/guides/package/#publishing-your-package).

### Release checklist

Before tagging, update the version and lockfile together and review
`packaging/github-release.md`. Complete the source/licensing review for the actual
platform binaries; the existing Windows evidence is not a completed Mac or Linux
audit. Run a manual branch build to inspect candidates first. No signing credentials
are required for the current unsigned downloads, and they must not be described as
signed installers or Store-approved builds.

The workflow refuses to replace an existing release. If an upload fails, inspect
the unpublished draft, delete that incomplete draft without deleting its tag, then
rerun the failed publication job. Keep successful public releases immutable; ship
a new version for corrections. Do not reuse an old release tag for new code.

Before Store submission, also test actual playback, Sync with user-installed tools, backup and
restore, disconnect recovery, and safe eject in each **installed store package**.
Use virtual Volumes for automated mutation tests; physical iPod acceptance requires
an explicitly selected test device. Complete package signing, store metadata,
privacy/support URLs, notices and native platform acceptance before Store release.
