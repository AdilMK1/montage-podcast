"""Ce que toutes les tâches partagent : chemins de l'app, configuration, profil de la machine, lancement d'un
script du moteur avec progression, création des tâches qui suivent."""
import re
import subprocess
import sys
from pathlib import Path

from app.fichiers import lire_json
from app.packs.bibliotheque import migrer as migrer_packs
from app.ressources.profil import profil as _profil
from app.taches import file
from app.taches.atelier import ErreurTache
from app.taches.modele import FINIS

RACINE = Path(__file__).resolve().parents[2]
MOTEUR = RACINE / "moteur"
PRESETS = RACINE / "presets"
PACKS = RACINE / "packs"
CONSIGNES = RACINE / "CONSIGNES IA.md"
PY = sys.executable


def config() -> dict:
    return lire_json(RACINE / "config.json", {}) or {}


def packs() -> Path:
    """bibliothèque des packs de l'app ; migrée depuis presets/ au premier appel (serveur ou atelier)"""
    migrer_packs(PACKS, PRESETS)
    return PACKS


def profil() -> dict:
    return _profil(RACINE / ".cache" / "profil.json")


def duree(f) -> float:
    """durée d'un média en secondes (0 si illisible)"""
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)],
                           capture_output=True, text=True, timeout=20)
        return float(r.stdout.strip() or 0)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return 0.0


def env_moteur(d) -> dict:
    d = Path(d)
    (d / "tmp").mkdir(exist_ok=True)
    return {"CRAIE_TRAVAIL": str(d.parent), "TMPDIR": str(d / "tmp"), "PYTHONUNBUFFERED": "1"}


# erreurs connues d'un script du moteur : motif cherché dans ce que le script a écrit au journal de la tâche
# -> message en français simple et actions proposées (au lieu du message générique de l'étape)
ERREURS_CONNUES = [
    (r"need at least one array to concatenate",
     "Un micro n'a aucun passage de parole à lui : les micros ne sont pas un micro par personne (même son sur deux "
     "micros, ou micro silencieux). Récupère les pistes séparées de chaque micro (export de Reaper ou de la table "
     "de mixage), puis crée le podcast avec ces fichiers.", ["rapport"]),
    (r"No space left on device",
     "Le disque est plein. Libère de la place, puis réessaie.", ["liberer_disque", "reessayer"]),
    (r"No such file or directory: '/Volumes/",
     "Un fichier des rushes est introuvable : le disque qui les contient est peut-être débranché. Rebranche-le, "
     "puis réessaie.", ["reessayer", "rapport"]),
]


def erreur_connue(journal: str) -> tuple[str, list[str]] | None:
    for motif, message, actions in ERREURS_CONNUES:
        if re.search(motif, journal):
            return message, list(actions)
    return None


def _taille(f) -> int:
    try:
        return Path(f).stat().st_size
    except (OSError, TypeError):
        return 0


def _lire_depuis(f, debut: int) -> str:
    try:
        with open(f, "rb") as j:
            j.seek(debut)
            return j.read().decode("utf-8", errors="replace")
    except (OSError, TypeError):
        return ""


def rushes_manquants(d) -> list[str]:
    """rushes (caméras, micros) du projet introuvables : disque débranché, dossier déplacé"""
    from .session import chemin_rush  # import local : session importe contexte
    pj = lire_json(Path(d) / "projet.json", {}) or {}
    tous = list((pj.get("mics") or {}).values())
    for v in (pj.get("cams") or {}).values():
        tous += [v] if isinstance(v, str) else list(v or [])
    return [x for x in (chemin_rush(y) for y in tous if isinstance(y, str)) if not Path(x).exists()]


def message_rushes(manquants: list[str]) -> str:
    """« branche le disque X » : le volume (Mac /Volumes/X, Windows X:) du premier rush manquant"""
    p = Path(manquants[0])
    m = re.match(r"^/Volumes/([^/]+)/", p.as_posix())
    if m and not Path("/Volumes", m.group(1)).exists():
        return f"Les rushes de ce podcast sont sur le disque « {m.group(1)} », qui n'est pas branché. Branche-le, puis Réessayer."
    if re.match(r"^[A-Za-z]:", str(p)) and not Path(str(p)[:3]).exists():
        return f"Les rushes de ce podcast sont sur le disque {str(p)[:2]}, qui n'est pas branché. Branche-le, puis Réessayer."
    n = len(manquants)
    return (f"{n} rush{'es' if n > 1 else ''} de ce podcast {'sont introuvables' if n > 1 else 'est introuvable'} "
            f"(par exemple « {p.name} » dans « {p.parent} »). Remets-le{'s' if n > 1 else ''} à sa place, puis Réessayer.")


def erreur_rushes(d):
    """lève une ErreurTache claire si des rushes manquent (appelée quand une étape a échoué)"""
    manquants = rushes_manquants(d)
    if manquants:
        raise ErreurTache(message_rushes(manquants), ["reessayer"])


def lancer_script(ctx, script: str, *args, texte: str | None = None, debut: float = 0.0, fin: float = 1.0,
                  env: dict | None = None):
    """lance moteur/<script> ; la jauge va de debut à fin ; échec -> ErreurTache avec le message d'une erreur
    connue trouvée dans ce que le script vient d'écrire au journal, sinon avec le texte de l'étape"""
    if texte:
        ctx.progres(debut, texte)
    d = Path(ctx.projet_dir)
    journal = getattr(ctx, "journal", None)
    avant = _taille(journal)
    rc = ctx.executer([PY, MOTEUR / script, *args], debut=debut, fin=fin, cwd=str(MOTEUR),
                      env={**env_moteur(d), **(env or {})},
                      fichier_progres=d / "tmp" / f"progres_{ctx.tache['id']}.txt")
    if rc:
        erreur_rushes(d)  # disque des rushes débranché : la vraie raison, avant toute autre
        connue = erreur_connue(_lire_depuis(journal, avant))
        if connue:
            raise ErreurTache(*connue)
        raise ErreurTache(f"L'étape « {texte or script} » a échoué. Réessaie ; si ça recommence, envoie un rapport.",
                          ["reessayer", "rapport"])


def creer_si_absente(d, type_: str, params: dict | None = None):
    """crée la tâche sauf si une tâche de ce type est déjà en attente ou en cours sur ce projet"""
    d = Path(d)
    for f in sorted((d / "taches").glob("*.json")) if (d / "taches").exists() else []:
        t = lire_json(f)
        if isinstance(t, dict) and t.get("type") == type_ and t.get("statut") not in FINIS:
            return None
    return file.creer(d, type_, params)
