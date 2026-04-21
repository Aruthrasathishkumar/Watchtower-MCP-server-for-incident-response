#!/usr/bin/env bash
# Stop the WatchTower stack (preserves data volumes)
# Usage: ./scripts/down.sh
set -euo pipefail

echo "==> Stopping WatchTower data services..."
cd "$(dirname "$0")/../infra"
docker compose down

echo ""
echo "==> WatchTower stack is down."
echo "    Data is preserved in Docker volumes. Run ./scripts/up.sh to restart."
echo "    To wipe data too: docker compose down -v"