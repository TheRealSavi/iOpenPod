from __future__ import annotations

import argparse
import io
import math
import os
import random
import shutil
import sys
import time
import wave
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from mutagen.id3._frames import APIC, TALB, TCON, TDRC, TIT2, TPE1, TPE2, TRCK
from mutagen.wave import WAVE
from PIL import Image, ImageDraw, ImageFont
from tqdm import tqdm

ADJECTIVES = [
    "Amber",
    "Broken",
    "Circuit",
    "Crimson",
    "Golden",
    "Hidden",
    "Ivory",
    "Lunar",
    "Midnight",
    "Neon",
    "Quiet",
    "Silver",
    "Solar",
    "Velvet",
    "Wild",
]

NOUNS = [
    "Atlas",
    "Bloom",
    "Cascade",
    "Comet",
    "Drift",
    "Echo",
    "Harbor",
    "Meadow",
    "Mirror",
    "Mosaic",
    "Nova",
    "Parade",
    "Signal",
    "Temple",
    "Valley",
]

GENRES = [
    "Ambient",
    "Electronic",
    "Instrumental",
    "Lo-Fi",
    "Synthwave",
]

FONT_CANDIDATES = ("DejaVuSans-Bold.ttf", "Arial.ttf", "Helvetica.ttf")
DEFAULT_OUTPUT = Path("tests/fixtures/fake_music_library")
DEFAULT_ALBUMS = 4
DEFAULT_TRACKS_PER_ALBUM = 6
DEFAULT_DURATION = 3.0
DEFAULT_SAMPLE_RATE = 22050
DEFAULT_SEED = 160
DEFAULT_ART_SIZE = 640


def _default_workers() -> int:
    return max(1, min(os.cpu_count() or 4, 8))


@dataclass(frozen=True)
class TrackSpec:
    serial: int
    path: Path
    title: str
    artist: str
    album: str
    genre: str
    year: int
    track_number: int
    track_total: int
    art_bytes: bytes


@dataclass(frozen=True)
class GenerationStats:
    created: list[Path]
    elapsed_seconds: float
    prep_seconds: float
    generation_seconds: float
    total_bytes: int
    workers: int


@dataclass(frozen=True)
class MusicalRecipe:
    seed: int
    root_midi: int
    mode: tuple[int, ...]
    chord_degrees: tuple[int, ...]
    melody_degrees: tuple[int, ...]
    melody_rests: tuple[bool, ...]
    signature_offsets: tuple[int, ...]
    bass_pattern: tuple[int, ...]
    kick_hits: tuple[float, ...]
    snare_hits: tuple[float, ...]
    tempo_bpm: float
    tone_color: int
    pulse_depth: float


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a fake WAV music library with metadata and album art."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Destination folder for the generated library.",
    )
    parser.add_argument(
        "--albums",
        type=int,
        default=DEFAULT_ALBUMS,
        help="Number of albums to generate.",
    )
    parser.add_argument(
        "--tracks-per-album",
        type=int,
        default=DEFAULT_TRACKS_PER_ALBUM,
        help="Number of songs per album.",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=DEFAULT_DURATION,
        help="Duration of each WAV file in seconds.",
    )
    parser.add_argument(
        "--sample-rate",
        type=int,
        default=DEFAULT_SAMPLE_RATE,
        help="Sample rate for generated WAV files.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help="Random seed for reproducible names, tones, and artwork.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Delete the output folder first if it already exists.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=_default_workers(),
        help="Number of concurrent track workers.",
    )
    parser.add_argument(
        "--art-size",
        type=int,
        default=DEFAULT_ART_SIZE,
        help="Album art size in pixels. Lower values are faster and produce smaller files.",
    )
    return parser


def _supports_ansi() -> bool:
    return sys.stdout.isatty() and os.environ.get("TERM", "").lower() != "dumb"


def _style(text: str, *codes: str) -> str:
    if not _supports_ansi() or not codes:
        return text
    return f"\033[{';'.join(codes)}m{text}\033[0m"


def _print_wizard_header() -> None:
    width = 68
    print()
    print(_style("=" * width, "38;5;45"))
    print(_style(" Fake Music Library Generator ".center(width), "1", "38;5;45"))
    print(_style("=" * width, "38;5;45"))
    print(_style("Answer each option once. Press Enter to keep the default.", "38;5;252"))
    print()


def _read_prompt(prompt: str) -> str:
    print(prompt, end="", flush=True)
    line = sys.stdin.readline()
    if line == "":
        raise EOFError("Interactive input is not available on this stdin stream.")
    return line.rstrip("\r\n")


