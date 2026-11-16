"""Lecture / écriture de etat.json : écriture atomique et verrou par projet.

Verrou : un fichier `.verrou` dans le dossier du projet (créé s'il manque, JAMAIS supprimé) sur lequel on prend
un verrou exclusif du système : `fcntl.flock` sur Mac / Linux, `msvcrt.locking` sous Windows. C'est le système qui
tient le verrou, pas l'existence du fichier : si le processus meurt (même tué brutalement), le système le libère
aussitôt. Pas de péremption, pas de jeton, pas de reprise à gérer.
`flock` est attaché au descripteur de fichier : deux `verrou()` du même processus (deux fils) s'excluent aussi.
Disque réseau partagé (lot futur) : la fiabilité de flock y dépend du serveur (SMB / NFS / AFP), à vérifier alors.
"""
import json
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from app.fichiers import ecrire_json_atomique

from . import modele as M
from .regles import appliquer

NOM = "etat.json"


class Occupe(Exception):
    """le projet est verrouillé par une autre opération"""


class VerrouImpossible(Exception):
    """le fichier .verrou ne peut pas être ouvert ni créé (dossier en lecture seule, disque absent...)"""


class EtatIllisible(Exception):
    """etat.json existe mais ne peut pas être lu : on ne repart jamais d'un état neuf en silence"""


def lire_etat(dossier) -> dict:
    f = Path(dossier) / NOM
    if not f.exists():
        return M.nouvel_etat()
    nom = Path(dossier).name  # le nom du projet seulement : jamais de chemin complet dans un message
    try:
        e = json.loads(f.read_text(encoding="utf-8"))
    except ValueError:
        raise EtatIllisible(f"Le fichier d'état du projet « {nom} » (etat.json) est vide ou abîmé. "
                            "Rien n'a été modifié.") from None
    v = e.get("version") if isinstance(e, dict) else None
    if type(v) is not int or v != M.VERSION:  # entier strict : ni True, ni 1.0, ni "1"
        raise EtatIllisible(f"Le fichier d'état du projet « {nom} » (etat.json) n'est pas dans le bon format "
                            f"(version {v!r}, attendue {M.VERSION}). Rien n'a été modifié.")
    e.setdefault("casting", dict(M.CASTING_MANUEL))  # projet d'avant le casting : noms donnés à la création
    e.setdefault("pack", None)  # projet d'avant les packs : repris par le serveur (app/packs/projets.py)
    e.setdefault("packs", {})
    manquantes = [k for k in M.nouvel_etat() if k not in e]
    if manquantes:
        raise EtatIllisible(f"Le fichier d'état du projet « {nom} » (etat.json) est incomplet (il manque : "
                            f"{', '.join(manquantes)}). Rien n'a été modifié.")
    return e


def ecrire_etat(dossier, etat: dict):
    ecrire_json_atomique(Path(dossier) / NOM, etat)


if sys.platform == "win32":
    import msvcrt

    def _prendre(fd) -> bool:
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)  # 1 octet ; permis même au-delà de la fin du fichier
            return True
        except OSError:  # déjà verrouillé par un autre
            return False

    def _rendre(fd):
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _prendre(fd) -> bool:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:  # déjà verrouillé par un autre
            return False

    def _rendre(fd):
        fcntl.flock(fd, fcntl.LOCK_UN)


@contextmanager
def verrou(dossier, attente: float = 10.0):
    """verrou exclusif du projet ; Occupe après `attente` secondes, VerrouImpossible tout de suite si le
    fichier .verrou ne peut pas être ouvert"""
    f = Path(dossier) / ".verrou"
    try:
        fd = os.open(f, os.O_RDWR | os.O_CREAT, 0o666)
    except OSError as x:
        raise VerrouImpossible(f"Impossible de poser le verrou du projet ({f}) : {x.strerror or x}. "
                               "Le dossier est-il en lecture seule ou le disque débranché ?") from x
    try:
        t0 = time.monotonic()
        while not _prendre(fd):
            if time.monotonic() - t0 >= attente:
                raise Occupe("Le projet est occupé par une autre opération, réessaie dans un instant.")
            time.sleep(0.02)
        try:
            yield
        finally:
            _rendre(fd)
    finally:
        os.close(fd)


def modifier(dossier, action: dict, attente: float = 10.0) -> dict:
    """applique une action sous verrou et enregistre ; lève Refus sans rien écrire"""
    with verrou(dossier, attente):
        e = appliquer(lire_etat(dossier), action)
        ecrire_etat(dossier, e)
        return e
