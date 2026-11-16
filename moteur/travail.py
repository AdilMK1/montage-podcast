"""Dossier de travail d'un projet pour les scripts du moteur.

CRAIE_TRAVAIL = dossier qui contient les projets (l'app le donne : marche aussi sous Windows, sans lien).
Sinon : work/ à côté du script tel qu'il a été lancé (sys.argv[0], liens NON résolus : le labo, qui lance le
moteur par des liens, garde son propre work/).
"""
import os
import sys
from pathlib import Path


def racine() -> Path:
    v = os.environ.get("CRAIE_TRAVAIL")
    return Path(v) if v else Path(os.path.abspath(sys.argv[0])).parent / "work"


def dossier(nom: str) -> Path:
    return racine() / nom


def lien(src, dst: Path) -> None:
    """dst désigne le fichier src : lien symbolique (Mac), sinon lien dur (Windows sans droits d'admin, même disque),
    sinon copie"""
    src = Path(src).resolve()
    try:
        dst.symlink_to(src)
        return
    except OSError:
        pass
    try:
        os.link(src, dst)
    except OSError:
        import shutil
        shutil.copyfile(src, dst)


def chemin_filtre(p) -> str:
    """chemin à écrire dans un graphe de filtres ffmpeg (movie=...) : entre apostrophes (virgules, crochets, espaces
    protégés), « : » du lecteur Windows échappé pour l'option, comme la LUT de couleur.py"""
    s = Path(p).as_posix().replace("'", r"\'").replace(":", r"\:")
    return f"'{s}'"
