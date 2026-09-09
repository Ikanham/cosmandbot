# 🎭 CosmandBot

> **Bot Discord polyvalent et moderne pour communautés et groupes de cosplay.**  
> Développé avec **Python 3.12**, **discord.py 2.4.0** et **aiomysql**.

---

## 🌟 Fonctionnalités Principales

### 🎭 Organisation de Conventions Cosplay (`cogs/conventions.py`)
- **Inscriptions multi-jours personnalisables** : Création via formulaire Modal avec saisie libre des jours (ex: *Jeudi, Vendredi, Samedi, Dimanche* ou *Samedi, Dimanche*).
- **Rôle automatique intelligent** :
  - Dès qu'un membre sélectionne au moins un jour, le rôle de la convention lui est automatiquement attribué.
  - S'il désélectionne tous ses jours, le rôle lui est retiré.
- **Statut "En réflexion" & "Ne vient pas"** :
  - `[ 💭 Je réfléchis ]` : Retire le rôle et place le membre dans la liste des indécis.
  - `[ ❌ Ne vient pas ]` : Retire le rôle et incrémente le compteur d'absence.
- **Annonces en Markdown & Pings réels** : Le texte d'annonce est placé en contenu de message hors-embed avec gestion des mentions (`AllowedMentions`) pour déclencher de véritables notifications.
- **Persistance intégrale** : Les boutons restent actifs même après un redémarrage complet du bot (`bot.add_view()`).

### 📅 Sorties & Événements (`cogs/events.py`)
- Organisation des sorties du groupe gérées par l'équipe de modération.
- Liste des participants et gestion d'absences.

### ⏰ Planificateur & Messages Récurrents (`cogs/scheduler.py`)
- Planification de messages ponctuels et récurrents (ex: `/bonnejournee`).
- Prise en charge des fuseaux horaires (IANA, ex: `Europe/Paris`) configurables par serveur.
- Affichage des dates relatives dynamiques Discord (`<t:timestamp:R>`).

### ⏳ Comptes à Rebours (`cogs/countdowns.py`)
- Suivi du temps restant avant les conventions, sorties ou sorties de cosplays.
- Mise à jour automatique et autocomplétion pour la suppression.

### 🎂 Anniversaires (`cogs/anniversaires.py`)
- Souhaits automatiques dans le salon configuré.
- Prise en charge du 29 février pour les années bissextiles.
- Regroupement des anniversaires multiples le même jour.

### 🛡️ Modération, Logs & Configuration Dynamique (`cogs/admin.py`, `cogs/logs.py`)
- Rôle modérateur dynamique configurable par serveur (`/config role-mod`).
- Journalisation complète des événements (messages supprimés/modifiés, arrivées/départs, changements de rôles).
- Purges de messages sécurisées avec filtres (par utilisateur, bots uniquement, etc.).

### 📢 Annonces Sécurisées (`cogs/say.py`)
- Publication d'annonces personnalisées sous forme d'Embeds propres.
- Protection contre l'usurpation des pings `@everyone` / `@here` si l'utilisateur n'a pas les permissions requises.
- Limite de sécurité sur les pièces jointes (protection anti-DoS 25 Mo).

---

## 📁 Architecture du Projet

```text
cosmandbot/
├── .github/
│   └── workflows/
│       └── ci.yml              # Intégration continue GitHub Actions
├── cogs/                       # Modules et commandes du bot
│   ├── admin.py                # Configuration serveur, purges et gestion des rôles
│   ├── anniversaires.py        # Gestion des anniversaires et rappels automatiques
│   ├── conventions.py          # Organisation de conventions cosplay avec boutons interactifs
│   ├── countdowns.py            # Comptes à rebours d'événements
│   ├── errors.py               # Gestion centralisée des erreurs de commandes slash
│   ├── events.py               # Organisation des sorties et événements
│   ├── help.py                 # Commande /aide interactive avec pagination
│   ├── logs.py                 # Système d'audit logs Discord complet
│   ├── say.py                  # Commande d'annonce sécurisée
│   ├── scheduler.py            # Planification de messages et messages récurrents
│   ├── settings.py             # Affichage des réglages du serveur
│   └── welcome_goodbye.py      # Messages de bienvenue et d'au revoir
├── utils/                      # Utilitaires et fonctions transverses
│   ├── date_parser.py          # Analyseur robuste de dates en français
│   └── permissions.py          # Vérifications de permissions et fuseaux horaires
├── .env.example                # Exemple de variables d'environnement
├── .gitignore                  # Fichiers et dossiers exclus de Git
├── db.py                       # Gestion du pool asynchrone MariaDB/MySQL avec cache
├── main.py                     # Point d'entrée du bot Discord
├── requirements.txt            # Dépendances Python requises
├── schema.sql                  # Schéma SQL complet de la base de données
└── LICENSE                     # Licence MIT
```

