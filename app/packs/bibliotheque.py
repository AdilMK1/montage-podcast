"""Bibliothèque des packs de shorts, commune à toute l'app : packs/<id>/pack.json + les fichiers du pack (logo,
polices, musique) dans le même dossier. pack.json = {"nom", "format", "reglages"} ; un fichier y est désigné par son
nom seul, cherché dans le dossier du pack, puis parmi ceux livrés avec le moteur (moteur/fonts, moteur/assets/musique).

`id` = slug du nom à la création (« mon-pack »), unique et stable : renommer ne change que le nom affiché.
« Aucun pack » (id réservé `aucun`) est intégré : pas de dossier, ni modifiable, ni renommable, ni supprimable.
Écritures sûres : un nouveau pack est préparé dans un dossier caché puis renommé d'un coup (jamais de pack à moitié
écrit, même si deux processus migrent en même temps) ; pack.json est écrit de façon atomique. Marche sous Windows :
noms de fichiers sans caractère interdit, chemins construits avec pathlib.
"""
import hashlib
import io
import os
import re
import shutil
import threading
import time
import unicodedata
import uuid
from copy import deepcopy
from pathlib import Path, PurePosixPath

from PIL import Image, ImageFont

from app.fichiers import ecrire_json_atomique, lire_json
from app.projet.modele import empreinte
from app.projet.regles import Refus

from .reglages import NEUTRE, forme_canonique, fusion, valider

RACINE_APP = Path(__file__).resolve().parents[2]
MOTEUR = RACINE_APP / "moteur"
FORMAT = 1
AUCUN = "aucun"
NOM_MAX = 40
ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,59}$")
FICHIER = re.compile(r'^[^\\/:*?"<>|\x00-\x1f]{1,80}\.(png|ttf|otf|mp3|wav|m4a)$', re.I)
EXT_LOGO, EXT_POLICE, EXT_MUSIQUE = (".png",), (".ttf", ".otf"), (".mp3", ".wav", ".m4a")
LIVRES = (("fonts", EXT_POLICE), ("assets/musique", EXT_MUSIQUE))  # fichiers livrés avec le moteur
AUCUN_REGLAGES = fusion(NEUTRE, {"couleur": [255, 255, 255], "logo": False, "logo_fichier": None, "sans_fin": True,
                                 "defauts_short": {"sans_musique": True}})
INTEGRE = "« Aucun pack » est livré avec l'app"
# noms réservés par Windows, quelle que soit l'extension (« con.png », « aux.tar.png ») et la casse
RESERVES = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
CACHES_PERIMES = 3600  # secondes : dossiers .tmp-* / .corbeille-* laissés par un arrêt brutal
_EMPREINTES: dict = {}
_VERROUS: dict = {}  # un verrou par pack : pack.json se lit puis se réécrit (serveur à plusieurs fils)
_VERROUS_GARDE = threading.Lock()


def _verrou(racine, pid) -> threading.Lock:
    with _VERROUS_GARDE:
        return _VERROUS.setdefault((os.path.abspath(racine), pid), threading.Lock())


def _ascii(t: str) -> str:
    return unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()


def slug(nom) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", _ascii(str(nom)).lower()).strip("-")[:40].strip("-")
    return s or "pack"


def nom_de_fichier_valide(n) -> bool:
    return (isinstance(n, str) and bool(FICHIER.match(n)) and not n.startswith(".") and n == n.strip()
            and not n.endswith(".") and n.split(".")[0].rstrip(" ").upper() not in RESERVES)


def _nom_valide(nom) -> str:
    n = " ".join(nom.split()) if isinstance(nom, str) else ""
    if not n:
        raise Refus("Donne un nom au pack.")
    if len(n) > NOM_MAX:
        raise Refus(f"Ce nom est trop long ({NOM_MAX} caractères au plus).")
    return n


# ---------- lecture ----------

def dossier(racine, pid) -> Path:
    """dossier d'un pack de la bibliothèque (jamais hors de `racine`) ; FileNotFoundError s'il n'existe pas"""
    if not isinstance(pid, str) or pid == AUCUN or not ID.match(pid):
        raise FileNotFoundError("Ce pack est introuvable.")
    d = Path(racine) / pid
    if not (d / "pack.json").is_file():
        raise FileNotFoundError("Ce pack est introuvable.")
    return d


