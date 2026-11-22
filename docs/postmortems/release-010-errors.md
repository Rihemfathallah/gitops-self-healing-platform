# Postmortem — Release fautive 'errors' annulée automatiquement (essai 10)

> Postmortem sans reproche : on cherche ce qui a permis l'incident dans le système,
> pas qui l'a causé. Brouillon généré par `make postmortems` à partir de `results/` ;
> les sections marquées ✍️ sont à rédiger à la main.

| | |
| --- | --- |
| Date | 2026-11-22 |
| Statut | Résolu |
| Déclencheur | Release configurée pour faire échouer 50 % des requêtes API (CHAOS_ERROR_RATE=0.5). |
| Détection | AnalysisRun Argo Rollouts (Prometheus, pods du canary uniquement) |
| Délai de détection (s) | 94.1 |
| Délai de rétablissement après détection (s) | 11.9 |

## Impact

Seule la pod canary (environ 50 % des requêtes) a servi la version fautive, pendant 94.1 s au plus.

Budget d'erreur consommé : ✍️ (lire le panneau « error budget left » du tableau de bord
Grafana avant/après l'incident).

## Chronologie (UTC)

| Heure | Événement |
| --- | --- |
| 2026-11-22T00:10:05+00:00 | Release fautive poussée dans Git (commit aa92e9b) |
| 2026-11-22T00:10:09+00:00 | Argo CD a synchronisé ; Argo Rollouts lance le canary |
| 2026-11-22T00:11:39+00:00 | Analyse du canary en échec, rollout annulé (détection) |
| 2026-11-22T00:11:51+00:00 | 100 % du trafic revenu sur la dernière version saine |

## Cause racine ✍️

Pourquoi le défaut a-t-il pu atteindre la production ? (méthode des 5 pourquoi)

## Ce qui a bien fonctionné ✍️

## Ce qui a moins bien fonctionné ✍️

## Actions ✍️

| Action | Type (prévenir / détecter / atténuer) | Responsable | État |
| --- | --- | --- | --- |
| | | | |
