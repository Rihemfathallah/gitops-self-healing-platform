# ADR 0001 — Argo CD pour le déploiement GitOps

**Statut** : accepté

## Contexte
Exigence EF-04 : NeuralRAG ne doit être déployé que depuis Git, sans `kubectl apply` manuel.
Les offres visées (Cognira, Tanitjobs DevOps/SRE) citent Argo CD.

## Décision
Argo CD, installé par Terraform, avec une seule *Application* racine (« app of apps ») qui
pointe vers `gitops/apps/`. Synchronisation automatique, `prune` et `selfHeal` activés.
Les dépendances (CRD avant ressources) sont ordonnées par *sync waves*, avec un contrôle de
santé des Applications ajouté dans `argocd-cm`.

## Alternatives écartées
- **Flux** : équivalent techniquement, moins demandé dans les offres ciblées, pas d'UI.
- **`helm install` depuis la CI (push)** : la CI aurait besoin d'un accès au cluster ;
  pas de détection de dérive.

## Conséquences
- Tout changement (nouvelle image, release fautive simulée, retour arrière) est un commit :
  l'historique Git est le journal des changements de production.
- Terraform ne gère que ce qui doit exister avant Argo CD : cluster, Argo CD, Velero.
