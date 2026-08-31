variable "cluster_name" {
  description = "Name of the kind cluster."
  type        = string
  default     = "selfheal"
}

variable "kubeconfig_path" {
  description = "Where the kubeconfig of the cluster is written (gitignored)."
  type        = string
  default     = "../../../.kube/config"
}

variable "host_ports" {
  description = "NodePorts of the cluster published on localhost (host port => node port)."
  type        = map(number)
  default = {
    "8080" = 30080 # NeuralRAG API
    "3000" = 30030 # Grafana
    "9090" = 30090 # Prometheus
    "9093" = 30093 # Alertmanager
    "8443" = 30443 # Argo CD
  }
}

variable "minio_image" {
  description = "MinIO image, pinned (backup target, lives outside the cluster on purpose)."
  type        = string
  default     = "minio/minio:RELEASE.2025-09-07T16-13-09Z"
}

variable "minio_mc_image" {
  description = "MinIO client image used once to create the bucket."
  type        = string
  default     = "minio/mc:RELEASE.2025-08-13T08-35-41Z"
}

variable "velero_bucket" {
  description = "Bucket used by Velero."
  type        = string
  default     = "velero"
}
