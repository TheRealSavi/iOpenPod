# Genius calmness and vocal-presence evidence

Date: 2026-11-18. Investigation and implementation guidance, not a new accepted
architecture. The requested Focus behavior is very calm music with very few
vocals; occasional calm vocals are acceptable.

Implementation decision: [ADR-0290](../adr/0290-require-rhythm-dynamics-and-vocal-evidence-for-mood-mixes.md).

## Recommendation

Use the existing CPU acoustic analysis to find calm candidates, then optionally
measure bounded, distributed excerpts with the installed Phase source worker.
Keep one retained worker per preparation and serialize its requests. Reuse its
already downloaded six-source Demucs checkpoint. A missing provider, failed
analysis, silence, or incomplete observation means **unknown vocal presence**,
never instrumental. Do not install a new inference stack during ordinary Genius
analysis. This is a proposed reuse of the existing isolated-runtime contract,
not a claim that Phase currently supplies Genius evidence.

Calmness and vocal presence are separate questions. Tempo, spectral activity,
beat strength, dynamics and flatness describe acoustic character; they cannot
identify vocals. ADR-0046 explicitly distinguishes acoustic source families from
learned instrument identity. ADR-0187's original tempo/centroid rules are only
suggestions and do not meet the stronger vocal requirement by themselves.
See [ADR-0046](../adr/0046-preserve-musical-context-in-synesthesia-evidence.md)
and [ADR-0187](../adr/0187-propose-audio-informed-genius-mixes.md).

## Existing application seams

The relevant public imports are:

```python
from iOpenPod.app.phase_parts import HOP, RATE, PhasePartKind
from iOpenPod.app.phase_runtime import ManagedPhaseSources

installed = ManagedPhaseSources.installed()
if installed is not None:
    provider = installed.for_analysis()
    try:
        parts = provider.analyze(
            pcm,
            sample_rate=22_050,
            channels=1,
            checkpoint=checkpoint,
        )
        vocals = next(p for p in parts if p.kind is PhasePartKind.VOCALS)
        actual_provider_identity = provider.identity
    finally:
        provider.close()
```

The caller must handle unavailable/malformed installation receipts and provider
failure separately from cancellation. A preparation should stop retrying a failed
optional provider, preserve successful acoustic profiles and propagate its normal
cancellation/disconnection checkpoint. `for_analysis()` retains one lazy worker;
the instance rejects concurrent analysis. `close()` owns worker termination and
temporary-file cleanup. The actual provider identity can change after GPU-to-CPU
fallback, so capture it after successful analysis. Sources:
[managed provider](../../src/iOpenPod/app/phase_runtime.py),
[worker session](../../src/iOpenPod/app/phase_worker_session.py),
[ADR-0225](../adr/0225-install-optional-phase-analysis-with-safe-fallbacks.md),
[ADR-0226](../adr/0226-reuse-phase-analysis-work-without-changing-gameplay.md).

Existing mono 22,050 Hz float32 PCM is accepted. Internally the provider resamples
to 44,100 Hz and duplicates mono for the stereo model; this does not recover lost
stereo information. It measures six sources in approximately four-second cores
with context and `shifts=0`, returning compact arrays on a 256/22,050-second grid.
Using the same already decoded Genius PCM avoids a second device read. Whole
Phase measurement additionally computes attacks, chroma and magnitudes that Genius
does not need. A future narrow worker request could retain only vocal summaries
without changing Phase chart behavior. Sources:
[source analysis](../../src/iOpenPod/app/phase_sources.py) and
[Part measurement](../../src/iOpenPod/app/phase_parts.py).

Phase's persisted validation cache records chart/source identity and provenance,
not Part arrays. Existing charts cannot supply the missing vocal evidence.
Synesthesia's `DemucsSourceEnricher` independently imports Demucs in the main
environment, uses the four-source `htdemucs` model and whole-track arrays, and
returns runtime-only Track Analysis. It does not discover the managed Phase
installation. Its estimated power-share formula is useful precedent, but its
reconstruction-derived confidence is not a calibrated vocal-presence probability.
Sources: [Phase cache](../../src/iOpenPod/app/phase_cache.py),
[Synesthesia enrichment](../../src/iOpenPod/app/synesthesia/enrichment.py),
[ADR-0046](../adr/0046-preserve-musical-context-in-synesthesia-evidence.md).

## Local installation observed

Read-only inspection found an installation under
`%LOCALAPPDATA%/iOpenPod/PhaseAnalysis`. Its `current.json` selected
`runtime-d6159941489844a5a7c4663017e663b1`. The private environment's `pyvenv.cfg`
reports CPython 3.12.14; package metadata reports Demucs 4.1.0,
Torch 2.14.0+cu130, librosa 0.11.0 and NumPy 2.3.5. Its saved receipt records CUDA;
that is historical installation evidence, not a guarantee about a new request.

