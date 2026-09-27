# Windows third-party release materials

`sources.json` pins upstream source archives by version, URL, size, and SHA-256.
`notices/` contains complete license, copyright, authorship, and attribution text
sets preserved from those archives. `notices/provenance.json` records each original
member and its hash. These are intentionally a superset of upstream notices,
including build/test and other-platform dependencies; their presence does not mean
every such upstream component is included in the Windows executable.

macOS candidates use Qt/PySide/Shiboken 6.9.3 and Intel-specific numerical
versions under [ADR-0094](../../docs/adr/0094-target-macos-12-3-with-platform-specific-native-dependencies.md).
The native evidence below establishes the Windows components. Complete the
corresponding Mac source archives and source-derived notices, including the actual
Qt FFmpeg and Intel LLVM/OpenBLAS versions, before publicly distributing Mac
candidates. The installed runtime inventory records the versions actually selected
for each candidate.

Third-party components retain their own licenses. The iOpenPod GPL grant does not
replace permissive notices, LGPL requirements, or Microsoft's runtime terms.
The separate application acknowledgements credit Dylan Staley's HASHAB and thank
libgpod and gtkpod. HASHAB's exact pinned source is included here as well.

## Reproduce the source materials

From the repository root:

```powershell
uv run python scripts/prepare_release_sources.py --download
uv run python scripts/prepare_release_sources.py --notices packaging/third-party/notices
```

Omit `--download` to verify the already downloaded archives offline. Downloads go
to ignored `build/release-sources/`; no downloaded code is installed or executed by
this collector. Include the manifest-listed archives with the exact application
source and build recipes in the publicly available release source kit. A local
cache or a private GitHub repository is not access for binary recipients.

## Windows libsndfile build

The original SoundFile wheel embeds libsndfile 1.2.2 with static codec libraries
built through an unpinned vcpkg environment. Its DLL is deliberately replaced in
the Windows release. The replacement retains libsndfile's internal formats and
disables optional FLAC/Vorbis/Opus/MPEG dependencies. iOpenPod uses user-installed
FFmpeg to decode media and uses librosa for numerical analysis; it does not use
SoundFile as its compressed-media decoder.

```powershell
uv run python -m scripts.build_windows_sndfile
```

This downloads the hash-pinned portable tools in `native-build-tools.json`, builds
the verified `libsndfile-1.2.2.tar.xz` source using Zig 0.14.1 / Clang 19.1.7,
CMake 4.1.3, and Ninja 1.13.0, and writes:

- `build/native-libs/sndfile/libsndfile_x64.dll`
- `build/native-libs/sndfile/build-record.json`

It does not alter the project environment or install system software. The only
source patch, `libsndfile-no-version-resource.patch`, omits cosmetic Windows
VERSIONINFO metadata to avoid an SDK resource compiler. The library still reports
1.2.2 through `sf_version_string`. The exact patch, build configuration, compiler
runtime source, source hash, and produced DLL hash accompany the source kit.
The linked Zig/MinGW runtime sources and notices are in `zig-runtime-0.14.1`.
The remaining DLL imports are Windows' kernel and Universal CRT system libraries.

SoundFile float-WAV roundtrip and librosa HPSS tests passed with the replacement
DLL loaded explicitly. The frozen application's runtime checks must also pass
after packaging the replacement.

## Native component evidence

- **Qt/PySide/Shiboken 6.11.2:** Windows DLL product version and runtime `qVersion`
  agree. Qt Core, GUI, Widgets, Network, DBus, SVG, OpenGL, QML/Quick, Multimedia,
  image format, shader, tools, and translation source modules are included.
  Qt PDF and Virtual Keyboard are excluded from the release bundle.
- **Qt FFmpeg 7.1.5:** the bundled DLL's exported version, license, and configure
  strings establish the actual version. Qt's online attribution page mentioned
  7.1.3 during this audit, so it was not used as binary-version evidence.
  The DLL reports LGPL 2.1 or later, shared MSVC libraries, programs disabled,
  zlib 1.3.1 enabled, and neither `--enable-gpl` nor `--enable-nonfree`.
  See `native-evidence.json` for the unmodified configure string.
- **Python 3.12.14:** python-build-standalone release 20260825; its pinned build
  recipes and CPython source are included, as are the observed OpenSSL 3.5.8,
  SQLite 3.53.1, Expat 2.8.3, zlib 1.3.2, libffi, bzip2, xz, and mpdecimal sources.
  The actual Windows interpreter's additional binary-license terms are retained.
- **Mesa software OpenGL 11.2.2 / LLVM 3.6.2:** both versions are embedded in
  `opengl32sw.dll`. Both source distributions and notices are included.
- **Wasmtime Python 38.0.0 / native 38.0.1:** the Python source's pinned
  `ci/download-wasmtime.py` specifies native v38.0.1. All registry dependencies in
  that native source's Cargo.lock are included with their published checksums.
- **llvmlite 0.49.0 / LLVM 22.1.0:** the loaded LLVM version establishes the native
  source version; LLVM's source and license exceptions are retained.
- **NumPy/SciPy OpenBLAS:** the release requirements pin scipy-openblas64
  0.3.34.106.0 and scipy-openblas32 0.3.31.22.0. The matching build repositories
  and their exact OpenBLAS submodule commits are preserved.
- **Pillow 12.3.0:** the full tagged source includes its Windows build recipe and
  upstream `wheels/dependency_licenses` text set, omitted by the Python sdist.
- **PyInstaller:** its pinned source, GPL bootloader license with the distribution
  exception, and notices are included. The exception allows distributing bundled
  applications under their own applicable licenses.
- **WinRT 3.2.1:** the PyWinRT v3.2.1 repository supplies the MIT text omitted from
  individual namespace wheels/sdists. **tqdm 4.70.0:** its `LICENCE` spelling is
  recognized and both MIT attribution and MPL text are retained.

The full GPL license and application source grant live at the repository root.
Release-specific application source, native build records, final binary hashes,
and public source availability must travel with a release. This directory is
reusable release evidence, not a substitute for matching the final packaged files.
