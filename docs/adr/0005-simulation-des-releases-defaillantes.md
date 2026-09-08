# ADR 0005 — Simuler une release défaillante par sa configuration

**Statut** : accepté

## Contexte
EF-10 : injecter des incidents reproductibles et étiquetés. Il faut au moins 10 releases
défaillantes pour mesurer le temps de rollback, sans reconstruire une image à chaque fois
(≈ 10 min par image avec PyTorch).

## Décision
- Le backend contient un middleware de chaos inactif par défaut (`app/backend/chaos.py`),
  piloté par trois variables : `CHAOS_ERROR_RATE`, `CHAOS_LATENCY_MS`, `CHAOS_CRASH_ON_START`.
- Une « release défaillante » est un **commit** qui modifie `gitops/releases/neuralrag.yaml` :
  le Rollout reçoit un nouveau template de pod, donc une nouvelle révision, exactement comme
  pour une nouvelle image. Le message de commit `test(incident): ...` étiquette l'incident.
- Les sondes `/health` restent vertes même en mode défaillant : c'est le cas réaliste et
  difficile (une version qui passe ses health checks mais sert mal les utilisateurs).
- Les incidents d'infrastructure (perte de dépendance, latence réseau, pods en panne) sont
  injectés par Chaos Mesh (`incidents/`), appliqués et retirés par le script de mesure.

## Conséquences
- Mesures reproductibles et rapides ; même chemin GitOps qu'une vraie release.
- Honnêteté : le README précise que les releases fautives sont simulées par configuration.
