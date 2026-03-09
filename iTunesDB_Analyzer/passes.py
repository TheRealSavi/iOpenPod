"""Analysis passes A–E — the core intelligence of the comparative pipeline.

Each pass is a function that takes a list of ParsedDatabase objects and a
HypothesisDB, runs its analysis, and records findings.

Pass A — Unknown Territory Mapping
Pass B — Type Inference on Unknowns
Pass C — Cross-Field Correlation
Pass D — Version-Stratified Analysis
Pass E — Known Pattern Matching
"""

from __future__ import annotations

import logging
import math
from collections import Counter, defaultdict
from typing import Optional

from .field_schema import FieldStatus, fields_for_chunk
from .hypothesis_db import HypothesisDB
from .models import ParsedDatabase, ValueObservation

logger = logging.getLogger(__name__)

# HFS+ timestamp range for sanity checks (~2001-01-01 to ~2030-01-01).
_MAC_TS_MIN = 3_061_152_000   # 2001-01-01
_MAC_TS_MAX = 3_976_300_800   # 2030-01-01
_MAC_EPOCH_OFFSET = 2_082_844_800


def run_all(dbs: list[ParsedDatabase], hdb: HypothesisDB) -> None:
    """Execute all analysis passes in sequence."""
    logger.info("=== Pass A: Unknown Territory Mapping ===")
    pass_a_unknown_mapping(dbs, hdb)
    logger.info("=== Pass B: Type Inference ===")
    pass_b_type_inference(dbs, hdb)
    logger.info("=== Pass C: Cross-Field Correlation ===")
    pass_c_correlation(dbs, hdb)
    logger.info("=== Pass D: Version-Stratified Analysis ===")
    pass_d_version_stratified(dbs, hdb)
    logger.info("=== Pass E: Known Pattern Matching ===")
    pass_e_known_patterns(dbs, hdb)
    logger.info("=== All passes complete ===")


# ────────────────────────────────────────────────────────────────────
# Pass A — Unknown Territory Mapping
# ────────────────────────────────────────────────────────────────────

def pass_a_unknown_mapping(dbs: list[ParsedDatabase], hdb: HypothesisDB) -> None:
    """Cluster unknowns by (chunk_type, offset, length) and characterize."""
    # Group all unknown observations.
    clusters: dict[tuple[str, int, int], list[ValueObservation]] = defaultdict(list)

    for db in dbs:
        for u in db.unknowns:
            key = (u.chunk_type, u.rel_offset, u.length)
            clusters[key].append(ValueObservation(
                chunk_type=u.chunk_type,
                rel_offset=u.rel_offset,
                length=u.length,
                raw_bytes=u.raw_bytes,
                file_path=db.file_path,
                db_version=db.db_version,
            ))

    file_count = len(dbs)

    for (ct, off, length), obs_list in sorted(clusters.items()):
        # Frequency = fraction of chunks of this type that contain this unknown.
        total_chunks = sum(
            sum(1 for c in db.all_chunks if c.chunk_type == ct)
            for db in dbs
        )
        freq = len(obs_list) / max(total_chunks, 1)

        # Value characterization.
        all_zero = all(o.is_all_zero for o in obs_list)
        distinct_vals = len(set(o.raw_bytes for o in obs_list))
        all_same = distinct_vals == 1

        if all_zero:
            kind = "all_zero"
            summary = f"All {len(obs_list)} samples are zero — likely padding"
        elif all_same:
            kind = "constant"
            summary = f"Constant value across {len(obs_list)} samples: {obs_list[0].raw_bytes.hex()}"
        elif distinct_vals <= 5:
            kind = "binary"
            vals = Counter(o.raw_bytes.hex() for o in obs_list).most_common(5)
            summary = f"Low cardinality ({distinct_vals} distinct): {vals}"
        else:
            kind = "distribution"
            summary = f"{distinct_vals} distinct values across {len(obs_list)} samples"

        vj = {
            "distinct_count": distinct_vals,
            "sample_count": len(obs_list),
            "total_chunks": total_chunks,
            "frequency": round(freq, 4),
            "all_zero": all_zero,
        }

        hdb.upsert_pattern(ct, off, length, kind, summary, vj, len(obs_list))


# ────────────────────────────────────────────────────────────────────
# Pass B — Type Inference on Unknowns
# ────────────────────────────────────────────────────────────────────

