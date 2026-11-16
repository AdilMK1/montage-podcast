"""Lecture / écriture JSON sûres, partagées par tout le code de l'app.

Écriture atomique : fichier temporaire + fsync + os.replace. Sous Windows, os.replace échoue si un autre
programme a le fichier ouvert (lecteur, antivirus) : on retente, jusqu'à ~3 s au total (30 × 100 ms).
"""
import json
import os
import time
import uuid
from pathlib import Path


def ecrire_json_atomique(chemin, obj, essais: int = 30, pause: float = 0.1):
    chemin = Path(chemin)
    tmp = chemin.with_name(f".{chemin.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        for i in range(essais):
            try:
                os.replace(tmp, chemin)
                return
            except PermissionError:
                if i == essais - 1:
                    raise
                time.sleep(pause)
    finally:
        tmp.unlink(missing_ok=True)


def lire_json(chemin, defaut=None):
    try:
        return json.loads(Path(chemin).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return defaut
