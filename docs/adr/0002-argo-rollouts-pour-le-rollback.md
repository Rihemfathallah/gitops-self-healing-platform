# ADR 0002 — Argo Rollouts (analyse Prometheus) pour le rollback automatique

**Statut** : accepté

## Contexte
EF-09 : annuler automatiquement une version défaillante sur alerte SLO. Contrainte de
sécurité : l'action automatique ne peut que revenir à la dernière version saine.

Le cahier des charges proposait deux options : Argo Rollouts, ou un webhook Alertmanager
qui déclenche un rollback Argo CD.

## Décision
**Argo Rollouts**, stratégie canary (50 % des pods), avec une *AnalysisTemplate* qui
interroge Prometheus **sur les seules pods du canary** :
- taux de 5xx du canary ≤ 5 % ;
- part des requêtes du canary plus lentes que le seuil du SLO (10 s) ≤ 5 %.
Deux mesures en échec (toutes les 30 s, après 60 s de chauffe) → abandon → 100 % du trafic
sur la version stable. Une release qui ne devient jamais prête (crash) est abandonnée par
`progressDeadlineAbort` au bout de 5 min.

## Pourquoi pas le webhook Alertmanager → Argo CD
- Les alertes de burn rate portent sur tout le service et sur des fenêtres d'1 h : trop lentes
  et trop globales pour juger une release de quelques minutes.
- Un rollback Argo CD désactive l'auto-sync et laisse Git et le cluster divergents.
- Il faudrait écrire et sécuriser un service qui a les droits d'écriture sur le cluster.

## Conséquences
- La garantie « revenir uniquement à la dernière version saine » est native : un Rollout
  abandonné revient au ReplicaSet stable, il ne peut rien faire d'autre.
- Le commit fautif reste dans Git : l'annuler (`git revert`) reste une action humaine,
  signalée par l'alerte `NeuralRAGRolloutAborted`.
- Sans routeur de trafic, la répartition se fait au nombre de pods : il faut 2 réplicas
  pour un canary à 50 %.
