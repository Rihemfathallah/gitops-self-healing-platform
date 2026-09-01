output "api_key" {
  description = "X-API-Key of the NeuralRAG API (also in the neuralrag-api secret)."
  value       = random_password.api_key.result
  sensitive   = true
}

output "grafana_password" {
  description = "Grafana admin password (user: admin)."
  value       = random_password.grafana.result
  sensitive   = true
}

output "urls" {
  value = {
    neuralrag    = "http://localhost:8080/docs"
    grafana      = "http://localhost:3000"
    prometheus   = "http://localhost:9090"
    alertmanager = "http://localhost:9093"
    argocd       = "http://localhost:8443"
  }
}
