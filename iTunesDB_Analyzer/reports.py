"""Report generators — schema export, annotated hex, hypothesis ranking, version analysis."""

from __future__ import annotations

import io
import json
from pathlib import Path

from .field_schema import (
    SCHEMA,
    FieldStatus,
    covered_ranges,
    fields_for_chunk,
)
from .hypothesis_db import HypothesisDB
from .models import ParsedDatabase


# ────────────────────────────────────────────────────────────────────
# 1. Schema Completion Report
# ────────────────────────────────────────────────────────────────────

def schema_completion(hdb: HypothesisDB, header_lengths: dict[str, int] | None = None) -> str:
    """Generate a Markdown table showing known/unknown coverage per chunk type.

    Args:
        hdb: Hypothesis database with analysis results.
        header_lengths: Optional mapping of chunk_type → observed header length.
            If not provided, uses the sum of field sizes from the schema.
    """
    out = io.StringIO()
    out.write("# Schema Completion Report\n\n")
    out.write("| Chunk | Header (B) | Known (B) | Unknown (B) | Coverage | Top Hypothesis |\n")
    out.write("|-------|-----------|-----------|-------------|----------|----------------|\n")

    for ct in sorted(SCHEMA.keys()):
        fields = SCHEMA[ct]
        if not fields:
            continue

        hl = header_lengths.get(ct) if header_lengths else None
        if hl is None:
            hl = max((f.offset + f.size for f in fields), default=12)

        known = sum(
            f.size for f in fields
            if f.status in (FieldStatus.CONFIRMED, FieldStatus.INFERRED) and f.offset + f.size <= hl
        )
        unknown = hl - known
        pct = (known / hl * 100) if hl > 0 else 100.0

        # Best hypothesis for any unknown in this chunk type.
        hypotheses = hdb.top_hypotheses(limit=1, chunk_type=ct)
        top = ""
        if hypotheses:
            h = hypotheses[0]
            top = f"{h['candidate_name'] or h['candidate_type']} @0x{h['rel_offset']:X} ({h['confidence']:.0%})"

        out.write(f"| {ct:6s} | {hl:9d} | {known:9d} | {unknown:11d} | {pct:6.1f}% | {top} |\n")

    return out.getvalue()


# ────────────────────────────────────────────────────────────────────
# 2. Annotated Hex Dump
# ────────────────────────────────────────────────────────────────────

def annotated_hex(
    db: ParsedDatabase,
    chunk_type: str | None = None,
    chunk_index: int = 0,
    hdb: HypothesisDB | None = None,
) -> str:
    """Produce an annotated hex dump for a specific chunk instance.

    Args:
        db: Parsed database containing chunk records.
        chunk_type: Type of chunk to dump (e.g. 'mhit'). If None, dumps the root.
        chunk_index: 0-based index among chunks of that type.
        hdb: Optional hypothesis database for annotations.
    """
    # Find the target chunk.
    if chunk_type is None:
        target = db.root
    else:
        matching = [c for c in db.all_chunks if c.chunk_type == chunk_type]
        if chunk_index >= len(matching):
            return f"No {chunk_type} chunk at index {chunk_index} (found {len(matching)})"
        target = matching[chunk_index]

    raw = target.raw_header
    fields = fields_for_chunk(target.chunk_type)
    covered = covered_ranges(target.chunk_type, len(raw))

    # Build offset → annotation map.
    annotations: dict[int, str] = {}
    for start, end, name in covered:
        annotations[start] = f"  <- {name} ({end - start}B)"

    # Add hypothesis annotations.
    if hdb:
        for h in hdb.all_hypotheses(chunk_type=target.chunk_type):
            off = h["rel_offset"]
            if off not in annotations:
                label = h["candidate_name"] or h["candidate_type"]
                annotations[off] = f"  <- [HYPO] {label} ({h['confidence']:.0%})"

    out = io.StringIO()
    out.write(f"# Annotated Hex: {target.chunk_type} @ file offset 0x{target.abs_offset:X}\n")
    out.write(f"# Header length: {target.header_length} bytes, Total length: {target.total_length}\n\n")

    for off in range(0, len(raw), 16):
        row = raw[off:off + 16]
        hex_part = " ".join(f"{b:02X}" for b in row)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in row)
        line = f"  {off:04X}  {hex_part:<48s}  |{ascii_part}|"

        # Attach annotation if any byte in this row starts a field.
        for byte_off in range(off, min(off + 16, len(raw))):
            if byte_off in annotations:
                line += annotations[byte_off]
                break

        out.write(line + "\n")

    return out.getvalue()


