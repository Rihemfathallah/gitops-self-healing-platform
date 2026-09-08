# ADR 0004 — Sauvegardes hors du cluster et ordre de restauration

**Statut** : accepté

## Contexte
EF-12/EF-13 : sauvegarder le cluster et le volume ChromaDB, détruire le cluster, restaurer,
mesurer RTO et RPO.

## Décisions
1. **MinIO tourne hors du cluster**, comme conteneur Docker sur le réseau `kind`, créé par
   Terraform. Un stockage de sauvegarde à l'intérieur du cluster disparaîtrait avec lui. Les
   données MinIO vivent dans un volume Docker que `make destroy-cluster` ne supprime pas.
2. **Velero** sauvegarde le namespace `neuralrag` toutes les 15 min (*Schedule*), volumes
   copiés fichier par fichier (kopia) car kind n'a pas de snapshots CSI. Le cache de modèles
   d'Ollama est exclu (il se retélécharge).
3. **Ordre de restauration** : Terraform recrée le cluster puis Argo CD et Velero **sans
   l'Application racine** (`restore_mode=true`) ; Velero restaure ChromaDB (StatefulSet, pod,
   volume) ; puis l'Application racine est créée et Argo CD resynchronise tout le reste
   depuis Git. Si Argo CD passait en premier, il créerait un volume ChromaDB vide et Velero
   ne restaurerait pas par-dessus.
4. **Pas d'indexation au démarrage** (`AUTO_INDEX_ON_STARTUP=false`) : sinon les documents
   reviendraient par réindexation et le test de restauration ne prouverait rien.

## Mesure
- RPO = instant de la panne − horodatage du marqueur le plus récent retrouvé après restauration
  (des marqueurs sont écrits dans ChromaDB toutes les 10 s jusqu'à la panne).
- RTO = instant de la panne → `POST /api/query` répond 200 et le nombre de documents est
  identique à avant.

## Limites
- Copie à chaud de la base SQLite de ChromaDB : cohérence « après crash », acceptable pour
  un index reconstructible. En production : hook Velero de mise en pause ou snapshot CSI.
- RPO théorique maximal = intervalle du Schedule (15 min) + durée de la sauvegarde.
