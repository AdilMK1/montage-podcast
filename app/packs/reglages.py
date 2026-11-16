"""Réglages d'un pack de shorts (lot A : ce que le moteur des shorts sait déjà faire) : valeurs du pack neutre, fusion,
validation champ par champ (type, bornes) avec un refus en français.

Un champ absent prend la valeur du neutre ; un champ inconnu est refusé (faute de frappe, ou pack d'une version plus
récente de l'app). Les fichiers (polices, logo, musique) sont désignés par leur nom seul et doivent être disponibles
(`dispo` : {"logo": [...], "police": [...], "musique": [...]}, fourni par la bibliothèque)."""
from copy import deepcopy

from app.projet.regles import Refus, fini

# presets/neutre.json, fichiers désignés par leur nom (cherchés dans le pack, puis parmi ceux livrés avec le moteur)
NEUTRE = {
    "da": "craie", "logo": False, "logo_fichier": None, "logo_marge": 0.06, "couleur": [79, 107, 237],
    "accroche_y": 0.118, "yeux": 0.4, "sans_fin": True, "musique": {"fichier": "686.mp3", "lufs": -26},
    "sous_titres": {"police": "Inter.ttf", "graisse": 200, "optique": 18, "taille": 58, "approche": -50, "x": 18,
                    "y_bas": 445, "echelle_cle": 1.0, "graisse_cle": 200, "casse": "normale", "interligne": 1.06},
    "defauts_short": {"glisse": False, "sans_musique": True, "accroche_duree": 3.2},
    "corrections": {}, "police_accent": "Inter.ttf", "teintes": {"clair": [240, 240, 240], "fond": [20, 20, 24]},
    # ajouté après le lot A, défaut sans effet sur le rendu (le logo restait en haut à droite) : voir la règle ci-dessous
    "logo_position": "haut",
}
# Base FIGÉE de l'empreinte d'un pack (copie du neutre du lot A) : ne JAMAIS la modifier, même quand NEUTRE change.
# Règle de l'empreinte (forme_canonique) : seuls comptent les réglages qui diffèrent de cette base (pour un réglage
# ajouté après le lot A : de sa valeur dans NEUTRE). Ajouter à NEUTRE un réglage dont la valeur par défaut reproduit
# le rendu d'avant ne change donc aucune empreinte (les shorts déjà fabriqués restent « à jour »). Conséquences :
# - un nouveau réglage DOIT avoir un défaut sans effet sur le rendu ;
# - ne jamais changer ensuite le défaut d'un réglage ajouté après le lot A (son empreinte ne le verrait pas) : pour
#   ça, figer d'abord sa valeur ici sous un nouveau nom (NEUTRE_V2) et l'ajouter à la base.
NEUTRE_V1 = {
    "da": "craie", "logo": False, "logo_fichier": None, "logo_marge": 0.06, "couleur": [79, 107, 237],
    "accroche_y": 0.118, "yeux": 0.4, "sans_fin": True, "musique": {"fichier": "686.mp3", "lufs": -26},
    "sous_titres": {"police": "Inter.ttf", "graisse": 200, "optique": 18, "taille": 58, "approche": -50, "x": 18,
                    "y_bas": 445, "echelle_cle": 1.0, "graisse_cle": 200, "casse": "normale", "interligne": 1.06},
    "defauts_short": {"glisse": False, "sans_musique": True, "accroche_duree": 3.2},
    "corrections": {}, "police_accent": "Inter.ttf", "teintes": {"clair": [240, 240, 240], "fond": [20, 20, 24]},
}
GROUPES = ("musique", "sous_titres", "defauts_short", "teintes")
LIBRES = ("_", "corrections")  # note libre et corrections de mots : gardées telles quelles


def _n(nom, mini, maxi):
    return {"sorte": "nombre", "min": mini, "max": maxi, "nom": nom}


CHAMPS = {
    "da": {"sorte": "choix", "valeurs": ("craie", None), "nom": "style de l'habillage"},
    "couleur": {"sorte": "rgb", "nom": "couleur d'accent"},
    "teintes.clair": {"sorte": "rgb", "nom": "teinte claire"},
    "teintes.fond": {"sorte": "rgb", "nom": "teinte de fond"},
    "accroche_y": _n("position de l'accroche", 0.02, 0.9),
    "yeux": _n("hauteur des yeux", 0.1, 0.7),
    "logo": {"sorte": "oui_non", "nom": "logo"},
    "logo_fichier": {"sorte": "fichier", "type": "logo", "vide": True, "nom": "fichier du logo"},
    "logo_marge": _n("marge du logo", 0.0, 0.3),
    # "bas" : petit, centré tout en bas, comme les Reels CRAIE livrés (clips Sarah × Inès, 11/11/2026)
    "logo_position": {"sorte": "choix", "valeurs": ("haut", "bas"), "nom": "emplacement du logo"},
    "sans_fin": {"sorte": "oui_non", "nom": "écran de fin"},
    "police_accent": {"sorte": "fichier", "type": "police", "nom": "police du mot clé de l'accroche"},
    "musique.fichier": {"sorte": "fichier", "type": "musique", "nom": "musique"},
    "musique.lufs": _n("volume de la musique", -40, -10),
    "sous_titres.police": {"sorte": "fichier", "type": "police", "nom": "police des sous-titres"},
    "sous_titres.taille": _n("taille des sous-titres", 20, 160),
    "sous_titres.graisse": _n("graisse des sous-titres", 100, 900),
    "sous_titres.graisse_cle": _n("graisse du mot clé", 100, 900),
    "sous_titres.optique": _n("taille optique", 6, 40),
    "sous_titres.approche": _n("approche des lettres", -200, 200),
    "sous_titres.x": _n("décalage horizontal des sous-titres", -300, 300),
    "sous_titres.y_bas": _n("hauteur des sous-titres", 0, 1500),
    "sous_titres.echelle_cle": _n("taille du mot clé", 0.5, 2.5),
    "sous_titres.interligne": _n("interligne", 0.8, 2.0),
    "sous_titres.casse": {"sorte": "choix", "valeurs": ("normale", "majuscules"), "nom": "casse des sous-titres"},
    "defauts_short.accroche_duree": _n("durée de l'accroche", 0.5, 10),
    "defauts_short.sans_musique": {"sorte": "oui_non", "nom": "musique"},
    "defauts_short.glisse": {"sorte": "oui_non", "nom": "glissé entre les extraits"},
}


