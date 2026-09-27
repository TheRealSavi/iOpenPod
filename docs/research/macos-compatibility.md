# macOS 12 and 13 compatibility

Researched September 27, 2026 against the committed dependency lock, application
source, packaging configuration, upstream documentation, and upstream package
metadata. Scope: preserve current native application functionality while lowering
the deployment target. This is a feasibility investigation, not a support claim
or an accepted architectural decision. No dependency or application changes were
made, and no macOS application execution was possible on the Windows research
machine.

Implementation follow-up: the user selected the **12.3** target on September 27,
2026. [ADR-0094](../adr/0094-target-macos-12-3-with-platform-specific-native-dependencies.md)
records the accepted dependency split and build controls. The findings below
describe the pre-change baseline. Real macOS 12.3 execution remains pending.

## Findings

Both targets appear feasible with small dependency and packaging changes, but
the current locked PySide6 artifacts do not substantiate a packaging-only reduction. Despite
their `macosx_13_0_universal2` wheel tags, PySide6 6.11.2's imported bindings and
Shiboken libraries declare a macOS 15.0 native deployment minimum on both
architectures. Two independent Mach-O parsers confirmed this discrepancy.
PySide6 6.9.3's corresponding binaries declare macOS 12.0 and are the inspected
candidate for both targets, with two small groups of Qt API adaptations. Every
inspected PySide6 6.10 and 6.11 release had the higher binding deployment minimum.

For Apple Silicon, the inspected older-target SciPy 1.18.1 wheel additionally
declares macOS 12.3 in its native payload despite its macOS 12.0 wheel tag. The
smallest demonstrated Monterey dependency candidate is therefore **12.3+**;
supporting 12.0–12.2 requires a different SciPy artifact or version. None of these
findings establishes that a frozen application works on those systems.

| Target and architecture | Smallest indicated change |
| --- | --- |
| macOS 13, Apple Silicon | macOS Qt 6.9.3 constraint, the same 13 localized Qt call adaptations as Monterey, controlled older-target wheels, managed Python, and frozen-bundle acceptance |
| macOS 12.3+, Apple Silicon | The same packaging changes, macOS Qt 6.9.3 constraint, 11 row-filter completion calls, two buffer-update calls, and minimum bundle declaration |
| macOS 13, Intel | Compatible Qt and packaging changes plus an Intel Numba constraint, older resolved llvmlite/NumPy, and a separate Intel build |
| macOS 12, Intel | Combine the Qt 6.9 adaptations with the Intel analysis dependency selection and build; inspected Intel SciPy does not have the ARM 12.3 floor |

