# Free Claude Code VPS

Interface Web officielle de DeepSeek Harness avec le proxy Free Claude Code. Utilisable depuis Android ou PC. Le serveur exécute les agents et conserve leurs projets sur le volume Docker lorsqu’il est installé sur un VPS.

## Render

Le service utilise Docker et le plan Free. Dans **Environment**, ajoutez `WEB_PASSWORD` (16 à 72 octets) et `ROUTEWAY_API_KEY` (depuis le [tableau de bord Routeway](https://routeway.ai/)), puis choisissez **Save, rebuild, and deploy**. Ouvrez l’URL HTTPS du service et connectez-vous avec l’identifiant `admin` et ce mot de passe. `WEB_USERNAME` permet de changer l’identifiant.

La page `/_status` affiche le fournisseur et l’état de la configuration de la clé, sans afficher sa valeur. Si vous effacez vos cookies ou que la session Harness expire, ouvrez la racine du service ou `/_login`.

[Render Free](https://render.com/docs/free) met le service en veille après 15 minutes d’inactivité et efface ses fichiers locaux à l’arrêt ou au redéploiement. Poussez vos modifications sur Git avant de quitter. Le volume de la configuration VPS conserve les projets, conversations et réglages lorsque la conteneurisation est redémarrée.

## VPS avec disque persistant

Sur un serveur Linux avec Docker et le plugin Compose v2 :

```bash
git clone https://github.com/dbrckk/Free_claude_code_vps.git
cd Free_claude_code_vps
cp .env.example .env
chmod 600 .env
nano .env
docker compose up -d --build
```

Renseignez `WEB_PASSWORD` et la clé du fournisseur choisi. Pour relier votre PC au VPS sans exposer le port sur Internet, ouvrez un terminal sur votre PC et maintenez le tunnel :

```bash
ssh -N -L 8080:127.0.0.1:8080 utilisateur@serveur
```

Ouvrez ensuite [localhost:8080](http://localhost:8080). Pour accéder depuis Android sans tunnel SSH, publiez le port via un proxy HTTPS ou Tailscale Serve, renseignez son origine dans `PUBLIC_URL`, puis recréez le conteneur avec `docker compose up -d`. Le proxy HTTPS doit conserver l’en-tête Host et transmettre les WebSockets. Réservez le service à votre usage personnel : les sessions, le terminal et les accès Git sont partagés par les utilisateurs authentifiés.

Pour lancer le client Claude Code en CLI sur le même proxy depuis le serveur :

```bash
docker compose exec harness python scripts/run.py claude
```

Pour autoriser vos dépôts GitHub privés, ouvrez le terminal du serveur et utilisez `gh auth login --web`, puis `gh auth setup-git`. Les clés du fournisseur doivent rester dans l’environnement du serveur. Les agents doivent être utilisés uniquement avec des dépôts auxquels vous souhaitez leur donner accès.

## DeepSeek V4.1 Flash

| `MODEL_PROVIDER` | Variable de clé | Modèle |
| --- | --- | --- |
| `routeway` (par défaut) | `ROUTEWAY_API_KEY` | [V4.1 Flash :free](https://routeway.ai/models/deepseek-v4.1-flash%3Afree), 42 000 tokens de contexte. Routeway annonce 200 requêtes par jour avec disponibilité selon la file. Le suffixe 1017 est publié par Routeway comme une offre distincte. |
| `unorouter` | `UNOROUTER_API_KEY` | [V4.1 Flash 1017 :free](https://unorouter.com/en/blog/free-deepseek-api-key), annoncé à environ une requête par minute. À vérifier avec votre clé, le catalogue public du 15 novembre 2026 ne l’affichait pas. |
| `openrouter` | `OPENROUTER_API_KEY` | [V4.1 Flash 1017 :free](https://openrouter.ai/deepseek/deepseek-v4.1-flash-1017:free), sans fournisseur actif lors de la vérification du 15 novembre 2026. |
| `deepseek` | `DEEPSEEK_API_KEY` | [V4.1 Flash 1017 via deepseek-flash](https://api-docs.deepseek.com/quick_start/pricing/), facturé par DeepSeek. |

Le fournisseur choisi reçoit les requêtes. Aucun changement automatique de modèle ou de fournisseur. Une tâche d’agent peut effectuer plusieurs requêtes.

## Plugins

Le profil Web est initialisé avec neuf bundles officiels additionnels. Il inclut les extensions de recherche des sessions, de terminal persistant, de gestion des worktrees et changements Git, de saisie vocale, de révision automatique, de boucles de travail, de traduction, de badges et de découverte de plugins. La saisie vocale peut télécharger ses ressources à la première utilisation. La traduction de raisonnement et la révision automatique ont leurs propres réglages. Activez ces modes selon vos besoins.

Deux serveurs MCP locaux sont branchés au profil : mémoire persistante et réflexion séquentielle. Les outils de code, les fichiers, les sessions et les extensions Office sont fournis par le profil Web. Ouvrez **Plugins** ou **Settings → MCP** pour voir les intégrations. Le menu **Discover** accepte un index HTTPS de plugins que vous avez choisi. Le cloud gratuit dispose de 512 Mo de RAM et convient aux sessions légères. Les gros projets, les tâches parallèles et les extensions gourmandes sont mieux adaptés au VPS.

## Vérifier le service

`/healthz` confirme la disponibilité du point d’entrée. `/_status` vérifie que la clé du fournisseur sélectionné est renseignée. Pour vérifier l’inférence, démarrez une nouvelle session, envoyez « Réponds uniquement OK », puis demandez de créer et relire un fichier dans l’espace de travail.

Sources amont : [Free Claude Code](https://github.com/Alishahryar1/free-claude-code) et [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness). Le conteneur installe leurs distributions officielles épinglées.
