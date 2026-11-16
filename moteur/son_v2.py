"""Son v2 des micros : remplace la chaîne de son.py (débruiteur + gate) qui faisait de l'écho et du grain.

Retour d'l'invité (Exemple 2) : « quand on est deux, écho, grain ». Mesure : chaque micro capte l'autre voix
~5,5 ms plus tard ; à l'origine 22 dB sous la voix, mais le gros gain du micro le plus faible + le compresseur
remontaient cette repisse à -10/-17 dB -> la même voix deux fois, décalée = son creux / écho. Le débruiteur
(afftdn) ajoutait le grain, et la chaîne décalait le son de ~35 ms par rapport à l'image.
v2 : coupe-bas, gain (parole de chacun à TARGET_MIC), automix type Dugan (le micro de celui qui se tait baisse
jusqu'à FLOOR_DB), compression légère, limiteur à latence compensée. Pas de débruiteur, pas de gate.
Micros signalés par transcribe.py (work/<nom>/alertes.json) : un micro silencieux est coupé ; un micro sans
phrase à lui (micros identiques, transcrits comme une seule voix) prend le gain mesuré sur toutes les phrases.

Usage : python son_v2.py sessions/exemple2.json  -> écrit les WAV « (v2 automix) » à côté des WAV v1
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pyloudnorm as pyln
import soundfile as sf
from scipy.ndimage import uniform_filter1d
from scipy.signal import butter, sosfilt

import travail

ROOT = Path(__file__).parent
TARGET_MIC = -17.5
FLOOR_DB = -12.0
STEP = 64  # lissage des gains calculé tous les 64 échantillons


def smooth(g, sr, att=0.01, rel=0.25):
    a, r = np.exp(-STEP / (att * sr)), np.exp(-STEP / (rel * sr))
    gd = g[::STEP]
    out = np.empty_like(gd)
    y = gd[0]
    for i, v in enumerate(gd):
        y = a * y + (1 - a) * v if v > y else r * y + (1 - r) * v
        out[i] = y
    return np.repeat(out, STEP)[:len(g)]


def speech_loud(x, sr, segs):
    y = np.concatenate([x[int(a * sr):int(b * sr)] for a, b in segs])
    return pyln.Meter(sr).integrated_loudness(y)


def main(cfg_path):
    cfg = json.loads(Path(cfg_path).read_text())
    work = travail.dossier(cfg["name"])
    sentences = json.loads((work / "transcript.json").read_text())
    alertes = json.loads((work / "alertes.json").read_text()) if (work / "alertes.json").exists() else {}
    muets = set(alertes.get("micros_silencieux", []))
    out_dir = Path(cfg["dossier_son"]) if cfg.get("dossier_son") else Path(next(iter(cfg["mics"].values()))).parent / "SON -16 LUFS"
    out_dir.mkdir(exist_ok=True)
    segs, X = {}, {}
    denoise = cfg.get("debruitage", {})
    for k, path in cfg["mics"].items():
        if k in denoise:
            # débruitage par empreinte (afftdn) AVANT le gain, sur le signal remonté de 30 dB pour que le seuil
            # de bruit (nf) soit lisible ; validé à l'écoute à l'écoute sur d'autres (micro d'un invité qui souffle)
            tmp = out_dir / f"{Path(path).stem} (débruité tmp).wav"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(path), "-af",
                            f"volume=30dB,{denoise[k]},volume=-30dB", "-c:a", "pcm_f32le", str(tmp)], check=True)
            x, sr = sf.read(tmp, dtype="float32", always_2d=True)
            tmp.unlink()
        else:
            x, sr = sf.read(path, dtype="float32", always_2d=True)
        x = sosfilt(butter(2, 70, "hp", fs=sr, output="sos"), x.mean(1)).astype(np.float32)
        segs[k] = [(s["start"], s["end"]) for s in sentences if s["speaker"] == k and s["end"] - s["start"] > 1.5
                   and not any(o["speaker"] != k and o["start"] < s["end"] and o["end"] > s["start"] for o in sentences)]
        if not segs[k]:  # aucune phrase à lui seul : on mesure sa parole sur toutes les phrases
            segs[k] = [(s["start"], s["end"]) for s in sentences if s["end"] - s["start"] > 1.5]
        lu = speech_loud(x, sr, segs[k]) if segs[k] and k not in muets else -np.inf
        X[k] = x * np.float32(10 ** ((TARGET_MIC - lu) / 20)) if np.isfinite(lu) else np.zeros_like(x)
    n = min(len(v) for v in X.values())
    env = {k: uniform_filter1d(v[:n] ** 2, int(0.03 * sr)) + 1e-12 for k, v in X.items()}
    tot = sum(env.values())
    floor = 10 ** (cfg.get("automix_plancher_db", FLOOR_DB) / 20)
    for k in X:
        g = smooth(np.maximum(env[k] / tot, floor), sr).astype(np.float32)
        tmp = out_dir / f"{Path(cfg['mics'][k]).stem} (v2 tmp).wav"
        dst = out_dir / f"{Path(cfg['mics'][k]).stem} (v2 automix).wav"
        sf.write(tmp, X[k][:n] * g, sr, subtype="FLOAT")
        comp = "acompressor=threshold=0.1:ratio=2:attack=15:release=200"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(tmp), "-af", comp, "-c:a", "pcm_f32le", str(dst)], check=True)
        # la compression a baissé le niveau : on recale sur la parole AVANT le limiteur (latence compensée)
        y, _ = sf.read(dst, dtype="float32")
        fix = TARGET_MIC - speech_loud(y, sr, segs[k]) if segs[k] else 0.0
        fix = fix if np.isfinite(fix) else 0.0  # micro coupé : rien à recaler
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(tmp), "-af",
                        f"{comp},volume={fix:.2f}dB,alimiter=limit=0.84:level=false:latency=1",
                        "-c:a", "pcm_s24le", str(dst)], check=True)
        tmp.unlink()
        print(f"micro {k:6s} automix médiane {20 * np.log10(np.median(g)):+.1f} dB, recalage {fix:+.1f} dB : {dst.name}")


if __name__ == "__main__":
    main(sys.argv[1])
