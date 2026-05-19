#!/bin/bash
#
# Generate the JSON schema for one anyscale version. Installs the
# matching wheel into a cached venv, runs introspect.py, then
# archive_json.py to produce <repo-root>/<version>.json.
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

# `--allow-duplicate-models` softens the introspector's uniqueness
# check (anyscale 0.26.48-0.26.52 had a duplicate CloudDeployment).
"$VENV_DIR/bin/python" "$SCRIPTS_DIR/introspect.py" "$TMP_JSON" --allow-duplicate-models
"$VENV_DIR/bin/python" "$SCRIPTS_DIR/archive_json.py" "$TMP_JSON" "$OUT_JSON" "$ANYSCALE_VERSION"

echo "Wrote $OUT_JSON"