The model file is
`models/hub/checkpoints/5c90dfd2-34c22ccb.th`, 54,996,327 bytes, with SHA-256
`34c22ccb381c6f9fdbf324f04e1e2fe21aaaf293f5ded163a162697ff9a02ddd`.
The same checkpoint exists in the user's ordinary Torch cache. No four-source
`htdemucs` checkpoint, EfficientAT, YAMNet or ONNX Runtime installation was found
in the inspected application environments/cache locations. This is a bounded
inventory, not a scan of every disk. No dependency or model was downloaded.

The managed environment's torchaudio metadata reports 2.11.0+cu130, differing
from Torch. Existing Phase deliberately uses librosa for resampling to avoid a
matching torchaudio ABI dependency. Do not assume that this environment can run a
new torchaudio-dependent tagger without its own validation.
Source: [Phase resampling implementation](../../src/iOpenPod/app/phase_sources.py).

## Interpreting estimated vocal activity

`PhasePart.energy` is an amplitude-like spectral RMS value, not power or a class
probability. For source amplitudes `e_s(t)`, define estimated vocal power share
as `e_v(t)^2 / sum(e_s(t)^2)`. Its square root is the corresponding ratio of vocal
amplitude to combined root-sum-square amplitude. Dividing by the sum of amplitudes
is a different statistic and must not use the same thresholds. Source:
[energy calculation](../../src/iOpenPod/app/phase_parts.py).

Suggested policy to calibrate, rather than established model accuracy:

- Gate on audible combined energy before computing ratios. Ignore near-silent
  frames and excerpt boundary padding. Otherwise a tiny vocal residual divided
  by near-zero total energy can appear dominant.
- Retain duration/coverage, mean power share, a high percentile and the fraction
  of observed time with sustained vocal evidence. A single maximum frame is too
  sensitive to leakage and boundary artifacts to establish vocal dominance.
- Measure multiple excerpts across the body, with enough context around each.
  Keep the maximum of excerpt-level summaries as well as duration-weighted
  summaries. Do not dilute one vocal passage by averaging it with long silence.
- Require low vocal evidence for the principal Focus pool. Use a separate,
  explicitly bounded quota for particularly calm tracks with some vocals. A
  per-track threshold alone cannot enforce that a Mix contains few vocal tracks.
- Preserve unknown as a separate value. Genre/title words can be hints, but cannot
  turn an unmeasured track into a measured instrumental track.

Distributed excerpts only establish low observed vocal activity. They can miss a
vocal bridge or late verse. Source separation may leak instruments into vocals or
miss soft, choral, processed and distant vocals. Reduced mono input and short
contexts can also change results. A calm voice is not established by stem power;
the whole-mix calmness gate and limited vocal quota remain necessary. No chosen
threshold makes this a lyric, emotion or ground-truth instrumental classifier.

The native Genius Mix contains candidate seeds; firmware may follow relationships
outside those seeds. Better seed analysis therefore does not guarantee an entirely
calm playback queue. This is an existing product constraint in
[ADR-0187](../adr/0187-propose-audio-informed-genius-mixes.md) and
[the Genius contract](../ipod-genius.md).

## Compact CPU alternatives

