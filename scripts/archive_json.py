"""Package reference.json as a versioned archive JSON for the SPA.

Replaces archive.py for 0.26.100+. Reads the introspector output, optionally
strips fields the SPA doesn't render, tags with the version, and writes one
minified JSON per version under docs/ref/.

Usage:
    python archive_json.py <reference_json> <output_path> <anyscale_version>
              [--drop-legacy]

The SPA loads docs/ref/<version>.json and renders sections by URL params
(?v=<version>&type=<cli|sdk|models>). No markdown intermediate.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


KEEP_KEYS = ("schema_version", "features", "constants", "model_index", "modules")


def transform(data: dict, version: str, drop_legacy: bool) -> dict:
    out = {k: data[k] for k in KEEP_KEYS if k in data}
    out["anyscale_version"] = version
    if not drop_legacy and "legacy_sources" in data:
        out["legacy_sources"] = data["legacy_sources"]
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Package reference.json as a versioned archive JSON."
    )
    parser.add_argument("reference_json")
    parser.add_argument("output_path")
    parser.add_argument("anyscale_version")
    parser.add_argument(
        "--drop-legacy",
        action="store_true",
        help="Omit legacy_sources from the output (cuts ~50%% of bytes).",
    )
    args = parser.parse_args()

    data = json.loads(Path(args.reference_json).read_text())
    transformed = transform(data, args.anyscale_version, args.drop_legacy)

    out = Path(args.output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(transformed, separators=(",", ":")))

    print(
        f"Archive ready at {out} "
        f"(anyscale=={args.anyscale_version}, "
        f"{out.stat().st_size:,} bytes, "
        f"drop_legacy={args.drop_legacy}).",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