def pass_b_type_inference(dbs: list[ParsedDatabase], hdb: HypothesisDB) -> None:
    """Apply heuristics to guess the type of each unknown byte range."""
    clusters = _collect_unknown_observations(dbs)

    for (ct, off, length), obs_list in clusters.items():
        non_zero = [o for o in obs_list if not o.is_all_zero]
        n_total = len(obs_list)
        n_nonzero = len(non_zero)

        if n_total == 0:
            continue

        # All zero → padding.
        if n_nonzero == 0:
            hdb.upsert_hypothesis(
                ct, off, length, "padding", "padding",
                confidence=0.95,
                supporting_files=n_total,
                rationale="All samples zero across all files",
            )
            continue

        # Try sub-field splitting for larger unknown regions.
        if length > 4:
            _infer_large_region(ct, off, length, obs_list, hdb)
            continue

        # 1-byte heuristics.
        if length == 1:
            _infer_1byte(ct, off, obs_list, hdb)
            continue

        # 2-byte heuristics.
        if length == 2:
            _infer_2byte(ct, off, obs_list, hdb)
            continue

        # 4-byte heuristics.
        if length == 4:
            _infer_4byte(ct, off, obs_list, hdb)
            continue


def _infer_1byte(
    ct: str, off: int, obs: list[ValueObservation], hdb: HypothesisDB,
) -> None:
    vals = [o.raw_bytes[0] for o in obs]
    unique = set(vals)
    n = len(obs)

    # Boolean flag.
    if unique <= {0, 1}:
        ones = sum(1 for v in vals if v == 1)
        hdb.upsert_hypothesis(
            ct, off, 1, "flag", "boolean_flag",
            confidence=0.80,
            supporting_files=n,
            rationale=f"Values in {{0,1}}; {ones}/{n} are 1",
        )
        return

    # Rating.
    if unique <= {0, 20, 40, 60, 80, 100}:
        hdb.upsert_hypothesis(
            ct, off, 1, "rating", "rating_candidate",
            confidence=0.75,
            supporting_files=n,
            rationale=f"Values are multiples of 20 (rating pattern): {sorted(unique)}",
        )
        return

    # Small enum.
    if len(unique) <= 8 and max(vals) <= 10:
        hdb.upsert_hypothesis(
            ct, off, 1, "enum", "small_enum",
            confidence=0.50,
            supporting_files=n,
            rationale=f"Small value set: {sorted(unique)}",
        )
        return

    hdb.upsert_hypothesis(
        ct, off, 1, "u8", "",
        confidence=0.30,
        supporting_files=n,
        rationale=f"Uncategorized byte; range {min(vals)}..{max(vals)}, {len(unique)} distinct",
    )


def _infer_2byte(
    ct: str, off: int, obs: list[ValueObservation], hdb: HypothesisDB,
) -> None:
    vals = [int.from_bytes(o.raw_bytes[:2], "little", signed=False) for o in obs]
    unique = set(vals)
    n = len(obs)

    if unique == {0}:
        hdb.upsert_hypothesis(ct, off, 2, "padding", "padding", 0.90, n,
                              rationale="Always zero u16")
        return

    if len(unique) <= 4:
        hdb.upsert_hypothesis(ct, off, 2, "enum", "u16_enum", 0.55, n,
                              rationale=f"Low cardinality u16: {sorted(unique)}")
        return

    hdb.upsert_hypothesis(ct, off, 2, "u16", "", 0.30, n,
                          rationale=f"u16; range {min(vals)}..{max(vals)}")


