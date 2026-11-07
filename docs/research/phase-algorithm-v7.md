# Phase algorithm version 7 evaluation

Date: 2026-11-01. Decision:
[ADR-0222](../adr/0222-anchor-phase-attacks-to-percussion.md).

## Reproduced failure and policy

An authored drum attack preceded by a melodic attack three frames earlier
(34.83 ms) was discarded by the version-6 chronological duplicate merge. The
regression initially failed with retained frames 37/137/237 instead of drum
frames 40/140/240. Version 7 retains the measured percussion timing for both
earlier and later melodic competition, with acoustic or separated evidence.

Percussion gets a bounded 1.5 whole-vector preference, compared with 1.15 for
melodic foreground. Gains never stack. The shared spectral scale, spectral band
ratios, and five-bit quantizer remain. Eligible drum patterns anchor passages;
hooks and other melodic evidence remain available during drum breaks. Acoustic
HPSS attack magnitude qualifies the percussion preference without requiring the
optional model. This is an iOpenPod policy, not recovered iTunes analysis.

## Read-only full-song comparison

The user requested yeule's *softscars*. Five local FLAC files were available.
The complete recordings were analyzed, rather than selecting favorable excerpts.
Version 6 and version 7 reuse exactly the same mono PCM and separated source
arrays. The pinned provider identifies itself as
`demucs-4.1.0-5c90dfd2-torch-2.14.0+cu130-cuda-shifts0`.

| Local Track | Duration (ms) | SHA-256 |
| --- | ---: | --- |
| softscars | 206099 | `684a3304f4f477f4c1b54fb071878a7ecb3c01ce1b8c21e35985ab24b54aea2c` |
| inferno (edit) | 139920 | `8fb136df0c7a14bb2b0286f43605b16dcdc176e12b2d5230b3a14db4108092de` |
| dazies | 264854 | `aad8adbb048a4fe96273f32ba4f041289c79ba9f232665adf42e1afef41a1d01` |
| ghosts | 220776 | `bf418a33892ff4808fb88f08abff0629aba990ae917b5ae305ffec0d8d6eb199` |
| sulky baby | 278998 | `17de47e7b85a03453f09b69f79e82f336b84bdb832312628bd67e1fd5f012e25` |

The unchanged build-3168002 ARM converter accepted all 20 charts on Hard
(five Tracks, two algorithms, acoustic/source-assisted modes). Every output
matched the Windows translation's tap and annotation payloads, callback order,
and marker strings. Pulse records compare exactly equal between versions in
both modes on all five Tracks. Original recordings and device files were not modified.

For a fixed reference, drum attacks are detected once from the cached separated
drum novelty, with the existing 12% audibility threshold against combined source
RMS. A native tap matches if it lies within 35 ms of any reference attack. These
are inferred drum observations, not hand-annotated ground truth; dense attacks
can create incidental matches. Identical references and windows apply to both
versions. Tap counts exclude native sweeps and checkpoints.

Source-assisted Hard output:

| Track | v6 taps | v7 taps | v6 drum matches, 35 ms | v7 drum matches, 35 ms | v6/v7 drum matches, 60 ms |
| --- | ---: | ---: | ---: | ---: | --- |
| softscars | 406 | 406 | 198 | 197 | 225 / 220 |
| inferno (edit) | 289 | 295 | 182 | 202 | 196 / 206 |
| dazies | 493 | 495 | 261 | 265 | 281 / 276 |
| ghosts | 376 | 370 | 117 | 119 | 125 / 120 |
| sulky baby | 496 | 499 | 199 | 210 | 215 / 215 |

At 35 ms, source-assisted matches total 957/2060 taps in version 6 and
993/2065 in version 7 (46.5% to 48.1%). Improvement is concentrated in
*inferno (edit)* and *sulky baby*. At 60 ms the aggregate is slightly lower,
1042 versus 1037, so the evidence supports modestly tighter drum alignment,
not a uniform increase in percussion coverage or a demonstrated improvement
in physical play feel.

Acoustic Hard tap counts change from 395/287/474/368/485 to
398/287/475/367/485. Their 35 ms matches change from 196/178/254/114/193 to
200/180/252/114/193. This path changes less than source-assisted analysis;
HPSS cannot guarantee an instrument identity, particularly in distorted music.

## Reproduction and validation

Private `.scratch/phase-v7/prepare.py` retains the source hashes, bounded feature
arrays, exact decoded mono PCM, and generated chart records. `evaluate.py` reuses
the existing native adapters and records both matching windows and complete
native sink output. Baseline version-6 charts were captured before implementation
changes; reproducing those charts requires the preceding source revision.
Recordings, separated audio, charts, and game binaries are not committed.

```powershell
uv run python .scratch/phase-v7/prepare.py v7
uv run --with unicorn==2.1.4 python .scratch/phase-v7/evaluate.py v7
```

The 72 focused Phase tests pass, including timing, tempo, silence, spectral
balance, source cancellation, drum breaks, leakage rejection, provenance reuse,
and Storage publication. Physical listening/play acceptance remains open.

Repository validation passes: lock check, Ruff formatting and lint, Rumdl,
and Mypy. The full default eight-worker Pytest run reports **10,119 passed,
47 skipped**, with one existing large-photo Pillow warning, in 235.68 seconds.
