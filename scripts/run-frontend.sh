#!/usr/bin/env bash
# Start the Vite dev server. Dependencies and Vite's cache live outside the repo.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -f "$ROOT/.env.local" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT/.env.local"
  set +a
fi

export VITE_PROXY_TARGET="${VITE_PROXY_TARGET:-http://127.0.0.1:8000}"
export TMPDIR="${TMPDIR:-$ROOT/.tmp}"
cd "$ROOT/frontend"
exec npm run dev -- --host "${VITE_HOST:-127.0.0.1}"
