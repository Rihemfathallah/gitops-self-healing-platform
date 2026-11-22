# Postmortem — Incident 'pod-failure' (essai 3)

> Postmortem sans reproche : on cherche ce qui a permis l'incident dans le système,
> pas qui l'a causé. Brouillon généré par `make postmortems` à partir de `results/` ;
> les sections marquées ✍️ sont à rédiger à la main.

| | |
| --- | --- |
| Date | 2026-11-21 |
| Statut | Résolu |
| Déclencheur | Toutes les pods backend rendues indisponibles pendant 10 minutes (Chaos Mesh PodChaos). |
| Détection | Alerte Prometheus NeuralRAGBackendDown |
| Délai de détection (s) | 100.0 |
| Délai de rétablissement après détection (s) | voir la chronologie |

## Impact

À compléter depuis le tableau de bord SLO (requêtes en échec ou lentes, budget consommé).

Budget d'erreur consommé : ✍️ (lire le panneau « error budget left » du tableau de bord
Grafana avant/après l'incident).

## Chronologie (UTC)

| Heure | Événement |
| --- | --- |
| 2026-11-21T22:31:57+00:00 | Incident injecté |
| 2026-11-21T22:33:37+00:00 | Alerte NeuralRAGBackendDown déclenchée |
| 2026-11-21T22:33:37+00:00 | Cause retirée (objet Chaos Mesh supprimé) |

## Cause racine ✍️

Pourquoi le défaut a-t-il pu atteindre la production ? (méthode des 5 pourquoi)

## Ce qui a bien fonctionné ✍️

## Ce qui a moins bien fonctionné ✍️

## Actions ✍️

| Action | Type (prévenir / détecter / atténuer) | Responsable | État |
| --- | --- | --- | --- |
| | | | |
