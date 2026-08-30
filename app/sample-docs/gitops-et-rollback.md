# GitOps et rollback automatique

En GitOps, l'état souhaité du cluster est décrit dans un dépôt Git. Argo CD compare en
continu le cluster et le dépôt, et applique les différences. Personne n'exécute
kubectl apply à la main : une modification passe par un commit.

Argo Rollouts remplace le Deployment par une ressource Rollout qui déploie une nouvelle
version progressivement (canary). Pendant le canary, une AnalysisRun interroge Prometheus :
si le taux de réussite ou la latence de la nouvelle version sortent des seuils, le
déploiement est abandonné et tout le trafic revient à la dernière version saine.

Le rollback automatique ne peut que revenir à la version stable précédente. Toute autre
action, comme corriger le code ou annuler le commit fautif dans Git, reste humaine.
