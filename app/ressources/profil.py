"""Profil de la machine, mesuré une fois puis gardé en cache (re-mesuré si ffmpeg ou la machine change).

Les encodeurs matériels sont ESSAYÉS (une image encodée), pas seulement listés : ffmpeg peut lister un encodeur
que la machine ne sait pas utiliser (pas de carte NVIDIA, pilote absent…).
"""
import os
import platform
import subprocess
from pathlib import Path

import psutil

from app.fichiers import ecrire_json_atomique, lire_json

CANDIDATS = ["h264_videotoolbox", "h264_nvenc", "h264_qsv", "h264_amf"]


def _sans_fenetre() -> dict:
    """sous Windows, une sonde ne doit pas faire clignoter une console"""
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def version_ffmpeg() -> str | None:
    try:
        r = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=10, **_sans_fenetre())
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.splitlines()[0] if r.returncode == 0 and r.stdout else None


def encodeur_marche(nom: str, executer=subprocess.run) -> bool:
    try:
        r = executer(["ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i", "color=black:s=256x256:d=0.2",
                      "-frames:v", "1", "-c:v", nom, "-pix_fmt", "yuv420p", "-f", "null", "-"],  # comme l'usage réel
                     capture_output=True, timeout=20, **_sans_fenetre())
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0


def mesurer(executer=subprocess.run) -> dict:
    return {
        "systeme": platform.system(),
        "machine": platform.machine(),
        "coeurs": psutil.cpu_count(logical=False) or os.cpu_count() or 1,
        "coeurs_logiques": psutil.cpu_count() or os.cpu_count() or 1,
        "memoire_go": round(psutil.virtual_memory().total / 1e9, 1),
        "ffmpeg": version_ffmpeg(),
        "encodeurs": [e for e in CANDIDATS if encodeur_marche(e, executer)],
    }


def profil(cache, executer=subprocess.run) -> dict:
    cache = Path(cache)
    p = lire_json(cache)
    if isinstance(p, dict) and p.get("ffmpeg") == version_ffmpeg() and p.get("machine") == platform.machine():
        return p
    p = mesurer(executer)
    cache.parent.mkdir(parents=True, exist_ok=True)
    ecrire_json_atomique(cache, p)
    return p
