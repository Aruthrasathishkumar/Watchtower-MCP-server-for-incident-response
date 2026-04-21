# Prometheus via kube-prometheus-stack. Mirrors the values we used in
# scripts/k8s-up.sh (grafana + alertmanager disabled, 1-day retention).

resource "helm_release" "prometheus" {
  name       = "prometheus"
  repository = "https://prometheus-community.github.io/helm-charts"
  chart      = "kube-prometheus-stack"
  version    = "~> 56.0"
  namespace  = kubernetes_namespace.monitoring.metadata[0].name

  timeout          = 600
  wait             = true
  create_namespace = false

  values = [
    yamlencode({
      grafana      = { enabled = false }
      alertmanager = { enabled = false }
      prometheus = {
        prometheusSpec = {
          retention       = "1d"
          resources = {
            requests = { memory = "400Mi", cpu = "100m" }
            limits   = { memory = "1Gi",   cpu = "500m" }
          }
        }
      }
    }),
  ]

  depends_on = [kubernetes_namespace.monitoring]
}