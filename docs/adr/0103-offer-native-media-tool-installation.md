# Offer native media-tool installation

- Status: Accepted
- Date: 2026-10-01
- Amends: ADR-0081's prohibition on initiating installation

The owner requested a helper popup that installs missing FFmpeg, FFprobe, and
Chromaprint's fpcalc on Windows, Apple Silicon and Intel macOS, and Linux. iOpenPod
now checks these tools outside the GUI thread at startup and offers a skippable
setup dialog. Settings > Media Tools displays tool and FFmpeg encoder status and
offers the setup dialog when an executable is missing. Only the user's Install
action starts package installation. The executables remain separate from the
iOpenPod distribution; Qt's playback libraries remain unchanged.

Use native package managers instead of maintaining an executable download/update
and archive-extraction system. WinGet selects the exact `Gyan.FFmpeg` and
`AcoustID.Chromaprint` packages from its `winget` source in user scope. Homebrew
uses its standard architecture-specific prefix and an explicit `arch` invocation.
Linux selects packages by distribution identity: APT for Debian/Ubuntu families,
DNF for Fedora, Pacman for Arch families, and Zypper for openSUSE Tumbleweed.
Linux administrator approval belongs to polkit; the application never collects
passwords. Package-manager integrity checks remain enabled. Do not add repositories,
run a system-wide upgrade, or overwrite an existing but broken executable.

Missing package managers, unsupported distributions, and confined packages get
setup instructions and an official/channel help link. Bootstrapping a package
manager remains an explicit prerequisite outside the application. Homebrew's OS
support and available bottles do not establish tool compatibility with every
macOS 12.3 system supported by iOpenPod; older systems may build from source or
require manual setup. Fedora's `ffmpeg-free` uses its official repositories and
may lack encoders needed by a particular conversion.

Installation runs asynchronously with bounded visible logs. A stop request waits
for the current package-manager invocation to finish, skips remaining invocations,
and keeps installed packages. Closing the app during installation requests this
safe stop rather than terminating a package mutation. Each attempt ends with a
fresh executable/version check, including partial failures. Tool discovery is
shared by inspection, Sync, fingerprints, and Synesthesia, and includes standard
WinGet/Homebrew locations so new installs work without a restart or global PATH
changes. Existing PATH choices take precedence. Retrying a scan or Sync remains
a user action; fpcalc's optional gating from ADR-0084 is unchanged.

See [Media-tool setup](../media-tools.md) for channels, prerequisites, and the
validation limits of this implementation.