def _infer_4byte(
    ct: str, off: int, obs: list[ValueObservation], hdb: HypothesisDB,
) -> None:
    vals_u = [int.from_bytes(o.raw_bytes[:4], "little", signed=False) for o in obs]
    non_zero_u = [v for v in vals_u if v != 0]
    n = len(obs)

    if not non_zero_u:
        hdb.upsert_hypothesis(ct, off, 4, "padding", "padding", 0.90, n,
                              rationale="Always zero u32")
        return

    mn, mx = min(non_zero_u), max(non_zero_u)

    # Timestamp candidate.
    ts_count = sum(1 for v in non_zero_u if _MAC_TS_MIN <= v <= _MAC_TS_MAX)
    if ts_count >= len(non_zero_u) * 0.8:
        sample_unix = non_zero_u[0] - _MAC_EPOCH_OFFSET if non_zero_u else 0
        hdb.upsert_hypothesis(
            ct, off, 4, "timestamp", "mac_timestamp",
            confidence=0.85,
            supporting_files=n,
            rationale=(
                f"{ts_count}/{len(non_zero_u)} values fall in HFS+ timestamp range; "
                f"sample: raw={non_zero_u[0]}, Unix={sample_unix}"
            ),
        )
        return

    # Bitrate / sample rate / BPM candidate.
    if 0 < mn and mx <= 320:
        hdb.upsert_hypothesis(
            ct, off, 4, "u32", "bitrate_or_bpm",
            confidence=0.45,
            supporting_files=n,
            rationale=f"Range {mn}..{mx} consistent with bitrate/BPM",
        )

    # FourCC candidate — check if all bytes are printable ASCII.
    fourcc_count = 0
    for o in obs:
        if o.raw_bytes[:4] != b'\x00\x00\x00\x00':
            try:
                text = o.raw_bytes[:4].decode("ascii")
                if text.isprintable():
                    fourcc_count += 1
            except (UnicodeDecodeError, ValueError):
                pass
    if fourcc_count >= len(non_zero_u) * 0.8 and fourcc_count > 0:
        hdb.upsert_hypothesis(
            ct, off, 4, "fourcc", "ascii_fourcc",
            confidence=0.70,
            supporting_files=n,
            rationale=f"{fourcc_count}/{len(non_zero_u)} values are printable ASCII",
        )
        return

    # Pointer candidate — value matches another known offset in the file.
    # (This is best done in Pass C, but flag as candidate here.)
    if mn >= 0x0C and mx < 0x100000:
        hdb.upsert_hypothesis(
            ct, off, 4, "pointer", "offset_pointer",
            confidence=0.20,
            supporting_files=n,
            rationale=f"Range {hex(mn)}..{hex(mx)} could be offsets; verify in Pass C",
        )

    # High entropy → hash/encrypted.
    if n >= 3:
        entropy = _byte_entropy([o.raw_bytes for o in obs])
        if entropy > 7.0:
            hdb.upsert_hypothesis(
                ct, off, 4, "hash", "high_entropy_blob",
                confidence=0.50,
                supporting_files=n,
                rationale=f"Byte entropy={entropy:.2f} suggests hash/checksum",
            )
            return

    # Generic u32.
    hdb.upsert_hypothesis(
        ct, off, 4, "u32", "",
        confidence=0.20,
        supporting_files=n,
        rationale=f"Uncategorized u32; range {mn}..{mx}, {len(set(vals_u))} distinct",
    )


def _infer_large_region(
    ct: str, off: int, length: int,
    obs: list[ValueObservation], hdb: HypothesisDB,
) -> None:
    """For regions > 4 bytes, try to split into aligned sub-fields."""
    n = len(obs)

    # Check if entirely zero.
    if all(o.is_all_zero for o in obs):
        hdb.upsert_hypothesis(ct, off, length, "padding", "padding", 0.92, n,
                              rationale=f"All {n} samples zero across {length} bytes")
        return

    # Check entropy.
    entropy = _byte_entropy([o.raw_bytes for o in obs])
    if entropy > 7.0:
        hdb.upsert_hypothesis(ct, off, length, "hash", "high_entropy_blob", 0.60, n,
                              rationale=f"Byte entropy={entropy:.2f} over {length} bytes")
        return

    # Try to split into 4-byte aligned sub-fields.
    for sub_off in range(0, length, 4):
        sub_len = min(4, length - sub_off)
        sub_obs = []
        for o in obs:
            sub_bytes = o.raw_bytes[sub_off:sub_off + sub_len]
            if len(sub_bytes) == sub_len:
                sub_obs.append(ValueObservation(
                    chunk_type=ct,
                    rel_offset=off + sub_off,
                    length=sub_len,
                    raw_bytes=sub_bytes,
                    file_path=o.file_path,
                    db_version=o.db_version,
                ))
        if sub_obs:
            if sub_len == 4:
                _infer_4byte(ct, off + sub_off, sub_obs, hdb)
            elif sub_len == 2:
                _infer_2byte(ct, off + sub_off, sub_obs, hdb)
            elif sub_len == 1:
                _infer_1byte(ct, off + sub_off, sub_obs, hdb)


