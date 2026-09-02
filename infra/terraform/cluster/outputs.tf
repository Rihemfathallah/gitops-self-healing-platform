output "cluster_name" {
  value = kind_cluster.this.name
}

output "kubeconfig_path" {
  value = kind_cluster.this.kubeconfig_path
}

output "kube_context" {
  value = kind_cluster.this.context_name
}

output "s3_endpoint" {
  description = "S3 endpoint as seen from inside the cluster."
  value       = "http://${docker_container.s3.name}:8333"
}

output "s3_user" {
  value = local.s3_user
}

output "s3_password" {
  value     = random_password.s3.result
  sensitive = true
}

output "velero_bucket" {
  value = var.velero_bucket
}
