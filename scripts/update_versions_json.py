"""Regenerate versions.json from the schema files at the repo root.

Produces an array of version strings, sorted newest-first, e.g.:
    ["0.26.100", "0.26.99", "0.26.98", ...]

The SPA fetches this file once to populate the version switcher.
"""
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


def main() -> int:
    versions = sorted(
        (f.stem for f in ROOT.iterdir() if f.suffix == ".json" and PATTERN.match(f.stem)),
        key=lambda s: tuple(int(p) for p in s.split(".")),
        reverse=True,
    )
    out = ROOT / "versions.json"
    out.write_text(json.dumps(versions) + "\n")
    print(f"Wrote {out} ({len(versions)} versions)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
