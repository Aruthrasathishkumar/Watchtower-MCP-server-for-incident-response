# Namespaces for the WatchTower local cluster.
# We declare them but do NOT attempt to provision Boutique via Terraform;
# Boutique is a third-party demo app whose manifest evolves outside our
# repo. We apply it via kubectl in scripts/k8s-up.sh. Terraform owns the
# infrastructure primitives; kubectl owns the demo app.

resource "kubernetes_namespace" "boutique" {
  metadata {
    name = var.boutique_namespace
    labels = {
      managed_by = "terraform"
      component  = "boutique-demo"
    }
  }
}

resource "kubernetes_namespace" "monitoring" {
  metadata {
    name = var.monitoring_namespace
    labels = {
      managed_by = "terraform"
      component  = "observability"
    }
  }
}

resource "kubernetes_namespace" "logging" {
  metadata {
    name = var.logging_namespace
    labels = {
      managed_by = "terraform"
      component  = "observability"
    }
  }
}