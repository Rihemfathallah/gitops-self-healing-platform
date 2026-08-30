# SLO et budget d'erreur

Un SLI (Service Level Indicator) est une mesure de la qualité perçue par l'utilisateur,
par exemple la part des requêtes qui réussissent ou la part des requêtes servies en moins
d'un certain temps. Un SLO (Service Level Objective) fixe une cible pour cet indicateur
sur une période, par exemple 99,5 % de requêtes réussies sur 7 jours.

Le budget d'erreur est ce qui reste entre la cible et 100 % : avec un SLO de 99,5 %,
le service peut échouer sur 0,5 % des requêtes de la période. Le burn rate est la vitesse
à laquelle ce budget est consommé : un burn rate de 1 épuise le budget exactement à la fin
de la période, un burn rate de 10 l'épuise dix fois plus vite.

Une alerte multi-fenêtres compare le burn rate sur une fenêtre longue (1 h) et une fenêtre
courte (5 min) : la fenêtre longue évite les alertes sur un pic isolé, la fenêtre courte
permet à l'alerte de s'arrêter vite quand l'incident est résolu.