# ────────────────────────────────────────────────────────────────────
# Pass C — Cross-Field Correlation
# ────────────────────────────────────────────────────────────────────

def pass_c_correlation(dbs: list[ParsedDatabase], hdb: HypothesisDB) -> None:
    """For each unknown u32 field, test correlation with every known field."""
    # Only correlate within mhit — the richest chunk type.
    for ct in ("mhit", "mhyp", "mhbd"):
        _correlate_chunk_type(ct, dbs, hdb)


def _correlate_chunk_type(
    ct: str, dbs: list[ParsedDatabase], hdb: HypothesisDB,
) -> None:
    """Correlate unknowns with known fields for a specific chunk type."""
    # Collect per-chunk (known_fields, unknown_u32_values).
    known_fields_schema = [
        f for f in fields_for_chunk(ct)
        if f.status == FieldStatus.CONFIRMED and f.name not in ("chunk_type", "header_length", "length_or_children")
    ]
    known_names = [f.name for f in known_fields_schema]

    # Build parallel arrays: each entry = one chunk instance.
    known_vecs: dict[str, list[float]] = {name: [] for name in known_names}
    unknown_vecs: dict[tuple[int, int], list[float]] = {}  # (rel_offset, length) → values

    for db in dbs:
        for chunk in db.all_chunks:
            if chunk.chunk_type != ct:
                continue
            pf = chunk.parsed_fields

            # Known fields.
            for name in known_names:
                val = pf.get(name)
                if isinstance(val, (int, float)):
                    known_vecs[name].append(float(val))
                else:
                    known_vecs[name].append(0.0)

            # Unknown fields — extract u32 sub-values from unknown regions.
            for u in db.unknowns:
                if u.chunk_type != ct or u.chunk_offset != chunk.abs_offset:
                    continue
                # Try 4-byte aligned splits.
                for sub_off in range(0, u.length, 4):
                    sub_len = min(4, u.length - sub_off)
                    if sub_len == 4:
                        abs_rel = u.rel_offset + sub_off
                        val = int.from_bytes(
                            u.raw_bytes[sub_off:sub_off + 4], "little", signed=False,
                        )
                        key = (abs_rel, 4)
                        unknown_vecs.setdefault(key, []).append(float(val))

    if not unknown_vecs:
        return

    # For each unknown, correlate with each known.
    for (u_off, u_len), u_vals in unknown_vecs.items():
        for k_name in known_names:
            k_vals = known_vecs[k_name]
            if len(k_vals) != len(u_vals):
                continue
            n = len(k_vals)
            if n < 5:
                continue

            # Test exact equality.
            eq_count = sum(1 for a, b in zip(u_vals, k_vals) if a == b)
            if eq_count >= n * 0.9:
                hdb.upsert_correlation(
                    ct, u_off, u_len, k_name, "equal",
                    strength=eq_count / n,
                    sample_count=n,
                    rationale=f"{eq_count}/{n} exact matches",
                )
                continue

            # Test U == K ± 1.
            for rel, label in [(1, "plus1"), (-1, "minus1")]:
                match_count = sum(1 for a, b in zip(u_vals, k_vals) if a == b + rel)
                if match_count >= n * 0.9:
                    hdb.upsert_correlation(
                        ct, u_off, u_len, k_name, label,
                        strength=match_count / n,
                        sample_count=n,
                        rationale=f"{match_count}/{n} matches for U == K {'+' if rel > 0 else ''}{rel}",
                    )

            # Test U == K * 2 / K / 2.
            for factor, label in [(2.0, "times2"), (0.5, "half")]:
                match_count = sum(
                    1 for a, b in zip(u_vals, k_vals)
                    if b != 0 and abs(a - b * factor) < 0.5
                )
                if match_count >= n * 0.9:
                    hdb.upsert_correlation(
                        ct, u_off, u_len, k_name, label,
                        strength=match_count / n,
                        sample_count=n,
                    )

            # Co-null pattern: U is 0 when K is 0.
            k_zeros = [(a, b) for a, b in zip(u_vals, k_vals) if b == 0.0]
            if len(k_zeros) >= 3:
                co_null = sum(1 for a, _ in k_zeros if a == 0.0)
                ratio = co_null / len(k_zeros)
                if ratio >= 0.9:
                    hdb.upsert_correlation(
                        ct, u_off, u_len, k_name, "co_null",
                        strength=ratio,
                        sample_count=len(k_zeros),
                        rationale=f"When {k_name}==0, unknown==0 in {co_null}/{len(k_zeros)} cases",
                    )

            # Pearson correlation.
            r = _pearson(u_vals, k_vals)
            if r is not None and abs(r) >= 0.85:
                hdb.upsert_correlation(
                    ct, u_off, u_len, k_name, "pearson",
                    strength=abs(r),
                    sample_count=n,
                    rationale=f"Pearson r={r:.4f}",
                )


