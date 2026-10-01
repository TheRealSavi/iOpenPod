# Require user-installed command-line media tools

> ADR-0103 amends installation: users may now explicitly install missing tools
> through a native package-manager helper. Executables remain unbundled.
>
> ADR-0084 amends operation gating: FFmpeg/FFprobe are required for incoming Track
> preparation; unavailable fpcalc limits acoustic matching but does not block
> scanning, explicit Adds, or previously proven Sync relationships.

- Status: Accepted
- Date: 2026-09-25
- Supersedes: ADR-0079's external media-helper bundling requirement

The owner wants users to install FFmpeg, FFprobe, and Chromaprint's fpcalc rather
than distribute their executables with iOpenPod. The owner explicitly chose to
retain Qt's separate FFmpeg playback libraries. Native builds therefore omit the
command-line tools, expose no bundling option, and preserve the user's PATH for
existing tool discovery. Nothing installs or downloads those tools automatically.

Missing-tool failures must explain setup and stop the affected operation before
device changes. This trades a self-contained Sync installation for user-managed
prerequisites. Store listings and setup help must disclose that requirement. Qt's
bundled libraries retain their own redistribution obligations. Confined macOS,
Flatpak, and Snap releases require separately verified external-tool access;
ordinary Host installation does not establish sandbox access. Windows is the
current validation target.
