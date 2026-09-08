# Runbook NeuralRAG

Chaque alerte Prometheus pointe vers une section de ce document (`runbook_url`).
Règle commune : **la seule action automatique est le rollback vers la dernière version
saine**. Tout le reste passe par un humain et par Git.

## availability-burn

`NeuralRAGAvailabilityBudgetFastBurn` (page) / `...SlowBurn` (ticket) — trop de 5xx.

1. Grafana → *NeuralRAG — SLO* : le taux d'erreur est-il sur toutes les pods ou
   seulement sur le canary (panneau « Error ratio per pod ») ?
2. Une release est en cours ? `kubectl -n neuralrag get rollout neuralrag-backend` :
   si le canary est en cause, l'analyse l'annulera seule ; sinon
   `kubectl argo rollouts abort neuralrag-backend -n neuralrag`.
3. Dépendances : `kubectl -n neuralrag get pods` (ChromaDB, Ollama prêts ?),
   logs du backend : `kubectl -n neuralrag logs -l app.kubernetes.io/name=neuralrag-backend --tail=100`.
4. Après résolution : postmortem (`docs/postmortems/`).

## latency-burn

`NeuralRAGLatencyBudgetFastBurn` / `...SlowBurn` — trop de requêtes au-delà de 10 s.

1. Ollama saturé ? `kubectl -n neuralrag top pods` ; une seule génération à la fois sur CPU.
2. Réseau entre backend et Ollama/ChromaDB (incident simulé : NetworkChaos `incident-latency`) :
   `kubectl get networkchaos -A`.
3. Si une release récente est en cause : revenir en arrière **dans Git** (`git revert`).

## backend-down

`NeuralRAGBackendDown` — Prometheus ne voit plus aucune pod backend.

1. `kubectl -n neuralrag get pods -l app.kubernetes.io/name=neuralrag-backend` et `describe`.
2. Image introuvable (GHCR privé ?), OOMKilled (augmenter `backend.resources.limits` dans Git),
   pod-failure simulé (`kubectl get podchaos -A`).

## rollout-aborted

`NeuralRAGRolloutAborted` — l'analyse canary a échoué ; le trafic est déjà revenu sur la
version stable. L'action humaine attendue :

1. `kubectl argo rollouts get rollout neuralrag-backend -n neuralrag` : quelle métrique
   a échoué (taux d'erreur ou lenteur) ?
2. Annuler le commit fautif : `git revert <sha> && git push`. Argo CD resynchronise, le
   Rollout redevient *Healthy* sans redéployer (même spec que la version stable).
3. Rédiger le postmortem.

## Reprise après sinistre

Procédure complète et mesurée : `make exp-dr` (voir `scripts/experiments/dr_drill.py`).
Version manuelle :

```bash
make destroy-cluster                     # ou perte réelle du cluster
make cluster
terraform -chdir=infra/terraform/platform apply -var restore_mode=true
kubectl -n velero get backups            # choisir la dernière sauvegarde Completed
# créer un Restore limité à ChromaDB (voir dr_drill.py, étape 6), attendre Completed
terraform -chdir=infra/terraform/platform apply -var restore_mode=false
```
