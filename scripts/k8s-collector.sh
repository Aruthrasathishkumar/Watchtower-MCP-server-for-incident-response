#!/usr/bin/env bash
# Run the WatchTower Kubernetes event collector in watch mode.
# Usage: ./scripts/k8s-collector.sh [--once]
set -euo pipefail

cd "$(dirname "$0")/.."
source server/.venv/bin/activate

# Pass through args (e.g. --once)
python -m collectors.k8s.collector --namespace boutique "$@"