# ────────────────────────────────────────────────────────────────────
# 3. Hypothesis Ranking Table
# ────────────────────────────────────────────────────────────────────

def hypothesis_ranking(hdb: HypothesisDB, limit: int = 20) -> str:
    """Markdown table of the top-N hypotheses by confidence."""
    rows = hdb.top_hypotheses(limit=limit)

    out = io.StringIO()
    out.write("# Top Hypotheses\n\n")
    out.write("| # | Chunk | Offset | Len | Type | Name | Confidence | Files | Rationale |\n")
    out.write("|---|-------|--------|-----|------|------|------------|-------|----------|\n")

    for i, h in enumerate(rows, 1):
        out.write(
            f"| {i} "
            f"| {h['chunk_type']:6s} "
            f"| 0x{h['rel_offset']:04X} "
            f"| {h['length']:3d} "
            f"| {h['candidate_type']:12s} "
            f"| {h['candidate_name'] or '':24s} "
            f"| {h['confidence']:10.0%} "
            f"| {h['supporting_files']:5d} "
            f"| {_truncate(h['rationale'] or '', 60)} |\n"
        )

    return out.getvalue()


# ────────────────────────────────────────────────────────────────────
# 4. Version-Varying Fields
# ────────────────────────────────────────────────────────────────────

def version_report(hdb: HypothesisDB) -> str:
    """List fields that vary between database versions."""
    branches = hdb.version_branches()
    if not branches:
        return "# Version Report\n\nNo version-varying fields detected.\n"

    out = io.StringIO()
    out.write("# Version-Varying Fields\n\n")
    out.write("| Chunk | Offset | Len | Observation | Version Min | Version Max | Detail |\n")
    out.write("|-------|--------|-----|-------------|-------------|-------------|--------|\n")

    for b in branches:
        out.write(
            f"| {b['chunk_type']:6s} "
            f"| 0x{b['rel_offset']:04X} "
            f"| {b['length']:3d} "
            f"| {b['observation']:15s} "
            f"| 0x{b['version_min']:04X} "
            f"| 0x{b['version_max']:04X} "
            f"| {_truncate(b['detail'] or '', 50)} |\n"
        )

    return out.getvalue()


# ────────────────────────────────────────────────────────────────────
# 5. Full Report (all sections)
# ────────────────────────────────────────────────────────────────────

def full_report(
    dbs: list[ParsedDatabase],
    hdb: HypothesisDB,
    output_path: str | Path | None = None,
) -> str:
    """Generate the complete analysis report."""
    # Gather observed header lengths.
    header_lengths: dict[str, int] = {}
    for db in dbs:
        for c in db.all_chunks:
            existing = header_lengths.get(c.chunk_type, 0)
            if c.header_length > existing:
                header_lengths[c.chunk_type] = c.header_length

    summary = hdb.summary()

    parts = [
        "# iTunesDB Comparative Analysis Report\n",
        f"**Files analyzed**: {summary.get('files_ingested', 0)}\n",
        f"**Hypotheses**: {summary.get('total_hypotheses', 0)}\n",
        f"**Patterns**: {summary.get('pattern_observations', 0)}\n",
        f"**Correlations**: {summary.get('correlations', 0)}\n\n",
        "---\n\n",
        schema_completion(hdb, header_lengths),
        "\n---\n\n",
        hypothesis_ranking(hdb),
        "\n---\n\n",
        version_report(hdb),
    ]

    text = "".join(parts)

    if output_path:
        Path(output_path).write_text(text, encoding="utf-8")

    return text


# ────────────────────────────────────────────────────────────────────
# 6. JSON Export
# ────────────────────────────────────────────────────────────────────

def export_json(hdb: HypothesisDB, output_path: str | Path | None = None) -> str:
    """Export all hypotheses, patterns, correlations, and version branches as JSON."""
    data = {
        "summary": hdb.summary(),
        "hypotheses": hdb.top_hypotheses(limit=10000),
        "version_branches": hdb.version_branches(),
    }

    text = json.dumps(data, indent=2, default=str)

    if output_path:
        Path(output_path).write_text(text, encoding="utf-8")

    return text


def _truncate(s: str, max_len: int) -> str:
    return s if len(s) <= max_len else s[: max_len - 3] + "..."
