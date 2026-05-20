#!/bin/bash
#
# Generate the JSON schema for one anyscale version. Installs the
# matching wheel into a cached venv, downloads the docs-repo's
# introspect.py at the SHA pinned in .docs-introspect-sha, runs it
# against the venv, then post-processes with archive_json.py to
# produce <repo-root>/<version>.json.
#
# Why pin to a docs-repo SHA: introspect.py is also used to render
# current-version docs in anyscale/docs (`scripts/docgen/introspect.py`).
# Keeping a copy here would drift. Pulling at a pinned SHA makes the
# docs repo the single source of truth without coupling our nightly
# archive to whatever happens to be on master at 4am. Bump
# .docs-introspect-sha when an introspect change in the docs repo
# should propagate here.
#
# Usage:
#   ./scripts/archive_version.sh 0.26.100

set -exo pipefail

if [[ -z "$1" ]]; then
  echo "Usage: $0 <anyscale_version>"
  echo "Example: $0 0.26.100"
  exit 1
fi

ANYSCALE_VERSION="$1"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPTS_DIR="$REPO_ROOT/scripts"
TMP_JSON="$(mktemp -d)/reference-$ANYSCALE_VERSION.json"
OUT_JSON="$REPO_ROOT/$ANYSCALE_VERSION.json"

DOCGEN_PYTHON_VERSION="${DOCGEN_PYTHON_VERSION:-3.10}"

if ! command -v pyenv &>/dev/null; then
  echo "pyenv is required but not installed."
  echo "See: https://github.com/pyenv/pyenv#installation"
  exit 1
fi

PYTHON_FULL_VERSION=$(pyenv latest --known "$DOCGEN_PYTHON_VERSION")
pyenv install --skip-existing "$PYTHON_FULL_VERSION"
PYTHON_BIN=$(PYENV_VERSION="$PYTHON_FULL_VERSION" pyenv which python)

VENV_DIR="$HOME/.cache/anyscale-docgen/$ANYSCALE_VERSION"
if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
  "$VENV_DIR/bin/pip" install -q "anyscale==$ANYSCALE_VERSION"
fi

# Fetch introspect.py + util.py from anyscale/docs at the pinned SHA
# via `gh api` (works against the private docs repo unlike a plain
# curl). Downloaded into scripts/.docgen/ (gitignored) so the
# `from util import ...` inside introspect.py resolves against the
# sibling file.
#
# Locally: your `gh auth login` covers it. In the archive workflow:
# GH_TOKEN must be set to a token with contents:read on anyscale/docs.
DOCS_INTROSPECT_SHA="$(tr -d '[:space:]' < "$REPO_ROOT/.docs-introspect-sha")"
DOCGEN_CACHE_DIR="$SCRIPTS_DIR/.docgen"
mkdir -p "$DOCGEN_CACHE_DIR"
for f in introspect.py util.py; do
  gh api \
    "repos/anyscale/docs/contents/scripts/docgen/${f}?ref=${DOCS_INTROSPECT_SHA}" \
    -H "Accept: application/vnd.github.raw" \
    > "${DOCGEN_CACHE_DIR}/${f}"
done

# `--allow-duplicate-models` softens the introspector's uniqueness
# check (anyscale 0.26.48-0.26.52 had a duplicate CloudDeployment).
"$VENV_DIR/bin/python" "$DOCGEN_CACHE_DIR/introspect.py" "$TMP_JSON" --allow-duplicate-models
"$VENV_DIR/bin/python" "$SCRIPTS_DIR/archive_json.py" "$TMP_JSON" "$OUT_JSON" "$ANYSCALE_VERSION"

echo "Wrote $OUT_JSON"
