"""Création d'un projet : scan d'un dossier de rushes, projet.json + etat.json, tâches d'analyse et de proxys ;
et spec d'un short choisi dans le transcript (bornes calées sur les mots)."""
import re
import time
import unicodedata
from collections import Counter
from pathlib import Path

from app.fichiers import ecrire_json_atomique
from app.projet.modele import nouvel_etat
from app.projet.stockage import ecrire_etat
from app.services.cadrage import dans_plage
from app.services.transcript import mots
from app.taches import file

from . import rushes
from .rushes import AUDIO, VIDEO


def slug(t: str) -> str:
    s = re.sub(r"[^A-Z0-9]+", "_", _ascii(t).upper()).strip("_")
    return s or "PROJET"


def _ascii(t: str) -> str:
    """sans accents (é -> e, à -> a), puis sans tout ce qui n'est pas ASCII"""
    return unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()


PREFIXE = r"^(MICRO|MIC|AUDIO|CAM|CAMERA)[ _-]*"


def _naturel(f: Path):
    """« CAM A 9 » avant « CAM A 10 »"""
    return [int(x) if x.isdigit() else x.lower() for x in re.split(r"(\d+)", str(f))]


def scanner(dossier) -> dict:
    """liste les fichiers son / vidéo d'un dossier et devine leur rôle d'après le nom ; les morceaux d'une même
    caméra (fichiers coupés) reçoivent le même nom ; signale les fichiers son au contenu identique"""
    d = Path(dossier).expanduser()
    if not d.is_dir():
        raise ValueError("dossier introuvable")
    fichiers = []
    for f in sorted(d.rglob("*"), key=_naturel):
        ext = f.suffix.lower()
        if f.is_file() and ext in AUDIO | VIDEO and not f.name.startswith("."):
            kind = "micro" if ext in AUDIO else "camera"
            up = f.stem.upper()
            nom = re.sub(PREFIXE, "", up).split(" PISTE")[0].strip(" _-") or up
            if kind == "camera" and any(w in up for w in ("LARGE", "WIDE", "PLAN LARGE")):
                nom = "LARGE"
            fichiers.append({"chemin": str(f), "type": kind, "nom": _ident(nom),
                             "taille_mo": round(f.stat().st_size / 1e6)})
    _regrouper(fichiers)
    return {"fichiers": fichiers,
            "identiques": rushes.identiques([x["chemin"] for x in fichiers if x["type"] == "micro"])}


def _ident(nom: str) -> str:
    return re.sub(r"[^A-Z0-9_]", "_", nom)[:20]


def _regrouper(fichiers):
    """règle prudente : vidéos d'un même dossier, même nom une fois retiré un numéro final, numéros consécutifs
    (« CAM A 1 » + « CAM A 2 », « C8988 » + « C8989 ») ; « CAM 1 » / « CAM 2 » restent deux caméras. Un morceau
    n'est jamais retiré : regroupé, ou laissé comme caméra à part."""
    familles: dict[tuple, list] = {}
    for x in fichiers:
        p = Path(x["chemin"])
        m = re.match(r"^(.*?)[ _-]*(\d+)\s*$", p.stem)
        if x["type"] != "camera" or not m or x["nom"] == "LARGE":
            continue
        base = re.sub(PREFIXE, "", m.group(1).upper()).strip(" _-")
        if base:
            familles.setdefault((str(p.parent), base), []).append((int(m.group(2)), x))
    for (_, base), membres in familles.items():
        membres.sort(key=lambda t: t[0])
        suite = [membres[0]]
        for t in membres[1:] + [None]:
            if t is not None and t[0] == suite[-1][0] + 1:
                suite.append(t)
                continue
            pris = any(y["nom"] == _ident(base) and y["type"] == "camera" and y not in [z for _, z in suite]
                       for y in fichiers)  # une caméra porte déjà ce nom : on ne devine pas
            if len(suite) > 1 and not pris:
                for _, x in suite:
                    x["nom"] = _ident(base)
            suite = [t]


