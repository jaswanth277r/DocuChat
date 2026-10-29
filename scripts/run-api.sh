#!/usr/bin/env bash
# Start the DocuChat API. All caches and scratch files go to the data drive
# when .env.local defines the paths.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -f "$ROOT/.env.local" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT/.env.local"
  set +a
fi

export PYTHONPYCACHEPREFIX="${PYTHONPYCACHEPREFIX:-$ROOT/.pycache}"
export TMPDIR="${TMPDIR:-$ROOT/.tmp}"
mkdir -p "$PYTHONPYCACHEPREFIX" "$TMPDIR"

exec "${DOCUCHAT_VENV_DIR:-$ROOT/.venv}/bin/uvicorn" app.main:app \
  --app-dir "$ROOT/backend" \
  --host "${HOST:-127.0.0.1}" \
  --port "${PORT:-8000}"
