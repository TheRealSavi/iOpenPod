# Application updates

iOpenPod checks its installation's update source once after the main window opens.
Supported installations are Microsoft Store, authenticated standalone GitHub
releases, and eligible Python packages checking PyPI. Native Windows package
identity plus a Store signature selects the Store
channel. Other installations do not query the Store. An identity-query failure is
reported as unavailable.

Settings > About shows the version and detected Install Channel together, with a
**Check for updates** button. Manual checks reuse the same controller and backend,
prevent concurrent requests, respect the failure retry delay, and never install
an update automatically. Results also remain visible in About after the status-bar
notice expires. Unsupported installations explain that users should use their
software manager or original download source; they never claim to be up to date.

Source labels come from runtime evidence, without a per-build channel flag:

- Windows package identity and signature distinguish Microsoft Store from a
  sideloaded Windows package.
- Linux checks iOpenPod's application identity in `/.flatpak-info`, or its Snap
  environment. Flatpak does not by itself establish Flathub origin, and Snap does
  not by itself establish a store download rather than a local package.
- A frozen macOS app uses Foundation's bundle receipt URL and an existing receipt
  file for **Mac App Store (receipt detected)**. Sandbox receipts are labeled
  **App Store testing**. This is display evidence, not cryptographic receipt
  validation, and never authorizes an update backend. A missing receipt falls
  back to **Standalone executable**; it does not prove an app was never obtained
  from the Store. This compatibility API supports the macOS 12.3 target.
- PyInstaller's runtime marker identifies **Standalone executable**. It cannot
  establish which website supplied a download.
- An installed Python distribution must own the running module in this
  interpreter's package directory and record pip or UV as its installer. Editable,
  local archive and VCS installs remain **Python / source**. Ordinary index installs
  do not record the original index, so **Python package (PyPI updates)** identifies
  the update source without claiming historical PyPI provenance. A direct wheel
  from PyPI's official file host also remains eligible after a self-update.

Mac App Store, Flatpak, and
Snap source labels do not imply built-in update support. The shared application
code can detect its packaging; native platform builds, store signatures, package
formats, and sandbox adaptation still differ as described in [Packaging](packaging.md).

## Python packages and PyPI

Eligible Python installations check PyPI at launch and through **Settings > About**.
The updater selects the newest compatible stable wheel using Python version and
platform tags. It excludes pre-releases, development builds and yanked files. A
newer release with no compatible wheel prompts a manual upgrade rather than
claiming the installation is current. Network and metadata errors remain failures.

**Update now** downloads the wheel, verifies its byte length and SHA-256, and runs
the package manager's dependency resolution without changing the environment.
The app remains usable until **Restart to install**. That action takes the existing
Library Draft and workflow guard, rechecks the selected PyPI release, saves settings
and hands off to an independent helper. After the old process exits, the helper
obtains exclusive installation ownership, installs the selected wheel and any
required dependencies, verifies the installed version and device-free runtime,
then relaunches iOpenPod automatically. Another participating iOpenPod instance
blocks replacement and is never forcibly closed. Installation may still need
network access after shutdown.

The helper targets the exact running interpreter, using an available UV executable
or that interpreter's pip. A pip user-site installation keeps its user scope.
Standard `uv tool install --python 3.12 iopenpod` installations use UV's own tool
upgrade command. Their receipt binds the tool and executable directories, and its
requirements remain unpinned so subsequent upgrades continue to work.
Ambient package-manager configuration cannot redirect the target or index. The
updater never requests elevation or bypasses externally managed environments.
Customized or pinned UV tools, pipx, Conda, recognized project lockfiles, linked paths and read-only
installations receive update notices with manual guidance instead. Optional extras
are not newly enabled by an update. Repository development commands still use UV.

Trust comes from HTTPS PyPI index metadata and its SHA-256 wheel digest, separately
from the signed GitHub release feed. Metadata is limited to 2 MiB and a wheel to
100 MiB. Wheel URLs and redirects use only the configured PyPI hosts; installation
pins the selected public wheel URL and digest. Installed package identity is
checked again before handoff and replacement. The `packaging` runtime dependency
implements Python version requirements, wheel tags and PEP 440 ordering.