def fusion(base: dict, dessus: dict) -> dict:
    """copie de `base` complétée / remplacée par `dessus`, groupe par groupe (jamais de modification sur place)"""
    out = deepcopy(base)
    for k, v in (dessus or {}).items():
        out[k] = fusion(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else deepcopy(v)
    return out


_SANS = object()


def forme_canonique(r: dict) -> list:
    """réglages réduits à ce qui diffère de la base figée (NEUTRE_V1, complétée par NEUTRE pour les réglages
    ajoutés depuis), triés : [[chemin, valeur], ...]. Les notes libres (« _ ») n'y entrent pas (sans effet sur le rendu).
    Sert à l'empreinte d'un pack (voir la règle au-dessus de NEUTRE_V1)."""
    base = fusion(NEUTRE, NEUTRE_V1)
    out = []

    def parcourir(v, b, chemin):
        if isinstance(v, dict) and (isinstance(b, dict) or b is _SANS):
            b = b if isinstance(b, dict) else {}
            for k in v:
                if k != "_":
                    parcourir(v[k], b.get(k, _SANS), chemin + [k])
            for k in b:  # réglage de la base absent ici (corrections retirée...) : compte aussi
                if k != "_" and k not in v:
                    out.append([chemin + [k], "<absent>"])
        elif b is _SANS or v != b or type(v) is not type(b):
            out.append([chemin, v])
    parcourir(r, base, [])
    return sorted(out, key=lambda x: [str(c) for c in x[0]])


def _texte(x) -> str:
    return f"{x:g}".replace(".", ",")


def _plat(r: dict):
    for k, v in r.items():
        if k in GROUPES:
            if not isinstance(v, dict):
                raise Refus(f"Réglage invalide : « {k} » doit regrouper des réglages.")
            for k2, v2 in v.items():
                if k2 != "_":
                    yield f"{k}.{k2}", v2
        elif k not in LIBRES:
            yield k, v


def _verifier(v, c: dict, dispo: dict):
    nom, sorte = c["nom"], c["sorte"]
    if sorte == "nombre":
        ok = isinstance(v, (int, float)) and not isinstance(v, bool) and fini(v) and c["min"] <= v <= c["max"]
        if not ok:
            raise Refus(f"Réglage invalide : {nom} (entre {_texte(c['min'])} et {_texte(c['max'])}).")
    elif sorte == "rgb":
        ok = (isinstance(v, list) and len(v) == 3
              and all(isinstance(x, int) and not isinstance(x, bool) and 0 <= x <= 255 for x in v))
        if not ok:
            raise Refus(f"Réglage invalide : {nom} (trois nombres de 0 à 255).")
    elif sorte == "oui_non":
        if not isinstance(v, bool):
            raise Refus(f"Réglage invalide : {nom} (oui ou non).")
    elif sorte == "choix":
        if v not in c["valeurs"]:
            raise Refus(f"Réglage invalide : {nom}.")
    elif sorte == "fichier":
        if v is None and c.get("vide"):
            return
        if not isinstance(v, str) or v not in dispo.get(c["type"], []):
            raise Refus(f"Fichier introuvable dans le pack : « {v} » ({nom}).")


def _corrections(c):
    """{mots transcrits: mots affichés}, textes, autant de mots de chaque côté (le moteur l'exige)"""
    if not isinstance(c, dict):
        raise Refus("Réglage invalide : corrections de mots.")
    for src, dst in c.items():
        if not isinstance(src, str) or not isinstance(dst, str) or not src.split():
            raise Refus("Réglage invalide : corrections de mots (du texte des deux côtés).")
        if len(src.split()) != len(dst.split()):
            raise Refus(f"Réglage invalide : corrections de mots (« {src} » se remplace par autant de mots, "
                        "« _ » pour en afficher deux à la place d'un).")


def valider(reglages, dispo: dict) -> dict:
    """réglages complets (fusionnés avec le neutre) ; Refus en français au premier champ invalide"""
    if not isinstance(reglages, dict):
        raise Refus("Réglages du pack invalides.")
    if "corrections" in reglages:
        _corrections(reglages["corrections"])
    for cle, v in _plat(reglages):
        c = CHAMPS.get(cle)
        if c is None:
            raise Refus(f"Réglage inconnu dans le pack : « {cle} ».")
        _verifier(v, c, dispo)
    r = fusion(NEUTRE, reglages)
    if r["logo"] and not r["logo_fichier"]:
        raise Refus("Choisis un fichier pour le logo, ou désactive le logo.")
    return r