def existe(racine, pid) -> bool:
    if pid == AUCUN:
        return True
    try:
        dossier(racine, pid)
        return True
    except FileNotFoundError:
        return False


def _brut(d: Path) -> dict:
    p = lire_json(d / "pack.json", None)
    if not isinstance(p, dict) or not isinstance(p.get("reglages"), dict):
        raise FileNotFoundError(f"Le pack « {d.name} » est abîmé (pack.json illisible).")
    return p


def lire(racine, pid) -> dict:
    """{id, nom, integre, reglages (complets), fichiers (noms des fichiers du dossier du pack)}"""
    if pid == AUCUN:
        return {"id": AUCUN, "nom": "Aucun pack", "integre": True, "reglages": deepcopy(AUCUN_REGLAGES), "fichiers": []}
    d = dossier(racine, pid)
    p = _brut(d)
    fichiers = sorted((f.name for f in d.iterdir() if f.is_file() and f.name != "pack.json"
                       and not f.name.startswith(".")), key=str.casefold)
    return {"id": pid, "nom": str(p.get("nom") or pid), "integre": False, "reglages": fusion(NEUTRE, p["reglages"]),
            "fichiers": fichiers}


def _nettoyer(r: Path):
    """dossiers cachés laissés par une création ou une suppression interrompue, vieux de plus d'une heure (un pack en
    cours de création n'est jamais touché)"""
    limite = time.time() - CACHES_PERIMES
    for d in r.iterdir():
        if d.name.startswith((".tmp-", ".corbeille-")) and d.is_dir():
            try:
                if d.stat().st_mtime < limite:
                    shutil.rmtree(d, ignore_errors=True)
            except OSError:
                continue


def lister(racine) -> list[dict]:
    """packs de la bibliothèque par nom, puis « Aucun pack » ; un pack abîmé est ignoré"""
    r = Path(racine)
    if r.is_dir():
        _nettoyer(r)
    out = []
    for d in (sorted(r.iterdir()) if r.is_dir() else []):
        if d.is_dir() and ID.match(d.name) and d.name != AUCUN:
            try:
                p = lire(r, d.name)
            except FileNotFoundError:
                continue
            out.append({"id": p["id"], "nom": p["nom"], "integre": False})
    out.sort(key=lambda p: p["nom"].casefold())
    return out + [{"id": AUCUN, "nom": "Aucun pack", "integre": True}]


def _livres(sous: str, exts) -> list[str]:
    d = MOTEUR / sous
    return [f.name for f in d.iterdir() if f.is_file() and f.suffix.lower() in exts] if d.is_dir() else []


def disponibles_avec(noms) -> dict:
    """fichiers utilisables par un pack qui contient `noms` : les siens + ceux livrés avec le moteur"""
    noms = [n for n in noms if isinstance(n, str)]

    def du_pack(exts):
        return [n for n in noms if Path(n).suffix.lower() in exts]
    return {"logo": sorted(du_pack(EXT_LOGO), key=str.casefold),
            "police": sorted(set(du_pack(EXT_POLICE)) | set(_livres("fonts", EXT_POLICE)), key=str.casefold),
            "musique": sorted(set(du_pack(EXT_MUSIQUE)) | set(_livres("assets/musique", EXT_MUSIQUE)),
                              key=str.casefold)}


def disponibles(racine, pid) -> dict:
    return disponibles_avec(lire(racine, pid)["fichiers"])


def chemin_fichier(racine, pid, nom) -> Path | None:
    """fichier `nom` d'un pack : dans son dossier, sinon parmi ceux livrés avec le moteur ; chemin absolu"""
    if not nom_de_fichier_valide(nom) or not isinstance(pid, str) or (pid != AUCUN and not ID.match(pid)):
        return None
    if pid != AUCUN:
        f = Path(racine) / pid / nom
        if f.is_file():
            return Path(os.path.abspath(f))
    ext = Path(nom).suffix.lower()
    for sous, exts in LIVRES:
        if ext in exts and (MOTEUR / sous / nom).is_file():
            return MOTEUR / sous / nom
    return None


