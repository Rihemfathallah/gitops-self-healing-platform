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

variable "s3_image" {
  description = "S3-compatible object store (SeaweedFS). Pin it to a version tag or digest after the first pull."
  type        = string
  default     = "chrislusf/seaweedfs:latest"
}

variable "velero_bucket" {
  description = "Bucket used by Velero."
  type        = string
  default     = "velero"
}
