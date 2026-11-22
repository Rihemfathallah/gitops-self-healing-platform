# Postmortem — Release fautive 'latency' annulée automatiquement (essai 2)

> Postmortem sans reproche : on cherche ce qui a permis l'incident dans le système,
> pas qui l'a causé. Brouillon généré par `make postmortems` à partir de `results/` ;
> les sections marquées ✍️ sont à rédiger à la main.

| | |
| --- | --- |
| Date | 2026-11-21 |
| Statut | Résolu |
| Déclencheur | Release configurée pour ajouter 40 s à chaque requête API (CHAOS_LATENCY_MS=40000). |
| Détection | AnalysisRun Argo Rollouts (Prometheus, pods du canary uniquement) |
| Délai de détection (s) |  |
| Délai de rétablissement après détection (s) |  |

## Impact

Seule la pod canary (environ 50 % des requêtes) a servi la version fautive, pendant  s au plus.

Budget d'erreur consommé : ✍️ (lire le panneau « error budget left » du tableau de bord
Grafana avant/après l'incident).

## Chronologie (UTC)

| Heure | Événement |
| --- | --- |
| 2026-11-21T22:38:11+00:00 | Release fautive poussée dans Git (commit 7b58ea3) |
| 2026-11-21T22:38:15+00:00 | Argo CD a synchronisé ; Argo Rollouts lance le canary |
|  | Analyse du canary en échec, rollout annulé (détection) |
|  | 100 % du trafic revenu sur la dernière version saine |

## Cause racine ✍️

Pourquoi le défaut a-t-il pu atteindre la production ? (méthode des 5 pourquoi)

## Ce qui a bien fonctionné ✍️

## Ce qui a moins bien fonctionné ✍️

## Actions ✍️

| Action | Type (prévenir / détecter / atténuer) | Responsable | État |
| --- | --- | --- | --- |
| | | | |
