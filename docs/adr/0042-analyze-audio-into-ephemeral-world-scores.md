# ADR-0042: Analyze audio into ephemeral World Scores

- Status: Accepted
- Date: 2026-09-13

## Context

Synesthesia needs substantially more musical understanding than a renderer-facing
FFT or a collection of independently normalized scalars. Whole-Track analysis may
run before visualization, so it can use source separation, learned embeddings,
structural recurrence, future context, and expensive GPU inference. The renderer
must not coordinate model libraries or reinterpret their incompatible frame rates,
confidence signals, and failure modes.

Analysis is distinct from Playback. Its input is an explicitly selected audio file,
not a Playback Source or transport stream. Persisting decoded audio, separated
stems, embeddings, or Track-specific scores is not desired. Static installed model
weights must remain reusable or every Job would require a model download.

## Decision

The Application Layer defines a `MusicUnderstandingBackend` with one operation that
accepts an explicit audio-file path, `AnalysisRequest`, cancellation checkpoint,
and progress callback and returns an immutable `WorldScore`.

The `WorldScore` is the only renderer-facing musical-analysis contract. It retains
multi-rate fields, distributions, and embeddings rather than flattening every model
into scalar controls. Values carry confidence, validity, provenance, interpolation,
units, and optional attack, release, and maximum-slew guidance. Sparse events,
Source Objects, hierarchical structure, relationships, motif returns, and known
future evidence remain first-class data. A `WorldMoment` supplies one coherent
time sample and an event lookahead without hiding the complete fields.

Each Job decodes its selected file into memory and computes a new score. The module
has no Track-derived load, save, cache-key, or reuse operation and writes no PCM,
stems, embeddings, or World Score. Static model weights are application resources
and may remain in provider-managed stores.

A deterministic spectral-musical interpreter is always present. An optional locked
GPU dependency set contributes Beat This! beat/downbeat inference, HTDemucs Source
Objects, TorchCrepe vocal and bass pitch, LAION CLAP semantic trajectories, and an
ONNX Runtime CUDA foundation. Providers merge by stable feature identity. One
provider failure becomes a typed degradation issue and does not discard evidence
from successful providers or the deterministic interpreter.

## Consequences

- Frontend code depends on stable musical concepts, not librosa arrays, Torch
  tensors, model checkpoints, or one fixed feature list.
- Renderers can use perceptually restrained control samples while advanced systems
  consume full distributions, embeddings, events, sources, and structure.
- Analysis can take substantial time and memory and must run outside the GUI thread.
- Every Job repeats audio decoding and Track-derived computation by design.
- The normal application installation gains NumPy and librosa. GPU inference remains
  optional because its dependency and model footprint is large.
- Provider versions and confidence remain visible, so model replacements do not
  silently change the meaning of a score.
