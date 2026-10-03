# iOpenPod

iOpenPod manages filesystem-accessible iPods on Windows, macOS, and Linux.

## Downloads

- **Windows x64:** extract the Windows ZIP and run the standalone `iOpenPod.exe`.
- **macOS Apple Silicon:** extract the macOS arm64 ZIP.
- **macOS Intel:** extract the macOS x86_64 ZIP.
- **Linux x64:** extract the Linux tar.gz and run `iOpenPod` inside its folder.

Windows includes its dependencies in the executable and extracts them temporarily
at launch, which adds startup time. Keep the macOS and Linux application bundles
intact. These are unsigned native downloads
(macOS uses development ad-hoc signing), not signed installers or Store packages.
macOS builds target 12.3; execution on that minimum OS still needs acceptance testing.
The Linux binary is built on Ubuntu 24.04; compatibility with older distributions
is not established. Operating-system trust prompts may apply.

FFmpeg and FFprobe are installed separately for media inspection and conversion.
Chromaprint's fpcalc is optional for acoustic matching. The app offers installation
through supported native package managers after you choose Install.

## Build information

Release downloads contain only the four native binary archives. Checksums, build
reports, Python distributions, and application and third-party source archives
are retained in the producing Actions run's `release-supporting-files` artifact.
Each component retains its own license; bundled notices remain in the application.

The native source audit currently documents Windows. Source provenance and notices
for macOS-specific dependency versions, and Linux native-library provenance, still
need completion; the retained inventories and source archives do not establish
that this review is complete. Store certification, macOS production signing and
notarization, and installed-device acceptance are separate from these automated
builds. Review `docs/packaging.md` and `docs/licensing.md` in the repository.
