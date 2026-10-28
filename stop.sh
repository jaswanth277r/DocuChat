#!/usr/bin/env bash
cd "$(dirname "$0")"
echo "Stopping DocuChat backend..."
docker compose down
echo "✅ All containers stopped. Data remains on D: drive."