# ────────────────────────────────────────────────────────────────────
# Pass D — Version-Stratified Analysis
# ────────────────────────────────────────────────────────────────────

def pass_d_version_stratified(dbs: list[ParsedDatabase], hdb: HypothesisDB) -> None:
    """Group files by db_version, re-run type inference per group, detect version additions."""
    # Group by version.
    by_version: dict[int, list[ParsedDatabase]] = defaultdict(list)
    for db in dbs:
        by_version[db.db_version].append(db)

    if len(by_version) < 2:
        logger.info("Only %d version(s) found; skipping version-stratified analysis", len(by_version))
        return

    # For each version group, collect which unknown offsets exist.
    version_offsets: dict[int, set[tuple[str, int, int]]] = {}
    for ver, ver_dbs in sorted(by_version.items()):
        offsets: set[tuple[str, int, int]] = set()
        for db in ver_dbs:
            for u in db.unknowns:
                offsets.add((u.chunk_type, u.rel_offset, u.length))
        version_offsets[ver] = offsets

    sorted_versions = sorted(by_version.keys())

    # Detect fields that appear in newer versions but not older.
    for i in range(1, len(sorted_versions)):
        newer_v = sorted_versions[i]
        older_v = sorted_versions[i - 1]
        new_offsets = version_offsets[newer_v] - version_offsets[older_v]
        disappeared = version_offsets[older_v] - version_offsets[newer_v]

        for ct, off, length in new_offsets:
            hdb.upsert_version_branch(
                ct, off, length, "appears_in",
                version_min=newer_v, version_max=newer_v,
                detail=f"Unknown at {ct}+0x{off:X} ({length}B) first seen in version 0x{newer_v:X}",
            )

        for ct, off, length in disappeared:
            hdb.upsert_version_branch(
                ct, off, length, "disappears_in",
                version_min=newer_v, version_max=newer_v,
                detail=f"Unknown at {ct}+0x{off:X} ({length}B) absent from version 0x{newer_v:X}",
            )

    # Re-run type inference per version group.
    for ver, ver_dbs in sorted(by_version.items()):
        clusters = _collect_unknown_observations(ver_dbs)
        for (ct, off, length), obs_list in clusters.items():
            non_zero = [o for o in obs_list if not o.is_all_zero]
            if not non_zero:
                continue
            if length == 4:
                vals = [int.from_bytes(o.raw_bytes[:4], "little") for o in non_zero]
                ts_count = sum(1 for v in vals if _MAC_TS_MIN <= v <= _MAC_TS_MAX)
                if ts_count >= len(vals) * 0.8:
                    hdb.upsert_hypothesis(
                        ct, off, length, "timestamp", f"mac_timestamp_v{ver:X}",
                        confidence=0.80,
                        supporting_files=len(obs_list),
                        rationale=f"Timestamp in version 0x{ver:X}: {ts_count}/{len(vals)} in range",
                    )


# ────────────────────────────────────────────────────────────────────
# Pass E — Known Pattern Matching
# ────────────────────────────────────────────────────────────────────

# Known FourCC file type codes.
_KNOWN_FOURCCS = {b"M4A ", b"MP3 ", b"AIFF", b"WAV ", b"M4B ", b"M4V ", b"M4P ", b"ALAC"}
_KNOWN_FOURCCS_BE = {int.from_bytes(cc, "big") for cc in _KNOWN_FOURCCS}

# Media type enum values.
_MEDIA_TYPES = {0x01: "audio", 0x02: "video_d", 0x04: "podcast", 0x06: "video_podcast",
                0x08: "audiobook", 0x20: "music_video", 0x40: "tv_show", 0x60: "tv_show_2"}

