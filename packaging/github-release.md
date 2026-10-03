# iOpenPod

iOpenPod manages filesystem-accessible iPods on Windows, macOS, and Linux.

## Downloads

- **Windows x64:** extract the Windows ZIP and run `iOpenPod.exe` inside its folder.
- **macOS Apple Silicon:** extract the macOS arm64 ZIP.
- **macOS Intel:** extract the macOS x86_64 ZIP.
- **Linux x64:** extract the Linux tar.gz and run `iOpenPod` inside its folder.
- **Python:** the wheel and sdist require Python 3.12 and their declared dependencies.

Keep the extracted application folder intact. These are unsigned native downloads
(macOS uses development ad-hoc signing), not signed installers or Store packages.
macOS builds target 12.3; execution on that minimum OS still needs acceptance testing.
The Linux binary is built on Ubuntu 24.04; compatibility with older distributions
is not established. Operating-system trust prompts may apply.

FFmpeg and FFprobe are installed separately for media inspection and conversion.
Chromaprint's fpcalc is optional for acoustic matching. The app offers installation
through supported native package managers after you choose Install.

## Verification and source

`SHA256SUMS` covers the attached assets. `release.json` records the source commit,
version, and asset hashes; platform inventories describe the built dependencies.
The application source archive includes build recipes. The third-party source
archive(s) contain the pinned upstream archives and notices currently recorded in
the repository. Each component retains its own license.

The native source audit currently documents Windows. Source provenance and notices
for macOS-specific dependency versions, and Linux native-library provenance, still
need completion; the attached inventories and source archives do not establish
that this review is complete. Store certification, macOS production signing and
notarization, and installed-device acceptance are separate from these automated
builds. Review `docs/packaging.md` and `docs/licensing.md` in the source archive.
