# api-docs-schema

Versioned JSON schemas for the Anyscale CLI and SDK, consumed by the SPA archive on [docs.anyscale.com](https://docs.anyscale.com).

Each file in the repo root is the structured introspection of one published `anyscale` PyPI release. The schema is rendered client-side by the docs site as the versioned API archive.

## URL pattern (jsDelivr)

```
https://cdn.jsdelivr.net/gh/anyscale/api-docs-schema@latest/<version>.json
https://cdn.jsdelivr.net/gh/anyscale/api-docs-schema@latest/versions.json
https://cdn.jsdelivr.net/gh/anyscale/api-docs-schema@latest/pages.json
```

- `@latest` resolves to the highest semver-shaped git tag — auto-updated by the archive workflow.
- Pin to a specific tag (`@v2026.05.19-12`) for reproducible builds.

`versions.json` is a JSON array of version strings, newest first. `pages.json` is a `{version: [pages]}` map used by the docs site's redirect generator to map pre-SPA `/ref/<version>/<page>` URLs onto the new `/ref/<page>?v=<version>` query-param scheme.

## Automation

`.github/workflows/archive.yml` runs every Monday and on manual dispatch. It:

1. Reads PyPI for all `anyscale` releases.
2. Diffs against the JSON files in this repo.
3. For each missing version, installs the matching wheel and runs `scripts/archive_version.sh`.
4. Regenerates `versions.json`.
5. Commits, pushes, and tags. jsDelivr's `@latest` picks up the new tag within ~15 minutes.

## Where introspect.py lives

The introspector this repo runs against each anyscale wheel is **not** stored here. It lives in `anyscale/docs` at `scripts/docgen/introspect.py` (plus its `util.py` sibling) and powers current-version reference rendering there too. `scripts/archive_version.sh` downloads both files at run time from a SHA pinned in [`.docs-introspect-sha`](./.docs-introspect-sha), so the docs repo stays the single source of truth and the two surfaces can't silently drift.

Because `anyscale/docs` is a private repo, the fetch uses `gh api` rather than raw.githubusercontent.com. Locally that means having an authenticated `gh` session (`gh auth login`). In CI, the archive workflow exports `GH_TOKEN` from `secrets.DOCS_DISPATCH_TOKEN`; that token needs `contents: read` scope on `anyscale/docs`.

To pick up an introspect change after it lands in the docs repo, edit `.docs-introspect-sha` with the new commit SHA and merge. The next archive run uses it.

## Manual regeneration

```
./scripts/archive_version.sh 0.26.100
python3 scripts/update_manifests.py
```

## Layout

```
<version>.json             # one per anyscale release
versions.json              # array of versions, sorted desc
pages.json                 # {version: [page_names]} map for the docs redirect generator
.docs-introspect-sha       # pinned anyscale/docs commit that scripts/archive_version.sh
                           #   pulls introspect.py + util.py from
scripts/
  archive_json.py          # post-processes reference.json into the schema served at <version>.json
  archive_version.sh       # one-shot wrapper used by the workflow and humans
  update_manifests.py      # regenerates versions.json and pages.json
.github/workflows/
  archive.yml              # weekly cron + manual dispatch
```

## License

See [LICENSE](LICENSE).
