# Déploiement test email — V3.1

Cette version n'est pas encore déployée. Aucun email réel n'a été envoyé.

1. Créer un dépôt GitHub PRIVÉ, puis y charger les fichiers de cette archive décompressée. Ne jamais y ajouter planner.db, .env, .venv ni les mots de passe.
2. Sur Render, choisir New > Blueprint, connecter GitHub et sélectionner le dépôt. Le fichier render.yaml définit un service Python payant avec disque persistant. Vérifier le coût avant de valider l'achat.
3. Définir PUBLIC_BASE_URL avec l'adresse HTTPS du service Render. Définir SMTP_HOST, SMTP_USER et SMTP_PASSWORD selon les instructions de l'administrateur Visiplus. Le transport prévu est SMTP STARTTLS sur le port 587. Un SMTP autorisant ce mode est nécessaire ; Microsoft Graph n'est pas utilisé. Si l'entreprise impose OAuth ou interdit SMTP, il faudra adapter le transport.
4. CDP_PASSWORD est généré par Render. Le récupérer dans Environment et le conserver en privé. Identifiant CDP_USER : cdp. Tous les accès CDP et prestataires partagent ce compte pour ce test. Seule la page personnelle du coach est publique.
5. Garder MAIL_ENABLED à 0 jusqu'à configuration complète. Puis passer à 1 et redéployer. Expéditeur : jean-baptiste.guillaume@visiplus.com ; tous les coachs reçoivent sur guillaume.log@gmail.com. L'expéditeur doit être autorisé par le fournisseur SMTP.
6. Ouvrir l'application, simuler puis pré-réserver une option. Un email est envoyé après validation SQLite. En cas d'échec, les pré-réservations restent en attente ; corriger SMTP et utiliser Envoyer / renvoyer le mail coach. Le renvoi invalide le lien précédent.
7. Ouvrir le mail, consulter les dates puis cliquer sur Accepter ou Refuser sur la page. Le lien expire après 7 jours et devient invalide après réponse ou remplacement. Un lien expiré ne libère pas automatiquement les réservations : le CDP doit choisir une nouvelle option ou renvoyer le mail.

Le fichier render.yaml désactive les journaux d'accès Uvicorn pour éviter d'y inscrire les liens personnels. Ces liens restent des secrets : ne pas les partager. Les journaux éventuels de l'hébergeur restent sous sa gestion.

SQLite se trouve dans /var/data/planner.db. Une seule instance du serveur est prévue. Sauvegarder la base avant remplacement. Pour reprendre une base réelle V2/V3, transférer une copie cohérente de cette base sur le disque persistant avant usage ; aucune base réelle n'est incluse.

Validation : tests/test_v3.py et tests/test_mail.py passent le 6 novembre 2026. SMTP réel et hébergement non testés faute de comptes configurés. Tests d'intégration réalisés sur bases temporaires ; accès protégé, remplacement, acceptation/refus, expiration, usage unique et invalidation des liens. Moockapp et Microsoft Graph déconnectés.