Intel requires a separate compatibility choice at either target. The locked Numba
and llvmlite releases no longer publish Intel macOS wheels. Their last supported
Intel combination is Numba 0.62.x and llvmlite 0.45.x, which also constrains NumPy to
less than 2.4. These constraints can be scoped to Intel macOS without changing the
other platforms. [Numba 0.63 release notes](https://numba.readthedocs.io/en/stable/release/0.63.0-notes.html#deprecation-of-macos-x86-64-intel-support),
[Numba version compatibility](https://numba.readthedocs.io/en/stable/user/installing.html#version-support-information)

The existing bundle already declares `LSMinimumSystemVersion = 13.0` in
`packaging/iOpenPod.spec`. The candidate workflow builds on `macos-14` and installs
with an unrestricted `uv sync --locked --group packaging`. It can therefore bundle
macOS 14 variants of NumPy and SciPy despite the declared macOS 13 minimum. More
seriously, the locked Qt bindings themselves declare macOS 15 in their
native load commands. The bundle declaration does not lower the native
dependencies' deployment targets.

## Baseline dependency audit

The table records the lowest declared macOS wheel targets compatible with Python
3.12, as found in `uv.lock` and checked against PyPI's exact-version metadata. A
wheel tag is the publisher's compatibility declaration; the native payload and
final bundle still need inspection. A `universal2` wheel tagged below macOS 11
supports its Intel slice on that older OS; Apple Silicon itself starts at macOS 11.

| Dependency | Locked version | Intel wheel floor | Apple Silicon wheel floor | Consequence |
| --- | --- | --- | --- | --- |
| PySide6, Essentials, Addons, Shiboken6 | 6.11.2 | 13.0, universal2 | 13.0, universal2 | Tags understate the bindings' declared 15.0 native minimum; support for either target is unverified |
| NumPy | 2.5.3 | 10.13 | 11.0 | Also offers macOS 14 wheels; choose the older target when packaging |
| SciPy | 1.18.1 | 10.15 | 12.0 | ARM native payload declares 12.3; also offers macOS 14 wheels |
| scikit-learn | 1.9.1 | 10.13 | 12.0 | Both requested targets have a wheel |
| Numba | 0.67.0 | No wheel | 12.0 | Intel needs an older compatible dependency selection |
| llvmlite | 0.49.0 | No wheel | 12.0 | Follows the Numba compatibility selection |
| Pillow | 12.3.0 | 10.13 | 11.0 | No target change indicated |
| PyObjC core and compiled framework bindings | 12.2.2 | 10.13, universal2 | 11.0, universal2 | Package version 12 is unrelated to macOS version 12 |
| PyObjC MediaPlayer | 12.2.2 | Pure Python wrapper | Pure Python wrapper | Depends on PyObjC core and AVFoundation bindings |
| Wasmtime | 38.0.0 | 10.13 | 11.0 | No target change indicated |
| SoundFile | 0.14.0 | 10.9 | 11.0 | Bundled libsndfile targets confirmed by inspection |
| soxr | 1.1.0 | 10.14 | 11.0 | No target change indicated |
| CFFI | 2.1.1 | 10.15 | 11.0 | No target change indicated |
| msgpack | 1.2.2 | 10.13 | 11.0 | No target change indicated |
| PyCryptodome | 3.23.0 | 10.9 | 11.0 | No target change indicated |
| charset-normalizer | 3.5.1 | 10.9, ABI3 universal2 | 11.0, universal2 | No target change indicated |
| PyInstaller, build tool | 6.22.3 | 10.13, universal2 | 11.0, universal2 | Its bootloader is not the highest indicated floor |

Exact-version package files:
[PySide6](https://pypi.org/project/PySide6/6.11.2/#files),
[NumPy](https://pypi.org/project/numpy/2.5.3/#files),
[SciPy](https://pypi.org/project/scipy/1.18.1/#files),
[scikit-learn](https://pypi.org/project/scikit-learn/1.9.1/#files),
[Numba](https://pypi.org/project/numba/0.67.0/#files),
[llvmlite](https://pypi.org/project/llvmlite/0.49.0/#files),
[Pillow](https://pypi.org/project/pillow/12.3.0/#files),
[PyObjC core](https://pypi.org/project/pyobjc-core/12.2.2/#files),
[MediaPlayer](https://pypi.org/project/pyobjc-framework-MediaPlayer/12.2.2/#files),
[Wasmtime](https://pypi.org/project/wasmtime/38.0.0/#files),
[SoundFile](https://pypi.org/project/soundfile/0.14.0/#files),
[soxr](https://pypi.org/project/soxr/1.1.0/#files),
[CFFI](https://pypi.org/project/cffi/2.1.1/#files),
[msgpack](https://pypi.org/project/msgpack/1.2.2/#files),
[PyCryptodome](https://pypi.org/project/pycryptodome/3.23.0/#files),
[charset-normalizer](https://pypi.org/project/charset-normalizer/3.5.1/#files),
[PyInstaller](https://pypi.org/project/pyinstaller/6.22.3/#files).

The remaining baseline closure consists of Python modules without an additional
macOS wheel floor: audioread, certifi, cloudpickle, decorator, feedparser and its
SGML parser, idna, importlib-resources, joblib, lazy-loader, librosa, mutagen,
narwhals, packaging, platformdirs, pooch, pycparser, requests, threadpoolctl, tqdm,
typing-extensions, and urllib3. This classification comes from the locked wheel
files and dependency edges, rather than assuming every locked package ships in
the native app.

PyObjC's platform documentation explicitly describes Python 3.12 and newer wheels
as targeting macOS 10.13 or later. Individual framework APIs still have their own
OS availability requirements. [PyObjC platform support](https://pyobjc.readthedocs.io/en/latest/supported-platforms.html#macos-platform-support)

NumPy's newer-target wheels select Apple's updated Accelerate BLAS/LAPACK, while
the older-target variants retain OpenBLAS. Choosing an older-compatible wheel
keeps the NumPy API and analysis functionality, with potential differences in
linear algebra speed, numerical rounding, and bundle size. It does not require a
NumPy version downgrade for Apple Silicon. [NumPy Accelerate wheel policy](https://numpy.org/doc/stable/release/2.0.0-notes.html#macos-accelerate-support-including-the-ilp64)

## Actual native binary inspection

Hash-verified wheel downloads were inspected directly for Mach-O deployment load
commands, including every architecture in universal binaries. The numerical,
audio, imaging, cryptography, WebAssembly, and PyObjC audit covered 32 wheels and
770 native files, including the proposed Intel versions. Qt and the PyInstaller
bootloader were inspected separately. These are declared native deployment
targets, not proof that every library loads or executes on an older system.

| Inspected artifact | Highest observed native minimum | Meaning |
| --- | --- | --- |
| PySide6 Essentials/Addons and Shiboken6 6.11.2 | 15.0, both architectures | Qt frameworks target 13.0, but imported Python bindings and support libraries target 15.0 |
| PySide6 Essentials and Shiboken6 6.10.0–6.10.3 and 6.11.0–6.11.1 | 15.0, both architectures | Selecting an earlier available 6.10/6.11 patch does not remove the binding discrepancy |
| PySide6 Essentials/Addons and Shiboken6 6.9.3 | 12.0, both architectures | Compatible deployment metadata for both requested targets |
| SciPy 1.18.1 older-target ARM wheel | 12.3 | Its macOS 12.0 wheel tag understates the native payload's deployment target |
| SciPy 1.18.1 older-target Intel wheel | 10.15 | Does not have the ARM wheel's 12.3 floor |
| scikit-learn 1.9.1 | ARM 12.0; Intel 10.13 | Does not raise the candidate minimum further |
| Numba 0.67.0 and llvmlite 0.49.0 | ARM 11.0 | The native payloads are lower than their macOS 12 wheel tags; no Intel wheels |
| Numba 0.62.1 and llvmlite 0.45.1 | 10.15, Intel | Inspected Intel fallback |
| NumPy 2.5.3 older-target wheels and NumPy 2.3.5 Intel | ARM 11.0; Intel 10.13 | Preserve the analysis API while avoiding the macOS 14 variants |
| Pillow and compiled PyObjC closure | ARM 11.0; Intel 10.13 | No additional floor found |
| Wasmtime 38.0.0 | ARM 11.0; Intel 10.12 | Bundled runtime does not impose 12/13 restriction |
| SoundFile 0.14.0 bundled libsndfile | ARM 11.0; Intel 10.9 | Bundled native audio library does not impose 12/13 restriction |
| Other inspected baseline native extensions | ARM at most 11.0; Intel at most 10.15 | Includes soxr, CFFI, msgpack, PyCryptodome, and charset-normalizer |

For example, `PySide6/QtCore.abi3.so`, `QtGui.abi3.so`,
`QtWidgets.abi3.so`, `QtMultimedia.abi3.so`, `libpyside6`, the Shiboken binding,
and `libshiboken6` in the locked 6.11.2 wheels have `LC_BUILD_VERSION` with
macOS platform 1, minimum 15.0.0, and SDK 15.0.0 in both slices. Two independent
parsers agreed on these values. A deployment load command alone does not prove
that a loadable library fails on every older OS, but it does not substantiate
support for one either. Treat 15.0 as the declared native minimum and require a
compatible artifact or actual older-OS validation before promising 13. Rewriting
the binary's version does not resolve unavailable API or linkage requirements.
[PySide6 Essentials 6.11.2 artifact](https://pypi.org/project/PySide6-Essentials/6.11.2/#files),
[Shiboken6 6.11.2 artifact](https://pypi.org/project/shiboken6/6.11.2/#files)

SciPy's `_fblas`, `_flapack`, and many signal/statistics extension modules in the
ARM `macosx_12_0` wheel declare minimum 12.3.0. Targeting Monterey 12.3+ avoids
adding another dependency change. A strict 12.0 target would require investigating
an older SciPy wheel or building a suitable SciPy distribution; neither option
has been resolved or validated here. Additional hash-verified ARM CPython 3.12
wheels for SciPy 1.17.1, 1.17.0, 1.16.3, 1.15.3, and 1.14.1 all also declared
maximum native minimum 12.3 despite their 12.0 wheel tags. A simple downgrade to
one of those recent releases therefore does not establish 12.0 compatibility.
[SciPy 1.18.1 artifacts](https://pypi.org/project/scipy/1.18.1/#files),
[SciPy 1.17.1 artifacts](https://pypi.org/project/scipy/1.17.1/#files),
[SciPy 1.14.1 artifacts](https://pypi.org/project/scipy/1.14.1/#files)

The complete hashes, binary names, architectures, and load-command values are
retained in private research inventories under `.scratch/macos-compatibility`.
An accepted release should retain an inventory of the final collected bundle,
because wheel inspection alone does not account for host runtime libraries and
every build-time collection decision.

Key artifact identities are recorded here so the findings remain auditable
without the private inventories. All are wheel filenames from the cited
exact-version PyPI release pages; hashes matched the release metadata.

| Wheel filename | SHA-256 |
| --- | --- |
| `pyside6_essentials-6.11.2-cp310-abi3-macosx_13_0_universal2.whl` | `77795c145202e65a78d88f7cd409d186e3ba23d159bdb3ba2dcd159ae5e5f0d9` |
| `pyside6_essentials-6.9.3-cp39-abi3-macosx_12_0_universal2.whl` | `ad3664ff0ced9f92ed7872e512c86328894d29f262e6c3400400232a36dda357` |
| `pyside6_addons-6.9.3-cp39-abi3-macosx_12_0_universal2.whl` | `189c9a9a2fdaffa95e91731f5c0afdc47ba231f5f683d3f8977b22c233749ba4` |
| `shiboken6-6.9.3-cp39-abi3-macosx_12_0_universal2.whl` | `e9b240828790b8e21a50e66449a5aa8b99f9b8a538c80c1a325fa04f8364985e` |
| `scipy-1.18.1-cp312-cp312-macosx_12_0_arm64.whl` | `e708533e8b2ae2497d65346538a7dcc92814410b25b81432eac66de0f2af8265` |
| `scipy-1.18.1-cp312-cp312-macosx_10_15_x86_64.whl` | `457fd7a2a8edeb044ab6ffbc0aa03ff6cd18491356e5e0c834d76ce621b916d1` |

To reproduce the inspection, download those exact artifacts from their PyPI
release metadata, verify their SHA-256, and read every ZIP member whose first
four bytes identify a thin or universal Mach-O file. Follow each universal
architecture offset and inspect its thin load commands. Decode
`LC_BUILD_VERSION` (`0x32`) as platform, minimum, SDK; decode
`LC_VERSION_MIN_MACOSX` (`0x24`) as minimum, SDK. Version integers contain the
major in the high 16 bits, minor in the next 8, and patch in the final 8. Record
each slice's CPU type and the maximum macOS minimum across the wheel. On a Mac,
Apple's native object inspection tools provide an independent check of the same
load commands. Check deployment minima separately from SDK version: a binary
built using a newer SDK can still declare and support an older deployment target.

## Python runtime

Python 3.12 need not change to pursue either target. UV obtains managed CPython
distributions from Astral's `python-build-standalone` project. Its target
configuration includes Python 3.12 and compiles for macOS 11.0 on Apple Silicon
and 10.15 on Intel. The exact CPython 3.12.14, build 20260825, install-only
stripped archives selected by UV 0.12.7 were also downloaded and hash-verified
against UV's versioned download metadata. All 11 native files in each archive,
including the executable, `libpython3.12.dylib`, dynamic extension modules, and
Tcl/Tk libraries, declare those same deployment minima. No interpreter version
downgrade is indicated. Runtime execution and the final collected bundle remain
unverified.
[UV managed Python distributions](https://docs.astral.sh/uv/concepts/python-versions/#managed-python-distributions),
[Python standalone target configuration](https://github.com/astral-sh/python-build-standalone/blob/main/cpython-unix/targets.yml),
[UV 0.12.7 exact runtime download metadata](https://github.com/astral-sh/uv/blob/0.12.7/crates/uv-python/download-metadata.json)

| Inspected standalone archive | SHA-256 | Native minimum |
| --- | --- | --- |
| `cpython-3.12.14+20260825-aarch64-apple-darwin-install_only_stripped.tar.gz` | `8b0f1fa71eab7ca644e482c631807a1116fa848491051cd1c8d9429491de63a6` | 11.0 |
| `cpython-3.12.14+20260825-x86_64-apple-darwin-install_only_stripped.tar.gz` | `bd486eadd20259ad1fece28c800205baac0113c3b9cc663ddae495c19ba9db38` | 10.15 |

The release workflow currently does not force a managed interpreter. Add
`--managed-python` to the controlled installation so a previously installed
Homebrew interpreter does not silently become the frozen runtime. Pin and record
the Python patch and standalone build used for an accepted release; `3.12` alone
does not pin those artifacts. Inspect the collected `libpython`, extension
modules, and dependent native libraries before publishing a minimum OS claim.

## Packaging for an older target on a newer builder

UV's macOS wheel priority lists descend from the selected macOS major version.
For a macOS 14 environment, a matching macOS 14 wheel ranks ahead of the same
package's older-compatible wheel. The universal lock contains both variants, so
`--locked` fixes versions without fixing which platform artifact is installed.
[UV 0.12.7 platform-tag implementation](https://github.com/astral-sh/uv/blob/0.12.7/crates/uv-platform-tags/src/tags.rs#L597)

Use `--python-platform aarch64-apple-darwin` together with
`MACOSX_DEPLOYMENT_TARGET=13.0` or `12.3` to select older-compatible dependencies
on an Apple Silicon builder. The environment variable is documented for an
explicit `--python-platform`; setting it alone must not be assumed to change
native-host wheel selection. For an Intel builder, use
`x86_64-apple-darwin`. The option selects wheels; a source distribution can still
build for the current host, so native source builds require separate control.
[UV deployment-target environment variable](https://docs.astral.sh/uv/reference/environment/#macosx_deployment_target),
[UV target-platform option](https://docs.astral.sh/uv/reference/cli/#uv-sync--python-platform)

First apply the macOS Qt 6.9.3 candidate selection and relock, for either target.
Candidate commands for a fresh Apple Silicon macOS 13 freeze environment:

```shell
export MACOSX_DEPLOYMENT_TARGET=13.0
uv sync --locked --managed-python --no-dev --group packaging \
  --python-platform aarch64-apple-darwin \
  --no-build-package numpy --no-build-package scipy \
  --no-build-package numba --no-build-package llvmlite
uv build --no-build-isolation
uv run --no-sync python scripts/check_wheel.py
uv run --no-sync python scripts/package_app.py freeze
uv run --no-sync python scripts/package_app.py archive
```

For Apple Silicon Monterey, change the deployment environment variable to `12.3`
and the `.app` declaration to `12.3`. Supporting 12.0–12.2 needs the additional
SciPy artifact work described above. Prefer one reviewed packaging target shared by wheel
selection, bundle metadata, native-payload checks, and release documentation.

Use `uv run --no-sync` after the explicit installation so subsequent commands
preserve the selected environment. Ordinary `uv run`, including `--locked`,
automatically checks and synchronizes it. An already-installed compatible wheel
need not be replaced on every invocation, but new or refreshed dependencies must
not be installed using an unconstrained host target. A fresh freeze environment
also prevents previously installed optional packages or host-built artifacts
from affecting collection. [UV automatic synchronization](https://docs.astral.sh/uv/concepts/projects/sync/#automatic-lock-and-sync)

PyInstaller recommends freezing on the oldest OS intended for support because
collected third-party native binaries can depend on newer system libraries.
Targeted wheel selection on a newer macOS runner is a candidate approach that
still needs native-binary audit and execution on the older OS. It is not a
substitute for macOS 12 or 13 acceptance. [PyInstaller macOS compatibility](https://pyinstaller.org/en/stable/usage.html#making-macos-apps-forward-compatible)

Do not assume switching GitHub Actions to an old hosted runner is available. The
current repository has only an Apple Silicon macOS 14 packaging candidate. An
older physical Mac, permitted virtual machine, or suitable self-hosted runner
can supply target-system validation; Intel needs its own build and validation.

## Intel analysis compatibility

The concrete binary candidates are Numba 0.62.1, llvmlite 0.45.1, and NumPy
2.3.5. Each has Python 3.12 Intel macOS wheels; the first two target macOS 10.15
and NumPy targets 10.13. Numba 0.62.1 requires `llvmlite>=0.45.0dev0,<0.46` and
`numpy>=1.22,<2.4`, and supports Python 3.12. SciPy 1.18.1 requires
`numpy>=2.0,<2.8`, and scikit-learn 1.9.1 requires `numpy>=1.24.1`, so their
declared requirements admit that NumPy selection.
[Numba 0.62.1 metadata](https://pypi.org/pypi/numba/0.62.1/json),
[llvmlite 0.45.1 files](https://pypi.org/project/llvmlite/0.45.1/#files),
[NumPy 2.3.5 files](https://pypi.org/project/numpy/2.3.5/#files),
[SciPy metadata](https://pypi.org/pypi/scipy/1.18.1/json),
[scikit-learn metadata](https://pypi.org/pypi/scikit-learn/1.9.1/json)

The smallest dependency expression is a Numba `>=0.62.1,<0.63` constraint scoped
to `sys_platform == 'darwin' and platform_machine == 'x86_64'`. Numba's existing
metadata then selects the older llvmlite and NumPy compatibility ranges. The
current direct NumPy requirement `>=2.2,<3` admits NumPy 2.3.5, so a global
NumPy downgrade is unnecessary. Adding Numba as a marker-scoped direct
dependency would make that compatibility requirement visible in the project's
published package metadata as well as UV resolution. A UV-only constraint has a
narrower scope and does not communicate the requirement to other installers.

Librosa can remain at 0.11.0: its declared requirements admit this Numba and NumPy
combination. The application does not import or call Numba or llvmlite directly;
Librosa supplies that implementation detail. A static scan of the application
found 51 direct NumPy attribute names, all represented in NumPy 2.3.5's wheel
source or stubs. Used functions include reductions, interpolation, STFT-related
array preparation, `linalg.norm`, and `random.default_rng`. This supports an
inference that no NumPy API adaptation is needed; call signatures, numerical
results, and compilation behavior were not executed or verified.
[Librosa 0.11 metadata](https://pypi.org/pypi/librosa/0.11.0/json),
[NumPy 2.3.5 package](https://pypi.org/project/numpy/2.3.5/)

The existing frozen-runtime setting
`NUMBA_CACHE_LOCATOR_CLASSES=UserWideCacheLocator` is supported by Numba 0.62.1:
its caching code resolves that named locator and handles frozen executables.
The app therefore does not appear to need a cache workaround for the Intel
selection. Frozen execution and writable per-user cache creation remain
unverified. [Numba 0.62.1 cache implementation](https://github.com/numba/numba/blob/0.62.1/numba/core/caching.py#L225)

The developer group presents a separate Intel installation issue: locked Mypy
2.3.1 also lacks an Intel macOS wheel. A freeze environment using `--no-dev`
avoids that build-only dependency. Run packaging QA in an appropriately prepared
development environment; do not infer that Mypy's wheel availability raises the
application's runtime minimum.

## Optional learned analysis

The standard freeze already excludes `torch`, `torchaudio`, and `demucs` and its
documented baseline includes ordinary Synesthesia analysis. The
`synesthesia-gpu` extra is a separate optional installation, with Torch 2.14.0
on macOS in the lock. Its Python 3.12 Apple Silicon wheel targets macOS 14, so
the unchanged extra is not compatible with the requested older systems.

An Apple Silicon extra candidate can keep the current declared lower bound and
constrain macOS Torch to `>=2.11,<2.12`: Torch 2.11.0 provides a macOS 11 wheel,
including on the configured PyTorch CPU index, while 2.12.0 and later provide
macOS 14 wheels. Torchaudio 2.11.0's macOS wheel also targets 11.0. Demucs 4.1.0
remains a separate API and model validation task. This optional candidate has
not been resolved as a full installation or executed.
[Torch 2.11 files](https://pypi.org/project/torch/2.11.0/#files),
[configured Torch CPU index](https://download.pytorch.org/whl/cpu/torch/),
[Torch 2.12 files](https://pypi.org/project/torch/2.12.0/#files),
[Torch 2.14 files](https://pypi.org/project/torch/2.14.0/#files),
[Torchaudio 2.11 files](https://pypi.org/project/torchaudio/2.11.0/#files)

Intel optional learned analysis needs a larger dependency review because recent
Torch releases do not publish Intel macOS wheels. Torch and Torchaudio 2.2.2
have Python 3.12 Intel wheels, but they violate the project's existing 2.11
lower bounds, and using them requires checking model-loading, NumPy ABI, Demucs,
and Torchaudio behavior. Do not fold that separate undertaking into a claim of
minimal changes to the current native baseline.
[Torch 2.2.2 files](https://pypi.org/project/torch/2.2.2/#files),
[Torchaudio 2.2.2 files](https://pypi.org/project/torchaudio/2.2.2/#files)

## Application Qt and native API audit

Qt's support tables document macOS 12 for 6.9 and macOS 13 for 6.10/6.11; the
inspected newer PySide bindings nevertheless declare 15.0, as detailed above.
Restrict macOS PySide6 to the inspected `==6.9.3`, with the current requirement
retained on other platforms, to pursue either target. A wider `>=6.9.3,<6.10`
constraint is possible once future patch artifacts are inspected. A global
change would extend the Qt version review to Windows and Linux.
[Qt 6.9 macOS support](https://doc.qt.io/archives/qt-6.9/macos.html),
[Qt 6.10 macOS support](https://doc.qt.io/qt-6.10/macos.html),
[PySide6 6.9.3 files](https://pypi.org/project/PySide6/6.9.3/#files)

Keeping macOS on Qt 6.9.3 while other platforms use 6.11.2 adds a small
compatibility path and requires reviewing fixes available in newer Qt releases
when maintaining the macOS branch. No baseline feature removal is indicated by
the inspected imports and calls, but retaining behavior is still a runtime
acceptance requirement.

For macOS 13, an alternative is maintaining a custom PySide6/Shiboken 6.11 build
with deployment target 13 and the matching Qt 6.11 frameworks. Upstream build
documentation supports `--macos-deployment-target` provided it is no lower than
Python and Qt's deployment targets. That could preserve current application API
calls, but adds wheel building, artifact maintenance, and validation. It is a
candidate rather than a tested build, and is more packaging work than using the
existing 6.9.3 wheels with localized adaptations.
[PySide macOS deployment build option](https://github.com/pyside/pyside-setup#macos-minimum-deployment-target)

The accompanying static audit compared 182 unique PySide imports across six
modules with the PySide6 6.9.3 Windows wheel stubs; all those imported names are
present. A scan of 500 named attribute chains found one relevant missing enum:
`QSortFilterProxyModel.Direction`. This is a source and binding-availability
inspection, not proof of macOS runtime behavior.

`endFilterChange` and its `Direction` enum were introduced in Qt 6.10, while
`beginFilterChange` exists in 6.9. The application has 11 row-filter completion
calls requiring adaptation: seven in
`src/iOpenPod/app/models/library_filter_models.py`, three in
`src/iOpenPod/app/models/sync_plan_table_model.py`, and one in
`src/iOpenPod/app/models/photo_list_model.py`. The Qt 6.9 equivalent is
`invalidateRowsFilter()` after the existing `beginFilterChange()` and state
update. A shared compatibility helper can select the appropriate completion
method while newer platforms retain their current calls. Both APIs are intended
for row-filter invalidation; retained selection and incremental model updates
still need verification. [Qt row-filter API versions](https://doc.qt.io/qt-6/qsortfilterproxymodel.html#endFilterChange),
[Qt 6.9 row-filter invalidation](https://doc.qt.io/archives/qt-6.9/qsortfilterproxymodel.html#invalidateRowsFilter)

Two Synesthesia renderer calls also need explicit byte lengths with the older
binding: `QRhiResourceUpdateBatch.updateDynamicBuffer(buffer, offset, data)` in
`src/iOpenPod/GUI/synesthesia/renderer.py` at lines 812 and 1196. An isolated
PySide6 6.9.3 Windows Null-backend probe rejected that three-argument form and
accepted `updateDynamicBuffer(buffer, offset, len(data), data)`. The existing
`uploadStaticBuffer(buffer, data)` form worked in that probe. These findings
identify a narrow call-signature adaptation; actual Metal buffer updates remain
unverified. The same isolated probe accepted the four-argument bytes form in
the current Windows 6.11.2 binding too. Older stubs annotate the data argument as
`int`, despite accepting bytes at runtime, so a narrow typed compatibility helper
may be needed to keep the authoritative Mypy checks clean.

All 12 existing compiled `.qsb` shader assets deserialized as valid with five
shader variants each in the isolated PySide6 6.9.3 probe. That evidence does not
show that shaders must be regenerated, and it does not establish that Metal
pipeline creation or rendering succeeds on Monterey. No newer QMediaPlayer
`pitchCompensation` or `playbackOptions` API use was found in application source.

The native macOS source review found no clear newer-OS requirement in the used
MediaPlayer/AppKit selectors, Storage's IOKit/SCSITask observations, `diskutil`
and `ioreg`, or filesystem attribute APIs. Apple's macOS 12-era XNU header
matches the application's full `__DARWIN_STRUCT_STATFS64` ABI, including
`f_flags_ext` and seven reserved fields. PyObjC's upstream availability checks
place the used now-playing playback constants, default rate, external content
identifier, and remote-command `addTargetWithHandler` API at 10.12. The optional
`ExcludeFromSuggestions` property was introduced in 15.0 and is already guarded
by the application's `_optional_string` lookup. These are source-supported
compatibility inferences; device discovery, safe removal, metadata updates, and
media keys still require execution on the actual older OS.
[Apple XNU macOS 12-era filesystem ABI](https://github.com/apple-oss-distributions/xnu/blob/xnu-8019.80.24/bsd/sys/mount.h),
[PyObjC now-playing availability checks](https://github.com/ronaldoussoren/pyobjc/blob/main/pyobjc-framework-MediaPlayer/PyObjCTest/test_mpnowplayinginfocenter.py),
[PyObjC remote-command availability checks](https://github.com/ronaldoussoren/pyobjc/blob/main/pyobjc-framework-MediaPlayer/PyObjCTest/test_mpremotecommand.py)

## Evidence and remaining acceptance

Read-only UV 0.12.7 dry-run inspections of the current lock, without changing the
Windows environment, produced these results:

| Requested target | Result |
| --- | --- |
| Apple Silicon macOS 13 | Installation plan succeeds with source builds blocked for NumPy, SciPy, Numba, and llvmlite; this trusts wheel tags and does not detect the actual Qt binding minimum of 15 |
| Apple Silicon macOS 12 | Fails on locked PySide6 6.11.2 when its source build is blocked; its wheel tag requires 13 |
| Intel macOS 13 | Fails on locked Numba 0.67.0 when its source build is blocked; no Intel macOS wheel exists |

A scratch-only copy of the complete project metadata and lock was then updated
with macOS `PySide6==6.9.3` and Intel macOS `Numba>=0.62.1,<0.63`. UV resolved
the full universal lock, including optional groups, to 139 package records.
Baseline plus packaging dry-runs used `--no-dev --no-install-project --no-build`
with the explicit target platform and deployment environment variable. Each
produced a complete 56-package plan without installing or building anything:

| Candidate target | Selected analysis stack | Result |
| --- | --- | --- |
| Apple Silicon macOS 12.3 | NumPy 2.5.3, Numba 0.67.0, llvmlite 0.49.0 | Complete binary-only baseline and packaging plan |
| Apple Silicon macOS 13 | Same Apple Silicon selection | Complete binary-only baseline and packaging plan |
| Intel macOS 13 | NumPy 2.3.5, Numba 0.62.1, llvmlite 0.45.1 | Complete binary-only baseline and packaging plan |
| Intel macOS 12.3 | Same Intel selection | Complete binary-only baseline and packaging plan |

All four candidates selected PySide6 6.9.3, SciPy 1.18.1, and scikit-learn
1.9.1. The optional GPU extra was not selected for these installation plans.
The source project's `pyproject.toml` and `uv.lock` were unchanged.

These are dependency-selection observations, not macOS import tests. No test
suite, frozen build, or full application execution was performed. Narrow isolated
Qt binding and shader-deserialization probes were run on Windows as described
above; none exercised a macOS native backend.

Before claiming support, inspect every collected Mach-O slice, including Qt
frameworks and plugins, Qt's FFmpeg playback libraries, Python, native extension
modules, and embedded numerical/audio libraries. Read `LC_BUILD_VERSION` or
`LC_VERSION_MIN_MACOSX` and confirm each relevant minimum is at or below the
declared target. Inspect linkage for unavailable non-weak system symbols as
well: lowering `Info.plist` or rewriting a deployment version does not make an
incompatible binary safe. Retain the native inventory with the candidate.

Run the existing frozen `--smoke-test` outside the checkout on each promised OS
and architecture without installed Python. That mode explicitly imports and
exercises the analysis stack; normal application startup does not invoke the
entire `check_runtime` routine. Follow with actual GUI launch, playback, graphics
and Synesthesia rendering, analysis of representative audio, MediaPlayer keys,
Storage discovery, safe removal, Sync, and recovery using an authorized test
device or virtual Volume. User-installed FFmpeg/FFprobe/fpcalc binaries need
their own compatibility with the target OS; their launchability is not decided
by the application's Python wheels.

Changing Qt, Numba, llvmlite, or NumPy selections also requires refreshing the
corresponding native-library provenance and licensing evidence under
`packaging/third-party`. A target deployment choice should be recorded as an ADR
once chosen. Existing Mac App Store sandbox and signing release gates in
`docs/packaging.md` remain independent of this minimum-OS investigation.
