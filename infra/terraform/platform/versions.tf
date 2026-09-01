terraform {
  required_version = ">= 1.6.0"

  required_providers {
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.17.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.35"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

# Outputs of the cluster root (local state, same machine).
data "terraform_remote_state" "cluster" {
  backend = "local"
  config = {
    path = "${path.module}/../cluster/terraform.tfstate"
  }
}

locals {
  kubeconfig = data.terraform_remote_state.cluster.outputs.kubeconfig_path
  context    = data.terraform_remote_state.cluster.outputs.kube_context
}

provider "kubernetes" {
  config_path    = local.kubeconfig
  config_context = local.context
}

provider "helm" {
  kubernetes {
    config_path    = local.kubeconfig
    config_context = local.context
  }
}