def _references(r: dict) -> list[str]:
    """fichiers réellement utilisés au rendu"""
    out = [r["sous_titres"]["police"], r["police_accent"], r["musique"]["fichier"]]
    if r.get("logo") and r.get("logo_fichier"):
        out.append(r["logo_fichier"])
    return [x for x in out if isinstance(x, str)]


def empreinte_pack(racine, pid) -> str:
    """empreinte du contenu, sans le nom : réglages sous forme canonique (seulement ce qui diffère de la base figée
    NEUTRE_V1, voir reglages.py : un réglage ajouté au neutre avec un défaut sans effet sur le rendu ne la change pas)
    + contenu des fichiers du pack utilisés ; en mémoire tant que rien ne change dans le dossier du pack (date et
    taille des fichiers)"""
    if pid == AUCUN:
        return empreinte({"aucun": forme_canonique(AUCUN_REGLAGES)})
    d = dossier(racine, pid)
    sig = tuple((f.name, f.stat().st_mtime_ns, f.stat().st_size) for f in sorted(d.iterdir()) if f.is_file())
    cle = (os.path.abspath(d), sig)
    if cle not in _EMPREINTES:
        r = lire(racine, pid)["reglages"]
        fichiers = {n: hashlib.sha256((d / n).read_bytes()).hexdigest()[:16]
                    for n in sorted(set(_references(r))) if (d / n).is_file()}
        _EMPREINTES[cle] = empreinte({"reglages": forme_canonique(r), "fichiers": fichiers})
    return _EMPREINTES[cle]


# ---------- écriture ----------

ESSAIS, PAUSE = 30, 0.1  # ~3 s de réessais quand Windows bloque un renommage un instant (comme ecrire_json_atomique)


def _preparer(racine: Path, contenu: dict, fichiers: dict) -> Path:
    """pack complet dans un dossier caché (à poser ensuite d'un coup avec _poser)"""
    tmp = racine / f".tmp-{uuid.uuid4().hex}"
    tmp.mkdir(parents=True)
    try:
        for nom, src in fichiers.items():
            (tmp / nom).write_bytes(src if isinstance(src, bytes) else Path(src).read_bytes())
        ecrire_json_atomique(tmp / "pack.json", contenu)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return tmp


def _poser(tmp: Path, cible: Path) -> bool:
    """renomme le dossier préparé en `cible` ; False si `cible` existe (autre processus, autre pack au même id).
    Un échec alors que `cible` n'existe pas (Windows : antivirus, indexation) est réessayé, puis l'OSError remonte."""
    for i in range(ESSAIS):
        try:
            os.rename(tmp, cible)
            return True
        except OSError:
            if cible.exists():
                return False
            if i == ESSAIS - 1:
                raise
            time.sleep(PAUSE)
    return False


def _ecrire_dossier(racine: Path, pid: str, contenu: dict, fichiers: dict) -> bool:
    """prépare le pack dans un dossier caché puis le renomme d'un coup ; False si `pid` est déjà pris ; OSError si
    le renommage échoue durablement"""
    tmp = _preparer(racine, contenu, fichiers)
    try:
        return _poser(tmp, racine / pid)
    finally:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)


def ecrire_nouveau_pack(racine, nom: str, reglages: dict, fichiers: dict) -> str:
    """nouveau pack (id libre tiré du nom) ; fichiers : {nom: octets ou chemin source}, recopiés une seule fois même
    si l'id visé est pris entre-temps"""
    racine = Path(racine)
    racine.mkdir(parents=True, exist_ok=True)
    base = slug(nom)
    tmp = _preparer(racine, {"nom": nom, "format": FORMAT, "reglages": reglages}, fichiers)
    try:
        for i in range(1, 1000):
            pid = base if i == 1 else f"{base}-{i}"
            if pid == AUCUN or (racine / pid).exists():
                continue
            if _poser(tmp, racine / pid):
                return pid
    except OSError:
        raise Refus("Impossible de créer ce pack pour l'instant (dossier bloqué). Réessaie.") from None
    finally:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
    raise Refus("Impossible de créer ce pack. Réessaie.")


