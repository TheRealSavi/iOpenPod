"""Export an iTunesDB to readable, lossless forensic JSON."""

from __future__ import annotations

import argparse
from pathlib import Path

from iopenpod.itunesdb_parser.forensics import export_forensic_json


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="iTunesDB or iTunesCDB file to inspect")
    parser.add_argument("destination", type=Path, help="JSON file to create")
    args = parser.parse_args()

    output = export_forensic_json(args.source, args.destination)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
