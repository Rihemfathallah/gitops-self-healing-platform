# ─────────────────────────────────────────────────────────────────────
# EF-12 — backup target: an S3-compatible object store (SeaweedFS) running
# as a plain Docker container on the "kind" network, NOT inside the cluster:
# destroying the cluster must not destroy the backups.
#
# Why not MinIO: MinIO withdrew its public images from Docker Hub and Quay
# (2026) and its community edition is archived. See docs/adr/0004.
# ─────────────────────────────────────────────────────────────────────
resource "random_password" "s3" {
  length  = 24
  special = false
}

locals {
  s3_user = "velero"
}

# Survives `make destroy-cluster`: the backups live here.
resource "docker_volume" "s3" {
  name = "${var.cluster_name}-s3-data"
}

resource "docker_image" "s3" {
  name         = var.s3_image
  keep_locally = true
}

resource "docker_container" "s3" {
  name    = "${var.cluster_name}-s3"
  image   = docker_image.s3.image_id
  command = ["mini", "-dir=/data"]
  restart = "unless-stopped"

  # `weed mini` creates the credentials and the bucket from these variables.
  env = [
    "AWS_ACCESS_KEY_ID=${local.s3_user}",
    "AWS_SECRET_ACCESS_KEY=${random_password.s3.result}",
    "S3_BUCKET=${var.velero_bucket}",
  ]

  # Same Docker network as the kind node: Velero reaches http://<name>:8333
  networks_advanced {
    name = "kind"
  }

  # S3 API also reachable from the VM, for inspection (aws/rclone/s3cmd).
  ports {
    internal = 8333
    external = 8333
    ip       = "127.0.0.1"
  }

  volumes {
    volume_name    = docker_volume.s3.name
    container_path = "/data"
  }

  # The "kind" network is created by the first kind cluster.
  depends_on = [kind_cluster.this]
}