def _nom_pris(racine, nom: str, sauf=None) -> bool:
    return any(p["nom"].casefold() == nom.casefold() and p["id"] != sauf for p in lister(racine))


def nom_libre(racine, nom) -> str:
    """`nom`, ou « nom 2 », « nom 3 »… s'il est déjà pris (import d'un pack)"""
    base = " ".join(str(nom or "").split())[:NOM_MAX] or "Pack importé"
    if not _nom_pris(racine, base):
        return base
    for i in range(2, 1000):
        n = f"{base[:NOM_MAX - len(str(i)) - 1]} {i}"
        if not _nom_pris(racine, n):
            return n
    raise Refus("Impossible de trouver un nom libre pour ce pack.")


def creer(racine, nom, depuis=None) -> str:
    """nouveau pack : copie de `depuis` (réglages et fichiers), sinon réglages du neutre"""
    nom = _nom_valide(nom)
    if _nom_pris(racine, nom):
        raise Refus("Un pack porte déjà ce nom : choisis-en un autre.")
    if depuis:
        src = lire(racine, depuis)
        fichiers = {} if src["integre"] else {f: Path(racine) / depuis / f for f in src["fichiers"]}
        reglages = src["reglages"]
    else:
        reglages, fichiers = deepcopy(NEUTRE), {}
    return ecrire_nouveau_pack(racine, nom, reglages, fichiers)


def renommer(racine, pid, nom):
    if pid == AUCUN:
        raise Refus(f"{INTEGRE} : il ne se renomme pas.")
    d = dossier(racine, pid)
    nom = _nom_valide(nom)
    if _nom_pris(racine, nom, sauf=pid):
        raise Refus("Un pack porte déjà ce nom : choisis-en un autre.")
    with _verrou(racine, pid):
        p = _brut(d)
        p["nom"] = nom
        ecrire_json_atomique(d / "pack.json", p)


def enregistrer(racine, pid, reglages) -> dict:
    """valide et enregistre les réglages ; renvoie les réglages complets"""
    if pid == AUCUN:
        raise Refus(f"{INTEGRE} : duplique-le pour le modifier.")
    d = dossier(racine, pid)
    with _verrou(racine, pid):
        r = valider(reglages, disponibles(racine, pid))
        p = _brut(d)
        p.update(reglages=r, format=FORMAT)
        ecrire_json_atomique(d / "pack.json", p)
    return r


def _cite(noms: list[str]) -> str:
    n = [f"« {x} »" for x in noms]
    return n[0] if len(n) == 1 else ", ".join(n[:-1]) + " et " + n[-1]


def supprimer(racine, pid, utilisateurs: list[str]):
    """refusé si des podcasts l'utilisent (leurs titres dans le message)"""
    if pid == AUCUN:
        raise Refus(f"{INTEGRE} : il ne se supprime pas.")
    d = dossier(racine, pid)
    if utilisateurs:
        un = len(utilisateurs) == 1
        raise Refus(f"Ce pack est utilisé par {_cite(utilisateurs)} : choisis un autre pack pour "
                    f"{'ce podcast' if un else 'ces podcasts'} avant de le supprimer.")
    corbeille = Path(racine) / f".corbeille-{uuid.uuid4().hex}"
    try:
        os.rename(d, corbeille)
    except OSError:
        raise Refus("Ce pack est en cours d'utilisation : réessaie dans un instant.") from None
    shutil.rmtree(corbeille, ignore_errors=True)


def verifier_contenu(nom: str, octets: bytes):
    """Refus si le contenu ne correspond pas au type annoncé par l'extension : logo PNG lisible, police lisible
    (ajout d'un fichier, import d'un pack) ; la musique n'est pas vérifiée ici"""
    ext = Path(nom).suffix.lower()
    if ext in (*EXT_LOGO, *EXT_POLICE) and not octets:
        raise Refus(f"Le fichier « {nom} » est vide.")
    if ext in EXT_LOGO:
        try:
            if not octets.startswith(b"\x89PNG\r\n\x1a\n"):
                raise OSError
            Image.open(io.BytesIO(octets)).verify()
        except Exception:
            raise Refus(f"Cette image n'est pas un PNG lisible (« {nom} »).") from None
    elif ext in EXT_POLICE:
        try:
            ImageFont.truetype(io.BytesIO(octets), 20)
        except Exception:
            raise Refus(f"Cette police est illisible (« {nom} ») : choisis un fichier .ttf ou .otf.") from None


