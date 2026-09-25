# iOpenPod for Windows: support

iOpenPod is a free, open-source desktop app for managing a filesystem-accessible
iPod. All features are free. Optional donations support development and do not
unlock features. Microsoft is not the fundraiser or sponsor.

## Before you start

Use Windows 10 version 2004 (build 19041) or later, or Windows 11, on an x64 PC.
Connect a supported iPod that Windows can mount as a readable and writable drive.
The release targets classic, mini, and nano families; device-specific capabilities
vary. iPod touch, iPhone, and iPod shuffle are outside this release's scope.
A Mac-formatted iPod that Windows cannot mount is not supported by this package.
The app does not format your iPod or install filesystem drivers.

For media scanning, fingerprint matching, conversion, and Sync, install these
separate command-line tools:

- [FFmpeg and FFprobe](https://ffmpeg.org/download.html): obtain a Windows build
  linked from the FFmpeg project's download page that contains both
  `ffmpeg.exe` and `ffprobe.exe`.
- [Chromaprint](https://acoustid.org/chromaprint): obtain its Windows command-line
  tools, including `fpcalc.exe`, from the project's linked releases.

Extract each tool into a stable folder. Open Windows **Edit environment variables
for your account**, edit your user **Path**, and add the folders containing those
executables. Do not put the executable filename in Path. Close and reopen iOpenPod
afterward. You do not need to run iOpenPod as administrator. The app does not
download or install these tools. Qt's included playback libraries are separate
from these command-line programs.

In a newly opened terminal, these commands should print version information:

```text
ffmpeg -version
ffprobe -version
fpcalc -version
```

Missing tools block the affected operations; the app checks them before Sync
changes the iPod. Settings, library browsing, and supported local playback remain
available without all three command-line tools.

## Use your iPod

1. Connect the iPod and choose it in the Device Picker.
2. Browse Albums, Tracks, Playlists, and the other media pages supported by it.
3. Before extensive edits, create a Backup Snapshot in Backups. Keep another
   copy of irreplaceable media independently of the iPod.
4. Choose your computer's media folders in Sync, select the media you want, and
   inspect Review before selecting Sync Selected. Review removals deliberately.
5. Use the app's eject action after operations finish, then disconnect the cable.

Library edits save automatically by default. Enable **Draft all changes** in
Settings if you want to review and save those edits manually. Backups and draft
review complement the app's transaction protections; no tool can prevent every
hardware failure or damaged cable.

## Troubleshooting

**No iPod appears:** check whether Windows File Explorer can see the device and
its `iPod_Control` folder. Try another cable or USB port, unlock the device if
needed, and reopen the Device Picker. Never format a device merely because
Windows offers to do so. This app does not support iPhone/iPod touch protocols.

**A tool is missing:** verify all three commands above in a new terminal and
restart the app. A downloaded ZIP must be extracted first. Your Path must refer
to the directories that directly contain the executables.

**A podcast fails to refresh:** Internet access is required for podcast search,
feeds, and covers. A feed can be unavailable, moved, restricted, or malformed.
Try the feed publisher's current HTTPS RSS URL. Search uses Apple's public
directory and does not require an Apple account.

**A write or Sync is interrupted:** reconnect the same iPod and follow the app's
recovery diagnostics. Keep the recovery files and Backup Snapshots. Avoid further
manual changes to the affected files until recovery is resolved.

**Report a bug:** include the app version from Settings, Windows version, iPod
model, what you did, and what happened. Diagnostic logs normally reside in
`%LOCALAPPDATA%\iOpenPod\Logs`, though packaged Windows paths can be redirected.
Review logs and screenshots for private file paths, serial numbers, and media
information before sharing them. The app does not upload logs automatically.

## Contact, privacy, and source

- Private support and privacy requests: <johngibbons167@gmail.com>.
- Public bug reports: [iOpenPod issue tracker](https://github.com/TheRealSavi/iOpenPod/issues).
- [Privacy policy](privacy.html).
- [License, credits, and source availability](license.html).
- [Optional donations through Ko-fi](https://ko-fi.com/johngibbons).

iOpenPod is licensed under GPLv3 or later, with third-party license notices
included in the distribution. It comes without warranty to the extent permitted
by law. iOpenPod is an independent project and is not affiliated with or endorsed
by Apple Inc. iPod and iTunes are trademarks of Apple Inc.

Uninstall through Windows Settings → Apps → Installed apps → iOpenPod → Uninstall.
Your original media, exported files, iPod data, and backups stored separately may
remain. Preserve anything you need before deleting it.
