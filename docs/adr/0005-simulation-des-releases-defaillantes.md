# ADR 0005 — Simuler une release défaillante par sa configuration

**Statut** : accepté

## Contexte
EF-10 : injecter des incidents reproductibles et étiquetés. Il faut au moins 10 releases
défaillantes pour mesurer le temps de rollback, sans reconstruire une image à chaque fois
(≈ 10 min par image avec PyTorch).

## Décision
- Le backend contient un middleware de chaos inactif par défaut (`app/backend/chaos.py`),
  piloté par trois variables : `CHAOS_ERROR_RATE`, `CHAOS_LATENCY_MS`, `CHAOS_CRASH_ON_START`.
- Une « release défaillante » est un **commit** qui modifie `gitops/releases/neuralrag.yaml` :
  le Rollout reçoit un nouveau template de pod, donc une nouvelle révision, exactement comme
  pour une nouvelle image. Le message de commit `test(incident): ...` étiquette l'incident.
- Les sondes `/health` restent vertes même en mode défaillant : c'est le cas réaliste et
  difficile (une version qui passe ses health checks mais sert mal les utilisateurs).
- Les incidents d'infrastructure (perte de dépendance, latence réseau, pods en panne) sont
  injectés par Chaos Mesh (`incidents/`), appliqués et retirés par le script de mesure.

## Retour d'expérience (incident « latency », novembre 2026)
L'incident de latence réseau n'a déclenché aucune alerte : il ne ralentissait rien.
Le `NetworkChaos` retardait le trafic du backend **vers les pods** Ollama, or le backend
appelle Ollama par son Service (`http://neuralrag-ollama:11434`). tc/netem filtre sur l'IP du
pod cible, et l'IP du Service n'est traduite en IP de pod qu'en dehors de l'espace réseau du
backend. Mesuré depuis un pod backend, incident actif : 0,01 s par le Service, 40,7 s par
l'IP du pod. La partition vers ChromaDB, elle, fonctionnait : Chaos Mesh pose aussi des
règles côté cible, où les paquets portent la vraie IP du backend.

Correction (`incidents/latency.yaml`) : le retard est posé côté Ollama, sur ce qu'il envoie
aux pods backend. Ses réponses sont adressées à l'IP réelle du backend, le filtre les
reconnaît : 70,8 s mesurées par le Service pour une nouvelle connexion. Sans cible du tout,
netem retarde aussi les réponses ARP et le pod devient injoignable (« No route to host »).
Retard ramené de 20 s à 25 s, de sorte que toute requête dépasse 30 s, durée portée à 20 min
(ADR 0003).

Leçon retenue : avant de mesurer la détection d'un incident, vérifier qu'il dégrade bien le
service (une requête chronométrée pendant l'incident suffit).

## Conséquences
- Mesures reproductibles et rapides ; même chemin GitOps qu'une vraie release.
- Honnêteté : le README précise que les releases fautives sont simulées par configuration.
