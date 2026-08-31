# ─────────────────────────────────────────────────────────────────────
# EF-12 — backup target. MinIO runs as a plain Docker container on the
# "kind" network, NOT inside the cluster: destroying the cluster must not
# destroy the backups. `make destroy-cluster` targets kind_cluster only.
# ─────────────────────────────────────────────────────────────────────
resource "random_password" "minio" {
  length  = 24
  special = false
}

locals {
  minio_user = "velero"
}

resource "docker_volume" "minio" {
  name = "${var.cluster_name}-minio-data"
}

resource "docker_image" "minio" {
  name         = var.minio_image
  keep_locally = true
}

resource "docker_image" "mc" {
  name         = var.minio_mc_image
  keep_locally = true
}

resource "docker_container" "minio" {
  name    = "${var.cluster_name}-minio"
  image   = docker_image.minio.image_id
  command = ["server", "/data", "--console-address", ":9001"]
  restart = "unless-stopped"

  env = [
    "MINIO_ROOT_USER=${local.minio_user}",
    "MINIO_ROOT_PASSWORD=${random_password.minio.result}",
  ]

  # Same Docker network as the kind node: Velero reaches http://<name>:9000
  networks_advanced {
    name = "kind"
  }

  ports {
    internal = 9001
    external = 9001
    ip       = "127.0.0.1"
  }

  volumes {
    volume_name    = docker_volume.minio.name
    container_path = "/data"
  }

  # The "kind" network is created by the first kind cluster.
  depends_on = [kind_cluster.this]
}

resource "docker_container" "minio_init" {
  name     = "${var.cluster_name}-minio-init"
  image    = docker_image.mc.image_id
  must_run = false
  attach   = true
  logs     = true

  entrypoint = ["/bin/sh", "-c"]
  command = [join(" && ", [
    "until mc alias set local http://${docker_container.minio.name}:9000 ${local.minio_user} ${random_password.minio.result}; do sleep 2; done",
    "mc mb --ignore-existing local/${var.velero_bucket}",
  ])]

  networks_advanced {
    name = "kind"
  }
}
