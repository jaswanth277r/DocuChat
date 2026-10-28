#!/usr/bin/env bash
# ============================================================
#  DocuChat — single command launcher
#  Usage: ./run.sh
#  All Docker data lives on D: drive (/media/sandeep/DData/07_Docker)
# ============================================================
set -e
cd "$(dirname "$0")"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
info()  { echo -e "${CYAN}[docuchat]${NC} $*"; }
ok()    { echo -e "${GREEN}[✓]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
err()   { echo -e "${RED}[✗]${NC} $*"; exit 1; }

# ── Check D: drive is mounted ─────────────────────────────────
if ! mountpoint -q /media/sandeep/DData 2>/dev/null; then
  err "D: drive is not mounted! Run: sudo mount -t ntfs3 /dev/nvme0n1p5 /media/sandeep/DData -o uid=\$(id -u),gid=\$(id -g),umask=022"
fi
ok "D: drive is mounted"

# ── Check Docker is using D: drive ────────────────────────────
DOCKER_ROOT=$(docker info 2>/dev/null | grep "Docker Root Dir" | awk '{print $NF}')
if [[ "$DOCKER_ROOT" != *"DData"* ]]; then
  warn "Docker is NOT using D: drive yet (currently: $DOCKER_ROOT)"
  warn "Run setup first: sudo bash setup_docker_on_d.sh"
  warn "Continuing anyway — images will build on Linux root!"
else
  ok "Docker using D: drive ($DOCKER_ROOT)"
fi

# ── Load .env ─────────────────────────────────────────────────
[ -f .env ] || err ".env not found"
set -a; source .env; set +a
[ -z "$JWT_SECRET" ]     && err "JWT_SECRET empty in .env"
[ -z "$INTERNAL_TOKEN" ] && err "INTERNAL_TOKEN empty in .env"

if [ -z "$GROQ_API_KEY" ]; then
  warn "GROQ_API_KEY not set — Cloud (Groq) mode will error."
  warn "Get a free key at: https://console.groq.com"
  warn "Then add it to .env: GROQ_API_KEY=gsk_..."
fi

# ── Ollama check ───────────────────────────────────────────────
if command -v ollama &>/dev/null; then
  MODEL="${OLLAMA_MODEL:-llama3.2:3b}"
  if ollama list 2>/dev/null | grep -q "${MODEL%%:*}"; then
    ok "Ollama ready — model: $MODEL"
  else
    info "Pulling Ollama model: $MODEL (this takes a while first time)..."
    ollama pull "$MODEL"
    ok "Ollama model $MODEL ready"
  fi
else
  warn "Ollama not installed — Local mode unavailable. Using Groq only."
fi

# ── Start backend ──────────────────────────────────────────────
info "Starting backend (Mongo + Qdrant + RAG + Gateway) on D: drive..."
docker compose --env-file .env up --build -d

# ── Wait for gateway ───────────────────────────────────────────
info "Waiting for gateway at :4000..."
for i in $(seq 1 60); do
  curl -sf http://localhost:4000/api/health >/dev/null 2>&1 && break
  [ $i -eq 60 ] && err "Gateway didn't start after 60s. Check: docker compose logs gateway"
  sleep 2
done
ok "Gateway healthy at http://localhost:4000"

# ── Frontend ───────────────────────────────────────────────────
info "Installing frontend dependencies..."
cd apps/web
npm install --cache /tmp/npm-cache --silent
ok "Frontend ready"

echo ""
echo -e "${BOLD}${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}${GREEN}  🚀 DocuChat is live!${NC}"
echo -e "${BOLD}${GREEN}  🌐  http://localhost:5173${NC}"
echo -e "${GREEN}  📡  API: http://localhost:4000/api/health${NC}"
echo -e "${GREEN}  Ctrl+C stops frontend  |  ./stop.sh stops backend${NC}"
echo -e "${BOLD}${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
npm run dev
