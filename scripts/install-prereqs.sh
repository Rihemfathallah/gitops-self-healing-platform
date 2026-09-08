#!/usr/bin/env bash
# Installs the tools needed by `make up` on Debian / Ubuntu / Kali (amd64).
# Run once: sudo ./scripts/install-prereqs.sh   then log out and back in (docker group).
set -euo pipefail

if [[ $EUID -ne 0 ]]; then echo "run with sudo"; exit 1; fi
USER_NAME="${SUDO_USER:-$USER}"

apt-get update
apt-get install -y ca-certificates curl gnupg git make python3 unzip lsb-release

# Docker (Kali/Debian package; Docker Desktop on Windows also works through WSL2)
if ! command -v docker >/dev/null; then
  apt-get install -y docker.io
  systemctl enable --now docker
fi
usermod -aG docker "$USER_NAME"

# Terraform (official binary, pinned)
TF_VERSION=1.9.8
if ! command -v terraform >/dev/null; then
  curl -fsSL -o /tmp/tf.zip "https://releases.hashicorp.com/terraform/${TF_VERSION}/terraform_${TF_VERSION}_linux_amd64.zip"
  unzip -o /tmp/tf.zip -d /usr/local/bin terraform
fi

# kubectl (pinned)
KUBECTL_VERSION=v1.31.3
if ! command -v kubectl >/dev/null; then
  curl -fsSL -o /usr/local/bin/kubectl "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl"
  chmod +x /usr/local/bin/kubectl
fi

# Optional: kubectl argo rollouts plugin (nicer rollout view) and helm (make lint)
curl -fsSL -o /usr/local/bin/kubectl-argo-rollouts \
  https://github.com/argoproj/argo-rollouts/releases/download/v1.8.3/kubectl-argo-rollouts-linux-amd64 \
  && chmod +x /usr/local/bin/kubectl-argo-rollouts || true
if ! command -v helm >/dev/null; then
  curl -fsSL https://get.helm.sh/helm-v3.16.3-linux-amd64.tar.gz | tar xz -C /tmp && mv /tmp/linux-amd64/helm /usr/local/bin/ || true
fi

# promtool (make test-rules)
if ! command -v promtool >/dev/null; then
  curl -fsSL https://github.com/prometheus/prometheus/releases/download/v2.55.1/prometheus-2.55.1.linux-amd64.tar.gz \
    | tar xz --strip-components=1 -C /usr/local/bin prometheus-2.55.1.linux-amd64/promtool || true
fi

# kind clusters run many processes: raise inotify limits (otherwise pods crash with "too many open files")
cat > /etc/sysctl.d/99-kind.conf <<'SYSCTL'
fs.inotify.max_user_watches = 524288
fs.inotify.max_user_instances = 512
SYSCTL
sysctl --system >/dev/null

echo "Done. Log out and back in so that '$USER_NAME' can use docker without sudo."
