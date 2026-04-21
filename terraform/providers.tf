# Docker provider — connects to local Docker daemon via WSL socket.
provider "docker" {
  host = var.docker_host
}

# Kubernetes provider — uses the kubeconfig written by minikube.
provider "kubernetes" {
  config_path    = var.kubeconfig_path
  config_context = var.kube_context
}

# Helm provider — piggybacks on the same kubeconfig.
provider "helm" {
  kubernetes {
    config_path    = var.kubeconfig_path
    config_context = var.kube_context
  }
}