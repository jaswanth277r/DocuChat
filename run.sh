#!/usr/bin/env bash
set -e

# ==============================================================================
# Unified Launcher: DocuChat (FastAPI + React Frontend)
# ==============================================================================

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API_PORT="${PORT:-8010}"
FRONTEND_PORT="${VITE_PORT:-5173}"

echo "========================================================"
echo "🚀 Starting DocuChat System"
echo "========================================================"

# Free ports if occupied
free_port() {
    local port=$1
    local pids=$(lsof -t -i :"$port" 2>/dev/null || true)
    if [ -n "$pids" ]; then
        echo ">> Freeing port ${port} occupied by PID(s): ${pids}..."
        kill -9 $pids 2>/dev/null || true
        sleep 0.5
    fi
}

free_port "$API_PORT"
free_port "$FRONTEND_PORT"

# Cleanup child processes on exit
cleanup() {
    echo ""
    echo "🛑 Shutting down DocuChat backend and frontend..."
    kill $(jobs -p) 2>/dev/null || true
    exit 0
}
trap cleanup SIGINT SIGTERM EXIT

# 1. Start DocuChat Backend
echo ">> [1/2] Launching DocuChat API on http://127.0.0.1:${API_PORT}..."
PORT="${API_PORT}" "$ROOT/scripts/run-api.sh" &
BACKEND_PID=$!

sleep 2
if ! kill -0 $BACKEND_PID 2>/dev/null; then
    echo "❌ API failed to start."
    exit 1
fi
echo "   ✅ API online at http://127.0.0.1:${API_PORT}"
echo "   📖 API docs at http://127.0.0.1:${API_PORT}/api/docs"

# 2. Start DocuChat Frontend
echo ">> [2/2] Launching DocuChat Frontend on http://127.0.0.1:${FRONTEND_PORT}..."
VITE_PROXY_TARGET="http://127.0.0.1:${API_PORT}" "$ROOT/scripts/run-frontend.sh" &

wait
