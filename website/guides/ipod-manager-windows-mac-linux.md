---
layout: guide
title: Free iPod manager for Windows, Mac & Linux | iOpenPod
description: Choose an iOpenPod download for Windows, Apple Silicon, Intel Mac, or Linux. Compare installation routes and requirements for managing an iPod without iTunes.
heading: Your iPod. Your choice of computer.
lead: iOpenPod is a free, open-source iPod manager for Windows, macOS, and Linux. Native downloads include the application runtime, so you do not need to install Python separately.
breadcrumb_title: Windows, Mac & Linux
body_class: iop2-page guide-page
permalink: /guides/ipod-manager-windows-mac-linux/
related_guides:
  - /guides/apple-devices-itunes-ipod-windows/
  - /guides/sync-ipod-without-itunes/
  - /guides/ipod-compatibility/
---

## Choose your installation route

| Computer | Available route | Requirement to check |
| --- | --- | --- |
| Windows | Native x64 ZIP or Microsoft Store | Windows 10 or 11; native in-app updates need a writable folder on a fixed NTFS drive. |
| Mac with Apple Silicon | Native arm64 DMG | The build targets macOS 12.3 or later; testing on 12.3 remains pending. |
| Intel Mac | Native x86_64 DMG | Use the Intel download, not the Apple Silicon package; the same macOS validation limit applies. |
| Linux x64 | Native tar.gz archive | Built on Ubuntu 24.04; requires glibc 2.39 or later plus desktop graphics and audio libraries. |

All available downloads are linked from the [download directory]({{ '/#install' | relative_url }}).
Mac App Store, Flathub, and Snap Store remain planned. Do not treat a packaging
configuration in the repository as an available store release.

## Windows: portable download or Microsoft Store

The native ZIP contains `iOpenPod.exe`. Extract it to a writable folder on a fixed
NTFS drive and keep its filename so the updater can replace it. The Microsoft
Store route installs and updates through the Store.

Use the [Windows installation steps]({{ '/install-help/#native-windows' | relative_url }})
for the current filename and recommended location, or visit the
[Microsoft Store listing](https://apps.microsoft.com/detail/9P2LXCHHWLG9).

## Mac: select the DMG for your processor

Choose the Apple Silicon or Intel DMG, drag iOpenPod into Applications, and run
that installed copy. The ZIP archives labeled `sparkle-update` are for the updater,
not manual first installation.

Current downloads are ad-hoc signed and not notarized. The
[Mac installation guide]({{ '/install-help/#native-macos' | relative_url }})
explains the current launch guidance and links to Apple's documentation. The
minimum build target is not a claim that every supported Mac configuration has
completed acceptance testing.

## Linux: check the runtime before downloading

The native Linux app needs glibc 2.39 or later and a working desktop graphics and
audio environment. Compatibility with older distributions is not established.
Keep the complete extracted application folder together and use its top-level
launcher; its supporting files are part of the installation.

Read the [Linux setup steps]({{ '/install-help/#native-linux' | relative_url }}).
iOpenPod uses its own iPod database implementation, so a separate libgpod
installation is not required. The computer must still mount and access the iPod's
filesystem; follow any device-identification setup offered by the app.

## Prefer a Python package?

iOpenPod is also published on [PyPI](https://pypi.org/project/iopenpod/).
The [uv installation route]({{ '/install-help/#python' | relative_url }}) manages
the app's Python environment. It is an alternative installation method, not a
guarantee that an older operating system meets the application dependencies.

## Before you add music

Check [iPod compatibility]({{ '/guides/ipod-compatibility/' | relative_url }}), set up
FFmpeg and FFprobe for inspection and conversion, and capture a Backup Snapshot.
Then follow the [first-Sync guide]({{ '/guides/sync-ipod-without-itunes/' | relative_url }}).
The workflow lets you select media folders and review changes without iTunes.
