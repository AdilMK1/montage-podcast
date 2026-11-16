# Montage Podcast

L'app de montage podcast : de la carte SD à l'épisode monté et aux shorts, avec validation à chaque étape.

À partir des rushes d'un podcast (2 à 4 micros, 1 à 3 caméras), elle synchronise, transcrit, nettoie le son, monte l'épisode en multicam et fabrique des **shorts verticaux habillés** (habillage au choix : neutre, ou celui de ta marque). Les propositions créatives (shorts, accroches, passages à retirer de l'épisode) viennent de l'IA installée sur l'ordinateur (Claude Code), qui suit `CONSIGNES IA.md`. Tu valides tout dans l'app.

## Installer (une fois)

Il faut un **Mac avec puce Apple** (M1 ou plus récent, macOS 14 ou plus) ou un **PC Windows 10 / 11** 64 bits (idéalement avec une carte NVIDIA).

**Sous Windows** : décompresse le dossier (hors OneDrive, par exemple `C:\Montage Podcast`), double-clique **`Installer.bat`** (il installe ffmpeg et Python avec winget s'ils manquent : ferme puis relance-le quand il le demande), puis **`Lancer.bat`**. La transcription passe par faster-whisper (même modèle que sur Mac), sur la carte NVIDIA si elle répond, sinon sur le processeur (plus lent) ; les rendus utilisent la carte graphique (NVIDIA, Intel ou AMD) quand elle est là. L'IA : installe Claude Code pour Windows et connecte-le (`claude` dans PowerShell). Le reste de cette page vaut aussi pour Windows (`.bat` à la place de `.command`).

**Sur Mac** :

1. **Récupère l'app** : sur https://github.com/AdilMK1/montage-podcast, bouton vert **Code › Download ZIP** (ou le zip qu'on t'a donné), puis décompresse le dossier où tu veux (sous Windows : hors OneDrive).
2. **Installe les outils** : ouvre l'app Terminal, installe [Homebrew](https://brew.sh) (copie la commande donnée sur leur site) si tu ne l'as pas, puis tape `brew install ffmpeg python@3.14`.
3. **Installe l'app** : double-clique **`Installer.command`** dans le dossier (crée l'environnement, installe les modules et le modèle de transcription d'environ 1,5 Go, ~5 min). Si macOS refuse de l'ouvrir (« développeur non identifié ») : clic droit sur le fichier, **Ouvrir**, puis **Ouvrir** encore. Même chose la première fois pour `Lancer.command`.
4. **L'IA (facultatif)** : pour les propositions de shorts et des passages à retirer, installe [Claude Code](https://claude.com/claude-code) et connecte-le avec ton propre compte (la commande `claude` doit marcher dans le Terminal). Sans IA, l'app marche quand même : tu choisis les shorts et les passages dans le transcript.

Les rushes de démo ne sont pas dans le dépôt (trop lourds) : demande-les à part si tu veux t'entraîner, et mets-les dans `demo/rushes/`.

## Lancer

Double-clique **`Lancer.command`** : l'app s'ouvre dans ton navigateur sur http://localhost:8765.

- Garde la petite fenêtre du Terminal ouverte pendant que tu travailles.
- Pendant un rendu, garde le capot du Mac ouvert : l'app empêche la mise en veille, mais un Mac fermé s'endort quand même. Le rendu reprend tout seul au réveil.
- **La fermer arrête l'interface, pas les rendus** : ils continuent en fond (le « moteur de travail »). Relance `Lancer.command` quand tu veux : tu retrouves tout où tu l'avais laissé.
- Si l'app est déjà ouverte, `Lancer.command` ouvre juste un nouvel onglet.

## Le parcours

L'app te prend par la main : une étape se débloque quand la précédente est prête, et un bouton grisé dit toujours pourquoi.

1. **Dossier** : « Nouveau podcast », tu choisis le dossier des rushes (ou tu écris son emplacement). C'est tout (titre et brief facultatifs). Si l'app ne s'y retrouve pas (un fichier mal reconnu), elle propose de choisir les fichiers et les noms à la main.
2. **Pré-analyse** (l'app, quelques minutes) : lecture du son, synchro, morceaux d'une même caméra regroupés, pièges repérés (micros au même son, muets ou trop bas), puis l'app **devine qui est qui** : le plan large (la caméra qui voit le plus souvent plusieurs visages), le micro de chaque caméra (la voix qui colle au mouvement des lèvres), les prénoms et qui anime (le début de la conversation, lu par l'IA ; sans IA : « Personne 1 », « Personne 2 »).
3. ✋ **Casting** : une carte par caméra (un extrait muet qui tourne en boucle), une pastille par micro (sa forme d'onde, ▶ pour l'écouter). Tout est déjà placé. Clique sur une personne (ou « Tout vérifier ») pour voir sa caméra avec le son de SON micro au même instant : « Ça colle » ou « Pas lui/elle » (tu choisis alors la bonne caméra). Corrige si besoin : prénom écrit sur la carte, qui anime, glisser une pastille micro sur une autre carte (au clavier : la poignée ⠿, Entrée, flèches, Entrée), échanger deux personnes, plan large. Puis **valide** : l'analyse démarre. Si les micros ont le même son, l'écran l'explique : place chaque personne d'après son visage, l'app continue avec une seule voix.
4. **Analyse** (l'app, quelques minutes) : synchro, transcription, son nettoyé, visages. Pendant ce temps, tu règles déjà la **couleur** (une image par caméra suffit).
5. **Son** : écoute avant / après, volume des voix, anti-écho, souffle. Tu valides.
6. **Shorts** : l'IA propose, chaque proposition se regarde tout de suite (aperçu instantané), tu corriges l'accroche et tu retiens ceux qui te plaisent (ou tu en crées un toi-même dans le transcript).
7. **Fabrication** des shorts retenus (couleur et son validés obligatoires), puis réécoute automatique des coupes.
8. **Contrôle** : chaque coupe douteuse se réécoute en un clic (« c'est bon » ou « recaler »), puis tu gardes, jettes ou fais retoucher chaque short.
9. **Livraison** : les shorts gardés (au volume des réseaux) et l'épisode exporté, rangés dans un dossier daté `EXPORT/`.

Changer le casting après l'analyse est possible : l'analyse (et ce qui en dépend) passe « à refaire » et repart à la validation. Les noms propres et le brief se donnent dans le projet. Un podcast créé avec l'ancien écran (fichiers et noms choisis à la main) n'a pas d'étape Casting.

**En parallèle, l'épisode** : l'IA repère les passages à retirer (hors antenne, réglages, longs blancs) ; tu les revois un par un (« garder » le remet) ; l'app calcule le montage multicam (rapide), puis rend tout seul un **essai d'export de 3 minutes** : les 3 premières minutes de l'épisode, exactement comme l'export final (rushes d'origine, pleine qualité, couleur, son traité, zooms). Tu le regardes ; un doute sur un autre moment ou sur la 4K ? choisis un autre départ ou un autre format et « Refaire l'essai ». Si c'est bon, « Valider l'essai », puis l'export complet en 1080p ou 4K, avec une durée estimée d'après la vitesse mesurée sur l'essai. Changer la couleur, le son ou un passage rend l'essai « à refaire ».

**Couper après l'export** : un passage à enlever une fois l'épisode exporté (hors antenne à la fin, une phrase ratée au milieu) ? Dans « Couper dans l'épisode », marque le début et la fin sur la vidéo, écoute la jointure (▶), puis « Appliquer les coupes ». L'app ne réencode que quelques secondes autour de chaque coupe (environ 30 s pour un épisode de 30 min, au lieu d'un nouvel export) ; l'export d'origine est gardé et la livraison prend la version coupée. Un nouvel export du même montage garde les coupes (à réappliquer) ; un épisode remonté autrement les efface, leurs heures ne correspondant plus.

## L'écran Activité

Clique sur le **voyant** en haut à droite de n'importe quel écran (« Tout est calme », le nombre de tâches en cours…) : l'écran Activité montre toutes les tâches de tous les podcasts (en cours avec barre, temps restant et dernier signe de vie, en attente avec la raison, terminées, en échec), et l'état du Mac (processeur, mémoire, disque, veille). Le voyant résume : vert, tout va bien ; orange, à surveiller (une tâche semble ralentie, le disque se remplit) ; rouge, une tâche a échoué, le disque est presque plein ou le moteur de travail est arrêté. Si le moteur de travail est arrêté, un bandeau rouge apparaît sur tous les écrans avec un bouton **Redémarrer**.

## Si quelque chose bloque

1. Lis le message : il dit ce qui se passe et propose une action (réessayer, contourner, annuler).
2. Une tâche qui ne donne plus signe de vie est relancée toute seule ; si elle échoue encore, elle passe en échec avec un bouton **Réessayer**.
3. Moteur de travail arrêté (bandeau rouge) : **Redémarrer**. Si l'app ne répond plus du tout : ferme la fenêtre du Terminal et relance `Lancer.command` (les rendus en cours ne sont pas perdus).
4. Toujours bloqué : **Envoyer un rapport** (sur la tâche en échec ou dans l'écran Activité). L'app prépare un fichier zip (bouton **Ouvrir le dossier** pour le retrouver dans `rapports/`) : envoie-le par mail ou par message. Il contient les journaux et l'état des projets, jamais tes vidéos ni ton son.

## Démo

L'app n'est plus livrée avec un projet de démo : la liste des podcasts ne contient que les tiens. Les rushes de démo (4 min 20 de Sarah × Léo, 3 caméras, 2 micros) vont dans `demo/rushes/` ; ils ne sont pas dans le dépôt GitHub (trop lourds), ils se transmettent à part.

- **Démonstration en direct** : `./demo/reinitialiser.sh` crée un projet neuf **Démo en direct** (`projets/DEMO_EN_DIRECT`) à partir de ces rushes, comme si tu venais de le créer dans l'app : l'analyse et les proxys partent dès que l'app tourne. Relancé, il range d'abord l'ancienne démo dans `demo/archives/<date>/` (rien n'est effacé). Après la démonstration, déplace `projets/DEMO_EN_DIRECT` ailleurs pour qu'elle quitte ta liste. Un autre dossier de projets peut être donné en paramètre : `./demo/reinitialiser.sh /chemin/vers/projets`.
- **Essais lents** (`pytest -m lent`) : ils construisent eux-mêmes un projet de référence à partir des mêmes rushes, une fois, dans `.cache/demo_test/` (jamais dans `projets/`), puis le réutilisent. Pour le reconstruire : `pytest --reconstruire-demo` (ou `CRAIE_DEMO_RECONSTRUIRE=1`).

Les projets créés avec l'ancienne version (1.1) s'ouvrent normalement : à la première ouverture, l'app reprend leur avancement (fichier `etat.json` ajouté, rien d'autre n'est modifié).

## Personnaliser (nom, couleurs, marque)

- `config.json` : nom affiché de l'app, couleur de l'interface, habillage par défaut.
- **Packs de shorts** (accueil, bouton « Packs de shorts ») : l'habillage des shorts (sous-titres, couleurs, accroche, logo, musique, écran de fin), réglé dans l'app avec un aperçu rendu par le moteur des shorts. Un pack se choisit à la création d'un podcast (pré-rempli avec le dernier utilisé), se change à l'étape Shorts, et peut être différent pour un short précis (« Aucun pack » : sans logo ni musique). Modifier un pack utilisé, ou en changer, rend « à refaire » les shorts déjà fabriqués avec lui (jamais les shorts jetés). Export / import en `.zip` pour passer un pack d'un ordinateur à l'autre (Mac ou PC).
- Les packs sont rangés dans `packs/<nom>/` (pack.json + logo, polices). Au premier lancement, les anciens `presets/` (neutre, CRAIE) y sont recopiés en packs ; `presets/` ne sert plus qu'à cette reprise. Les podcasts existants gardent leur habillage et leurs shorts restent à jour. `preset_defaut` dans `config.json` : pack proposé à la création tant que tu n'en as choisi aucun.

## Structure

```
Lancer.command                lanceur (ouvre l'app dans le navigateur)
Installer.command             installation
CONSIGNES IA.md               règles créatives données à l'IA
PROCESS.md                    le parcours, étape par étape
config.json                   nom de l'app, couleur, pack proposé par défaut
packs/<nom>/                  packs de shorts (créés au premier lancement depuis presets/)
presets/                      anciens habillages, repris en packs au premier lancement
app/web/                      l'interface (écrans)
app/api/                      le serveur local (vues, actions, règles du parcours)
app/taches/                   le moteur de travail (tâches qui survivent à la fermeture)
app/services/, app/projet/    étapes du montage, état de chaque projet (etat.json)
moteur/                       moteur de montage (synchro, transcript, son, rendu)
projets/<ID>/                 un dossier par projet (tout ce qui est produit)
rapports/                     rapports de dépannage
demo/                         rushes de démo, création d'une démo en direct (reinitialiser.sh)
```

Version : voir `VERSION` · Historique : `CHANGELOG.md`.