Python package managers do not provide the standalone helper's rollback protocol.
A failed install can leave an environment requiring repair; the helper retains
logs under a private `python-update-*` directory in the application cache and
attempts to relaunch the app. On its next successful launch, iOpenPod reports the
retained installation failure once. If it cannot launch, use the retained
`installer.log`, `helper.log` and `relaunch.log` to repair the Python environment
with its package manager. Settings and device contents are not part of replacement.

Tests cover install ownership, source/editable exclusion, release compatibility,
yanking, hash changes, shared/exclusive ownership, guarded UI handoff, retained
failures, and real UV package and tool upgrades in disposable environments. Release acceptance
must still exercise a real published A-to-B update through the GUI on each OS,
including pip user installs, failed dependency resolution and a failed relaunch.
Existing versions without this updater need one manual upgrade. See
[ADR-0113](adr/0113-update-installed-python-packages-through-pypi.md).

## GitHub standalone releases

Frozen build metadata identifies the exact release target and installation layout;
it does not override Store or package-manager evidence. A build with no public
update key can report newer numeric GitHub tags and open their download page, but
cannot download or execute an update. Legacy mutable tags such as `BETA` are not
version identities. Existing 2.0.1 downloads need a manual bootstrap upgrade.

With keys configured, the updater verifies the signed description on the
`update-feed` branch, checks expiry, remembered sequence/version, target, layout,
protocol and minimum runtime, and derives the download URL for that exact version.
It validates the archive's signed byte length and SHA-256. Metadata is limited to
256 KiB, archives to 2 GiB, and downloads to 30 minutes with individual network
timeouts. Errors are never presented as proof that the app is current.

New releases use updater protocol 2 for the `Windows-x86_64.zip` and
`sparkle-update-macOS-<architecture>.zip` filenames. Protocol-1 clients, including
2.0.3, report that a manual update is required; install the Windows ZIP, macOS DMG,
or Linux tar.gz once to move to the new updater. New clients retain protocol-1
verification for existing signed history. See
[ADR-0114](adr/0114-distinguish-install-downloads-from-update-archives.md).

Windows and managed Linux builds download in the background after **Update now**.
The application remains usable until the user chooses **Restart to install**.
That action takes the same Library Draft and workflow guard as Store updates.
The independent helper acknowledges ownership before the app closes, waits for
the actual old process lifetime, and obtains exclusive installation ownership.
Every participating launch holds a shared OS lock. Another open instance prevents
replacement; it is never forcibly closed.

Windows accepts a ZIP containing only `iOpenPod.exe` and updates only that exact
file on a writable, fixed NTFS volume. Links, reparse points, hard-linked binaries,
changed file identities and occupied destinations are rejected. Keep the standard
executable name. Linux uses the managed archive layout described in Packaging;
it installs a fresh version directory and switches `current.json`, retaining all
previous versions. Archive links, devices and traversal paths are rejected.

The helper checks the new frozen runtime without settings or devices before
replacement. After replacement, the new window starts disabled, acknowledges a
responsive Qt event turn and waits for a durable commit before enabling device
discovery or Sync recovery. If startup fails, rollback preserves the previous
executable or version pointer, provided the expected files are still unchanged.
There is no mirroring or recursive deletion. Recovery material remains in a
private `.iopenpod-update-*` directory next to the installation; previous Linux
version directories also remain. A retry can reuse a complete Linux version only
after verifying every file again. An incomplete or changed version directory is
left for manual review; the installer will not overwrite it. Review retained
material manually before reclaiming space.

If power loss interrupts Windows between its two no-replace renames, the main EXE
may be absent. From the retained operation directory, run the embedded
`iOpenPod-update.exe --recover <absolute-operation-directory>` with all iOpenPod
instances closed. Recovery checks the signed historical release and exact old
identity and refuses to overwrite an unrelated file. Linux's retained helper uses
the same `--recover` option. Never rename an unrelated backup over the app.

macOS uses Sparkle's signed appcast and native installer. **Update now** takes the
work guard before downloading because Sparkle can install staged updates on quit.
Only the already selected version and GitHub URL are accepted; signed feed
validation must succeed. Sparkle owns verification, installation, cancellation and
relaunch. Its callbacks do not falsely report installation success. A custom
compiled bridge retains the native blocks and uses the existing Qt event loop.

