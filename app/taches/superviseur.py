"""Côté serveur : savoir si l'atelier tourne, le (re)démarrer sinon.

L'atelier écrit un battement (pid + heure) à chaque tour ; plus de battement depuis `delai` secondes, ou pid mort,
= atelier arrêté. Il est lancé dans son propre groupe de processus (sans fenêtre sous Windows), en priorité
normale, journal dans .atelier/. Deux lancements rapprochés sont sans danger : le second atelier ne prend pas
le verrou d'instance et s'arrête aussitôt.
"""
import os
import subprocess
import sys
import time
from pathlib import Path

import psutil

from app.fichiers import lire_json


def _pid_vivant(pid) -> bool:
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE  # mort mais pas encore ramassé = mort
    except (psutil.Error, TypeError, ValueError):
        return False


def atelier_vivant(battement, maintenant: float | None = None, delai: float = 10.0) -> bool:
    b = lire_json(battement)
    if not isinstance(b, dict) or "pid" not in b:
        return False
    if (time.time() if maintenant is None else maintenant) - b.get("t", 0) > delai:
        return False
    return _pid_vivant(b["pid"])


def demarrer_atelier(racine_app, racine_projets, battement, env: dict | None = None) -> subprocess.Popen:
    battement = Path(battement)
    battement.parent.mkdir(parents=True, exist_ok=True)
    groupe = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
              if os.name == "nt" else {"start_new_session": True})
    with open(battement.parent / "atelier.log", "ab") as journal:  # l'atelier garde sa propre copie du fichier
        return subprocess.Popen([sys.executable, "-m", "app.taches.atelier", "--racine", str(racine_projets),
                                 "--battement", str(battement)], cwd=str(racine_app), stdin=subprocess.DEVNULL,
                                stdout=journal, stderr=subprocess.STDOUT, env={**os.environ, **(env or {})}, **groupe)


def assurer_atelier(racine_app, racine_projets, battement, env: dict | None = None,
                    delai: float = 10.0) -> subprocess.Popen | None:
    """démarre l'atelier s'il ne tourne pas ; renvoie le processus lancé, ou None s'il tournait déjà"""
    if atelier_vivant(battement, delai=delai):
        return None
    return demarrer_atelier(racine_app, racine_projets, battement, env)
