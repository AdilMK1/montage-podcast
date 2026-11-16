"""Fichiers des tâches. Le serveur CRÉE les tâches et pose des drapeaux d'annulation ; seul l'atelier modifie
ensuite un fichier de tâche (aucune course entre processus)."""
from pathlib import Path

from app.fichiers import ecrire_json_atomique, lire_json

from .modele import nouvelle_tache


def dossier(projet_dir) -> Path:
    return Path(projet_dir) / "taches"


def chemin(projet_dir, tid: str) -> Path:
    return dossier(projet_dir) / f"{tid}.json"


def creer(projet_dir, type_: str, params: dict | None = None, maintenant: float | None = None) -> dict:
    dossier(projet_dir).mkdir(parents=True, exist_ok=True)
    t = nouvelle_tache(Path(projet_dir).name, type_, params, maintenant)
    ecrire_json_atomique(chemin(projet_dir, t["id"]), t)
    return t


def lire(projet_dir, tid: str) -> dict | None:
    return lire_json(chemin(projet_dir, tid))


def ecrire(projet_dir, t: dict):
    ecrire_json_atomique(chemin(projet_dir, t["id"]), t)


CLES = ("id", "projet", "type", "statut", "priorite", "poids", "cree", "tentatives", "morceaux_faits", "params",
        "progression")


def lister(racine_projets, signaler=None) -> list[tuple[Path, dict]]:
    """toutes les tâches complètes ; un fichier illisible ou incomplet est ignoré (signaler(fichier, raison))"""
    out = []
    for f in sorted(Path(racine_projets).glob("*/taches/*.json")):
        t = lire_json(f)
        if not isinstance(t, dict):
            raison = "illisible"
        elif manque := [k for k in CLES if k not in t]:
            raison = "clés manquantes : " + ", ".join(manque)
        else:
            out.append((f.parent.parent, t))
            continue
        if signaler is not None:
            signaler(f, raison)
    return out


def demander_annulation(projet_dir, tid: str):
    dossier(projet_dir).mkdir(parents=True, exist_ok=True)
    (dossier(projet_dir) / f"{tid}.annuler").touch()


def annulation_demandee(projet_dir, tid: str) -> bool:
    return (dossier(projet_dir) / f"{tid}.annuler").exists()


def nettoyer_annulation(projet_dir, tid: str):
    (dossier(projet_dir) / f"{tid}.annuler").unlink(missing_ok=True)
