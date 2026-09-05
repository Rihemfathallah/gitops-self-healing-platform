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
- part des requêtes du canary plus lentes que le seuil du SLO (30 s) ≤ 50 % ;
- aucun redémarrage des conteneurs du canary (kube-state-metrics).
Chaque mesure porte sur les 2 dernières minutes. Deux mesures en échec (toutes les 30 s, après 60 s de chauffe) → abandon → 100 % du trafic
sur la version stable. L'analyse tourne tant que le canary existe (pause de 6 min, pas de
`count`). `progressDeadlineAbort` (5 min) reste en filet pour une release qui ne devient
jamais prête.

## Pourquoi pas le webhook Alertmanager → Argo CD
- Les alertes de burn rate portent sur tout le service et sur des fenêtres d'1 h : trop lentes
  et trop globales pour juger une release de quelques minutes.
- Un rollback Argo CD désactive l'auto-sync et laisse Git et le cluster divergents.
- Il faudrait écrire et sécuriser un service qui a les droits d'écriture sur le cluster.

## Retour d'expérience (premier canary réel)
La première version de l'analyse (fenêtre 1 min, ≤ 5 % de requêtes lentes) a annulé une
release saine : 0 % d'erreurs, mais 14 % puis 56 % de requêtes lentes, sur ~2 requêtes par
minute. Ollama est partagé par la version stable et le canary : une réponse lente isolée
ne dit rien de la nouvelle version. L'analyse cherche désormais une **régression nette**
(fenêtre 2 min, > 50 % de requêtes lentes) ; l'objectif de 95 % reste suivi par le SLO
et son budget d'erreur, sur 7 jours.

## Retour d'expérience (mesure de 10 rollbacks, novembre 2026)
Résultat : 7/10. Les 3 échecs ne sont **pas** les releases « crash » mais les 3 releases
« latency » (runs 2, 5, 8). Les 3 « crash » ont bien été annulées, mais en 544 à 550 s.

**Releases « latency » (+40 s par requête) : jamais annulées.** Aucun abandon en 15 min :
la pause de 4 min s'est terminée, le Rollout a promu la release lente à 100 % et l'analyse
en arrière-plan s'est arrêtée avec lui. Quatre causes se cumulaient :
1. L'analyse ne voit une requête qu'une fois terminée. Une requête du canary durait ~55 s
   (40 s injectées + génération) et le canary en recevait ~1 par minute.
2. `rate()` ignore la première valeur d'une série. Les séries du canary naissaient à 1, à la
   fin de sa première requête : la première réponse lente était invisible. Il en fallait une
   deuxième pour une mesure en échec, et deux mesures en échec pour l'abandon.
3. `count: 8` : l'analyse s'arrêtait d'elle-même 4 min 30 après le début du rollout,
   démarrage du pod compris, et la pause de 4 min bornait de toute façon l'observation.
4. Pas de données = succès (`or vector(0)`). Voulu, pour ne pas annuler un canary sans
   trafic, mais chaque manque de données passe alors pour une version saine.

Corrections : séries SLI créées à 0 au démarrage (`metrics/sli.py`, `preinitialize`), la
première requête compte ; analyse sans `count` ; pause portée à 6 min ; générateur de
trafic en boucle ouverte, le canary reçoit sa part même s'il est lent (ADR 0003).

**Releases « crash » : annulées, mais en ~9 min.** Les deux SLI ne peuvent rien voir : un
canary qui plante ne sert aucune requête, donc l'analyse réussit. Seul
`progressDeadlineAbort` a agi, à ~545 s pour un délai configuré de 300 s : le délai ne court
pas depuis la création du canary. Les AnalysisRuns ont disparu avec l'exercice de reprise,
l'événement qui l'a relancé n'est pas établi. Correction : troisième mesure,
`canary-restarts` (redémarrages des conteneurs du canary > 0). Abandon attendu ~90 s après
le début du rollout (60 s de chauffe + 2 mesures) ; le délai de progression reste en filet.

Leçon retenue : une analyse qui ne voit rien n'est pas une analyse qui voit une version
saine. Chaque type de défaillance doit produire un signal que l'analyse interroge.

## Conséquences
- La garantie « revenir uniquement à la dernière version saine » est native : un Rollout
  abandonné revient au ReplicaSet stable, il ne peut rien faire d'autre.
- Le commit fautif reste dans Git : l'annuler (`git revert`) reste une action humaine,
  signalée par l'alerte `NeuralRAGRolloutAborted`.
- Sans routeur de trafic, la répartition se fait au nombre de pods : il faut 2 réplicas
  pour un canary à 50 %.
- Une release saine est promue en ~6 min au lieu de ~4. Un canary qui redémarre une seule
  fois est annulé : c'est voulu.