### Signing and first release setup

`packaging/update-keys.json` pins the release trust key. Its matching private seed
is configured as the repository Actions secret `IOPENPOD_UPDATE_PRIVATE_KEY`.
Commit the public configuration before building the first signed release. Ed25519
release signing does not require an Apple Developer account.

The setup and publication procedure is:

1. Only when initializing release signing with no existing key, run
   `uv run --locked --group packaging python -m scripts.update_feed generate-key <private-parent-directory>`.
   Choose an existing directory outside this checkout. The command creates a new
   private directory, writes a base64 Ed25519 seed without displaying it, and pins
   its public key in `packaging/update-keys.json` if no key was configured.
2. Back up the private key securely. Set the repository Actions secret
   `IOPENPOD_UPDATE_PRIVATE_KEY` to the private file's contents. Commit the public
   key configuration before building the first updater-enabled release.
3. Build and validate a numeric `v<version>` release. Native archives embed the
   public trust configuration. macOS bundles also embed Sparkle's feed/key settings.
4. The release workflow publishes four update archives and two macOS first-install
   disk images, then calls
   **Publish signed update feed** when public keys are present. That workflow checks
   GitHub's published hashes, signs the JSON and appcasts, cross-verifies signatures
   with Sparkle's tool, and updates the feed branch without force-pushing.
5. Feed metadata expires after 45 days. Dispatch **Publish signed update feed**
   with the latest published numeric version to renew it. Older versions cannot
   replace newer history. Concurrent publication cannot overwrite another commit.

Do not publish the private seed, pass it as a command argument, or delete release
history to make a downgrade appear current. Losing or replacing the trust root
requires a reviewed migration; the current publisher has no automatic key-rotation
mode. Developer ID signing/notarization and Gatekeeper acceptance remain separate
from Ed25519 authentication. Ad-hoc Mac builds are supported during setup.

### Standalone validation

Tests cover signed metadata tampering, freshness and rollback; malicious archives;
all Linux runtime file hashes; canceled downloads; feed renewal and concurrent
publication; real Windows no-replace operations; file identity changes;
shared/exclusive locks; interruption at each publication boundary; adjacent-file
preservation; the two-step download/restart UI; and the deferred GUI health handshake.
Native builds include the independent helper and frozen smoke checks.
Before first signed publication, perform a real A-to-B update
on each shipped OS/architecture, including a readonly installation, a concurrent
instance, canceled work guard and failed new launch. Exercise both Mac architectures
and macOS 12.3; a Windows development run cannot establish Sparkle behavior.

See [ADR-0109](adr/0109-authenticate-and-isolate-github-application-updates.md).

The existing status bar and statuses popup show checking, availability, progress,
cancellation, and failures. For Store installs, **Update now** refreshes the package collection
before installation. An empty successful response means no update was reported;
exceptions are not converted into that result. The complete collection, including
optional packages, is passed to Windows. No product ID or guessed target version
is needed.

The Store may cache results. Its documented fresh-detection limits are once per
30 minutes and ten times per 24 hours. The requested launch check runs on every
launch; there is no periodic polling of the Store and no automatic failure retry.
Error retries have a 30-second in-process backoff. The pre-install query does not
bypass Store caching. This follows the requested launch policy rather than the
reference report's proposed six-hour persisted scheduling policy.

## Installation and work protection

Installation is explicitly requested by the user; Windows owns its consent
dialogs and package replacement. Windows may close or restart iOpenPod. Before
handing control to it, iOpenPod requires the Library Draft to be saved or discarded,
dialogs and the Sync Workspace to be closed, and running workflows to finish.
Settings and window geometry are saved, playback is paused, the Library Workspace
is locked, and a device-operation reservation prevents new discovery or writes.
The main workspace is disabled during installation. Cancellation or a terminal
failure restores the controls and releases the reservation without discarding work.
Playback stays paused. Existing runtime-only Playback Queue and History retain
their existing restart semantics; this feature does not add session persistence.