def _prompt_text(label: str, default: str) -> str:
    prompt = f"{_style(label, '1', '38;5;111')} [{default}]: "
    value = _read_prompt(prompt).strip()
    return value or default


def _prompt_int(label: str, default: int, *, minimum: int | None = 1) -> int:
    while True:
        raw = _prompt_text(label, str(default))
        try:
            value = int(raw)
        except ValueError:
            print(_style("Enter a whole number.", "38;5;203"))
            continue
        if minimum is not None and value < minimum:
            print(_style(f"Value must be at least {minimum}.", "38;5;203"))
            continue
        return value


def _prompt_float(label: str, default: float, *, minimum: float = 0.1) -> float:
    while True:
        raw = _prompt_text(label, f"{default:g}")
        try:
            value = float(raw)
        except ValueError:
            print(_style("Enter a number like 2.5.", "38;5;203"))
            continue
        if value < minimum:
            print(_style(f"Value must be at least {minimum:g}.", "38;5;203"))
            continue
        return value


def _prompt_bool(label: str, default: bool) -> bool:
    default_hint = "Y/n" if default else "y/N"
    while True:
        raw = _read_prompt(f"{_style(label, '1', '38;5;111')} [{default_hint}]: ").strip().lower()
        if not raw:
            return default
        if raw in {"y", "yes"}:
            return True
        if raw in {"n", "no"}:
            return False
        print(_style("Please answer y or n.", "38;5;203"))


def _prompt_output_path(default_output: Path) -> tuple[Path, bool]:
    while True:
        output = Path(_prompt_text("Output folder", str(default_output))).expanduser()
        force = _prompt_bool("Force overwrite if the folder already exists?", False)
        if output.exists() and not force:
            print(_style(f"{output} already exists. Choose a new folder or enable overwrite.", "38;5;203"))
            default_output = output.with_name(f"{output.name}_new")
            continue
        return output, force


def _print_wizard_summary(
    *,
    output: Path,
    albums: int,
    tracks_per_album: int,
    duration: float,
    sample_rate: int,
    art_size: int,
    workers: int,
    seed: int,
    force: bool,
) -> None:
    total_tracks = albums * tracks_per_album
    total_audio_seconds = total_tracks * duration
    print()
    print(_style("-" * 68, "38;5;45"))
    print(_style(" Planned Run ".center(68), "1", "38;5;45"))
    print(_style("-" * 68, "38;5;45"))
    print(f"  Output      : {output}")
    print(f"  Library     : {albums} albums, {tracks_per_album} tracks each ({total_tracks} total)")
    print(f"  Audio       : {duration:g}s per track at {sample_rate} Hz")
    print(f"  Artwork     : {art_size}px square covers")
    print(f"  Execution   : {workers} workers | seed {seed} | overwrite {'yes' if force else 'no'}")
    print(f"  Payload     : about {total_audio_seconds / 60.0:.1f} minutes of audio")
    print(_style("-" * 68, "38;5;45"))
    print()


def _run_interactive_wizard(parser: argparse.ArgumentParser) -> argparse.Namespace:
    _print_wizard_header()
    output, force = _prompt_output_path(parser.get_default("output"))
    print(_style("Configure the library:", "1", "38;5;153"))
    albums = _prompt_int("Albums", parser.get_default("albums"), minimum=1)
    tracks_per_album = _prompt_int("Tracks per album", parser.get_default("tracks_per_album"), minimum=1)
    duration = _prompt_float("Track duration (seconds)", parser.get_default("duration"), minimum=0.1)
    sample_rate = _prompt_int("Sample rate", parser.get_default("sample_rate"), minimum=8000)
    seed = _prompt_int("Seed", parser.get_default("seed"), minimum=None)
    workers = _prompt_int("Worker threads", parser.get_default("workers"), minimum=1)
    art_size = _prompt_int("Cover art size (px)", parser.get_default("art_size"), minimum=64)

    _print_wizard_summary(
        output=output,
        albums=albums,
        tracks_per_album=tracks_per_album,
        duration=duration,
        sample_rate=sample_rate,
        art_size=art_size,
        workers=workers,
        seed=seed,
        force=force,
    )

    if not _prompt_bool("Generate this library now?", True):
        raise SystemExit("Cancelled.")

    return argparse.Namespace(
        output=output,
        albums=albums,
        tracks_per_album=tracks_per_album,
        duration=duration,
        sample_rate=sample_rate,
        seed=seed,
        force=force,
        workers=workers,
        art_size=art_size,
    )


