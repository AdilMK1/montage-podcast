# Montage Podcast 2.0 · le parcours

Le même déroulé pour chaque podcast. L'app fait le technique, l'IA propose, **l'humain valide aux points ✋**. L'app refuse toute étape sautée et dit pourquoi.

**Lancer** : double-clic sur `Lancer.command`. Fermer sa fenêtre arrête l'interface, pas les rendus : ils continuent, et la prochaine ouverture les retrouve.

### Piste shorts

| # | Étape | Qui | Ce qui la débloque |
|---|---|---|---|
| 1 | **Dossier** : le dossier des rushes (titre et brief facultatifs) | humain | rien |
| 2 | **Pré-analyse** : son, synchro, morceaux regroupés, pièges (micros identiques, muets, bas), suggestion de casting : plan large (visages), micro ↔ caméra (voix ↔ lèvres), prénoms et animateur (IA sur le début) (+ proxys en fond) | app | dossier |
| ✋ | **Casting** : vérifier chaque personne (sa caméra + le son de son micro au même instant), corriger, valider | humain | pré-analyse |
| 3 | **Analyse** : transcription guidée par les noms propres, son nettoyé, visages, avec les bons noms (son et synchro de la pré-analyse réutilisés) | app | casting validé |
| ✋ | **Couleur**, réglée pendant l'analyse (une image par caméra) | humain | casting validé |
| 3 | ✋ **Son** : écoute avant / après, volume des voix, anti-écho, souffle | humain | analyse |
| 4 | ✋ **Choix des shorts** : l'IA propose, aperçu instantané de chaque proposition, accroche corrigeable, on retient | humain | analyse |
| 5 | **Fabrication** des shorts retenus, puis réécoute automatique des coupes | app | un short retenu, couleur et son validés |
| 6 | ✋ **Contrôle** : chaque alerte de coupe se réécoute (« c'est bon » ou « recaler ») ; garder / jeter / retoucher | humain | fabrication |
| 7 | **Livraison** : shorts gardés à -14 LUFS + épisode exporté, dans `EXPORT/<date>/` | app | un short gardé ou un épisode exporté |
| ✋ | Avant de publier : accords (invités, logo), crédits photo, traduction relue, date | humain | |

### Piste épisode (en parallèle, dès la fin de l'analyse)

| # | Étape | Qui | Ce qui la débloque |
|---|---|---|---|
| E1 | **Passages retirés** : l'IA repère hors antenne, réglages, « on coupe ça », longs blancs | app (IA) | analyse |
| E2 | ✋ **Revue** : chaque passage a son aperçu ; « garder » le remet dans l'épisode | humain | E1 |
| E3 | **Montage** multicam selon qui parle (calcul rapide) ; fichier XML pour Premiere | app | E2, couleur et son validés |
| E4 | **Essai d'export de 3 minutes** : rendu exactement comme l'export final (même script, même format, rushes d'origine, couleur, son traité, zooms), par défaut les 3 premières minutes ; se lance tout seul après le montage, en 1080p | app | E3 |
| E5 | ✋ **Valider l'essai** : plans, son, rythme, qualité ; sinon « Refaire l'essai » avec un autre départ (curseur sur la durée de l'épisode) ou en 4K | humain | E4 |
| E6 | **Export** de l'épisode complet en 1080p ou 4K depuis les rushes originaux ; durée estimée d'après la vitesse de rendu mesurée sur l'essai | app | essai validé et à jour |

### Règles garanties par l'app

- **Essai à jour** : l'export complet exige un essai validé pour l'épisode actuel. Changer la couleur, le son ou un passage remonte l'épisode et rend l'essai « à refaire » ; un nouvel essai (autre départ, autre format) se revalide.
- **Retour en arrière visible** : changer une étape validée (le casting, la couleur, le son) passe ce qui en dépend en « à refaire », et un short à refaire ne peut pas être livré.
- **Une série à la fois** : une nouvelle proposition de l'IA ouvre une nouvelle série ; les anciennes vidéos sont rangées à part, jamais effacées ni livrées.
- **Rien n'est livré par défaut** : aucun short gardé = rien à livrer.
- **Un short avec une alerte de coupe** n'est gardé qu'après réécoute.
- **Un échec ne bloque jamais le projet** : message clair et une action (réessayer, ou contourner : choisir les shorts ou les passages à la main si l'IA ne répond pas).

### Suivre et dépanner

- **Écran Activité** (clic sur le voyant en haut) : toutes les tâches de tous les podcasts, avec barre, temps restant, dernier signe de vie, et l'état du Mac.
- Une tâche sans signe de vie est relancée toute seule, puis passe en échec avec **Réessayer**.
- Bandeau rouge « moteur de travail arrêté » : **Redémarrer**.
- Toujours bloqué : **Envoyer un rapport** (zip dans `rapports/` : journaux et états, jamais de vidéo ni de son), à envoyer par mail ou message.

## Réglages verrouillés (habillage : `presets/<preset>.json`, neutre par défaut)

- **Habillage** : accroche Inter Black blanc + mot clé dans la couleur et la police d'accent du preset, logo optionnel en haut à droite, incrustations en haut à gauche sans boîte, dégradés sombres haut et bas.
- **Sous-titres** (réglage issu de Premiere) : Inter 18pt ExtraLight, taille 58, approche -50, centré bas (-445 px), casse normale, mots clés en couleur d’accent.
- **Shorts** : 1080×1920, 25 i/s, sans musique, sans carton de fin, coupes franches, visage à 40 % de la hauteur, son -14 LUFS.
- **Épisode** : plan selon qui parle, plan large toutes les ~90 s, 30 s max sur un visage, zooms lents.

Changer un réglage verrouillé = le tester sur un extrait, le valider, puis monter la version (`VERSION`).

## Pièges connus (et ce qui les évite)

| Piège | Garde-fou |
|---|---|
| Rushes mal nommés, on ne sait pas qui est qui | casting deviné par l'app (visages, voix ↔ lèvres, prénoms), vérifié à l'image et au son |
| Deux micros au même son (mélange exporté deux fois) | repéré à la pré-analyse, expliqué sur l'écran Casting ; on continue avec une seule voix |
| Short coupé en pleine phrase | règle de bornage + réécoute automatique des coupes après chaque fabrication |
| Export Reaper de 17 h (silence) | l'app ne lit que la partie utile ; régler la plage d'export dans Reaper |
| Écho entre micros voisins | son traité « automix » (le micro de celui qui se tait baisse) |
| Texte sur le visage | visage cadré à 40 %, textes en haut |
| « demain » à l'écran publié le lendemain | date en toutes lettres |
| Photo de tiers sans droits | licence libre + crédit dans la description |