# Gapless playback markers.
_GAPLESS_INDICATORS = {"pregap", "postgap", "sample_count", "gapless_audio_payload_size"}


def pass_e_known_patterns(dbs: list[ParsedDatabase], hdb: HypothesisDB) -> None:
    """Test unknown 4-byte fields against known iTunesDB-specific patterns."""
    clusters = _collect_unknown_observations(dbs)

    for (ct, off, length), obs_list in clusters.items():
        if length != 4:
            continue

        non_zero = [o for o in obs_list if not o.is_all_zero]
        if not non_zero:
            continue

        vals_u = [int.from_bytes(o.raw_bytes[:4], "little") for o in non_zero]
        n_total = len(obs_list)

        # FourCC file type codes.
        fourcc_matches = sum(1 for v in vals_u if v in _KNOWN_FOURCCS_BE)
        if fourcc_matches >= len(vals_u) * 0.5 and fourcc_matches > 0:
            hdb.upsert_hypothesis(
                ct, off, 4, "fourcc", "known_filetype_fourcc",
                confidence=0.85,
                supporting_files=n_total,
                rationale=f"{fourcc_matches}/{len(vals_u)} match known FourCC codes",
            )

        # Media type enum.
        mt_matches = sum(1 for v in vals_u if v in _MEDIA_TYPES)
        if mt_matches >= len(vals_u) * 0.8:
            hdb.upsert_hypothesis(
                ct, off, 4, "enum", "media_type_enum",
                confidence=0.80,
                supporting_files=n_total,
                rationale=f"{mt_matches}/{len(vals_u)} match known media_type values",
            )

        # Skip-when-shuffling (1-byte within 4-byte field).
        if all(v in (0, 1) for v in vals_u):
            hdb.upsert_hypothesis(
                ct, off, 4, "flag", "skip_when_shuffling_candidate",
                confidence=0.55,
                supporting_files=n_total,
                rationale="All values 0 or 1 (boolean-like)",
            )

        # Gapless data range — large values consistent with sample counts.
        if all(v > 1000 for v in vals_u) and all(v < 100_000_000 for v in vals_u):
            hdb.upsert_hypothesis(
                ct, off, 4, "u32", "gapless_data_candidate",
                confidence=0.35,
                supporting_files=n_total,
                rationale=f"All values in 1000..100M range consistent with gapless fields",
            )


# ────────────────────────────────────────────────────────────────────
# Shared utilities
# ────────────────────────────────────────────────────────────────────

def _collect_unknown_observations(
    dbs: list[ParsedDatabase],
) -> dict[tuple[str, int, int], list[ValueObservation]]:
    """Group unknown regions into clusters keyed by (chunk_type, rel_offset, length)."""
    clusters: dict[tuple[str, int, int], list[ValueObservation]] = defaultdict(list)
    for db in dbs:
        for u in db.unknowns:
            key = (u.chunk_type, u.rel_offset, u.length)
            clusters[key].append(ValueObservation(
                chunk_type=u.chunk_type,
                rel_offset=u.rel_offset,
                length=u.length,
                raw_bytes=u.raw_bytes,
                file_path=db.file_path,
                db_version=db.db_version,
            ))
    return clusters


def _byte_entropy(blobs: list[bytes]) -> float:
    """Compute Shannon entropy across all bytes in the given blobs."""
    counts = Counter[int]()
    total = 0
    for blob in blobs:
        for b in blob:
            counts[b] += 1
            total += 1
    if total == 0:
        return 0.0
    entropy = 0.0
    for c in counts.values():
        p = c / total
        if p > 0:
            entropy -= p * math.log2(p)
    return entropy


def _pearson(xs: list[float], ys: list[float]) -> Optional[float]:
    """Compute Pearson correlation coefficient. Returns None if insufficient variance."""
    n = len(xs)
    if n < 5:
        return None

    sx = sum(xs)
    sy = sum(ys)
    sxx = sum(x * x for x in xs)
    syy = sum(y * y for y in ys)
    sxy = sum(x * y for x, y in zip(xs, ys))

    denom_x = n * sxx - sx * sx
    denom_y = n * syy - sy * sy

    if denom_x <= 0 or denom_y <= 0:
        return None

    return (n * sxy - sx * sy) / math.sqrt(denom_x * denom_y)