def creer_projet(racine, body: dict) -> str:
    """crée projets/<ID>/ (projet.json + etat.json) et lance l'analyse et les proxys ; renvoie l'ID"""
    titre = (body.get("titre") or "").strip() or "Podcast"
    mics = {f["nom"]: f["chemin"] for f in body.get("fichiers", []) if f["type"] == "micro"}
    if not mics:
        raise ValueError("Il faut au moins un micro (fichier son) dans le dossier des rushes.")
    cams = {}
    for f in body.get("fichiers", []):
        if f["type"] == "camera":
            cams.setdefault(f["nom"], []).append(f["chemin"])
    if not cams:
        raise ValueError("Il faut au moins une caméra (fichier vidéo) dans le dossier des rushes.")
    cams = {k: (v[0] if len(v) == 1 else v) for k, v in cams.items()}
    racine = Path(racine)
    pid, n = slug(titre), 2
    while (racine / pid).exists():
        pid, n = f"{slug(titre)}_{n}", n + 1
    d = racine / pid
    d.mkdir(parents=True)
    donnees = {k: v for k, v in (body.get("personnes") or {}).items() if k in mics and isinstance(v, dict)}
    # sans choix explicite, le 1er micro est l'animateur ; dès que l'interface en désigne un, les autres sont invités
    anime = any(v.get("role") == "animateur" for v in donnees.values())
    pers = {k: {"nom": "", "fonction": "", "role": "invité" if (i or anime) else "animateur"}
            for i, k in enumerate(mics)}
    for k, v in donnees.items():
        pers[k].update({c: v[c] for c in ("nom", "fonction", "role") if c in v})
    ecrire_json_atomique(d / "projet.json", {
        "titre": titre, "cree": time.strftime("%Y-%m-%d %H:%M"), "fps": 25, "mics": mics, "cams": cams,
        "personnes": pers, "noms_propres": [x.strip() for x in body.get("noms_propres", []) if x and x.strip()],
        "brief": (body.get("brief") or "").strip(), "auto_ia": body.get("auto_ia", True)})
    ecrire_etat(d, nouvel_etat())
    file.creer(d, "analyse")
    file.creer(d, "proxys")
    return pid


def creer_depuis_dossier(racine, body: dict) -> str:
    """crée un projet à partir du dossier des rushes seul : identifiants techniques (MIC_1, CAM_1… ; les morceaux
    d'une caméra regroupés sous un seul identifiant), casting à faire ; lance la pré-analyse et les proxys"""
    dossier = body.get("dossier")
    if not isinstance(dossier, str) or not dossier.strip():
        raise ValueError("Choisis le dossier qui contient les rushes.")
    fichiers = scanner(dossier)["fichiers"]
    ids, mics, cams = {}, {}, {}
    for f in fichiers:
        if f["type"] == "micro":
            k = f"MIC_{len(mics) + 1}"
            mics[k] = f["chemin"]
            ids[k] = {"type": "micro", "fichiers": [f["chemin"]]}
    groupes: dict[str, list[str]] = {}
    for f in fichiers:
        if f["type"] == "camera":
            groupes.setdefault(f["nom"], []).append(f["chemin"])
    for i, chemins in enumerate(groupes.values()):
        k = f"CAM_{i + 1}"
        cams[k] = chemins[0] if len(chemins) == 1 else chemins
        ids[k] = {"type": "camera", "fichiers": chemins}
    if not mics:
        raise ValueError("Il faut au moins un micro (fichier son) dans le dossier des rushes.")
    if not cams:
        raise ValueError("Il faut au moins une caméra (fichier vidéo) dans le dossier des rushes.")
    titre = (body.get("titre") or "").strip() or Path(dossier.rstrip("/\\")).name or "Podcast"
    racine = Path(racine)
    pid, n = slug(titre), 2
    while (racine / pid).exists():
        pid, n = f"{slug(titre)}_{n}", n + 1
    d = racine / pid
    d.mkdir(parents=True)
    ecrire_json_atomique(d / "projet.json", {
        "titre": titre, "cree": time.strftime("%Y-%m-%d %H:%M"), "fps": 25, "mics": mics, "cams": cams,
        "personnes": {k: {"nom": "", "fonction": "", "role": "invité" if i else "animateur"} for i, k in enumerate(mics)},
        "noms_propres": [], "brief": (body.get("brief") or "").strip(), "auto_ia": body.get("auto_ia", True),
        "dossier_rushes": str(Path(dossier).expanduser()),
        "casting": {"format": 1, "ids": ids, "cles": {k: k for k in ids}}})
    ecrire_etat(d, nouvel_etat(casting=True))
    file.creer(d, "pre_analyse")
    file.creer(d, "proxys")
    return pid


def short_depuis_texte(d, a: float, b: float) -> dict:
    """spec d'un short à partir d'un passage choisi dans le transcript : bornes calées sur les mots, petite marge"""
    d = Path(d)
    W = mots(d)
    dans = [w for w in W if a - 0.05 <= w[1] < b]
    if not dans:
        raise ValueError("Ce passage ne contient aucune parole : choisis d'autres phrases.")
    debut, fin = dans[0][1], dans[-1][2]
    plage = dans_plage(d, debut, fin)
    if not plage:
        raise ValueError("Ce passage n'est pas filmé par toutes les caméras (tout début ou toute fin) : "
                         "choisis un peu plus loin.")
    debut, fin = plage
    avant = [w for w in W if w[2] <= debut]
    apres = [w for w in W if w[1] >= fin]
    debut = max(debut - 0.15, (avant[-1][2] + 0.02) if avant else 0)
    fin = min(fin + 0.25, (apres[0][1] - 0.05) if apres else fin + 0.25)
    micro = Counter(w[3] for w in dans).most_common(1)[0][0]
    premiers = " ".join(w[0] for w in dans[:6])
    nom = re.sub(r"[^A-Z0-9 ]", "", _ascii(premiers).upper())[:28].strip()
    return {"nom": nom, "accroche": [], "micro": micro, "extraits": [{"rush": [round(debut, 2), round(fin, 2)]}],
            "_": "Choisi par toi dans le transcript."}