def pick_unique_pairs(rng: random.Random, count: int) -> list[str]:
    base_names = [f"{adjective} {noun}" for adjective in ADJECTIVES for noun in NOUNS]
    rng.shuffle(base_names)

    if count <= len(base_names):
        return base_names[:count]

    names: list[str] = []
    cycle = 0
    while len(names) < count:
        for base_name in base_names:
            if cycle == 0:
                names.append(base_name)
            else:
                names.append(f"{base_name} {cycle + 1:03d}")
            if len(names) == count:
                break
        cycle += 1
    return names


def safe_name(text: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {" ", "-", "_"} else "_" for ch in text)
    return " ".join(cleaned.split()).strip() or "Untitled"


@lru_cache(maxsize=1)
def _cover_font_name() -> str | None:
    for name in FONT_CANDIDATES:
        try:
            ImageFont.truetype(name, 12)
            return name
        except Exception:
            continue
    return None


@lru_cache(maxsize=64)
def _load_cover_font(pt: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    font_name = _cover_font_name()
    if font_name is None:
        return ImageFont.load_default()
    return ImageFont.truetype(font_name, pt)


@lru_cache(maxsize=8)
def _gradient_masks(size: int) -> tuple[Image.Image, Image.Image]:
    vertical = Image.linear_gradient("L").resize((size, size), Image.Resampling.BILINEAR)
    horizontal = vertical.transpose(Image.Transpose.ROTATE_90)
    return horizontal, vertical


def _fallback_gradient_image(
    size: int,
    color_a: tuple[int, int, int],
    color_b: tuple[int, int, int],
    color_c: tuple[int, int, int],
) -> Image.Image:
    image = Image.new("RGB", (size, size))
    pixels = image.load()
    assert pixels is not None
    for y in range(size):
        v = y / max(size - 1, 1)
        for x in range(size):
            u = x / max(size - 1, 1)
            blend_ab = [int((1.0 - u) * color_a[i] + u * color_b[i]) for i in range(3)]
            blend = [int((1.0 - v) * blend_ab[i] + v * color_c[i]) for i in range(3)]
            pixels[x, y] = tuple(blend)
    return image


def _random_rgb(rng: random.Random) -> tuple[int, int, int]:
    return (
        rng.randint(24, 232),
        rng.randint(24, 232),
        rng.randint(24, 232),
    )


def gradient_cover_bytes(rng: random.Random, label: str | None = None, size: int = 640) -> bytes:
    color_a = _random_rgb(rng)
    color_b = _random_rgb(rng)
    color_c = _random_rgb(rng)
    try:
        horizontal_mask, vertical_mask = _gradient_masks(size)
        image_ab = Image.composite(
            Image.new("RGB", (size, size), color_b),
            Image.new("RGB", (size, size), color_a),
            horizontal_mask,
        )
        image = Image.composite(
            Image.new("RGB", (size, size), color_c),
            image_ab,
            vertical_mask,
        )
    except Exception:
        image = _fallback_gradient_image(size, color_a, color_b, color_c)

    # Overlay label text if provided. Use large white text with a black stroke so
    # the album name remains readable against any random gradient.
    if label:
        draw = ImageDraw.Draw(image)

        def _measure_text_bbox(font: ImageFont.ImageFont | ImageFont.FreeTypeFont, stroke_width: int) -> tuple[int, int, int, int]:
            def _normalize_bbox(bbox: tuple[float, float, float, float] | tuple[int, int, int, int]) -> tuple[int, int, int, int]:
                return (int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3]))

            try:
                return _normalize_bbox(draw.textbbox((0, 0), label, font=font, stroke_width=stroke_width))
            except TypeError:
                # Older Pillow may support textbbox but not stroke_width.
                return _normalize_bbox(draw.textbbox((0, 0), label, font=font))
            except Exception:
                try:
                    return _normalize_bbox(font.getbbox(label))
                except Exception:
                    mask_bbox = font.getmask(label).getbbox()
                    if mask_bbox is None:
                        return (0, 0, 0, 0)
                    return _normalize_bbox(mask_bbox)

        # Start with a very large font and decrease until the text fits with padding.
        max_pt = max(12, size // 6)
        padding = int(size * 0.06)
        font = _load_cover_font(max_pt)
        stroke_w = max(1, max_pt // 20)
        bbox = _measure_text_bbox(font, stroke_w)

        # Reduce font size until it fits within the image with padding.
        while (bbox[2] - bbox[0] > size - 2 * padding) or (bbox[3] - bbox[1] > size - 2 * padding):
            max_pt = int(max_pt * 0.88)
            if max_pt < 8:
                break
            font = _load_cover_font(max_pt)
            stroke_w = max(1, max_pt // 20)
            bbox = _measure_text_bbox(font, stroke_w)

        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        x = (size - text_w) // 2 - bbox[0]
        y = (size - text_h) // 2 - bbox[1]

        # Draw white text with a solid black stroke for high contrast.
        try:
            draw.text((x, y), label, font=font, fill=(255, 255, 255), stroke_width=stroke_w, stroke_fill=(0, 0, 0))
        except TypeError:
            # Older Pillow: stroke arguments may not be supported. Draw shadow then text.
            shadow_offsets = [(-1, -1), (-1, 1), (1, -1), (1, 1)]
            for ox, oy in shadow_offsets:
                draw.text((x + ox, y + oy), label, font=font, fill=(0, 0, 0))
            draw.text((x, y), label, font=font, fill=(255, 255, 255))

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=92)
    return buffer.getvalue()


def _mix_u32(value: int) -> int:
    """Return a stable 32-bit mixed integer for deterministic track recipes."""
    value &= 0xFFFFFFFF
    value ^= value >> 16
    value = (value * 0x7FEB352D) & 0xFFFFFFFF
    value ^= value >> 15
    value = (value * 0x846CA68B) & 0xFFFFFFFF
    value ^= value >> 16
    return value


def _serial_chroma_signature(track_serial: int, length: int = 32) -> tuple[int, ...]:
    # Encodes the serial in base-12 so every track gets a distinct pitch-class path.
    serial_value = track_serial + 1
    return tuple(((serial_value // (12**step)) + step * 5 + (step // 4) * 2) % 12 for step in range(length))


def _build_music_recipe(track_serial: int) -> MusicalRecipe:
    seed = _mix_u32(track_serial + 1)
    modes = (
        (0, 2, 4, 5, 7, 9, 11),  # major
        (0, 2, 3, 5, 7, 8, 10),  # natural minor
        (0, 2, 3, 5, 7, 9, 10),  # dorian
        (0, 2, 4, 5, 7, 9, 10),  # mixolydian
        (0, 2, 3, 5, 7, 8, 11),  # harmonic minor
    )
    progressions = (
        (0, 4, 5, 3),
        (0, 5, 3, 4),
        (0, 3, 4, 4),
        (5, 3, 0, 4),
        (0, 2, 5, 4),
        (3, 4, 0, 5),
    )
    bass_patterns = (
        (0, 0, 4, 0, 0, 5, 4, 0),
        (0, 4, 0, 5, 0, 4, 5, 4),
        (0, 0, 2, 4, 0, 5, 4, 2),
        (0, 5, 4, 2, 0, 0, 4, 5),
    )

    mode = modes[seed % len(modes)]
    progression = progressions[(seed >> 3) % len(progressions)]
    root_midi = 40 + ((seed >> 8) % 12)
    tempo_bpm = 86.0 + float((seed >> 13) % 52)
    tone_color = (seed >> 20) % 4
    pulse_depth = 0.10 + (((seed >> 24) % 8) / 80.0)

    melody_degrees: list[int] = []
    melody_rests: list[bool] = []
    intervals = (0, 1, 2, 3, 4, 5, -1, -2)
    for step in range(32):
        mixed = _mix_u32(seed + step * 0x45D9F3B)
        bar = (step // 8) % 4
        chord_degree = progression[bar]
        if step % 8 in {0, 6}:
            interval = 0
        elif step % 8 == 7:
            interval = 1 if ((mixed >> 8) & 1) else -1
        else:
            interval = intervals[mixed % len(intervals)]
        melody_degrees.append(chord_degree + interval)
        melody_rests.append(step % 8 not in {0, 4} and ((mixed >> 12) & 0b11) == 0)

    kick_hits = [float(bar) for bar in range(0, 16, 4)] + [float(bar + 2) for bar in range(0, 16, 4)]
    if tone_color in {1, 3}:
        kick_hits.extend(float(bar) + 3.5 for bar in range(0, 16, 4))
    snare_hits = [float(bar + 1) for bar in range(0, 16, 4)] + [float(bar + 3) for bar in range(0, 16, 4)]

    return MusicalRecipe(
        seed=seed,
        root_midi=root_midi,
        mode=mode,
        chord_degrees=progression,
        melody_degrees=tuple(melody_degrees),
        melody_rests=tuple(melody_rests),
        signature_offsets=_serial_chroma_signature(track_serial),
        bass_pattern=bass_patterns[(seed >> 17) % len(bass_patterns)],
        kick_hits=tuple(sorted(kick_hits)),
        snare_hits=tuple(snare_hits),
        tempo_bpm=tempo_bpm,
        tone_color=tone_color,
        pulse_depth=pulse_depth,
    )


def _scale_midi(root_midi: int, mode: tuple[int, ...], degree: int, octave: int) -> int:
    return root_midi + 12 * octave + mode[degree % len(mode)] + 12 * (degree // len(mode))


def _midi_to_hz(midi_note: int) -> float:
    return 440.0 * (2.0 ** ((midi_note - 69) / 12.0))


def _fit_midi_range(midi_note: int, low: int, high: int) -> int:
    while midi_note < low:
        midi_note += 12
    while midi_note > high:
        midi_note -= 12
    return midi_note


def _note_envelope(phase: float, *, attack: float, release: float) -> float:
    if phase < attack:
        return phase / max(attack, 1e-9)
    if phase > 1.0 - release:
        return max((1.0 - phase) / max(release, 1e-9), 0.0)
    return 1.0


def _bar_envelope(beat_in_bar: float) -> float:
    attack = min(beat_in_bar / 0.35, 1.0)
    release = min((4.0 - beat_in_bar) / 0.65, 1.0)
    return max(min(attack, release), 0.0)


def _recent_hit_delta(beat_in_loop: float, hits: tuple[float, ...], *, max_delta: float) -> float | None:
    best: float | None = None
    for hit in hits:
        delta = (beat_in_loop - hit) % 16.0
        if delta <= max_delta and (best is None or delta < best):
            best = delta
    return best


def _noise(index: int, seed: int) -> float:
    mixed = _mix_u32(index + seed)
    return ((mixed & 0xFFFF) / 32767.5) - 1.0


def _sine_stack(hz: float, t: float, partials: tuple[tuple[float, float], ...]) -> float:
    total = 0.0
    for harmonic, level in partials:
        total += level * math.sin(math.tau * hz * harmonic * t)
    return total


def _warm_pad_voice(hz: float, t: float, tone_color: int) -> float:
    detune = 1.0015 + tone_color * 0.0005
    return (
        _sine_stack(hz, t, ((1.0, 0.72), (2.0, 0.10), (3.0, 0.04)))
        + _sine_stack(hz * detune, t, ((1.0, 0.14), (2.0, 0.03)))
    )


def _round_bass_voice(hz: float, t: float) -> float:
    return _sine_stack(hz, t, ((0.5, 0.18), (1.0, 0.78), (2.0, 0.10), (3.0, 0.035)))


def _clean_lead_voice(hz: float, t: float, note_phase: float, tone_color: int) -> float:
    brightness = math.exp(-note_phase * (3.2 + tone_color * 0.2))
    return _sine_stack(
        hz,
        t,
        (
            (1.0, 0.86),
            (2.0, 0.08 + brightness * 0.045),
            (3.0, brightness * 0.018),
        ),
    )


def _smooth_noise(index: int, seed: int) -> float:
    return (
        _noise(index, seed) * 0.55
        + _noise(index - 1, seed) * 0.30
        + _noise(index - 2, seed) * 0.15
    )


def _kick_voice(t_since: float) -> float:
    body_env = math.exp(-t_since / 0.16)
    thump = math.sin(math.tau * 52.0 * t_since) * body_env
    low_mid = math.sin(math.tau * 96.0 * t_since) * math.exp(-t_since / 0.045) * 0.14
    return thump + low_mid


def _snare_voice(index: int, t_since: float, seed: int) -> float:
    noise_env = math.exp(-t_since / 0.10)
    body_env = math.exp(-t_since / 0.065)
    noise = _smooth_noise(index * 5, seed ^ 0x55AA55AA)
    body = math.sin(math.tau * 175.0 * t_since) * 0.32
    return noise * noise_env * 0.55 + body * body_env


def _hat_voice(index: int, t_since: float, seed: int) -> float:
    hat_env = math.exp(-t_since / 0.035)
    return _smooth_noise(index * 13, seed ^ 0xA5A5A5A5) * hat_env


def write_tone_wav(
    path: Path,
    *,
    sample_rate: int,
    duration: float,
    track_serial: int,
) -> None:
    frame_count = max(int(sample_rate * duration), 1)
    fade_frames = max(int(sample_rate * 0.12), 1)
    frames = bytearray()
    recipe = _build_music_recipe(track_serial)
    beats_per_second = recipe.tempo_bpm / 60.0

    for index in range(frame_count):
        t = index / sample_rate
        beat = t * beats_per_second
        beat_in_loop = beat % 16.0
        bar_index = int(beat_in_loop // 4.0)
        beat_in_bar = beat_in_loop - bar_index * 4.0
        chord_degree = recipe.chord_degrees[bar_index % len(recipe.chord_degrees)]

        global_env = 1.0
        if index < fade_frames:
            global_env = index / fade_frames
        elif index >= frame_count - fade_frames:
            global_env = (frame_count - index - 1) / fade_frames
        global_env = max(global_env, 0.0)

        chord_offsets = (0, 2, 4)
        pad_env = _bar_envelope(beat_in_bar)
        pulse = 1.0 - recipe.pulse_depth + recipe.pulse_depth * math.sin(math.tau * beat / 2.0) ** 2
        pad = 0.0
        for offset in chord_offsets:
            note = _scale_midi(recipe.root_midi, recipe.mode, chord_degree + offset, 2)
            note = _fit_midi_range(note, 50, 70)
            pad += _warm_pad_voice(_midi_to_hz(note), t, recipe.tone_color)
        pad = (pad / len(chord_offsets)) * pad_env * pulse * 0.24

        bass_position = beat_in_loop * 2.0
        bass_step = int(bass_position)
        bass_phase = bass_position - bass_step
        bass_degree = chord_degree + recipe.bass_pattern[bass_step % len(recipe.bass_pattern)]
        bass_note = _scale_midi(recipe.root_midi, recipe.mode, bass_degree, 0)
        bass_note = _fit_midi_range(bass_note, 36, 52)
        bass_env = _note_envelope(bass_phase, attack=0.05, release=0.42)
        bass_accent = 1.15 if bass_step % 8 in {0, 4} else 0.82
        bass = _round_bass_voice(_midi_to_hz(bass_note), t) * bass_env * bass_accent * 0.36

        melody_position = beat_in_loop * 2.0
        melody_step = int(melody_position)
        melody_phase = melody_position - melody_step
        lead = 0.0
        if not recipe.melody_rests[melody_step % len(recipe.melody_rests)]:
            melody_degree = recipe.melody_degrees[melody_step % len(recipe.melody_degrees)]
            lead_octave = 2 + ((melody_step // 16 + recipe.tone_color) % 2)
            lead_note = _scale_midi(recipe.root_midi, recipe.mode, melody_degree, lead_octave)
            lead_note = _fit_midi_range(lead_note, 57, 76)
            lead_env = _note_envelope(melody_phase, attack=0.09, release=0.62)
            lead = _clean_lead_voice(_midi_to_hz(lead_note), t, melody_phase, recipe.tone_color) * lead_env * 0.16

        signature_step = int(melody_position)
        signature_phase = melody_position - signature_step
        signature_offset = recipe.signature_offsets[signature_step % len(recipe.signature_offsets)]
        signature_note = _fit_midi_range(recipe.root_midi + 24 + signature_offset, 55, 74)
        signature_env = _note_envelope(signature_phase, attack=0.06, release=0.70)
        signature_accent = 1.0 if signature_step % 4 in {0, 2} else 0.72
        signature = _clean_lead_voice(_midi_to_hz(signature_note), t, signature_phase, recipe.tone_color) * signature_env * signature_accent * 0.095

        kick_delta = _recent_hit_delta(beat_in_loop, recipe.kick_hits, max_delta=0.55)
        kick = 0.0
        if kick_delta is not None:
            kick = _kick_voice(kick_delta / beats_per_second) * 0.43

        snare_delta = _recent_hit_delta(beat_in_loop, recipe.snare_hits, max_delta=0.35)
        snare = 0.0
        if snare_delta is not None:
            snare = _snare_voice(index, snare_delta / beats_per_second, recipe.seed) * 0.16

        hat_delta = (beat_in_loop * 2.0) % 1.0 / 2.0
        hat_accent = 0.048 if int(beat_in_loop * 2.0) % 2 == 0 else 0.028
        hat = _hat_voice(index, hat_delta / beats_per_second, recipe.seed) * hat_accent

        sample = (pad + bass + lead + signature + kick + snare + hat) * global_env
        value = int(32767.0 * 0.86 * math.tanh(sample * 1.08))
        frames.extend(value.to_bytes(2, byteorder="little", signed=True))

    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(frames)


def tag_wav(
    path: Path,
    *,
    title: str,
    artist: str,
    album: str,
    genre: str,
    year: int,
    track_number: int,
    track_total: int,
    art_bytes: bytes,
) -> None:
    audio = WAVE(str(path))
    if audio.tags is None:
        audio.add_tags()

    assert audio.tags is not None
    audio.tags.delall("TIT2")
    audio.tags.delall("TPE1")
    audio.tags.delall("TPE2")
    audio.tags.delall("TALB")
    audio.tags.delall("TCON")
    audio.tags.delall("TDRC")
    audio.tags.delall("TRCK")
    audio.tags.delall("APIC")

    audio.tags.add(TIT2(encoding=3, text=[title]))
    audio.tags.add(TPE1(encoding=3, text=[artist]))
    audio.tags.add(TPE2(encoding=3, text=[artist]))
    audio.tags.add(TALB(encoding=3, text=[album]))
    audio.tags.add(TCON(encoding=3, text=[genre]))
    audio.tags.add(TDRC(encoding=3, text=[str(year)]))
    audio.tags.add(TRCK(encoding=3, text=[f"{track_number}/{track_total}"]))
    audio.tags.add(
        APIC(
            encoding=3,
            mime="image/jpeg",
            type=3,
            desc="Cover",
            data=art_bytes,
        )
    )
    audio.save()


def generate_track_file(
    spec: TrackSpec,
    *,
    sample_rate: int,
    duration: float,
) -> Path:
    write_tone_wav(
        spec.path,
        sample_rate=sample_rate,
        duration=duration,
        track_serial=spec.serial,
    )
    tag_wav(
        spec.path,
        title=spec.title,
        artist=spec.artist,
        album=spec.album,
        genre=spec.genre,
        year=spec.year,
        track_number=spec.track_number,
        track_total=spec.track_total,
        art_bytes=spec.art_bytes,
    )
    return spec.path


def _generate_tracks_concurrently(
    track_specs: list[TrackSpec],
    *,
    sample_rate: int,
    duration: float,
    worker_count: int,
    track_bar,
) -> dict[int, Path]:
    created_by_serial: dict[int, Path] = {}
    executor_class = ProcessPoolExecutor if worker_count > 1 else ThreadPoolExecutor
    try:
        with executor_class(max_workers=worker_count) as executor:
            futures = {
                executor.submit(
                    generate_track_file,
                    spec,
                    sample_rate=sample_rate,
                    duration=duration,
                ): spec
                for spec in track_specs
            }
            for future in as_completed(futures):
                spec = futures[future]
                created_path = future.result()
                created_by_serial[spec.serial] = created_path
                track_bar.set_postfix_str(created_path.name[:40], refresh=False)
                track_bar.update(1)
    except (BrokenProcessPool, RuntimeError, OSError):
        if executor_class is ThreadPoolExecutor:
            raise
        track_bar.set_postfix_str("process workers unavailable; retrying with threads", refresh=True)
        created_by_serial.clear()
        track_bar.reset(total=len(track_specs))
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(
                    generate_track_file,
                    spec,
                    sample_rate=sample_rate,
                    duration=duration,
                ): spec
                for spec in track_specs
            }
            for future in as_completed(futures):
                spec = futures[future]
                created_path = future.result()
                created_by_serial[spec.serial] = created_path
                track_bar.set_postfix_str(created_path.name[:40], refresh=False)
                track_bar.update(1)
        return created_by_serial
    return created_by_serial


def generate_library(
    output: Path,
    *,
    albums: int,
    tracks_per_album: int,
    duration: float,
    sample_rate: int,
    seed: int,
    force: bool,
    workers: int,
    art_size: int,
) -> GenerationStats:
    rng = random.Random(seed)
    if output.exists():
        if not force:
            raise FileExistsError(
                f"{output} already exists. Re-run with --force to replace it."
            )
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)
    total_started_at = time.perf_counter()
    prep_started_at = total_started_at

    artist_names = pick_unique_pairs(rng, albums)
    album_names = pick_unique_pairs(rng, albums)
    song_names = pick_unique_pairs(rng, albums * tracks_per_album)
    safe_song_names = [safe_name(title) for title in song_names]
    track_specs: list[TrackSpec] = []
    song_index = 0

    with tqdm(
        total=albums,
        desc="Preparing albums",
        unit="album",
        dynamic_ncols=True,
        mininterval=0.1,
    ) as prep_bar:
        for album_index in range(albums):
            artist = artist_names[album_index]
            album = album_names[album_index]
            safe_artist = safe_name(artist)
            safe_album = safe_name(album)
            genre = rng.choice(GENRES)
            year = 1998 + album_index * 4 + rng.randint(0, 2)
            art_bytes = gradient_cover_bytes(rng, album, size=art_size)

            album_dir = output / safe_artist / safe_album
            album_dir.mkdir(parents=True, exist_ok=True)

            for track_number in range(1, tracks_per_album + 1):
                title = song_names[song_index]
                safe_title = safe_song_names[song_index]
                song_index += 1
                track_serial = album_index * tracks_per_album + (track_number - 1)
                filename = f"{track_number:02d} - {safe_title}.wav"
                wav_path = album_dir / filename

                track_specs.append(
                    TrackSpec(
                        serial=track_serial,
                        path=wav_path,
                        title=title,
                        artist=artist,
                        album=album,
                        genre=genre,
                        year=year,
                        track_number=track_number,
                        track_total=tracks_per_album,
                        art_bytes=art_bytes,
                    )
                )
            prep_bar.set_postfix_str(f"{artist} - {album}"[:40], refresh=False)
            prep_bar.update(1)
    prep_elapsed = time.perf_counter() - prep_started_at

    if not track_specs:
        return GenerationStats(
            created=[],
            elapsed_seconds=0.0,
            prep_seconds=prep_elapsed,
            generation_seconds=0.0,
            total_bytes=0,
            workers=0,
        )

    cpu_count = os.cpu_count() or 1
    worker_count = max(1, min(workers, len(track_specs), cpu_count))
    generation_started_at = time.perf_counter()

    with tqdm(
        total=len(track_specs),
        desc="Generating tracks",
        unit="track",
        dynamic_ncols=True,
        mininterval=0.1,
    ) as track_bar:
        executor_label = "process" if worker_count > 1 else "thread"
        track_bar.set_postfix_str(f"starting {worker_count} {executor_label} worker{'s' if worker_count != 1 else ''}", refresh=True)
        created_by_serial = _generate_tracks_concurrently(
            track_specs,
            sample_rate=sample_rate,
            duration=duration,
            worker_count=worker_count,
            track_bar=track_bar,
        )
    generation_elapsed = time.perf_counter() - generation_started_at

    created = [created_by_serial[spec.serial] for spec in track_specs]
    elapsed = time.perf_counter() - total_started_at
    total_bytes = sum(path.stat().st_size for path in created)
    return GenerationStats(
        created=created,
        elapsed_seconds=elapsed,
        prep_seconds=prep_elapsed,
        generation_seconds=generation_elapsed,
        total_bytes=total_bytes,
        workers=worker_count,
    )


def _parse_args(parser: argparse.ArgumentParser) -> argparse.Namespace:
    argv = sys.argv[1:]
    if argv:
        return parser.parse_args(argv)
    if sys.stdin.isatty() and sys.stdout.isatty():
        return _run_interactive_wizard(parser)
    return parser.parse_args(argv)


def main() -> None:
    parser = build_parser()
    args = _parse_args(parser)
    total_tracks = args.albums * args.tracks_per_album
    print(
        f"Planning {args.albums} albums and {total_tracks} tracks"
        f" with {args.workers} workers..."
    )
    stats = generate_library(
        args.output,
        albums=args.albums,
        tracks_per_album=args.tracks_per_album,
        duration=args.duration,
        sample_rate=args.sample_rate,
        seed=args.seed,
        force=args.force,
        workers=args.workers,
        art_size=args.art_size,
    )
    track_count = len(stats.created)
    total_mib = stats.total_bytes / (1024 * 1024)
    print(
        f"Created {track_count} fake songs in {args.output}"
        f" using {stats.workers} worker"
        f"{'s' if stats.workers != 1 else ''}."
    )
    print(
        f"Elapsed: {stats.elapsed_seconds:.2f}s"
        f" | Prep: {stats.prep_seconds:.2f}s"
        f" | Track gen: {stats.generation_seconds:.2f}s"
        f" | Throughput: {track_count / max(stats.elapsed_seconds, 1e-9):.1f} tracks/s"
        f" | Size: {total_mib:.2f} MiB"
    )
    if stats.created:
        print(f"First track: {stats.created[0]}")


if __name__ == "__main__":
    main()