---

## ⚙️ Prérequis

- **Python 3.10+** (Python 3.12 recommandé)
- **MariaDB 10.5+** ou **MySQL 8.0+**
- Un compte [Discord Developer](https://discord.com/developers/applications) avec une application et un Bot configuré.

### Privileged Gateway Intents Requis :
Dans le portail développeur Discord (*Bot* > *Privileged Gateway Intents*), activez :
- ✅ **Server Members Intent** (nécessaire pour les arrivées/départs et anniversaires)
- ✅ **Message Content Intent** (nécessaire pour la commande de synchronisation `+sync`)

---

## 🚀 Installation & Déploiement

### 1. Cloner le Dépôt
```bash
git clone https://github.com/<VOTRE_PSEUDO>/cosmandbot.git
cd cosmandbot
```

### 2. Créer l'Environnement Virtuel
```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Base de Données
Créez la base de données MariaDB / MySQL :
```sql
CREATE DATABASE cosmandbot CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'cosmanduser'@'localhost' IDENTIFIED BY 'votre_mot_de_passe_securise';
GRANT ALL PRIVILEGES ON cosmandbot.* TO 'cosmanduser'@'localhost';
FLUSH PRIVILEGES;
```
*(Optionnel)* Importez le schéma initial :
```bash
mysql -u cosmanduser -p cosmandbot < schema.sql
```
> **Note** : Le bot exécute également des migrations automatiques au démarrage (`init_db_indexes()`).

### 4. Configuration de l'Environnement
Copiez le fichier d'exemple et renseignez vos identifiants :
```bash
cp .env.example .env
nano .env
```

Contenu type de `.env` :
```env
DISCORD_TOKEN=votre_token_bot_ici
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=cosmanduser
DB_PASSWORD=votre_mot_de_passe_securise
DB_NAME=cosmandbot
```

### 5. Lancement & Synchronisation
Lancez le bot :
```bash
python3 main.py
```
Dans un salon Discord où le bot a accès, tapez :
```text
+sync
```
Cette commande synchronise instantanément toutes les commandes slash sur votre serveur Discord.

---

## 🛠️ Déploiement en Service Systemd (Linux)

Pour maintenir le bot actif 24h/24 et le redémarrer automatiquement en cas de reboot :

1. Créez le fichier de service :
```bash
sudo nano /etc/systemd/system/cosmandbot.service
```

2. Collez la configuration suivante (adaptez les chemins si nécessaire) :
```ini
[Unit]
Description=CosmandBot Discord Service
After=network.target mariadb.service

[Service]
Type=simple
User=root
WorkingDirectory=/root/cosmandbot
ExecStart=/root/cosmandbot/venv/bin/python main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

3. Activez et démarrez le service :
```bash
sudo systemctl daemon-reload
sudo systemctl enable cosmandbot
sudo systemctl start cosmandbot
sudo systemctl status cosmandbot
```

---

## 📖 Commandes Disponibles

| Commande | Permissions | Description |
| :--- | :--- | :--- |
| `/convention creer` | Modérateur / Admin | Crée une convention avec choix multi-jours et rôle automatique. |
| `/convention archiver` | Modérateur / Admin | Clôture une convention et supprime son rôle associé. |
| `/convention liste` | Modérateur / Admin | Liste les conventions actives du serveur. |
| `/config` | Administrateur | Configure les salons de logs, bienvenue, anniversaires, fuseau horaire et rôle modérateur. |
| `/settings` | Modérateur / Admin | Affiche un aperçu visuel de la configuration actuelle du serveur. |
| `/planifier ajouter` | Modérateur / Admin | Planifie un message ponctuel avec date et heure. |
| `/bonnejournee` | Modérateur / Admin | Configure un message matinal automatique récurrent. |
| `/rebours ajouter` | Tout membre | Crée un compte à rebours vers une date clé. |
| `/anniversaire ajouter`| Tout membre | Enregistre sa date d'anniversaire. |
| `/say` | Modérateur / Admin | Rédige et publie une annonce personnalisée. |
| `/purge` | Modérateur / Admin | Nettoie les messages d'un salon avec filtres avancés. |
| `/aide` | Tout membre | Affiche l'aide interactive complète. |

---

## 📄 Licence

Ce projet est sous licence [MIT](LICENSE).