def ajouter_fichier(racine, pid, nom, octets: bytes) -> str:
    """ajoute (ou remplace) un logo .png ou une police .ttf / .otf dans le dossier du pack ; renvoie son nom"""
    if pid == AUCUN:
        raise Refus(f"{INTEGRE} : duplique-le pour le modifier.")
    d = dossier(racine, pid)
    nom = PurePosixPath(str(nom or "").replace("\\", "/")).name.strip()  # le navigateur peut donner un chemin
    ext = Path(nom).suffix.lower()
    if ext not in EXT_LOGO + EXT_POLICE:
        raise Refus("Ajoute un logo (.png) ou une police (.ttf, .otf).")
    if not nom_de_fichier_valide(nom):
        raise Refus("Ce nom de fichier n'est pas accepté : renomme le fichier (lettres, chiffres, espaces).")
    if not octets:
        raise Refus("Ce fichier est vide.")
    verifier_contenu(nom, octets)
    with _verrou(racine, pid):
        # même nom à la casse près (« LOGO.png » pour « logo.png ») : remplace ce fichier sous son nom actuel, que les
        # réglages désignent déjà (et un seul fichier, même sur un disque qui distingue la casse)
        nom = next((f.name for f in d.iterdir() if f.is_file() and f.name.casefold() == nom.casefold()), nom)
        tmp = d / f".{uuid.uuid4().hex}.tmp"
        try:
            tmp.write_bytes(octets)
            os.replace(tmp, d / nom)
        except OSError:  # Windows : fichier ouvert ailleurs (aperçu, fabrication d'un short)
            raise Refus(f"Le fichier « {nom} » est en cours d'utilisation : réessaie dans un instant.") from None
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
    return nom


# ---------- pour le moteur ----------

def spec_moteur(racine, pid, reglages=None) -> dict:
    """réglages prêts pour vertical.py : valeurs du neutre pour ce qui manque, chemins ABSOLUS des fichiers ;
    `reglages` : ceux en cours d'édition (déjà validés), sinon ceux enregistrés"""
    if not existe(racine, pid):  # fabrication d'un short dont le pack a disparu : on dit lequel
        raise FileNotFoundError(f"Le pack « {pid} » est introuvable.")
    p = lire(racine, pid)
    r = fusion(NEUTRE, p["reglages"] if reglages is None else reglages)

    def absolu(nom) -> str:
        f = chemin_fichier(racine, pid, nom)
        if f is None:
            raise FileNotFoundError(f"Le fichier « {nom} » du pack « {p['nom']} » est introuvable.")
        return str(f)
    s = deepcopy(r)
    s["sous_titres"]["police"] = absolu(r["sous_titres"]["police"])
    s["police_accent"] = absolu(r["police_accent"])
    s["musique"]["fichier"] = absolu(r["musique"]["fichier"])
    if r["logo"] and r["logo_fichier"]:
        s["logo_fichier"] = absolu(r["logo_fichier"])
    else:
        s["logo"] = False
        s.pop("logo_fichier", None)
    return s


# ---------- dernier pack utilisé (pré-rempli à la création d'un podcast) ----------

def dernier(racine) -> str | None:
    p = lire_json(Path(racine) / ".dernier.json", {})
    pid = p.get("pack") if isinstance(p, dict) else None
    return pid if isinstance(pid, str) and existe(racine, pid) else None


def noter_dernier(racine, pid):
    Path(racine).mkdir(parents=True, exist_ok=True)
    ecrire_json_atomique(Path(racine) / ".dernier.json", {"pack": pid})


# ---------- migration des presets (une fois) ----------

NOMS_PRESETS = {"neutre": "Neutre", "craie": "Craie"}
LOGO_MOTEUR = "assets/logo/logo blanc.png"  # logo par défaut de vertical.py (relatif au dossier du moteur)


