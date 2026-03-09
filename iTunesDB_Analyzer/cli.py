"""Interactive CLI for the iTunesDB Analyzer.

Commands:
    analyze <dir_or_file> [...]  — Ingest iTunesDB files and run all passes
    status                       — Show summary of hypothesis database
    inspect <chunk_type> <offset>— Show hypotheses/patterns for a specific field
    assert <chunk_type> <offset> <length> <type> <name>
                                 — Manually assert a field identity (ground truth)
    correlate [known_field]      — Show cross-field correlations
    export [path]                — Export all data as JSON
    report [path]                — Generate full Markdown report
    hex <chunk_type> [index]     — Annotated hex dump of a chunk instance
    help                         — Show this help
    quit / exit                  — Exit
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Sequence

from .bridge import ingest
from .hypothesis_db import HypothesisDB
from .models import ParsedDatabase
from .passes import run_all
from .reports import (
    annotated_hex,
    export_json,
    full_report,
    hypothesis_ranking,
    schema_completion,
    version_report,
)

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = "analyzer_hypotheses.sqlite"


# ────────────────────────────────────────────────────────────────────
# Public entry point
# ────────────────────────────────────────────────────────────────────

def main(argv: Sequence[str] | None = None) -> None:
    """CLI entry point — parse top-level args then enter interactive loop."""
    parser = argparse.ArgumentParser(
        prog="itunesdb-analyzer",
        description="Comparative analysis of iTunesDB binary files",
    )
    parser.add_argument(
        "--db", default=_DEFAULT_DB_PATH,
        help="Path to the hypothesis SQLite database (default: %(default)s)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "files", nargs="*",
        help="iTunesDB files or directories to analyze immediately on start",
    )

    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    hdb = HypothesisDB(args.db)
    loaded_dbs: list[ParsedDatabase] = []

    # If files were passed on the command line, analyze them immediately.
    if args.files:
        loaded_dbs = _do_analyze(args.files, hdb)
        print(f"Analyzed {len(loaded_dbs)} file(s). Type 'status' for summary.\n")

    # Interactive loop.
    _interactive_loop(hdb, loaded_dbs)


# ────────────────────────────────────────────────────────────────────
# Interactive loop
# ────────────────────────────────────────────────────────────────────

def _interactive_loop(hdb: HypothesisDB, loaded_dbs: list[ParsedDatabase]) -> None:
    """Read-eval-print loop."""
    print("iTunesDB Analyzer — type 'help' for commands\n")

    while True:
        try:
            line = input("analyzer> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not line:
            continue

        parts = line.split()
        cmd = parts[0].lower()
        rest = parts[1:]

        try:
            if cmd in ("quit", "exit", "q"):
                break
            elif cmd == "help":
                _cmd_help()
            elif cmd == "analyze":
                loaded_dbs = _do_analyze(rest, hdb)
                print(f"Analyzed {len(loaded_dbs)} file(s).")
            elif cmd == "status":
                _cmd_status(hdb)
            elif cmd == "inspect":
                _cmd_inspect(rest, hdb)
            elif cmd == "assert":
                _cmd_assert(rest, hdb)
            elif cmd == "correlate":
                _cmd_correlate(rest, hdb)
            elif cmd == "export":
                _cmd_export(rest, hdb)
            elif cmd == "report":
                _cmd_report(rest, hdb, loaded_dbs)
            elif cmd == "hex":
                _cmd_hex(rest, hdb, loaded_dbs)
            elif cmd == "ranking":
                print(hypothesis_ranking(hdb))
            elif cmd == "schema":
                print(schema_completion(hdb))
            elif cmd == "versions":
                print(version_report(hdb))
            else:
                print(f"Unknown command: {cmd}. Type 'help' for commands.")
        except Exception as exc:
            print(f"Error: {exc}")
            logger.debug("Command error", exc_info=True)


# ────────────────────────────────────────────────────────────────────
# Command implementations
# ────────────────────────────────────────────────────────────────────

def _do_analyze(paths: list[str], hdb: HypothesisDB) -> list[ParsedDatabase]:
    """Ingest files and run all analysis passes."""
    files = _resolve_files(paths)
    if not files:
        print("No iTunesDB files found.")
        return []

    dbs: list[ParsedDatabase] = []
    for f in files:
        print(f"  Ingesting {f} ...")
        try:
            db = ingest(str(f))
            hdb.record_file(db)
            dbs.append(db)
            print(f"    {db.track_count} tracks, version 0x{db.db_version:X} ({db.db_version_name}), "
                  f"{len(db.unknowns)} unknown regions")
        except Exception as exc:
            print(f"    ERROR: {exc}")
            logger.debug("Ingest error", exc_info=True)

    if dbs:
        print(f"\nRunning analysis passes on {len(dbs)} file(s) ...")
        run_all(dbs, hdb)
        print("Done.\n")

    return dbs


def _resolve_files(paths: list[str]) -> list[Path]:
    """Resolve paths to actual iTunesDB files (recurse into directories)."""
    result: list[Path] = []
    for p_str in paths:
        p = Path(p_str)
        if p.is_file():
            result.append(p)
        elif p.is_dir():
            # Look for iTunesDB files in subdirectories.
            for candidate in p.rglob("*"):
                if candidate.is_file() and candidate.name.lower() in (
                    "itunesdb", "itunesdb.bak", "itunesdb.orig",
                ):
                    result.append(candidate)
            # Also accept any file the user might have named iTunesDB-something.
            if not result:
                for candidate in p.rglob("*"):
                    if candidate.is_file() and "itunesdb" in candidate.name.lower():
                        result.append(candidate)
        else:
            print(f"  Warning: {p_str} not found, skipping")
    return result


def _cmd_help() -> None:
    print(__doc__ or "No help available.")


def _cmd_status(hdb: HypothesisDB) -> None:
    s = hdb.summary()
    print(f"  Files ingested  : {s.get('files_ingested', 0)}")
    print(f"  Hypotheses      : {s.get('total_hypotheses', 0)}")
    print(f"  Patterns        : {s.get('pattern_observations', 0)}")
    print(f"  Correlations    : {s.get('correlations', 0)}")
    print(f"  Version branches: {s.get('version_branches', 0)}")


def _cmd_inspect(args: list[str], hdb: HypothesisDB) -> None:
    if len(args) < 2:
        print("Usage: inspect <chunk_type> <hex_offset>")
        return

    chunk_type = args[0]
    try:
        offset = int(args[1], 0)  # Accept hex with 0x prefix or decimal.
    except ValueError:
        print(f"Invalid offset: {args[1]}")
        return

    hypotheses = hdb.hypotheses_for(chunk_type, offset)
    if not hypotheses:
        print(f"No hypotheses for {chunk_type}+0x{offset:X}")
        return

    print(f"\nHypotheses for {chunk_type}+0x{offset:X}:\n")
    for h in hypotheses:
        print(f"  [{h['confidence']:.0%}] {h['candidate_type']:12s}  "
              f"{h['candidate_name'] or '':24s}  "
              f"({h['supporting_files']} files)  {h['rationale'] or ''}")

    # Also show correlations.
    corrs = hdb.correlations_for(chunk_type=chunk_type, unknown_offset=offset)
    if corrs:
        print(f"\nCorrelations:")
        for c in corrs:
            print(f"  {c['known_field']:24s} {c['relation']:8s}  "
                  f"strength={c['strength']:.2f}  ({c['sample_count']} samples)")


def _cmd_assert(args: list[str], hdb: HypothesisDB) -> None:
    if len(args) < 5:
        print("Usage: assert <chunk_type> <hex_offset> <length> <type> <name>")
        return

    chunk_type = args[0]
    try:
        offset = int(args[1], 0)
        length = int(args[2], 0)
    except ValueError:
        print("Invalid offset or length")
        return

    cand_type = args[3]
    cand_name = " ".join(args[4:])

    hdb.upsert_hypothesis(
        chunk_type, offset, length, cand_type, cand_name,
        confidence=1.0,
        supporting_files=0,
        rationale="Manually asserted by user",
        is_ground_truth=True,
    )
    print(f"Asserted: {chunk_type}+0x{offset:X} ({length}B) = {cand_type} '{cand_name}'")


def _cmd_correlate(args: list[str], hdb: HypothesisDB) -> None:
    known_field = args[0] if args else None
    corrs = hdb.correlations_for(known_field=known_field, min_strength=0.5)

    if not corrs:
        filter_str = f" for {known_field}" if known_field else ""
        print(f"No correlations{filter_str} with strength >= 0.5")
        return

    print(f"\n{'Chunk':<6s}  {'UnkOff':>8s}  {'Len':>3s}  {'Known Field':<24s}  "
          f"{'Relation':<10s}  {'Strength':>8s}  {'Samples':>7s}")
    print("-" * 80)
    for c in corrs:
        print(f"{c['chunk_type']:<6s}  0x{c['unknown_offset']:04X}    "
              f"{c['length']:3d}  {c['known_field']:<24s}  "
              f"{c['relation']:<10s}  {c['strength']:8.3f}  {c['sample_count']:7d}")


def _cmd_export(args: list[str], hdb: HypothesisDB) -> None:
    path = args[0] if args else "analyzer_export.json"
    export_json(hdb, path)
    print(f"Exported to {path}")


def _cmd_report(args: list[str], hdb: HypothesisDB, dbs: list[ParsedDatabase]) -> None:
    path = args[0] if args else "analyzer_report.md"
    text = full_report(dbs, hdb, path)
    print(f"Report written to {path} ({len(text)} bytes)")


def _cmd_hex(args: list[str], hdb: HypothesisDB, dbs: list[ParsedDatabase]) -> None:
    if not dbs:
        print("No databases loaded. Run 'analyze' first.")
        return
    if not args:
        print("Usage: hex <chunk_type> [index] [file_index]")
        return

    chunk_type = args[0]
    index = int(args[1]) if len(args) > 1 else 0
    file_idx = int(args[2]) if len(args) > 2 else 0

    if file_idx >= len(dbs):
        print(f"File index {file_idx} out of range (have {len(dbs)} files)")
        return

    print(annotated_hex(dbs[file_idx], chunk_type, index, hdb))


if __name__ == "__main__":
    main()
