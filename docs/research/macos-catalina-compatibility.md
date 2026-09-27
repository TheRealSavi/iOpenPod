# macOS Catalina compatibility

Researched September 27, 2026 against the source, locked dependencies, packaging
configuration, primary documentation, and published native artifacts. Scope:
what would be required to preserve iOpenPod functionality on macOS 10.15
Catalina. This is an investigation, not an accepted deployment decision or a
support claim. Application code, dependency configuration, and the earlier
macOS 12/13 report were not changed. No Catalina execution was possible on the
Windows research machine.

## Findings

Catalina is substantially more work than the macOS 12.3 proposal. The Intel
numerical, audio, imaging, WebAssembly, and native macOS integration dependencies
are not the main obstacle: inspected compatible binaries exist, and Python 3.12
itself can remain. The principal unresolved work is finding or maintaining a Qt
and Python binding combination that preserves the current graphics renderer.
There is no demonstrated full-application candidate obtainable with only a
dependency pin and a lower bundle declaration.

Catalina support concerns the Intel `x86_64` application. Apple Silicon requires
a later OS and should retain its separate modern build rather than inheriting
the Catalina deployment choice. [Apple Catalina hardware requirements](https://support.apple.com/en-us/118458)

| Area | Smallest indicated Catalina work | Evidence status |
| --- | --- | --- |
| Qt and Synesthesia graphics | Qt 6.4.3 plus renderer/API changes and a compatible Python binding, or a maintained Catalina backport of newer Qt/PySide | Older native floor inspected; no complete viable bundle demonstrated |
| Python | Retain the inspected managed Python 3.12.14 Intel runtime if the chosen binding permits it | All 11 inspected native runtime files declare 10.15 |
| Ordinary analysis | Intel-scoped Numba 0.62.1, llvmlite 0.45.1, NumPy 2.3.5 | Compatible requirements and native deployment metadata; numerical execution unverified |
| Other baseline native dependencies | Use their existing older-target Intel wheels | Inspected native deployment minima are at most 10.15 |
| Storage and media keys | Verify actual Catalina behavior and `diskutil` output rather than introduce an assumed API rewrite | Catalina headers and upstream availability checks fit the used interfaces |
| Packaging | Separate Intel build, 10.15 artifact selection and bundle declaration, complete native audit and Catalina acceptance | Selection mechanism demonstrated for the non-Qt stack |
| Optional learned analysis | Separate older Torch/Torchaudio compatibility review, or custom builds | Excluded from current native baseline; not resolved or executed for Catalina |

## Qt and application API implications

The Qt audit inspected the actual Essentials, Addons, and Shiboken payloads for
PySide6 6.4.3 and 6.5.2, after verifying their release hashes. The older wheel
tags again understate some native deployment minima:

| Release | Wheel tag | Actual Intel deployment minimum | Python metadata |
| --- | --- | --- | --- |
| PySide6 6.4.3 | macOS 10.9 universal2 | 10.14 in all inspected Intel slices | Python less than 3.12 |
| PySide6 6.5.2 | macOS 10.9 universal2 | 11.0 in all inspected Intel slices | Python less than 3.12 |
| Current PySide6 6.11.2 | macOS 13 universal2 | Binding/support libraries declare 15.0 | Admits Python 3.12 |

The 6.4.3 inspection covered 366 Essentials, 268 Addons, and four Shiboken native
slices, including both architectures; its ARM slices target 11.0. The 6.5.2
inspection covered 374, 292, and four slices respectively, all targeting 11.0.
Consequently, 6.5.2 is not the inspected Catalina candidate, even though its
wheel tag initially suggests it. PySide6 6.4.3 supplies native deployment
metadata suitable for Catalina, but its Python limit and missing APIs prevent
using it as a drop-in current-app dependency.
[PySide6 6.4.3 metadata](https://pypi.org/pypi/PySide6/6.4.3/json),
[PySide6 Essentials 6.4.3 artifacts](https://pypi.org/project/PySide6-Essentials/6.4.3/#files),
[PySide6 Addons 6.4.3 artifacts](https://pypi.org/project/PySide6-Addons/6.4.3/#files),
[PySide6 6.5.2 metadata](https://pypi.org/pypi/PySide6/6.5.2/json)

Comparing the application's imports with the extracted 6.4.3 Mac stubs found
22 missing imported names: 20 QRhi names, QShader, and QRhiWidget,
all in `src/iOpenPod/GUI/synesthesia/renderer.py`. Public QRhi/QShader arrived in
Qt 6.6 and QRhiWidget in 6.7. The GUI imports the renderer through
`main_window` and `synesthesia_page` during startup, so merely leaving the
Synesthesia page unopened cannot make the older binding launch the current
application. The static scan was limited to parseable binding stubs; QtDBus's
invalid indentation prevented its inclusion in the AST inventory. No complete
older-binding application execution was performed.
[Qt QRhi public API](https://doc.qt.io/qt-6/qrhi.html),
[Qt QShader public API](https://doc.qt.io/qt-6/qshader.html),
[Qt QRhiWidget version](https://doc.qt.io/qt-6/qrhiwidget.html)

Other confirmed application adaptations for the older Qt base are three
`QEvent.DevicePixelRatioChange` references and one `QPalette.Accent` reference.
Both `beginFilterChange` and `endFilterChange` are absent at the application's
11 filter-update sites; `invalidateRowsFilter` is present in 6.4.3. This is more
filter compatibility work than the Qt 6.9 proposal, which retains the begin
method. The complete source usage and actual retained model behavior still need
review during implementation.
[Qt device-pixel-ratio event version](https://doc.qt.io/qt-6/qevent.html),
[Qt Accent palette role version](https://doc.qt.io/qt-6.8/qpalette.html)

All 12 packaged `.qsb` shader assets use serialization format version 9. Qt
6.4.3's source uses QSB version 6 and rejects unrecognized newer formats; a
6.4 renderer route needs matching shader regeneration or a different shader
pipeline. The current Metal renderer also depends on compute and storage-buffer
features. A visually equivalent Catalina adapter needs to preserve those
effects and validate the actual target GPU; changing the widget class alone
would not preserve Synesthesia.
[Qt 6.4.3 shader format definition](https://github.com/qt/qtbase/blob/v6.4.3/src/gui/rhi/qshader_p_p.h),
[Qt 6.4.3 shader version rejection](https://github.com/qt/qtbase/blob/v6.4.3/src/gui/rhi/qshader.cpp#L384)

### Two routes that could preserve functionality

1. **Maintain a Catalina backport of newer Qt and PySide.** Keep Python 3.12 and
   the current QRhi renderer, but build and audit the entire matching Qt,
   PySide, and Shiboken stack for 10.15. This is outside the inspected newer
   distributions' deployment targets. It could minimize application changes,
   but may require source patches for newer APIs and native plugins, not just
   `--macos-deployment-target=10.15`. Successful compilation, every collected
   native dependency, and actual Catalina execution remain unproven.
2. **Use the inspected Qt 6.4.3 base and port the graphics adapter.** Preserve
   the visual functionality through a Catalina-compatible Metal or native
   bridge implementation, regenerate the shader artifacts, and adapt the
   smaller UI API differences. Retaining Python 3.12 additionally needs a
   maintained PySide/Shiboken binding backport supporting that interpreter.
   Using the stock 6.4.3 bindings instead means moving the application to Python
   3.11 and converting its Python 3.12 source syntax and compatible dependencies.

The Python 3.11 option is a broad application/toolchain migration: the AST
inventory found 46 PEP 695 type aliases across 32 source files, plus 53 generic
class/function definitions across 19 source files. Those file groups overlap.
They need syntax conversion, followed by review of standard-library use,
supported dependency releases, and the Python 3.12 decision in ADR-0001.
Changing only `.python-version` and package metadata would not suffice.

The rendering-port route can preserve the product's analysis and world model.
ADR-0044 makes World Score, Persistent Topology, and World Biography independent
of disposable GPU projections; a replacement Rendering Adapter must preserve
their identities and consequences. This permits an adapter replacement without
rewriting musical analysis or weakening the continuity requirements. It still
constitutes substantive graphics implementation and maintenance work.
[ADR-0044 rendering boundary](../adr/0044-make-synesthesia-topology-and-biography-authoritative.md)

## Python and ordinary analysis

Python 3.12 does not inherently require leaving Catalina. The Python Software
Foundation's 3.12.10 installer explicitly supports macOS 10.13 and later. More
directly relevant to the repository, the exact managed runtime selected by UV
0.12.7 was downloaded and hash-verified:

```text
cpython-3.12.14+20260825-x86_64-apple-darwin-install_only_stripped.tar.gz
SHA-256: bd486eadd20259ad1fece28c800205baac0113c3b9cc663ddae495c19ba9db38
```

All 11 native files in that standalone runtime declare deployment target
10.15.0, including the interpreter, libpython, and extension libraries. This
supports retaining Python 3.12 when using a compatible custom binding; it does
not override an older PySide release's Python version limit. Actual Catalina
interpreter execution remains unverified.
[Python 3.12.10 macOS installer support](https://www.python.org/downloads/release/python-31210/),
[UV 0.12.7 managed-runtime manifest](https://github.com/astral-sh/uv/blob/0.12.7/crates/uv-python/download-metadata.json),
[exact standalone runtime release](https://github.com/astral-sh/python-build-standalone/releases/tag/20260825)

The Intel analysis selection from the macOS 12/13 investigation also fits
Catalina. Numba 0.62.1 requires `llvmlite>=0.45.0dev0,<0.46` and
`numpy>=1.22,<2.4`; the project's direct NumPy requirement `>=2.2,<3` permits
2.3.5. Current SciPy 1.18.1 and scikit-learn 1.9.1 admit that combination, and
Librosa 0.11.0 can remain. Numba's later releases stopped providing Intel macOS
wheels, so the Intel constraint is needed even when the OS is newer than
Catalina. [Numba Intel transition](https://numba.readthedocs.io/en/stable/release/0.63.0-notes.html#deprecation-of-macos-x86-64-intel-support),
[Numba 0.62.1 requirements](https://pypi.org/pypi/numba/0.62.1/json),
[Librosa 0.11.0 requirements](https://pypi.org/pypi/librosa/0.11.0/json)

| Inspected Python 3.12 Intel artifact | Highest native deployment minimum |
| --- | --- |
| Numba 0.62.1 and llvmlite 0.45.1 | 10.15 |
| NumPy 2.3.5 older-target wheel | 10.13 |
| SciPy 1.18.1 older-target wheel | 10.15 |
| scikit-learn 1.9.1 | 10.13 |
| Pillow 12.3.0 | 10.13 |
| PyObjC core and compiled framework closure 12.2.2 | 10.13 |
| Wasmtime 38.0.0 | 10.12 |
| SoundFile 0.14.0 bundled libsndfile | 10.9 |
| soxr 1.1.0 | 10.14 |
| CFFI 2.1.1 | 10.15 |
| msgpack and charset-normalizer | 10.13 |
| PyCryptodome 3.23.0 | 10.9 |
| PyInstaller 6.22.3 Intel bootloaders | 10.13 |

These values reuse hash-verified Mach-O inspections from the earlier
investigation, not just wheel tags. The ARM SciPy 12.3 issue does not apply to
its Intel 10.15 wheel. The remaining ordinary-analysis closure is Python code
without another native macOS deployment floor. Choosing the older-target NumPy
and SciPy wheels retains OpenBLAS rather than newer macOS Accelerate variants;
API functionality remains available, with possible performance, rounding, and
bundle-size differences.
[NumPy 2.3.5 artifacts](https://pypi.org/project/numpy/2.3.5/#files),
[SciPy 1.18.1 artifacts](https://pypi.org/project/scipy/1.18.1/#files),
[scikit-learn artifacts](https://pypi.org/project/scikit-learn/1.9.1/#files),
[NumPy older-target wheel policy](https://numpy.org/doc/stable/release/2.0.0-notes.html#macos-accelerate-support-including-the-ilp64)

An Intel-only Numba direct constraint or UV constraint can select that stack
without downgrading other platforms. Direct dependency metadata communicates the
compatibility requirement to other installers. The existing frozen
`UserWideCacheLocator` setting exists in Numba 0.62.1. The earlier static scan
found all 51 direct NumPy names used by the application in NumPy 2.3.5's source
or stubs; signatures, numerical equivalence, and compiled analysis remain
runtime acceptance work. [Numba 0.62.1 frozen cache source](https://github.com/numba/numba/blob/0.62.1/numba/core/caching.py#L225)

## Storage and system media integration

Catalina's XNU `xnu-6153.11.26` header contains the same full
`__DARWIN_STRUCT_STATFS64` layout as `src/storage/platform/macos.py`, including
`f_flags_ext` and seven reserved fields. The header retains 64-bit inode
interfaces used by the application's `statfs$INODE64`/`statfs` lookup. No
Catalina-specific structure rewrite is indicated by this source comparison.
[Catalina filesystem ABI](https://github.com/apple-oss-distributions/xnu/blob/xnu-6153.11.26/bsd/sys/mount.h)

The same kernel source includes `getattrlist`, `fgetattrlist`, and
`fsetattrlist`, with the descriptor-based argument layouts used for Volume
labels and Finder icon information. Its attribute definitions include the
requested Volume name, UUID/capabilities, and Finder information. These checks
support existing discovery and Volume metadata operations without substituting
a newer API. They do not establish device-specific filesystem behavior,
permissions, writable label support, or safe mutation on an actual iPod.
[Catalina filesystem attribute calls](https://github.com/apple-oss-distributions/xnu/blob/xnu-6153.11.26/bsd/kern/syscalls.master),
[Catalina attribute definitions](https://github.com/apple-oss-distributions/xnu/blob/xnu-6153.11.26/bsd/sys/attr.h)

Storage uses established CoreFoundation/IOKit registry calls and SCSITask
interfaces, rather than the newer DriverKit API. Apple's archived IOKit family
documentation describes the same SCSITask device/task interfaces before
Catalina. This supports an availability inference, while actual interface
versions, `com_apple_driver_iPodSBCNub` matching, and device response behavior
remain unverified. Discovery's `diskutil info -plist` and `ioreg` output and safe
removal through `diskutil unmountDisk` followed by `eject` should be checked on
Catalina, including the exact property keys and refusal behavior consumed by
the parser. No compatibility change is yet demonstrated as necessary.
[Apple archived IOKit family reference](https://developer.apple.com/library/archive/documentation/DeviceDrivers/Conceptual/IOKitFundamentals/Families_Ref/Families_Ref.html),
[Apple SCSITask interface](https://developer.apple.com/documentation/iokit/scsitaskinterface)

PyObjC's documented Python 3.12 wheel floor is 10.13; its current package major
version does not mean it requires macOS 12. The used playback state constants,
default playback rate, external content identifier, and remote-command handler
API appear in upstream availability checks for macOS 10.12. The optional
`MPNowPlayingInfoPropertyExcludeFromSuggestions` is a 15.0 API and already uses
the application's guarded optional lookup. Consequently, no media-key feature
removal is indicated for Catalina by the API inventory. Publishing metadata,
album artwork, seek commands, media keys, and callback lifetimes still require
native runtime verification.
[PyObjC supported platforms](https://pyobjc.readthedocs.io/en/latest/supported-platforms.html#macos-platform-support),
[exact-version now-playing availability checks](https://github.com/ronaldoussoren/pyobjc/blob/v12.2.2/pyobjc-framework-MediaPlayer/PyObjCTest/test_mpnowplayinginfocenter.py),
[exact-version remote-command checks](https://github.com/ronaldoussoren/pyobjc/blob/v12.2.2/pyobjc-framework-MediaPlayer/PyObjCTest/test_mpremotecommand.py)

## Build and distribution requirements

Make a separate Intel Catalina candidate instead of applying its Qt constraints
to Windows, Linux, or Apple Silicon. Once a compatible Qt/Python strategy has
been chosen, use an explicit target when installing its dependencies on a newer
Intel macOS builder:

```shell
export MACOSX_DEPLOYMENT_TARGET=10.15
uv sync --locked --managed-python --no-dev --group packaging \
  --python-platform x86_64-apple-darwin \
  --no-build-package numpy --no-build-package scipy \
  --no-build-package numba --no-build-package llvmlite
uv run --no-sync python scripts/package_app.py freeze
```

This is a proposed build step after dependency implementation, not a working
command against the unchanged lock. Set the Intel bundle's
`LSMinimumSystemVersion` to `10.15` only after its collected native payload
matches. Later build commands should use `uv run --no-sync` to retain the
explicitly selected environment. Native source builds need their own deployment
and SDK controls because UV's target option governs wheel selection, not the
output of arbitrary build systems.
[UV deployment target configuration](https://docs.astral.sh/uv/reference/environment/#macosx_deployment_target),
[UV target platform option](https://docs.astral.sh/uv/reference/cli/#uv-sync--python-platform),
[UV synchronization behavior](https://docs.astral.sh/uv/concepts/projects/sync/#automatic-lock-and-sync)

UV currently documents support for macOS 13+ and known operation on 12 with
`realpath`; it does not promise Catalina support. Separately, the exact UV
0.12.7 Intel wheel was hash-verified and its `uv`/`uvx` binaries declare native
minimum 10.12.0. That lower artifact minimum is not a support guarantee or a
successful Catalina run. Building on Catalina would require separately proving
the chosen UV and other build tools work there. Building on a supported newer
Intel Mac and accepting the frozen artifact on Catalina avoids making UV a
user runtime dependency. The installed application needs its bundled Python,
not UV.
[UV platform support policy](https://docs.astral.sh/uv/reference/policies/platforms/),
[UV 0.12.7 artifact metadata](https://pypi.org/pypi/uv/0.12.7/json)

PyInstaller recommends the oldest intended target OS for forward-compatible
builds; its Intel 6.22.3 bootloader declaration fits Catalina. A newer builder
with carefully selected dependencies remains a candidate requiring a complete
bundle audit and actual Catalina execution. The current release matrix's
Apple Silicon `macos-14` job does not supply an Intel Catalina build. A suitable
Intel builder and a real Catalina validation environment are required.
[PyInstaller macOS forward compatibility](https://pyinstaller.org/en/stable/usage.html#making-macos-apps-forward-compatible)

Locked Mypy 2.3.1 lacks an Intel wheel; keeping developer tools out of the freeze
environment avoids that unrelated source-build problem. Build-only tools should
have a separately working QA environment. Existing signing, sandbox, store
submission, licensing, and native provenance requirements continue to apply.
Custom Qt/binding builds need reproducible source, build options, corresponding
source, and refreshed third-party notices.

## Optional learned analysis and external tools

The native baseline already excludes Torch, Torchaudio, and Demucs. Ordinary
Synesthesia analysis is included; therefore Catalina support for that baseline
does not require a Torch downgrade. Preserving the optional learned-analysis
extra as well is a separate compatibility project. Current declared Torch and
Torchaudio lower bounds are 2.11, which do not provide Intel wheels. Torch and
Torchaudio 2.2.2 do provide CPython 3.12 Intel wheels with Catalina-compatible
tags, but using them needs relaxing those bounds and checking the actual native
payload, Demucs 4.1 API/model loading, and NumPy interoperation. Those extra
wheels and the full optional installation have not been audited or executed.
[Torch 2.2.2 artifacts](https://pypi.org/project/torch/2.2.2/#files),
[Torchaudio 2.2.2 artifacts](https://pypi.org/project/torchaudio/2.2.2/#files)

The application's learned-analysis adapter already defaults to CPU when CUDA is
unavailable, so Catalina does not require adding a new MPS fallback. It directly
uses `torch.from_numpy` and `tensor.numpy()`, making NumPy ABI compatibility a
functional requirement. PyTorch's upstream NumPy 2 transition discussion
distinguishes API version support from whether a particular binary was built
against a compatible NumPy ABI. Do not assume the 2.2.2 wheels safely preserve
this adapter with the present NumPy 2 requirement; an older NumPy/SciPy stack or
a rebuilt Torch may be necessary after verification.
[PyTorch NumPy ABI transition](https://github.com/pytorch/pytorch/issues/107302)

FFmpeg, FFprobe, and fpcalc remain user-installed executables under the existing
packaging design. Users would need Catalina-compatible Intel builds for media
inspection, acoustic fingerprinting, some decoding, and Sync. Their availability
and launchability need separate validation; the app's Python deployment target
does not determine those external binaries' minimum OS. No external-tool build
has been selected or verified in this investigation.

## Demonstrated selection and remaining acceptance

A scratch-only copy of the project metadata omitted Qt solely to isolate the
other dependencies, retained Python 3.12, and applied the Intel Numba constraint.
The complete universal lock resolved to 131 records. A Catalina Intel dry-run
with `--no-dev --group packaging --no-install-project --no-build` produced a
complete 52-package plan, including the compatible analysis selection, without
installing or building anything. This proves binary availability for the
non-Qt baseline and packaging stack; it is not a runnable application or a
proposal to remove Qt from the product.

Native evidence came from SHA-256-verified exact-version artifacts and direct
Mach-O inspection. Every universal architecture offset was followed, with
`LC_BUILD_VERSION` or `LC_VERSION_MIN_MACOSX` read for each native file and slice.
The key Intel runtime hash is recorded above. UV's inspected artifact was
`uv-0.12.7-py3-none-macosx_10_12_x86_64.whl`, SHA-256
`ec5b437aa60e8c94da263ad709d0bf6c8f268ac81f305d89c6115badd7d1cbe7`.
The numerical/native wheel inventories and reproducible inspection method are
also summarized in [the macOS 12/13 report](macos-compatibility.md).
Private Catalina scripts and source snapshots are under
`.scratch/macos-catalina-compatibility`.

Before claiming support, audit the entire chosen frozen Intel bundle for native
deployment minima, linked unavailable system symbols, architecture, collected
Qt backends, Python extensions, and embedded numerical/audio libraries. Run the
existing frozen smoke mode outside the checkout without installed Python, then
verify GUI launch, playback/codecs, Synesthesia rendering and analysis, system
media integration, Volume discovery, safe removal, Sync, and recovery using an
authorized test iPod or virtual Volume. Acceptance should include the oldest
Catalina point release actually promised. Deployment metadata, static imports,
and numerical resolution alone cannot establish preserved functionality.
