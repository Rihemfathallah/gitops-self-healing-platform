output "cluster_name" {
  value = kind_cluster.this.name
}

output "kubeconfig_path" {
  value = kind_cluster.this.kubeconfig_path
}

output "kube_context" {
  value = kind_cluster.this.context_name
}

output "minio_endpoint" {
  description = "S3 endpoint as seen from inside the cluster."
  value       = "http://${docker_container.minio.name}:9000"
}

output "minio_user" {
  value = local.minio_user
}

output "minio_password" {
  value     = random_password.minio.result
  sensitive = true
}

output "velero_bucket" {
  value = var.velero_bucket
}
