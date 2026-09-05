# Postmortem — Incident 'latency' (essai 2)

> Postmortem sans reproche : on cherche ce qui a permis l'incident dans le système,
> pas qui l'a causé. Brouillon généré par `make postmortems` à partir de `results/` ;
> les sections marquées ✍️ sont à rédiger à la main.

| | |
| --- | --- |
| Date | 2026-11-21 |
| Statut | Résolu |
| Déclencheur | Délai réseau de 20 s entre le backend et Ollama (Chaos Mesh NetworkChaos). |
| Détection | Alerte Prometheus NeuralRAGLatencyBudgetFastBurn |
| Délai de détection (s) | non détecté |
| Délai de rétablissement après détection (s) | voir la chronologie |

## Impact

À compléter depuis le tableau de bord SLO (requêtes en échec ou lentes, budget consommé).

Budget d'erreur consommé : ✍️ (lire le panneau « error budget left » du tableau de bord
Grafana avant/après l'incident).

## Chronologie (UTC)

| Heure | Événement |
| --- | --- |
| 2026-11-21T22:11:55+00:00 | Incident injecté |
|  | Alerte NeuralRAGLatencyBudgetFastBurn déclenchée |
| 2026-11-21T22:31:57+00:00 | Cause retirée (objet Chaos Mesh supprimé) |

## Cause racine ✍️

Pourquoi le défaut a-t-il pu atteindre la production ? (méthode des 5 pourquoi)

## Ce qui a bien fonctionné ✍️

## Ce qui a moins bien fonctionné ✍️

## Actions ✍️

| Action | Type (prévenir / détecter / atténuer) | Responsable | État |
| --- | --- | --- | --- |
| | | | |
