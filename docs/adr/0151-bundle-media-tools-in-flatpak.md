# Bundle media tools in the Flatpak

- Status: Accepted
- Date: 2026-10-19
- Amends: ADR-0081's unbundled executables, for the Flatpak channel only

Host-installed executables are not visible inside the Flatpak sandbox, and the
native installer from ADR-0103 cannot install into it. Without FFmpeg, FFprobe, and
fpcalc, the Flatpak cannot inspect, prepare, or acoustically match media. The owner
chose to build the tools from source in the Flatpak manifest rather than reach
Host executables through `flatpak-spawn --host`, which would need the
`org.freedesktop.Flatpak` sandbox escape.

The manifest pins x264 by commit and FFmpeg 7.1.5 and Chromaprint 1.6.2 by
SHA-256. FFmpeg is configured with `--enable-gpl`, x264, and the runtime's LAME, so
it provides every encoder iOpenPod selects (`aac`, `alac`, `libmp3lame`, `libx264`,
`mov_text`). fpcalc links statically to Chromaprint and uses FFmpeg's FFT. The
tools install into `/app`, so Storage's existing PATH discovery finds them and
Path Overrides keep precedence. Storage still removes PyInstaller's library path
from tool processes, so they load `/app/lib` rather than Qt's playback FFmpeg.

Other channels are unchanged: Windows, macOS, native Linux, and Snap builds still
rely on user-installed tools. The Flatpak grows by these tools and its builds take
longer. A Flatpak release must ship the tools' corresponding source, configure
options, and license notices. The GPL FFmpeg build is compatible with iOpenPod's
GPL-3.0-or-later license and is not a nonfree build.