EfficientAT is a promising future lower-cost tagger. Its official release lists
`mn01_as_mAP_298.pt` at 612,421 bytes, `mn04_as_mAP_432.pt` at 4,066,513 bytes and
`mn10_as_mAP_471.pt` at 19,708,753 bytes. These filenames encode AudioSet aggregate
mAP, not vocal accuracy. The model registry maps these files to `mn01_as`,
`mn04_as` and `mn10_as`. Sources:
[release metadata](https://api.github.com/repos/fschmid56/EfficientAT/releases/tags/v0.0.1)
and [model registry](https://github.com/fschmid56/EfficientAT/blob/main/models/mn/model.py).

Its label vocabulary includes speech, singing, choir, chant, synthetic singing,
rapping and humming. The official example supports CPU and applies sigmoid to
clip logits in sliding windows. It is not a framewise singing detector by default;
retain the relevant class outputs, not merely its displayed top-ten labels.
Sources: [labels](https://github.com/fschmid56/EfficientAT/blob/main/metadata/class_labels_indices.csv)
and [windowed inference](https://github.com/fschmid56/EfficientAT/blob/main/windowed_inference.py).

The exact pretrained front end uses 32 kHz mono, pre-emphasis 0.97, a nonperiodic
800-sample Hann window, 320-sample hop, 1024-point FFT, 128 Kaldi mel bands and its
own log normalization. Existing Genius mel features are not interchangeable.
The source imports Torch, torchaudio and torchvision; research requirements pin
Torch 1.13/torchaudio 0.13/torchvision 0.14 and older scientific packages. A modern
Windows/Python 3.12 inference-only integration must be separately validated.
Sources: [preprocessing](https://github.com/fschmid56/EfficientAT/blob/main/models/preprocess.py),
[model imports](https://github.com/fschmid56/EfficientAT/blob/main/models/mn/model.py),
[requirements](https://github.com/fschmid56/EfficientAT/blob/main/requirements.txt).

The EfficientAT repository has an
[MIT license](https://github.com/fschmid56/EfficientAT/blob/main/LICENSE).
No first-party ready-to-ship ONNX artifact was identified in the inspected release.
An exported, numerically checked `mn04_as` with ONNX Runtime is a plausible future
package; it is a new maintained asset, not an available dependency-free path.
ONNX Runtime does publish a Windows x64 CPython 3.12 CPU wheel; the observed 1.32.0
wheel is 16.7 MB. Source: [official package files](https://pypi.org/project/onnxruntime/#files).

Google YAMNet is another compact audio-event model: its source uses 16 kHz mono
and overlapping 0.96-second patches, yielding 521 class scores. The current Keras
implementation requires Keras 2 rather than Keras 3. Its research source is
Apache-2.0. This investigation did not qualify a Google-distributed ONNX model or
Windows deployment path. Sources:
[YAMNet source documentation](https://github.com/tensorflow/models/blob/master/research/audioset/yamnet/README.md)
and [source license](https://github.com/tensorflow/models/blob/master/LICENSE).

Essentia provides dedicated voice/instrumental models, but its published model
terms are CC-BY-NC-SA-4.0 or a separately negotiated license. That is a material
distribution tradeoff for a general application and does not justify replacing
the installed stack for this increment. Sources:
[model catalog](https://essentia.upf.edu/models.html) and
[model licensing](https://essentia.upf.edu/licensing_information.html).

Demucs publishes MIT licensing and supports CPU inference. Its `--two-stems=vocals`
option still separates all sources, so it does not save inference time or memory.
The upstream repository is archived; retain a qualified runtime rather than
depending on unbounded upgrades. Sources:
[Demucs documentation](https://github.com/facebookresearch/demucs/blob/main/README.md)
and [repository status](https://github.com/facebookresearch/demucs).

## Bounded local CPU probe

The private reproduction script `.scratch/genius-vocal-probe-20261118.py` read
existing Host PCM captures from the earlier Phase experiment. No device was
opened, no media was changed, and no new recording/model/dependency was downloaded.
It measured the 30–60 second excerpt of each recording, mono float32 at 22,050 Hz,
through the installed `ManagedPhaseSources` worker. CUDA was hidden only from this
probe's child processes; OpenMP/MKL were limited to four threads. The first request
started the worker and loaded the model; the second retained both. The identity
returned by both requests ended in `torch-2.14.0+cu130-cpu-shifts0`.

| Recording | Request time | Mean vocal power share | Vocal amplitude ratio p90 | Vocal amplitude ratio maximum | Frames with vocal power share at least 0.10 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Frank Ocean, Godspeed | 21.58 s | 0.213 | 0.887 | 1.000 | 35.5% |
| Daft Punk, Aerodynamic | 12.13 s | 0.267 | 0.935 | 0.997 | 42.9% |

Here amplitude ratio means `vocals / sqrt(sum(source_amplitude**2))`. The probe
omitted the first/last 0.25 seconds and any frame with combined amplitude below
the larger of `1e-7` and 1% of its 95th-percentile combined amplitude. The retained
mono captures' SHA-256 values are respectively
`373be0d15f15ff4c4787e5e8842aa285de247e896e4cb5cf1a00128a0bc0e9ff` and
`86e07dc251f8684318c3e0a2dd60aa44de47fcceee8390d74f0289ba9dc6389a`.
The private receipt is `.scratch/genius-vocal-probe-20261118.json`.

Two additional calm instrumental candidates were decoded read-only from existing
Host FLACs and measured at the same 30–60 second position in a second retained
worker session. Horizon's request took 15.87 seconds including worker/model
startup; A Quick One took 12.40 seconds warm. Decoding is outside those times.

| Recording | Mean vocal power share | Vocal amplitude ratio p90 | Vocal amplitude ratio maximum | Frames with vocal power share at least 0.10 |
| --- | ---: | ---: | ---: | ---: |
| Daft Punk, Horizon | 0.000000195 | 0.000657 | 0.001439 | 0% |
| Have a Nice Life, A Quick One Before the Eternal Worm Devours Connecticut | 0.0505 | 0.379 | 0.704 | 18.3% |

The source FLAC SHA-256 values are respectively
`ff769a55efc6899484c905b1f5a6ed8fcd242f7efa3554fadaf0434105dbd4f6` and
`1c951f9036a35726babbacb1f482adb3aa942ddcd8e8964ea22a13b9c9c6eac0`.
The private receipt is `.scratch/genius-vocal-probe-calm-20261118.json`.

These are integration/timing observations, not a listening-labelled
benchmark. The instrumental-source candidate Aerodynamic has more estimated vocal
energy than Godspeed under every summarized rule above. At minimum, these data
rule out interpreting a high raw stem ratio as a reliable voice label or assigning
a universal threshold from the model's source name. This failure is particularly
relevant to guitar/synth instrumental music. Horizon shows that the same provider
can return negligible vocal estimates for suitable music. A Quick One's higher
residual demonstrates that stricter thresholds can reject calm instrumental
candidates too. Source identity accuracy, stereo versus mono behavior and longer
contexts need separate evaluation.

No production cutoff is validated by this sample. The candidate application
policy uses one-second windows: mark a window occupied if mean vocal power divided
by mean combined source power is at least 0.10, then admit at most 0.15 occupied
fraction to Focus. These are explicit product heuristics, not confidence levels.
The power threshold corresponds to a root-sum-square amplitude ratio of about
0.316; it must not be applied directly to the amplitude values. High evidence
should reject or defer a candidate, not label it definitively vocal. Low estimates
remain vulnerable to missing soft or unsampled vocals. A single-frame maximum
offers especially poor evidence for a policy allowing occasional vocals.

A further replay called the actual `genius_vocals.vocal_fraction` implementation
on all four excerpts in one retained CPU session. The imported revision omitted
0.5 seconds at each edge and evaluated 29 one-second windows; the implementation
was subsequently changed to omit one second. The latter boundary revision was
not remeasured here.

| Recording | Occupied windows / evaluated windows | Occupied fraction | Vocal gate at 0.15 |
| --- | ---: | ---: | --- |
| Godspeed | 16 / 29 | 0.552 | Excluded |
| Aerodynamic | 16 / 29 | 0.552 | Excluded |
| Horizon | 0 / 29 | 0 | Eligible |
| A Quick One Before the Eternal Worm Devours Connecticut | 3 / 29 | 0.103 | Eligible |

These results concern only the vocal gate; the whole-track acoustic gates must
also pass. They illustrate useful separation of the calm candidates from a sung
example, together with an instrumental false positive. They do not establish
accuracy over a Library or guarantee that all excerpts of these recordings pass.
The corresponding request times were 15.34, 12.42, 12.74 and 12.27 seconds, with
startup only in the first request. The receipt is
`.scratch/genius-vocal-probe-occupancy-20261118.json`. CPU cost is material even
with warm weights; optional inference should remain limited to calm candidates.

## Acceptance still required

Use a listening-labelled corpus including quiet vocals, wordless choir, rap,
instrumental guitar/synth, soft jazz, ambient music, loud instrumental rock and
tracks with a single late vocal passage. Measure false instrumental admissions,
false vocal rejection, timing and peak memory on Windows CPU. Gain changes must
not change vocal ratios materially. Check source changes, model/version changes,
absent/corrupt models, cancellation, worker crashes and sampled coverage. These
are the missing grounds for selecting production thresholds; broad AudioSet mAP
and a successful model invocation do not supply them.

## Full-recording checks with the implemented sampler

The final adapter was also exercised on complete Host recordings, using the
implemented six distributed eight-second windows and one-second edge exclusions.
Acoustic features came from the full body, not just the earlier 30-second excerpt.
No audio or model was downloaded; no iPod files were changed. The receipt is
`.scratch/mix-analysis/full-track-results.json`.

| Recording | Sampled vocal occupancy | Focus with final acoustic rules | Relax |
| --- | ---: | --- | --- |
| Horizon | 0% | yes | yes |
| Godspeed | 64.7% | no | yes |
| A Quick One Before the Eternal Worm Devours Connecticut | 0% | yes | yes |

These checks exposed two acoustic-policy problems before completion. A pronounced
periodic pattern can consist of gentle repeated notes, so rhythmic drive now also
requires spectral activity. Centroid variation can reflect ordinary changes in
pitch and instrumentation, so dynamics lead the steadiness fit. The final fits
were recalculated from the same complete-recording acoustic profiles and retained
vocal evidence after these corrections. These three examples are regression
observations, not a representative accuracy evaluation or a guarantee about
unsampled vocals or native playback.
