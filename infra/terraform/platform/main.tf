# ─────────────────────────────────────────────────────────────────────
# EF-02 — Terraform installs only what must exist before GitOps can run:
#   Argo CD, Velero (needed before Argo CD during a restore) and the root
#   "app of apps". Everything else is declared in gitops/ and synced by Argo CD.
# ─────────────────────────────────────────────────────────────────────

resource "kubernetes_namespace" "neuralrag" {
  metadata {
    name = "neuralrag"
  }
  lifecycle {
    # Argo CD and Velero add labels/annotations; do not fight over them.
    ignore_changes = [metadata[0].labels, metadata[0].annotations]
  }
}

# The API key never goes to Git: generated here, kept in the local tfstate only.
resource "random_password" "api_key" {
  length  = 32
  special = false
}

resource "kubernetes_secret" "neuralrag_api" {
  metadata {
    name      = "neuralrag-api"
    namespace = kubernetes_namespace.neuralrag.metadata[0].name
  }
  data = {
    API_KEY = random_password.api_key.result
  }
}

# Grafana admin password: generated, stored in a Secret, never in Git.
resource "kubernetes_namespace" "monitoring" {
  metadata {
    name = "monitoring"
  }
  lifecycle {
    ignore_changes = [metadata[0].labels, metadata[0].annotations]
  }
}

resource "random_password" "grafana" {
  length  = 20
  special = false
}

resource "kubernetes_secret" "grafana_admin" {
  metadata {
    name      = "grafana-admin"
    namespace = kubernetes_namespace.monitoring.metadata[0].name
  }
  data = {
    admin-user     = "admin"
    admin-password = random_password.grafana.result
  }
}

resource "helm_release" "argocd" {
  name             = "argocd"
  namespace        = "argocd"
  create_namespace = true
  repository       = "https://argoproj.github.io/argo-helm"
  chart            = "argo-cd"
  version          = var.argocd_chart_version
  wait             = true
  timeout          = 900

  values = [file("${path.module}/values/argocd.yaml")]
}

resource "helm_release" "velero" {
  name             = "velero"
  namespace        = "velero"
  create_namespace = true
  repository       = "https://vmware-tanzu.github.io/helm-charts"
  chart            = "velero"
  version          = var.velero_chart_version
  wait             = true
  timeout          = 900

  values = [templatefile("${path.module}/values/velero.yaml.tftpl", {
    plugin_image    = var.velero_aws_plugin_image
    bucket          = data.terraform_remote_state.cluster.outputs.velero_bucket
    s3_url          = data.terraform_remote_state.cluster.outputs.s3_endpoint
    access_key      = data.terraform_remote_state.cluster.outputs.s3_user
    secret_key      = data.terraform_remote_state.cluster.outputs.s3_password
    backup_schedule = var.backup_schedule
  })]
}

# Root "app of apps": one Application that points to gitops/apps.
resource "helm_release" "root_app" {
  count     = var.restore_mode ? 0 : 1
  name      = "root-app"
  namespace = "argocd"
  chart     = "${path.module}/../../bootstrap"

  set {
    name  = "repoURL"
    value = var.git_repo_url
  }
  set {
    name  = "revision"
    value = var.git_revision
  }

  depends_on = [helm_release.argocd, kubernetes_secret.neuralrag_api, kubernetes_secret.grafana_admin]
}
