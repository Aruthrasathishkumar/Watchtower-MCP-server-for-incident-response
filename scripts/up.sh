#!/usr/bin/env bash
# Start the WatchTower stack (Docker services + checks)
# Usage: ./scripts/up.sh
set -euo pipefail

echo "==> Starting Docker service (if not already running)..."
sudo service docker start || true

echo "==> Starting WatchTower data services..."
cd "$(dirname "$0")/../infra"
docker compose up -d

echo "==> Waiting for Postgres to become healthy..."
for i in $(seq 1 30); do
    status=$(docker inspect watchtower-postgres --format='{{.State.Health.Status}}' 2>/dev/null || echo "starting")
    if [ "$status" = "healthy" ]; then
        echo "==> Postgres is healthy."
        break
    fi
    echo "    still $status... ($i/30)"
    sleep 2
done

if [ "$status" != "healthy" ]; then
    echo "==> ERROR: Postgres did not become healthy in time."
    echo "==> Last logs:"
    docker logs watchtower-postgres --tail 20
    exit 1
fi

echo ""
echo "==> WatchTower stack is up."
echo "    Postgres:  localhost:5432  (user: watchtower, db: watchtower)"
echo "    Use 'psql' to connect."