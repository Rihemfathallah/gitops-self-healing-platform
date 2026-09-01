# ─────────────────────────────────────────────────────────────────────
# EF-01 — local Kubernetes cluster created and destroyed by one command.
# The node image is the default of the pinned provider version, so the
# Kubernetes version is fixed by .terraform.lock.hcl.
# ─────────────────────────────────────────────────────────────────────
resource "kind_cluster" "this" {
  name            = var.cluster_name
  wait_for_ready  = true
  kubeconfig_path = abspath(var.kubeconfig_path)

  kind_config {
    kind        = "Cluster"
    api_version = "kind.x-k8s.io/v1alpha4"

    node {
      role = "control-plane"

      dynamic "extra_port_mappings" {
        for_each = var.host_ports
        content {
          host_port      = tonumber(extra_port_mappings.key)
          container_port = extra_port_mappings.value
          listen_address = "127.0.0.1"
        }
      }
    }
  }
}
