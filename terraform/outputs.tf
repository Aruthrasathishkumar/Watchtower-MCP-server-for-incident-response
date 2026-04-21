output "postgres_connection_string" {
  description = "DATABASE_URL-shaped connection string for the local Postgres."
  value       = "postgresql://${var.postgres_user}:${var.postgres_password}@localhost:${var.postgres_port}/${var.postgres_db}"
  sensitive   = true
}

output "postgres_host_port" {
  description = "Host port Postgres is listening on."
  value       = var.postgres_port
}

output "prometheus_port_forward_command" {
  value = "kubectl port-forward -n ${var.monitoring_namespace} svc/prometheus-kube-prometheus-prometheus 9090:9090"
}

output "loki_port_forward_command" {
  value = "kubectl port-forward -n ${var.logging_namespace} svc/loki 3100:3100"
}

output "namespaces" {
  description = "Namespaces managed by this Terraform config."
  value = [
    kubernetes_namespace.boutique.metadata[0].name,
    kubernetes_namespace.monitoring.metadata[0].name,
    kubernetes_namespace.logging.metadata[0].name,
  ]
}