The main window stays alive during consent/installation. Other processes in the
same Windows session cannot own competing Store updaters. This ownership lock
does not make the entire application single-instance or coordinate work in another
running process; Store acceptance testing must include multiple instances, and
users should finish work in all instances before accepting Windows' restart prompt.

The progress bar describes the **current package**, identified in its tooltip.
Windows reports combined download/install progress as 0–80% for download and
80–100% for installation. It is never labeled as an aggregate percentage across
packages. Until native progress arrives, the bar is indeterminate. Success requires
a completed overall result and no non-completed package status. Canceled,
network/power restrictions, and unexpected results remain distinct from success.

## Extension and native integration

`app/updates/backend.py` defines typed provider, outcome, and progress contracts.
`app/updates/platform.py` selects the provider from installation evidence.
`app/updates/windows.py` owns Store projections and opaque native package objects.
`app/updates/controller.py` owns scheduling, duplicate suppression, state transitions,
and source-owned status actions. The shell supplies work-protection callbacks.
A new channel adds its detector and backend, with a display name, without changing
status widgets or exposing native package objects to the controller. Unknown
channels fail closed; there is no fallback to a different update source.

PyWinRT establishes the GUI STA before Qt startup. StoreContext is associated with
the live main-window HWND. Qt polls the retained operation's nonblocking `status`
every 100 ms and reads `get_results()` only after completion; this is local operation
observation, not another Store check. Progress callbacks copy data into a thread-safe
queue and never access Qt widgets. No extra asyncio event loop or GUI dependency
is needed. Native projection dependencies are Windows-only and included in the
PyInstaller bundle. A check times out after 60 seconds; an active install is left
under Windows' control until it reports its outcome.

The Original iOpenPod's `gui/auto_updater.py` and `StartupUpdateController` provide
the baseline for nonblocking startup checks and install-source awareness. Its
GitHub download/replacement implementation is not reused for Store packages.

## Validation

Automated tests cover startup and duplicate actions, rechecking, optional packages,
errors, cancellation, per-package result inspection, callback thread isolation,
shutdown, status button wiring, draft/work guards, and settings-save failures.
These tests use fake Store operations; development-interpreter checks establish
only the unpackaged path and the availability of the installed projections.

Release validation still needs a Store-associated installed build A with an
eligible build B: verify both Windows consent dialogs, visible progress, declined
consent, offline/service failures, low-power/network outcomes, work preservation,
and the installed version on the subsequent launch. Include multiple app
instances and every shipped Windows architecture. A sideloaded test package alone
does not establish Store update eligibility.

## Sources

- [Microsoft: Download and install package updates](https://learn.microsoft.com/en-us/windows/uwp/packaging/self-install-package-updates)
- [Microsoft: Detect app and optional-package updates](https://learn.microsoft.com/en-us/uwp/api/windows.services.store.storecontext.getappandoptionalstorepackageupdatesasync)
- [Microsoft: Request download and installation](https://learn.microsoft.com/en-us/uwp/api/windows.services.store.storecontext.requestdownloadandinstallstorepackageupdatesasync)
- [Microsoft: Package signatures](https://learn.microsoft.com/en-us/uwp/api/windows.applicationmodel.packagesignaturekind)
- [PyWinRT: Async operations](https://pywinrt.readthedocs.io/en/latest/types.html)
- [PyWinRT: Runtime interop](https://pywinrt.readthedocs.io/en/latest/api/runtime.interop.html)
- [Apple: Bundle receipt URL](https://developer.apple.com/documentation/foundation/bundle/appstorereceipturl)
- [Flatpak: Sandbox metadata](https://github.com/flatpak/flatpak/wiki/Sandbox)
- [Snap: Runtime environment](https://snapcraft.io/docs/reference/development/environment-variables/)
- [PyPI: Index API](https://docs.pypi.org/api/index-api/)
- [PyPA: Recording direct URL origins](https://packaging.python.org/en/latest/specifications/direct-url/)
- [UV: Using Python environments](https://docs.astral.sh/uv/pip/environments/)
- [pip: Configuration](https://pip.pypa.io/en/stable/topics/configuration/)

The supplied October 2, 2026 implementation report and reference adapter informed
the Store contract. Their proposed application policy and asyncio example were
adapted to this repository's Qt lifecycle and the user's requested launch behavior.
