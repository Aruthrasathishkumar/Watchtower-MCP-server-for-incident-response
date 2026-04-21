# Loki single-binary mode + Promtail DaemonSet.
# Values mirror infra/k8s/loki-values.yaml and promtail-values.yaml.

resource "helm_release" "loki" {
  name       = "loki"
  repository = "https://grafana.github.io/helm-charts"
  chart      = "loki"
  namespace  = kubernetes_namespace.logging.metadata[0].name

  timeout          = 600
  wait             = true
  create_namespace = false

  values = [
    yamlencode({
      deploymentMode = "SingleBinary"
      loki = {
        auth_enabled = false
        commonConfig = { replication_factor = 1 }
        storage      = { type = "filesystem" }
        schemaConfig = {
          configs = [
            {
              from         = "2024-01-01"
              store        = "tsdb"
              object_store = "filesystem"
              schema       = "v13"
              index        = { prefix = "loki_index_", period = "24h" }
            },
          ]
        }
        limits_config = {
          retention_period            = "${var.loki_retention_hours}h"
          allow_structured_metadata   = true
          volume_enabled              = true
        }
      }
      singleBinary = {
        replicas    = 1
        persistence = { enabled = true, size = "5Gi" }
      }
      write   = { replicas = 0 }
      read    = { replicas = 0 }
      backend = { replicas = 0 }
      chunksCache   = { enabled = false }
      resultsCache  = { enabled = false }
      gateway       = { enabled = false }
      test          = { enabled = false }
      monitoring = {
        selfMonitoring  = { enabled = false, grafanaAgent = { installOperator = false } }
        lokiCanary      = { enabled = false }
        serviceMonitor  = { enabled = false }
      }
    }),
  ]

  depends_on = [kubernetes_namespace.logging]
}

resource "helm_release" "promtail" {
  name       = "promtail"
  repository = "https://grafana.github.io/helm-charts"
  chart      = "promtail"
  namespace  = kubernetes_namespace.logging.metadata[0].name

  timeout = 300
  wait    = true

  values = [
    yamlencode({
      config = {
        clients = [
          {
            url = "http://loki.${var.logging_namespace}.svc.cluster.local:3100/loki/api/v1/push"
          },
        ]
      }
      serviceMonitor = { enabled = false }
    }),
  ]

  depends_on = [helm_release.loki]
}