# Media-tool setup

iOpenPod checks FFmpeg, FFprobe, and Chromaprint's fpcalc at startup. A missing or
unusable tool opens **Set Up Media Tools**. Close the popup to continue browsing.
**Settings > Media Tools** shows each tool's status and executable path. Its FFmpeg
status also lists availability of `aac`, `aac_at`, `libfdk_aac`, and LAME
(`libmp3lame`) from the installed build's encoder list. **Check Again** refreshes
these results. **Set Up Media Tools** appears in this tab only when at least one
executable is missing; unavailable encoders do not trigger the setup button.

**Install Missing Tools** runs the selected native package manager, shows its
output, and verifies that the executables can run afterward. A successful check
does not prove that every optional FFmpeg encoder is present; Sync retains its
operation-specific encoder checks. A previously failed scan or Sync must be retried.
FFprobe supports inspection, FFmpeg prepares incoming media, and fpcalc supplies
optional acoustic matching. Missing fpcalc does not block explicit Adds or proven
Sync relationships.

| Host | Channel | Packages |
| --- | --- | --- |
| Windows x64 / ARM64 with x64 emulation | WinGet, user scope | `Gyan.FFmpeg`, `AcoustID.Chromaprint` |
| macOS Apple Silicon | Homebrew at `/opt/homebrew`, `arch -arm64` | `ffmpeg`, `chromaprint` |
| macOS Intel | Homebrew at `/usr/local`, `arch -x86_64` | `ffmpeg`, `chromaprint` |
| Debian, Ubuntu and derivatives | APT | `ffmpeg`, `libchromaprint-tools` |
| Fedora | DNF | `ffmpeg-free`, `chromaprint-tools` |
| Arch, Manjaro and derivatives | Pacman | `ffmpeg`, `chromaprint` |
| openSUSE Tumbleweed | Zypper | `ffmpeg`, `chromaprint-fpcalc` |

Only packages needed by absent executables are requested; FFmpeg and FFprobe are
one package. Dependencies are managed by the package manager. WinGet's Install
action accepts the displayed package/source agreement notice. Linux may show a
polkit administrator prompt; iOpenPod never sees the password. No repository is
added, no signature/hash check is bypassed, and no full system upgrade is requested.

Install [WinGet/App Installer](https://learn.microsoft.com/windows/package-manager/winget/)
or [Homebrew](https://brew.sh/) first if missing, then use **Check Again**.
Linux automatic setup needs `pkexec` and a desktop polkit authentication agent.
On other distributions or confined Flatpak, Snap, and macOS App Sandbox builds,
use the package-specific setup instructions; installing tools on the Host alone
does not make them accessible inside a sandbox. An existing executable that fails
its version check needs repair through its original installation channel.

Homebrew support differs from iOpenPod's macOS 12.3 baseline. Current formulae may
build from source or fail on older Intel/macOS systems. Fedora's official FFmpeg
build may not contain every conversion codec. The helper preserves these failures
and points to setup help instead of claiming compatibility.

**Stop After Current Package** waits for the running package-manager invocation
to finish, then skips remaining invocations. A manager may install several packages
in one invocation. Completed installations remain installed. The app keeps the
window open while installation is running. For a stalled system package manager,
follow that manager's recovery instructions; the helper deliberately does not kill
it midway through writes.

Executable discovery prefers the current PATH and then searches WinGet aliases,
the standard Homebrew prefixes, or native Linux executable directories. Installation
does not change iOpenPod's process PATH or write tools into the application bundle.

Frozen Linux builds restore the original `LD_LIBRARY_PATH` for external media
processes (or unset it when no original value exists). iOpenPod retains its bundled
libraries for its own use. This prevents installed FFmpeg, FFprobe, and fpcalc from
loading incompatible application libraries, which can otherwise cause startup
errors such as `undefined symbol: mpg123_open_handle64`. The same child environment
is used for version checks, file inspection, and media processing.

## Channel evidence and validation

Channel names and package contents were checked on 2026-10-01 against the
[WinGet manifests](https://github.com/microsoft/winget-pkgs),
[Homebrew FFmpeg](https://formulae.brew.sh/formula/ffmpeg),
[Homebrew Chromaprint](https://formulae.brew.sh/formula/chromaprint),
[Debian package](https://packages.debian.org/stable/sound/libchromaprint-tools),
[Fedora packages](https://packages.fedoraproject.org/pkgs/chromaprint/chromaprint-tools/),
[Arch package](https://archlinux.org/packages/extra/x86_64/chromaprint/), and
[openSUSE package](https://software.opensuse.org/package/chromaprint-fpcalc).
Homebrew's [installation requirements](https://docs.brew.sh/Installation) describe
its architecture prefixes and current OS support.

Automated tests simulate platform observations and run harmless local processes
through the actual Qt controller to cover success, failure, retry, and safe stop.
They do not install system packages. Native installation acceptance is still
required on clean Windows, both Mac architectures, each Linux family, and any
intended Store/sandbox distribution. Store disclosures must describe the installer
before submitting a build with this feature.
