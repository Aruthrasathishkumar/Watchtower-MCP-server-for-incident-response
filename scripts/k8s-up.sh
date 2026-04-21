#!/usr/bin/env bash
# Start the WatchTower minikube cluster and all deployed workloads.
# Assumes everything was originally deployed by following Phase 6.
set -euo pipefail

echo "==> Starting Docker (if not running)..."
sudo service docker start || true

echo "==> Starting minikube profile 'watchtower'..."
minikube start --profile=watchtower

echo "==> Setting default namespace to boutique..."
kubectl config set-context --current --namespace=boutique

echo "==> Waiting for Boutique pods to be ready..."
kubectl wait --for=condition=ready pod -l app=frontend -n boutique --timeout=180s || true

echo "==> Waiting for Prometheus to be ready..."
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=prometheus -n monitoring --timeout=120s || true

echo ""
echo "==> Cluster is up."
echo "    Pods:        kubectl get pods -A"
echo "    Boutique:    minikube service frontend-external --profile=watchtower --url"
echo "    Prometheus:  kubectl port-forward -n monitoring svc/prometheus-kube-prometheus-prometheus 9090:9090"