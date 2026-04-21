#!/usr/bin/env bash
# Stop the WatchTower minikube cluster (workloads and state are preserved).
set -euo pipefail

echo "==> Stopping minikube profile 'watchtower'..."
minikube stop --profile=watchtower

echo ""
echo "==> Cluster is stopped."
echo "    Workloads and state are preserved. Run ./scripts/k8s-up.sh to restart."
echo "    To wipe the cluster entirely: minikube delete --profile=watchtower"