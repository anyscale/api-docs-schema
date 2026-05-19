"""Regenerate the manifest files from the schema files at the repo root.

Writes two artifacts consumed by docs.anyscale.com at build/runtime:

- versions.json: array of version strings, newest-first.
    ["0.26.100", "0.26.99", ...]

- pages.json: per-version page list (filename without .md), used by
  the docs site's redirect generator to map old /ref/<v>/<page> URLs
  to the new /ref/<page>?v=<v> SPA scheme.
    {"0.26.100": ["aggregated-instance-usage", "cloud", ...], ...}
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


def version_key(s: str) -> tuple:
    return tuple(int(p) for p in s.split("."))


def main() -> int:
    schema_files = sorted(
        (f for f in ROOT.iterdir() if f.suffix == ".json" and PATTERN.match(f.stem)),
        key=lambda f: version_key(f.stem),
        reverse=True,
    )
    versions = [f.stem for f in schema_files]

    pages = {}
    for f in schema_files:
        data = json.loads(f.read_text())
        modules = data.get("modules", []) or []
        page_names = []
        for m in modules:
            filename = (m.get("filename") or "").removesuffix(".md")
            if filename:
                page_names.append(filename)
        pages[f.stem] = sorted(set(page_names))

    (ROOT / "versions.json").write_text(json.dumps(versions) + "\n")
    (ROOT / "pages.json").write_text(json.dumps(pages) + "\n")
    print(
        f"Wrote versions.json ({len(versions)} versions) "
        f"and pages.json ({sum(len(v) for v in pages.values())} entries)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
