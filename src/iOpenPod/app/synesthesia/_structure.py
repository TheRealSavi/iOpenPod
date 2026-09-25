"""Complete-song Section discovery and motif grouping."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from typing import TYPE_CHECKING

import numpy as np

from ._signals import FloatArray, as_float, robust_unit, smooth
from .models import (
    EventKind,
    MusicalEvent,
    MusicSection,
    SectionProfile,
    TimeGrid,
)

if TYPE_CHECKING:
    from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class StructureResult:
    sections: tuple[MusicSection, ...]
    novelty: FloatArray
    section_progress: FloatArray
    events: tuple[MusicalEvent, ...]


def analyze_structure(
    descriptors: FloatArray,
    *,
    grid: TimeGrid,
    duration_seconds: float,
    audibility: FloatArray,
    relative_energy: FloatArray,
    brightness: FloatArray,
    harmonicity: FloatArray,
    percussiveness: FloatArray,
) -> StructureResult:
    """Discover salient boundaries without forcing a duration-derived count."""

    frame_rate = 1.0 / grid.step_seconds
    if float(np.percentile(audibility, 95)) < 0.05:
        section = MusicSection(
            "section-1",
            "A",
            0.0,
            duration_seconds,
            0.25,
            SectionProfile(0.0, 0.0, 0.0, 0.0),
        )
        return StructureResult(
            (section,),
            np.zeros(grid.frame_count, dtype=np.float32),
            np.linspace(0.0, 1.0, grid.frame_count, dtype=np.float32),
            (),
        )
    coarse_step = max(1, round(frame_rate * 0.5))
    coarse = _coarsen(descriptors, coarse_step)
    centered = coarse - np.mean(coarse, axis=0)
    standardized = (centered / np.maximum(np.std(coarse, axis=0), 0.1)).astype(
        np.float32
    )
    novelty_coarse = _novelty(standardized)
    count = len(novelty_coarse)
    minimum_gap = max(3, round(5.5 / 0.5))
    maximum_sections = max(2, min(24, round(duration_seconds / 12.0) + 2))
    candidates = [
        index
        for index in range(minimum_gap, max(minimum_gap, count - minimum_gap + 1))
        if novelty_coarse[index] >= 0.30
        and novelty_coarse[index] >= novelty_coarse[index - 1]
        and novelty_coarse[index] >= novelty_coarse[index + 1]
    ]
    selected: list[int] = []
    for candidate in sorted(candidates, key=novelty_coarse.__getitem__, reverse=True):
        if all(abs(candidate - prior) >= minimum_gap for prior in selected):
            selected.append(candidate)
        if len(selected) >= maximum_sections - 1:
            break
    boundaries = [0, *sorted(selected), count]
    full_boundaries = np.asarray(
        [min(grid.frame_count, boundary * coarse_step) for boundary in boundaries],
        dtype=np.int32,
    )
    full_boundaries[-1] = grid.frame_count
    sections = _sections(
        standardized,
        boundaries,
        full_boundaries,
        novelty_coarse,
        grid,
        duration_seconds,
        relative_energy,
        brightness,
        harmonicity,
        percussiveness,
    )
    full_index = np.arange(grid.frame_count)
    coarse_index = np.minimum(np.arange(count) * coarse_step, grid.frame_count - 1)
    novelty = np.interp(full_index, coarse_index, novelty_coarse).astype(np.float32)
    section_index = np.clip(
        np.searchsorted(full_boundaries[1:], full_index, side="right"),
        0,
        len(sections) - 1,
    )
    starts = full_boundaries[section_index]
    ends = full_boundaries[section_index + 1]
    progress = np.clip(
        (full_index - starts) / np.maximum(ends - starts, 1), 0.0, 1.0
    ).astype(np.float32)
    events = tuple(
        MusicalEvent(
            event_id=f"section-boundary-{index}",
            kind=EventKind.SECTION_BOUNDARY,
            seconds=section.start_seconds,
            strength=float(np.clip(novelty_coarse[boundaries[index]], 0.0, 1.0)),
            confidence=section.confidence,
        )
        for index, section in enumerate(sections[1:], start=1)
    )
    return StructureResult(sections, novelty, progress, events)


def _coarsen(descriptors: FloatArray, step: int) -> FloatArray:
    return np.stack(
        [
            np.mean(descriptors[left : min(len(descriptors), left + step)], axis=0)
            for left in range(0, len(descriptors), step)
        ]
    ).astype(np.float32)


def _novelty(descriptors: FloatArray) -> FloatArray:
    count = len(descriptors)
    context = max(3, round(4.0 / 0.5))
    novelty = np.zeros(count, dtype=np.float32)
    for index in range(1, count - 1):
        left = max(0, index - context)
        right = min(count, index + context)
        before = np.mean(descriptors[left:index], axis=0)
        after = np.mean(descriptors[index:right], axis=0)
        novelty[index] = float(np.linalg.norm(after - before))
    novelty[:context] = 0.0
    novelty[-context:] = 0.0
    novelty = smooth(novelty, 2)
    if float(np.percentile(novelty, 95)) < 0.15:
        return np.zeros(count, dtype=np.float32)
    return robust_unit(novelty)


def _sections(
    descriptors: FloatArray,
    boundaries: list[int],
    full_boundaries: NDArray[np.int32],
    novelty: FloatArray,
    grid: TimeGrid,
    duration_seconds: float,
    relative_energy: FloatArray,
    brightness: FloatArray,
    harmonicity: FloatArray,
    percussiveness: FloatArray,
) -> tuple[MusicSection, ...]:
    means: list[FloatArray] = []
    labels: list[str] = []
    result: list[MusicSection] = []
    for index, (left, right) in enumerate(pairwise(boundaries)):
        mean = as_float(np.mean(descriptors[left:right], axis=0))
        mean /= np.linalg.norm(mean) + 1e-8
        label = _motif_label(index, mean, means, labels)
        means.append(mean)
        labels.append(label)
        full_left = int(full_boundaries[index])
        full_right = int(full_boundaries[index + 1])
        start_seconds = (
            0.0 if index == 0 else min(duration_seconds, grid.time_at(full_left))
        )
        end_seconds = (
            duration_seconds
            if index == len(boundaries) - 2
            else min(duration_seconds, grid.time_at(full_right))
        )
        result.append(
            MusicSection(
                section_id=f"section-{index + 1}",
                label=label,
                start_seconds=start_seconds,
                end_seconds=max(start_seconds + grid.step_seconds, end_seconds),
                confidence=float(
                    np.clip(
                        0.55 if index == 0 else 0.45 + 0.50 * novelty[left], 0.0, 0.96
                    )
                ),
                profile=SectionProfile(
                    _bounded_mean(relative_energy, full_left, full_right),
                    _bounded_mean(brightness, full_left, full_right),
                    _bounded_mean(harmonicity, full_left, full_right),
                    _bounded_mean(percussiveness, full_left, full_right),
                ),
            )
        )
    return tuple(result)


def _motif_label(
    index: int,
    descriptor: FloatArray,
    previous: list[FloatArray],
    labels: list[str],
) -> str:
    for prior, candidate in enumerate(previous):
        if float(np.dot(descriptor, candidate)) >= 0.82:
            return labels[prior]
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    quotient, remainder = divmod(index, len(alphabet))
    return (
        alphabet[remainder] if quotient == 0 else f"{alphabet[remainder]}{quotient + 1}"
    )


def _bounded_mean(values: FloatArray, left: int, right: int) -> float:
    right = max(left + 1, min(len(values), right))
    return float(np.clip(np.mean(values[left:right]), 0.0, 1.0))


__all__ = ["StructureResult", "analyze_structure"]
