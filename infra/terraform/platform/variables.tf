variable "git_repo_url" {
  description = "Public Git repository watched by Argo CD (this repository)."
  type        = string
  default     = "https://github.com/Rihemfathallah/gitops-self-healing-platform.git"
}

variable "git_revision" {
  description = "Branch, tag or commit Argo CD follows."
  type        = string
  default     = "main"
}

variable "restore_mode" {
  description = <<-EOT
    true during disaster recovery: install Argo CD and Velero but NOT the root
    application, so Velero can restore the volumes before Argo CD recreates
    empty ones. The DR script sets it to true, restores, then sets it back to false.
  EOT
  type        = bool
  default     = false
}

variable "backup_schedule" {
  description = "Cron schedule of the Velero backup of the neuralrag namespace (EF-12)."
  type        = string
  default     = "*/15 * * * *"
}

variable "argocd_chart_version" {
  type    = string
  default = "10.18.0"
}

variable "velero_chart_version" {
  type    = string
  default = "12.2.5"
}

variable "velero_aws_plugin_image" {
  type    = string
  default = "velero/velero-plugin-for-aws:v1.14.4"
}
