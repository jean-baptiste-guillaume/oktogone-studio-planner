# Oktogone Studio Planner V3 — POC local

Python 3.12 recommandé. Dans ce dossier :

    python -m venv .venv
    .venv\Scripts\python -m pip install -r requirements.txt
    .venv\Scripts\python -m uvicorn app:app --host 127.0.0.1 --port 8000

Ouvrir http://127.0.0.1:8000. Aucun appel Moockapp ou Microsoft Graph.

Pour reprendre une base existante, copier planner.db ici avant le lancement (sauvegarde conseillée), ou définir PLANNER_DB vers cette base. Les tables V2 sont conservées ; trois tables V3 sont ajoutées. Le ZIP V2 fourni ne contenait aucune base. Les réservations historiques V2 restent des occupations protégées.

CDP : sélectionner un projet fictif, simuler, choisir UNE option à pré-réserver, puis simuler la réponse coach. Une nouvelle option remplace transactionnellement les occupations V3 de ce seul projet. Un refus libère les réservations et enregistre les créneaux refusés du coach comme indisponibles ; relancer la simulation. La confirmation revérifie les conflits. Les propositions seules ne bloquent rien.

Règles : préparation de 1 à 3 mois calendaires ; minimum effectif de 60 jours pour permettre un syllabus entre J-90 et J-60 sans date passée. Sample à syllabus +10 jours ; annexes 10 jours après la deuxième journée de tournage. Répétitions l'après-midi, dernière à J-7/J-14 ; deux tournages consécutifs en semaine. La préférence coach conserve le comportement V2 : première date tous coachs, puis deux dates avec le coach préféré. Si moins de trois dates sont possibles, seules les dates disponibles sont retournées.

Portail prestataires et import ICS conservés. L'import remplace uniquement les occupations ICS de la ressource ciblée. Horizon de récurrences ICS hérité V2 : 90 jours ; disponibilités fictives jusqu'à juillet 2027. Le POC ne gère pas les jours fériés ni l'authentification : usage local seulement.

Le récapitulatif JSON est téléchargeable par projet et contient son identité, son RF, le statut, les ressources, les séances et les jalons. Il prépare une future intégration ; aucun envoi n'est effectué.

Tests V3 :

    .venv\Scripts\python tests\test_v3.py

Les tests utilisent une base temporaire. Les anciens tests V2 sont archivés dans tests_v2_reference et décrivent les anciens parcours supprimés.
