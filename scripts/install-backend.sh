#!/usr/bin/env bash
# Install backend dependencies without filling the system partition.
# Requires uv. The virtualenv and its cache live outside the repository.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -f "$ROOT/.env.local" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT/.env.local"
  set +a
fi
VENV_DIR="${DOCUCHAT_VENV_DIR:-$ROOT/.venv}"
export UV_CACHE_DIR="${DOCUCHAT_UV_CACHE:-$ROOT/.uv-cache}"
export PIP_CACHE_DIR="${DOCUCHAT_PIP_CACHE:-$ROOT/.pip-cache}"

if [ ! -x "$VENV_DIR/bin/python" ]; then
  uv venv "$VENV_DIR" --python 3.12
fi

"$VENV_DIR/bin/python" -m ensurepip >/dev/null 2>&1 || true
UV_PROJECT_ENVIRONMENT="$VENV_DIR" uv pip install --python "$VENV_DIR/bin/python" -r "$ROOT/backend/requirements.txt"
echo "Backend dependencies installed in $VENV_DIR"
