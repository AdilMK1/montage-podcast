"""Export / import d'un pack : un .zip à plat du dossier du pack (pack.json + fichiers). Marche d'un Mac à un PC :
noms de fichiers seuls, jamais de dossier ni de chemin, tout est vérifié avant d'écrire quoi que ce soit (noms,
contenu des logos et des polices). Un .zip fait par le Finder (dossier du pack compressé, fichiers __MACOSX /
.DS_Store) ou l'Explorateur Windows (Thumbs.db, desktop.ini) est accepté : ces fichiers du système sont ignorés."""
import io
import json
import zipfile
import zlib

from app.projet.regles import Refus

from . import bibliotheque as B
from .reglages import valider

TAILLE_MAX = 100 * 1024 * 1024
SYSTEME = {".ds_store", "thumbs.db", "desktop.ini"}  # ajoutés par le Finder ou l'Explorateur, ignorés
ABIME = "Ce fichier .zip est abîmé ou protégé : impossible de lire le pack."
# lecture d'une entrée : CRC faux, zip chiffré, compression inconnue, données tronquées
ERREURS_LECTURE = (zipfile.BadZipFile, RuntimeError, NotImplementedError, zlib.error, EOFError, OSError)


def exporter(racine, pid) -> bytes:
    """pack.json + les fichiers que l'import accepte (un Thumbs.db ou un fichier ajouté à la main n'est pas exporté)"""
    if pid == B.AUCUN:
        raise Refus(f"{B.INTEGRE} : rien à exporter.")
    d = B.dossier(racine, pid)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(d.iterdir()):
            if f.is_file() and (f.name == "pack.json" or B.nom_de_fichier_valide(f.name)):
                z.write(f, f.name)
    return buf.getvalue()


def _dossier_valide(n: str) -> bool:
    return bool(n) and n not in (".", "..") and not n.startswith(".") and "\\" not in n


def _du_systeme(nom: str) -> bool:
    return nom.startswith("__MACOSX/") or nom.rsplit("/", 1)[-1].casefold() in SYSTEME


def _entrees(z: zipfile.ZipFile) -> dict:
    """{nom du fichier: info zip}, sans le dossier englobant éventuel ; Refus au premier nom non autorisé"""
    gardes = [i for i in z.infolist() if not i.is_dir() and not _du_systeme(i.filename)]
    parts = [i.filename.split("/") for i in gardes]
    prefixe = ""
    if parts and all(len(p) == 2 for p in parts) and len({p[0] for p in parts}) == 1 and _dossier_valide(parts[0][0]):
        prefixe = parts[0][0] + "/"
    out = {}
    for i in gardes:
        n = i.filename[len(prefixe):]
        if n != "pack.json" and not B.nom_de_fichier_valide(n):
            raise Refus(f"Ce pack contient un fichier non autorisé (« {n} ») : import refusé.")
        if any(n.casefold() == x.casefold() for x in out):  # le même fichier sous Windows et sur Mac
            raise Refus(f"Ce pack contient deux fois le fichier « {n} » : import refusé.")
        out[n] = i
    return out


def _lire(z: zipfile.ZipFile, i: zipfile.ZipInfo) -> bytes:
    try:
        return z.read(i)
    except ERREURS_LECTURE:
        raise Refus(ABIME) from None


def importer(racine, octets: bytes) -> str:
    """ajoute le pack à la bibliothèque (nom « X 2 » s'il est déjà pris) ; renvoie son id"""
    try:
        z = zipfile.ZipFile(io.BytesIO(octets))
    except (zipfile.BadZipFile, ValueError, EOFError, OSError):
        raise Refus("Ce fichier n'est pas un pack (.zip) lisible.") from None
    with z:
        entrees = _entrees(z)
        if "pack.json" not in entrees:
            raise Refus("Ce fichier .zip ne contient pas de pack (pack.json manquant).")
        if sum(i.file_size for i in entrees.values()) > TAILLE_MAX:
            raise Refus("Ce pack est trop gros (100 Mo au plus).")
        try:
            data = json.loads(_lire(z, entrees["pack.json"]).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise Refus("Le fichier pack.json de ce pack est illisible.") from None
        if not isinstance(data, dict) or not isinstance(data.get("reglages"), dict):
            raise Refus("Le fichier pack.json de ce pack est illisible.")
        fichiers = {n: _lire(z, i) for n, i in entrees.items() if n != "pack.json"}
    if sum(len(b) for b in fichiers.values()) > TAILLE_MAX:
        raise Refus("Ce pack est trop gros (100 Mo au plus).")
    for n, b in fichiers.items():
        B.verifier_contenu(n, b)
    reglages = valider(data["reglages"], B.disponibles_avec(fichiers))
    return B.ecrire_nouveau_pack(racine, B.nom_libre(racine, data.get("nom")), reglages, fichiers)
