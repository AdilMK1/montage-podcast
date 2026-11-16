"""Étape « Son » : écoute avant / après et niveaux des voix. Port de app/reglages.py (v1) sur le dossier du projet."""
import hashlib
import json
import subprocess
from pathlib import Path

from app.fichiers import ecrire_json_atomique, lire_json

from .session import chemin_rush
from .transcript import phrases


def moment(d, duree=16.0) -> float:
    """le passage où les voix s'enchaînent le plus (pour entendre l'écho et l'équilibre)"""
    ph = phrases(d)
    best, t0 = -1, ph[0]["a"] if ph else 0.0
    for i, p in enumerate(ph):
        fen = [q for q in ph[i:] if q["a"] < p["a"] + duree]
        n = sum(1 for a, b in zip(fen, fen[1:]) if a["sp"] != b["sp"]) + 0.1 * len(fen)
        if n > best:
            best, t0 = n, p["a"]
    return max(0.0, t0 - 0.3)


def apercu_son(d, version: str, reglages_son: dict) -> tuple[Path, float | None]:
    """16 s du mix, « avant » (micros bruts) ou « apres » (son traité), au même volume pour comparer à l'oreille"""
    d = Path(d)
    pj = lire_json(d / "projet.json", {}) or {}
    a = moment(d)
    if version == "avant":
        sons = [chemin_rush(v) for v in pj["mics"].values()]
        cle = "avant"
    else:
        sons = [str(d / "son" / f"{Path(chemin_rush(v)).stem} (v2 automix).wav") for v in pj["mics"].values()]
        mt = [Path(s).stat().st_mtime for s in sons if Path(s).exists()]
        cle = "apres_" + hashlib.md5(json.dumps(reglages_son, sort_keys=True).encode()).hexdigest()[:8] + \
              f"_{int(max(mt) if mt else 0)}"
    out = d / "apercus" / f"son_{cle}.m4a"
    if not out.exists():
        out.parent.mkdir(exist_ok=True)
        ins = sum([["-ss", f"{a:.2f}", "-t", "16", "-i", s] for s in sons], [])
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-nostdin", *ins, "-filter_complex",
                        f"{''.join(f'[{i}:a]' for i in range(len(sons)))}amix=inputs={len(sons)}:normalize=0,"
                        "loudnorm=I=-16:TP=-1.5[a]", "-map", "[a]", "-c:a", "aac", "-b:a", "160k", str(out)], check=True)
    return out, a


def niveaux(d) -> dict:
    """niveau de chaque voix après traitement (LUFS, sur ses propres phrases, 3 min max) : elles doivent être proches"""
    import numpy as np
    import pyloudnorm as pyln
    import soundfile as sf
    d = Path(d)
    pj = lire_json(d / "projet.json", {}) or {}
    cache = d / "apercus" / "niveaux.json"
    sons = {k: d / "son" / f"{Path(chemin_rush(v)).stem} (v2 automix).wav" for k, v in pj["mics"].items()}
    if not all(f.exists() for f in sons.values()):
        return {}
    cle = str(int(max(f.stat().st_mtime for f in sons.values())))
    c = lire_json(cache, {}) or {}
    if c.get("cle") == cle:
        return c["niveaux"]
    ph = phrases(d)
    out = {}
    for k, f in sons.items():
        sr = sf.info(str(f)).samplerate
        morceaux, tot = [], 0.0
        for p in ph:
            if p["sp"] != k or p["b"] - p["a"] < 1.5:
                continue
            x, _ = sf.read(str(f), start=int(p["a"] * sr), stop=int(p["b"] * sr), dtype="float32", always_2d=True)
            morceaux.append(x.mean(1))
            tot += p["b"] - p["a"]
            if tot > 180:
                break
        if morceaux:
            out[k] = round(float(pyln.Meter(sr).integrated_loudness(np.concatenate(morceaux))), 1)
    (d / "apercus").mkdir(exist_ok=True)
    ecrire_json_atomique(cache, {"cle": cle, "niveaux": out})
    return out
