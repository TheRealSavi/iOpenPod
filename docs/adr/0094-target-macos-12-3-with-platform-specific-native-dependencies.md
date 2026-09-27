# ADR-0094: Target macOS 12.3 with platform-specific native dependencies

- Status: Accepted
- Date: 2026-09-27

## Context

The existing app declares macOS 13 in its bundle metadata. Inspection of the
locked PySide 6.11.2 wheels found Python binding libraries requiring macOS 15,
despite wheel tags advertising macOS 13. Raising the floor would exclude otherwise
capable Macs. Qt 6.9.3's inspected universal binaries declare macOS 12.0; the
locked SciPy Apple Silicon wheel raises the standard analysis floor to 12.3.

Recent Numba and llvmlite releases no longer provide Intel macOS wheels. A newer
builder can also select NumPy and SciPy wheel variants requiring macOS 14 unless
installation uses the intended deployment target.

See the [dependency and binary investigation](../research/macos-compatibility.md)
for artifact hashes, API comparisons, and the limits of this evidence.

## Decision

Target macOS **12.3 or later**, with separate Apple Silicon and Intel native
candidates. Keep Python 3.12 and ordinary application functionality, including
playback, Synesthesia rendering, and standard analysis.

- Pin PySide to the inspected **6.9.3** artifacts on macOS. Windows and Linux
  retain the existing PySide 6.11.2 minimum.
- Constrain Numba to **0.62.x** on Intel macOS. The lock selects 0.62.1,
  llvmlite 0.45.1, and NumPy 2.3.5 there. Other platforms retain their existing
  numerical versions.
- Complete row-filter changes through a shared Qt compatibility function. Qt 6.9
  uses `invalidateRowsFilter`; newer Qt uses `endFilterChange(Direction.Rows)`.
- Use QRhi's explicit buffer-size upload overload, accepted by both binding
  versions. Document the older binding's inaccurate pointer annotations through a
  narrow typed interface. Keep the existing compiled shaders.
- Store the deployment target and packaging Python version in
  `tool.iopenpod.packaging` in `pyproject.toml`. The Mac environment preparation,
  bundle metadata, freeze subprocess, and binary check consume that configuration.
- Install with UV-managed Python 3.12.14, explicit architecture tags, and
  `MACOSX_DEPLOYMENT_TARGET=12.3`. Require third-party wheels and keep dev tools out
  of the freeze environment. A separate `packaging-checks` group supplies the
  existing CI packaging checks without installing the Intel-unavailable Mypy wheel.
- Use `uv run --no-sync` after this controlled installation. Check every bundled
  Mach-O slice's architecture, platform, and deployment minimum, retaining a
  hash-addressed inventory. Reject newer requirements; never lower binary headers.

The native baseline continues to exclude the optional `synesthesia-gpu` extra.
Supporting that extra on older macOS is a separate dependency and packaging
decision; its current dependency requirements do not establish 12.3 compatibility.

## Consequences

macOS maintains an older Qt line and Intel maintains an older numerical stack.
Dependency updates require reviewing their fixes, wheel availability, and actual
binary targets. The bundle check catches deployment regressions even when wheel
tags are incorrect.

Qt 6.9's generated type annotations have additional defects, including missing
public fields, untyped Slot decorators, and inaccurate nullable return values.
The current Windows environment passes Mypy; replacing its Qt stubs with the 6.9.3
stubs produces annotation errors throughout existing code. A clean Mac development
type-check environment requires a separate typing correction. This change does
not weaken the project's Mypy rules or claim that the older stubs pass them.

Compilation and launch on newer CI runners do not establish compatibility with
every system symbol or the Metal backend on 12.3. Acceptance on **macOS 12.3 on
both architectures** remains required before claiming verified support. It must
cover launch, playback, standard analysis, Synesthesia's Metal pipelines, system
media integration, discovery, and safe Storage workflows. Source-derived notices
and corresponding source for the Mac-specific Qt and Intel dependency versions
must also be completed before public distribution.

The existing signing, App Sandbox, user-installed media-tool integration, and
store acceptance gates remain applicable. This decision establishes the native
compatibility target and build controls, not store approval.
