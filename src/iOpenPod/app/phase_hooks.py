"""Recognize repeated note phrases and direct instrument-specific Phase events."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from typing import TYPE_CHECKING, Any

import numpy as np

from iPodDB.games import PhaseTransient

from .phase_parts import HOP, RATE, PhasePart, PhasePartKind

_LEAD_BOOST = 1.15
_PERCUSSION_BOOST = 1.5

if TYPE_CHECKING:
    from collections.abc import Callable

    from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class PhaseHook:
    kind: PhasePartKind
    occurrences: tuple[tuple[int, ...], ...]


@dataclass(frozen=True, slots=True)
class PhasePassage:
    first_frame: int
    last_frame: int
    kind: PhasePartKind
    recurring_notes: int


def recognize_hooks(
    part: PhasePart,
    onsets: NDArray[np.int64],
    *,
    checkpoint: Callable[[], None],
) -> tuple[PhaseHook, ...]:
    """Match six-note pitch/rhythm sequences with bounded prototype memory.

    Every occurrence uses its own observed attacks. No event times are copied
    from an earlier performance, and a steady repeated pitch is not a hook.
    """
    prototypes: list[tuple[NDArray[np.float64], NDArray[np.float64], float]] = []
    occurrences: list[list[tuple[int, ...]]] = []
    completed: list[PhaseHook] = []
    for start in range(0, len(onsets) - 5, 3):
        checkpoint()
        frames = onsets[start : start + 6]
        duration = float(frames[-1] - frames[0])
        if not RATE / HOP <= duration <= 12 * RATE / HOP:
            continue
        # Sample just after the attack, where pitch evidence is established.
        pitches = part.chroma[:, np.minimum(frames + 4, len(part.energy) - 1)].T.copy()
        pitches /= np.maximum(np.linalg.norm(pitches, axis=1, keepdims=True), 1e-12)
        rhythm = np.diff(frames).astype(np.float64) / duration
        if (
            np.mean(np.sum(pitches[1:] * pitches[:-1], axis=1, dtype=np.float64)) > 0.98
            and np.std(rhythm) < 0.035
        ):
            continue
        match: int | None = None
        best = 0.9
        for index, (old_pitch, old_rhythm, old_duration) in enumerate(prototypes):
            if frames[0] <= occurrences[index][-1][-1]:
                continue
            if not 0.75 <= duration / old_duration <= 1.33:
                continue
            if float(np.max(np.abs(rhythm - old_rhythm))) > 0.045:
                continue
            similarity = float(
                np.mean(np.sum(pitches * old_pitch, axis=1, dtype=np.float64))
            )
            if similarity > best:
                best, match = similarity, index
        occurrence = tuple(int(frame) for frame in frames)
        if match is not None:
            occurrences[match].append(occurrence)
        elif len(prototypes) < 128:
            prototypes.append((pitches, rhythm, duration))
            occurrences.append([occurrence])
        else:
            # Retire the least recently heard prototype so late-song material
            # has the same opportunity to become a hook as an opening riff.
            oldest = min(range(len(occurrences)), key=lambda i: occurrences[i][-1][-1])
            if len(occurrences[oldest]) >= 2:
                completed.append(PhaseHook(part.kind, tuple(occurrences[oldest])))
            prototypes[oldest] = (pitches, rhythm, duration)
            occurrences[oldest] = [occurrence]
    return tuple(completed) + tuple(
        PhaseHook(part.kind, tuple(items)) for items in occurrences if len(items) >= 2
    )


def direct_parts(
    parts: tuple[PhasePart, ...],
    *,
    beats: list[int],
    length_ms: int,
    checkpoint: Callable[[], None],
    report: Callable[[PhasePassage], None] = lambda passage: None,
    mix_bands: NDArray[np.float64] | None = None,
    mix_energy: NDArray[np.float64] | None = None,
    mix_onsets: tuple[int, ...] = (),
    percussive_onsets: tuple[int, ...] = (),
) -> tuple[PhaseTransient, ...]:
    """Rank audible evidence on one mix scale; parts never replace the mix."""
    import librosa

    if len({part.kind for part in parts}) != len(parts):
        raise ValueError("Phase requires distinct source parts")
    if mix_energy is None:
        if not parts:
            return ()
        mix_energy = np.sqrt(sum(part.energy**2 for part in parts))
    count = len(mix_energy)
    if mix_bands is None:
        mix_bands = sum((part.magnitudes for part in parts), np.zeros((3, count)))
    if mix_bands.shape != (3, count):
        raise ValueError("Phase mix evidence disagrees")
    if any(len(part.energy) != count for part in parts):
        raise ValueError("Phase source timelines disagree")
    total = mix_energy
    active = total > max(float(np.max(total)) * 0.01, 1e-5)
    percussion = {
        frame for frame in percussive_onsets if 0 <= frame < count and active[frame]
    }
    envelopes: list[NDArray[np.float64]] = []
    onsets: list[NDArray[np.int64]] = []
    recurring: list[set[int]] = []
    api: Any = librosa
    for part in parts:
        checkpoint()
        scale = np.asarray(
            [
                max(float(np.percentile(row[row > 1e-5], 95)), 1e-5)
                if np.any(row > 1e-5)
                else 1.0
                for row in part.bands
            ]
        )
        envelope = np.minimum(part.bands / scale[:, None], 2).mean(axis=0)
        audible = active & (part.energy >= np.maximum(total * 0.12, 1e-5))
        envelope[~audible] = 0
        events = np.asarray(
            api.onset.onset_detect(
                onset_envelope=envelope,
                sr=RATE,
                hop_length=HOP,
                units="frames",
                wait=round(0.06 * RATE / HOP),
                delta=0.1,
            ),
            dtype=np.int64,
        )
        envelopes.append(envelope)
        onsets.append(events)
        hooks = recognize_hooks(part, events, checkpoint=checkpoint)
        recurring.append(
            {
                frame
                for hook in hooks
                for occurrence in hook.occurrences
                for frame in occurrence
            }
        )

    # Eight-pulse windows are a decision cadence, not inferred time signatures.
    candidates = sorted(set(beats[::8]) | set(range(0, count, round(4 * RATE / HOP))))
    boundaries = [0]
    for frame in candidates:
        if 0 < frame < count and frame - boundaries[-1] >= round(2 * RATE / HOP):
            boundaries.append(frame)
    boundaries.append(count)
    selected: list[tuple[int, int, bool]] = []
    previous: int | None = None
    for first, last in pairwise(boundaries):
        checkpoint()
        notes = [
            events[np.searchsorted(events, first) : np.searchsorted(events, last)]
            for events in onsets
        ]
        power = np.asarray([np.sum(part.energy[first:last] ** 2) for part in parts])
        shares = power / max(float(np.sum(power)), 1e-12)
        scores = np.zeros(len(parts))
        for index in range(len(parts)):
            if len(notes[index]) < 1 or shares[index] < 0.04:
                continue
            # Prominence, clear attacks, and a recognizable returning phrase.
            clarity = float(np.mean(envelopes[index][notes[index]]))
            repeat = sum(
                int(frame) in recurring[index] for frame in notes[index]
            ) / len(notes[index])
            scores[index] = (
                float(np.sqrt(shares[index])) + min(clarity, 1) * 0.15 + repeat * 0.35
            )
            if previous == index:
                scores[index] += 0.10
        if not np.any(scores):
            previous = None
            continue
        chosen = int(np.argmax(scores))
        # An audible drum pattern anchors the passage even under a recurring
        # melody. A lone hit does not seize focus for the whole passage.
        for index, part in enumerate(parts):
            if (
                part.kind == PhasePartKind.DRUMS
                and scores[index] > 0
                and len(notes[index]) >= 2
            ):
                chosen = index
                break
        previous = chosen
        primary = notes[chosen]
        report(
            PhasePassage(
                first,
                last,
                parts[chosen].kind,
                sum(int(frame) in recurring[chosen] for frame in primary),
            )
        )
        selected.extend((int(frame), chosen, True) for frame in primary)
        # A held lead is not a rest in the accompaniment. Keep audible attacks
        # underneath it; the native game still applies difficulty and spacing.
        # A shared energy scale below keeps quieter accompaniment proportional
        # without penalizing it merely because another source has the lead.
        for index in range(len(parts)):
            if index == chosen or scores[index] <= 0:
                continue
            selected.extend((int(frame), index, False) for frame in notes[index])
    # Magnitudes are measured in linear amplitude units, independently of the
    # normalized novelty used to detect attacks. A single calibration preserves
    # band ordering and quiet sources instead of giving each band its own gain.
    reference_frames = [f for f in mix_onsets if 0 <= f < count and active[f]]
    if not reference_frames:
        reference_frames = [f for f, _, _ in selected]
    peaks = np.max(mix_bands[:, reference_frames], axis=0)
    positive = peaks[peaks > 1e-10]
    amplitude_scale = (
        max(float(np.percentile(positive, 95)), 1e-10) if positive.size else 1.0
    )
    # Melodic sources annotate the mix. Drums anchor to measured acoustic
    # percussion when available, otherwise retain their own observed timing.
    evidence = {
        frame: mix_bands[:, frame].copy()
        for frame in mix_onsets
        if 0 <= frame < count and active[frame]
    }
    anchors = np.asarray(sorted(evidence), dtype=np.int64)
    anchor_set = set(evidence)
    percussion_anchors = np.asarray(sorted(percussion), dtype=np.int64)
    preferred: set[int] = set()
    for frame, source, primary_note in selected:
        checkpoint()
        is_drum = parts[source].kind == PhasePartKind.DRUMS
        targets = percussion_anchors if is_drum else anchors
        position = int(np.searchsorted(targets, frame))
        neighbors = targets[max(0, position - 1) : position + 1]
        nearest = (
            int(neighbors[np.argmin(np.abs(neighbors - frame))])
            if neighbors.size
            else frame
        )
        if abs(nearest - frame) > 4:
            nearest = frame
        value = parts[source].magnitudes[:, frame]
        # Source evidence can fill a missing attack or identify an existing
        # mix attack as belonging to the lead. Apply preference once per event
        # below, so a stronger mix does not hide that musical preference.
        if primary_note:
            preferred.add(nearest)
        if is_drum:
            percussion.add(nearest)
        if nearest in evidence:
            evidence[nearest] = np.maximum(evidence[nearest], value)
        else:
            evidence[nearest] = value.copy()
    for frame in preferred | percussion:
        if frame in evidence:
            evidence[frame] *= _PERCUSSION_BOOST if frame in percussion else _LEAD_BOOST
    # Within the existing duplicate window, measured percussion wins over a
    # melodic anticipation or late syllable. Never snap to an inferred beat.
    retained: list[int] = []
    for frame in sorted(evidence):
        checkpoint()
        if retained and frame - retained[-1] <= 4:
            previous_frame = retained[-1]
            if (frame in percussion and previous_frame not in percussion) or (
                (frame in percussion) == (previous_frame in percussion)
                and previous_frame not in anchor_set
                and (
                    frame in anchor_set
                    or float(np.sum(evidence[frame]))
                    > float(np.sum(evidence[previous_frame]))
                )
            ):
                retained[-1] = frame
        else:
            retained.append(frame)
    result: list[PhaseTransient] = []
    for frame in retained:
        checkpoint()
        timestamp = round(frame * HOP * 65536 / RATE)
        if timestamp >= length_ms * 65536 // 1000:
            continue
        # Compress/cap the whole attack together. Independent clipping can turn
        # a clear primary/alternative ordering into (31, 31, 31) lane ties.
        peak = float(np.max(evidence[frame]))
        gain = 31 * min(peak / amplitude_scale, 1) ** 0.65 / peak if peak > 0 else 0.0
        strengths = tuple(round(float(value) * gain) for value in evidence[frame])
        if any(strengths):
            result.append(PhaseTransient(timestamp, *strengths))
    if len(result) > 20_000:
        # Codec capacity is a separate bound, not difficulty selection. This
        # only applies to exceptionally dense long inputs. Keep the strongest
        # observed attack in each time bucket, so a loud ending cannot evict
        # every quieter event from the beginning. Never synthesize times.
        bounded: dict[int, PhaseTransient] = {}
        duration = length_ms * 65536 // 1000
        for event in result:
            checkpoint()
            bucket = event.time_q16 * 20_000 // duration
            old = bounded.get(bucket)
            if (
                old is None
                or event.low + event.mid + event.high > old.low + old.mid + old.high
            ):
                bounded[bucket] = event
        result = list(bounded.values())
    return tuple(result)
