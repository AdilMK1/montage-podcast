"""Étape 1 : extrait l'audio de chaque source en WAV mono 8 kHz (cache pour la synchro).

Usage : python extract.py sessions/exemple2.json
"""
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import travail

SR = 8000


def extract(src: str, dst: Path) -> str:
    if dst.exists() and dst.stat().st_size > 0:
        return f"déjà en cache : {dst.name}"
    tmp = dst.with_suffix(".part.wav")
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", src, "-vn", "-map", "0:a:0",
           "-ac", "1", "-ar", str(SR), "-c:a", "pcm_s16le", str(tmp)]
    subprocess.run(cmd, check=True)
    tmp.rename(dst)
    return f"ok : {dst.name}"


def cam_files(cfg: dict) -> list[tuple[str, str, str]]:
    """(cam, clé du fichier, chemin) : une cam coupée en plusieurs fichiers donne CAM_1, CAM_2…"""
    out = []
    for k, p in cfg["cams"].items():
        if isinstance(p, str):
            out.append((k, k, p))
        else:
            out += [(k, f"{k}_{i + 1}", q) for i, q in enumerate(p)]
    return out


def main(cfg_path: str) -> None:
    cfg = json.loads(Path(cfg_path).read_text())
    work = travail.dossier(cfg["name"])
    work.mkdir(parents=True, exist_ok=True)
    jobs = [(p, work / f"mic_{k}.wav") for k, p in cfg["mics"].items()]
    jobs += [(p, work / f"cam_{f}.wav") for _, f, p in cam_files(cfg)]
    # Disques différents en parallèle, mais un seul fichier à la fois par disque
    # (lire plusieurs gros rushs d'un même disque dur en même temps le fait ramer).
    drives: dict[str, list] = {}
    for j in jobs:
        parts = Path(j[0]).parts
        drives.setdefault(parts[2] if parts[1] == "Volumes" else "/", []).append(j)

    def run_drive(js):
        for j in js:
            print(extract(*j), flush=True)

    with ThreadPoolExecutor(max_workers=len(drives)) as ex:
        list(ex.map(run_drive, drives.values()))


if __name__ == "__main__":
    main(sys.argv[1])
