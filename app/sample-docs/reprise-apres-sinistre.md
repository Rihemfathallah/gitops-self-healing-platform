# Reprise après sinistre

Le RTO (Recovery Time Objective) est la durée entre la perte du service et son retour.
Le RPO (Recovery Point Objective) est la quantité de données perdues, exprimée en temps :
c'est l'écart entre la dernière sauvegarde utilisable et le moment de la panne.

Sur cette plateforme, Velero sauvegarde les objets Kubernetes et le volume de ChromaDB
vers un stockage objet MinIO situé hors du cluster. Après la destruction du cluster,
Terraform recrée un cluster vide, Velero restaure les données, puis Argo CD resynchronise
les applications depuis Git.