def _depuis_preset(preset: dict, moteur: Path) -> tuple[dict, dict]:
    """réglages d'un preset avec ses fichiers désignés par leur nom seul, et ces fichiers à recopier dans le pack"""
    r = deepcopy(preset)
    r.pop("_", None)  # la note du preset parle de projet.json : elle n'a plus cours
    fichiers, noms = {}, {}  # noms : fichier source -> nom dans le pack

    def reprendre(chemin):
        if not isinstance(chemin, str) or not chemin:
            return chemin
        src = Path(chemin) if Path(chemin).is_absolute() else Path(moteur) / chemin
        if not src.is_file():
            return src.name
        cle = os.path.normcase(os.path.abspath(src))
        if cle not in noms:  # deux fichiers différents de même nom : le second devient « nom-2 »
            nom, i = src.name, 1
            while nom.casefold() in {n.casefold() for n in fichiers}:
                i += 1
                nom = f"{src.stem}-{i}{src.suffix}"
            noms[cle], fichiers[nom] = nom, src
        return noms[cle]
    if r.get("logo", True) is not False and not r.get("logo_fichier"):
        # le moteur affichait alors son logo par défaut (« logo » absent valait oui) : recopié dans le pack
        r["logo"], r["logo_fichier"] = True, LOGO_MOTEUR
    for k in ("logo_fichier", "police_accent"):
        if k in r:
            r[k] = reprendre(r[k])
    if isinstance(r.get("sous_titres"), dict) and "police" in r["sous_titres"]:
        r["sous_titres"]["police"] = reprendre(r["sous_titres"]["police"])
    if isinstance(r.get("musique"), dict) and "fichier" in r["musique"]:
        r["musique"]["fichier"] = reprendre(r["musique"]["fichier"])
    return r, fichiers


def migrer(racine, presets, moteur=MOTEUR) -> list[str]:
    """au premier lancement : chaque presets/<nom>.json devient le pack packs/<slug>/ (logo, polices et musique
    recopiés dans son dossier) ; rien n'est supprimé de presets/, un pack déjà là n'est pas remplacé. Une seule fois
    (packs/.migration.json, écrit seulement si chaque preset a son pack) : un pack supprimé ensuite ne revient pas ;
    un pack qui n'a pas pu être créé (dossier bloqué) l'est au lancement suivant."""
    racine = Path(racine)
    marque = racine / ".migration.json"
    if marque.exists():
        return []
    racine.mkdir(parents=True, exist_ok=True)
    crees, complete = [], True
    for f in (sorted(Path(presets).glob("*.json")) if Path(presets).is_dir() else []):
        pid = slug(f.stem)
        preset = lire_json(f, None)
        if pid == AUCUN or (racine / pid).exists() or not isinstance(preset, dict):
            continue
        reglages, fichiers = _depuis_preset(preset, Path(moteur))
        nom = NOMS_PRESETS.get(pid) or " ".join(f.stem.replace("_", " ").replace("-", " ").split()).title()[:NOM_MAX]
        try:
            if _ecrire_dossier(racine, pid, {"nom": nom or pid, "format": FORMAT, "reglages": reglages}, fichiers):
                crees.append(pid)
        except OSError:
            complete = False
    if complete:
        # empreinte de chaque pack issu d'un preset, tel que migré : la reprise d'un projet d'avant les packs la
        # retient comme « pack d'origine » (ses shorts ont été fabriqués avec ce preset), même si le pack a été
        # modifié avant qu'il soit repris
        empreintes = {}
        for f in (sorted(Path(presets).glob("*.json")) if Path(presets).is_dir() else []):
            try:
                empreintes[slug(f.stem)] = empreinte_pack(racine, slug(f.stem))
            except (FileNotFoundError, OSError):
                continue
        ecrire_json_atomique(marque, {"presets": crees, "empreintes": empreintes})
    return crees


def migration_finie(racine) -> bool:
    return (Path(racine) / ".migration.json").exists()


def empreinte_migree(racine, pid) -> str | None:
    """empreinte du pack `pid` au moment où il a été migré depuis son preset (None : inconnue)"""
    m = lire_json(Path(racine) / ".migration.json", {})
    h = (m.get("empreintes") or {}).get(pid) if isinstance(m, dict) and isinstance(m.get("empreintes"), dict) else None
    return h if isinstance(h, str) and h else None
