# Certification notes: iOpenPod

Prepared September 25, 2026. Copy the applicable text into Partner Center after
the final artifact and testing evidence have been assembled. This file does not
claim Microsoft certification or unperformed device testing.

## Notes for certification

```text
iOpenPod is a free, GPLv3-or-later Windows desktop application for managing a user's filesystem-accessible iPod and local media. It is built with Python and Qt and packaged as an x64 MSIX. No iOpenPod account, subscription, payment, or administrator access is required to launch or use the application.

Hardware: device management needs a compatible iPod classic, mini, or nano mounted as a readable/writable Windows drive. iPod touch, iPhone, and iPod shuffle are unsupported. The app does not install drivers or NT services. It does not format devices. Different iPod models expose different features. Please use test media and a test device for write workflows.

External dependencies: media inspection and conversion require separately installed ffmpeg.exe and ffprobe.exe. Chromaprint fpcalc.exe enables optional acoustic matching. The startup popup and Settings > Media Tools > Set Up Media Tools offer user-directed installation through WinGet (Gyan.FFmpeg and AcoustID.Chromaprint, user scope). Tools are not bundled. Clicking Install accepts the package/source agreements and permits package downloads; skipping setup keeps browsing available. App Installer must already be installed. Test this opt-in installer in the final MSIX. Standard WinGet aliases are detected without restarting. This is disclosed at the beginning of the Store description and in support instructions. The app detects missing helpers and blocks affected operations before changing the iPod. Qt's ordinary playback libraries are included. The app can launch, show Settings, browse a compatible connected library, and play supported media without all command-line tools.

Basic check: launch from Start; open Settings and switch light/dark/system appearance; open the Device Picker. A machine without an iPod should show no available device rather than fail. Close and reopen the app to verify settings persistence.

Device check: connect a test iPod, select it, browse Albums and Tracks, and play a supported track. Check Windows media controls. Create a Backup Snapshot before testing writes. Library edits save automatically; enable Draft all changes to use manual review/save. For Sync, choose local test media folders, allow scanning, select media, inspect Review, and choose Sync Selected. Check the resulting library after reconnecting. Eject only after operations finish.

Podcast check: with a supported iPod selected, open Podcasts, use Add Podcast to search Apple's public directory or add a public HTTPS RSS feed, and refresh the show. Opening podcast pages may automatically refresh subscribed feeds and request artwork. These actions require Internet access but no Apple account. Third-party feeds can change or become unavailable. The app does not provide general web browsing or user-to-user publishing/messaging.

Data: media processing, acoustic fingerprints, settings, backups, and logs are local. Podcast queries/feed/artwork requests contact Apple and feed/image hosts. Optional tool installation contacts WinGet package sources and download hosts; it does not upload media or fingerprints. Windows media controls receive current-track metadata. There is no developer analytics or automatic crash upload. A privacy policy is provided. Diagnostic logs are user-shareable only; no login credentials are needed for certification.

Payments: Settings has an optional Donate button that opens the developer's Ko-fi page in the system browser. Ko-fi and its payment providers handle confirmation and payment details over their secure transaction flow. No donation is required and no features/content are unlocked. Microsoft is not the fundraiser or sponsor. This external donation flow is declared in Product declarations.

License: GPLv3-or-later for iOpenPod, with separate third-party notices and exact corresponding-source release materials. Please use the supplied custom license terms instead of treating the application as proprietary. Attribution includes Dylan Staley's HASHAB WebAssembly implementation and thanks to libgpod/gtkpod contributors.
```

## runFullTrust justification

```text
iOpenPod is a packaged desktop application with a Python runtime and Qt GUI that must run outside AppContainer. It uses ordinary desktop filesystem APIs to read the local media folders the user selects and to manage an explicitly selected removable iPod volume. It reads device identity using Windows storage/Plug and Play APIs, uses verified staged filesystem transactions for library/media updates and backup/restore, and requests native safe ejection. It starts user-installed FFmpeg/FFprobe/fpcalc processes for local media inspection, conversion, and acoustic fingerprints. Qt provides local playback and Direct3D 11 visualizations; WinRT publishes current-track metadata to Windows media controls. These desktop APIs and user-selected removable-media workflows require runFullTrust. The executable is asInvoker, does not request administrator elevation, does not install services/drivers, and offers user-directed installation of missing media tools through WinGet. The package manager downloads, verifies, and installs the selected external packages; iOpenPod does not implement its own binary downloader. It stores mutable state in user locations, not its installed package directory.
```

## Evidence to attach to the submitted version

- The final MSIX filename, version, architecture, and SHA-256 from its build record.
- The Windows App Certification Kit report for that exact package. Earlier
  preview reports are historical evidence, not certification of a new binary.
- Installation, launch, helper-missing behavior, playback, device discovery,
  representative safe write/Sync, and uninstall results for that exact build.
- Public privacy/support pages and the matching source-and-notices download.
- Screenshot capture/provenance record and the images actually uploaded.

Do not paste private signing keys or certificate passwords into certification
notes. The public Store identity is already recorded in `store-identity.toml`.
