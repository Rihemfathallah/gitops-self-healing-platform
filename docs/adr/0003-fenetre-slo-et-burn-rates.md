# ADR 0003 — SLO sur 7 jours et seuils de burn rate

**Statut** : accepté

## Contexte
EF-06/EF-07 : deux SLO (disponibilité, latence p95) et des alertes sur la vitesse de
consommation du budget d'erreur. La plateforme tourne sur un portable : l'historique dépasse
rarement quelques jours, et les incidents simulés doivent être détectés en quelques minutes.

## Décision
| SLO | SLI | Cible | Budget |
| --- | --- | --- | --- |
| Disponibilité | part des requêtes API non 5xx | 99,5 % sur 7 j | 0,5 % |
| Latence | part des requêtes API servies en ≤ 30 s (⇔ p95 ≤ 30 s) | 95 % sur 7 j | 5 % |

Alertes multi-fenêtres / multi-burn-rate (méthode du *SRE Workbook*), recalculées pour 7 jours :
- **page** : 2 % du budget en 1 h → burn rate 0,02 × 168 / 1 = **3,36** (fenêtres 1 h et 5 min) ;
- **ticket** : 5 % du budget en 6 h → burn rate 0,05 × 168 / 6 = **1,4** (fenêtres 6 h et 30 min).

## Pourquoi
- 30 jours (valeur habituelle) n'a pas de sens sans 30 jours d'historique ; 7 jours tient dans
  la rétention Prometheus (8 j) et reste interprétable.
- Le SLI de latence est un ratio de requêtes rapides et non un p95 calculé : un ratio se
  somme correctement sur des fenêtres et donne directement un budget d'erreur.
- 30 s : la réponse est générée par un LLM sur CPU (qwen2.5 0,5B), sans GPU. Le seuil initial
  de 10 s a été abandonné après la première mesure de base (`make exp-slo`, 10 min) : 100 %
  de disponibilité mais p95 ≈ 50 s, 0 % des requêtes sous 10 s. Le travail par requête a été
  réduit (96 tokens, 2 extraits), la charge de fond aussi (une question toutes les 15 s,
  1 utilisateur k6), et le seuil fixé à 30 s, la borne d'histogramme la plus proche d'un
  objectif tenable sur cette machine. Un SLO doit refléter ce que le service peut promettre ;
  sur GPU, il redescendrait sous 5 s. Le seuil doit être une borne de l'histogramme
  (`metrics/sli.py`). Pour que la latence reste bornée, la réponse est limitée à 160 tokens
  (`ollama.numPredict`) et le prompt à 3 extraits (`backend.topK`).

## Retour d'expérience (incidents simulés, 1/3 détecté, novembre 2026)
Seule la panne des pods (`NeuralRAGBackendDown`, 100 s) a été détectée.

**Perte de ChromaDB.** Hypothèse de départ : l'API répondait 200 sans ChromaDB.
Infirmée : une erreur de ChromaDB donnait déjà un 500. Le problème est que la requête ne
se terminait jamais. Reproduit sur le cluster : le client chromadb 0.5 n'a aucun timeout et
son appel synchrone bloquait la boucle d'événements ; `/health` ne répondait plus, le
kubelet a tué le conteneur après 3 échecs de la sonde liveness (code 137). La requête
n'est comptée nulle part, ni en 200 ni en 5xx : le SLI côté serveur ne voit que les requêtes
qui se terminent. Contre-épreuve involontaire pendant le diagnostic : Ollama sans modèle,
toutes les requêtes en 500, `NeuralRAGAvailabilityBudgetFastBurn` a bien sonné. Les règles
étaient justes ; il manquait les échecs.

Corrections dans `app/backend` : timeout de 5 s sur chaque appel HTTP à ChromaDB ; embedding
et recherche exécutés dans un thread avec un budget de 10 s ; création du moteur hors de la
boucle d'événements ; toute défaillance de ChromaDB ou d'Ollama renvoie **503**
(`DependencyUnavailable`), compté par le SLI. Test : `tests/test_dependency_failure.py`
(503 en moins de 3 s, `/health` répond pendant la panne, 503 compté). Nouvelle alerte
symptôme `NeuralRAGBackendRestarting` (plus de 2 redémarrages en 15 min) : des
redémarrages en boucle font disparaître les requêtes des SLI.

**Latence réseau.** L'incident ne ralentissait rien (ADR 0005). Second défaut, qui l'aurait
masqué quand même : le générateur de trafic attendait chaque réponse avant d'envoyer la
question suivante (boucle fermée). Un service lent reçoit alors moins de requêtes, ce qui
dilue le ratio de requêtes lentes : avec des réponses de ~65 s au lieu de ~15 s, la fenêtre
d'1 h n'atteignait 16,8 % qu'après ~22 min, plus que la durée de l'incident (15 min).
Correction : générateur en boucle ouverte, une question toutes les 30 s quel que soit le
temps de réponse (même charge moyenne, ~2 questions par minute). À débit constant, la
fenêtre d'1 h franchit 16,8 % après ~10 min ; l'incident dure désormais 20 min.

Leçon retenue : un SLI côté serveur ne compte que ce qui se termine. Une dépendance doit
échouer vite et visiblement, et le trafic de mesure ne doit pas ralentir avec le service.

## Limites
- Un SLI calculé côté application ne voit pas une panne totale (aucune requête n'arrive) :
  l'alerte symptôme `NeuralRAGBackendDown` couvre ce cas.
- Le SLI est mesuré côté serveur : une connexion coupée avant d'atteindre l'application
  n'y apparaît pas. La deuxième mesure de base l'a montré : Prometheus 100 % de réussite,
  k6 3 échecs « EOF » sur 31. Cause : keep-alive d'uvicorn (5 s) égal au délai entre deux
  requêtes de k6 (5 s), le serveur fermait parfois une connexion au moment où le client
  la réutilisait. Correction : keep-alive serveur à 75 s. Le rapport `make exp-slo` publie
  donc toujours aussi la vue client (k6) à côté de la vue Prometheus.
- Les règles sont testées hors cluster par `promtool test rules` (CI).
