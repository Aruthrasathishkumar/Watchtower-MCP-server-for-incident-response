# Knobs for the WatchTower local stack.

variable "docker_host" {
  type        = string
  description = "Docker daemon socket URL."
  default     = "unix:///var/run/docker.sock"
}

variable "kubeconfig_path" {
  type        = string
  description = "Path to the kubeconfig file minikube wrote."
  default     = "~/.kube/config"
}

variable "kube_context" {
  type        = string
  description = "kubectl context name — minikube profile name by default."
  default     = "watchtower"
}

variable "postgres_image" {
  type        = string
  description = "Postgres + pgvector + TimescaleDB image."
  default     = "timescale/timescaledb-ha:pg16"
}

variable "postgres_port" {
  type        = number
  description = "Host port exposing Postgres."
  default     = 5432
}

variable "postgres_user" {
  type    = string
  default = "watchtower"
}

variable "postgres_password" {
  type      = string
  sensitive = true
  default   = "watchtower-dev"
}

variable "postgres_db" {
  type    = string
  default = "watchtower"
}

variable "boutique_namespace" {
  type    = string
  default = "boutique"
}

variable "monitoring_namespace" {
  type    = string
  default = "monitoring"
}

variable "logging_namespace" {
  type    = string
  default = "logging"
}

variable "loki_retention_hours" {
  type        = number
  description = "Loki log retention in hours."
  default     = 72
}