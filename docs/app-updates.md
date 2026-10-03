# Application updates

iOpenPod checks its installation's update source once after the main window opens.
The first supported Install Channel is Microsoft Store. Native Windows package
identity plus a Store signature selects that channel. An unpackaged launch, a
developer-signed MSIX, or another platform does not query the Store or claim to be
up to date. An identity-query failure is reported as unavailable.

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
- Otherwise, PyInstaller's runtime marker distinguishes **Standalone executable**
  from **Python / source**. It cannot establish which website supplied a download.

Only Microsoft Store currently has an Update Backend. Mac App Store, Flatpak, and
Snap source labels do not imply built-in update support. The shared application
code can detect its packaging; native platform builds, store signatures, package
formats, and sandbox adaptation still differ as described in [Packaging](packaging.md).

The existing status bar and statuses popup show checking, availability, progress,
cancellation, and failures. **Update now** refreshes the Store's package collection
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

The supplied October 2, 2026 implementation report and reference adapter informed
the Store contract. Their proposed application policy and asyncio example were
adapted to this repository's Qt lifecycle and the user's requested launch behavior.
