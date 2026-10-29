#!/usr/bin/env bash
# Install frontend dependencies without filling the system partition.
#
# npm deletes a symlinked node_modules before installing, so dependencies are
# installed in a directory outside the repository and then linked in.
# Set DOCUCHAT_DEPS_DIR to choose the location; it defaults to a folder on the
# same volume as the repository.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -f "$ROOT/.env.local" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT/.env.local"
  set +a
fi
DEPS_DIR="${DOCUCHAT_DEPS_DIR:-$ROOT/.deps}"
CACHE_DIR="${DOCUCHAT_NPM_CACHE:-$ROOT/.deps/.npm-cache}"

mkdir -p "$DEPS_DIR" "$CACHE_DIR"
cp "$ROOT/frontend/package.json" "$DEPS_DIR/package.json"
if [ -f "$ROOT/frontend/package-lock.json" ]; then
  cp "$ROOT/frontend/package-lock.json" "$DEPS_DIR/package-lock.json"
fi

(cd "$DEPS_DIR" && npm install --no-audit --no-fund --cache "$CACHE_DIR")
ln -sfn "$DEPS_DIR/node_modules" "$ROOT/frontend/node_modules"
echo "Frontend dependencies installed in $DEPS_DIR/node_modules"
echo "Linked to $ROOT/frontend/node_modules"
