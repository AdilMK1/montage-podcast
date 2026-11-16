"""Pré-analyse : transcription rapide du début de la conversation (mélange des micros), pour que l'IA trouve les
prénoms et qui anime. Chaque phrase est attribuée au micro qui parle le plus pendant cette phrase.

Sortie : work/<nom>/debut_transcript.json [{start, end, text, micro}] (temps des micros).

Usage : python ecoute_debut.py session.json
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

import travail
from casting import activites
from edit import level_db
from transcribe import HALLU, MODEL, invite, progres, verifier_micros

SR = 16000
DUREE = 150.0  # secondes écoutées : les présentations sont au début


def attribuer(segments: list[dict], act: dict[str, np.ndarray]) -> list[dict]:
    """ajoute à chaque phrase le micro le plus actif sur ses instants (activité à 10 ms) ; le premier micro si
    aucune activité"""
    noms = list(act)
    out = []
    for s in segments:
        a, b = int(s["start"] * 100), max(int(s["end"] * 100), int(s["start"] * 100) + 1)
        parts = [float(np.mean(act[k][a:b])) if len(act[k][a:b]) else 0.0 for k in noms]
        micro = noms[int(np.argmax(parts))] if noms and max(parts) > 0 else (noms[0] if noms else None)
        out.append({**s, "micro": micro})
    return out


def melange(chemins: list[str], duree: float = DUREE) -> np.ndarray:
    """début de chaque micro à 16 kHz, chacun ramené au même niveau, additionnés"""
    pistes = []
    for c in chemins:
        r = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-t", f"{duree:.1f}", "-i", c, "-vn", "-ac", "1",
                            "-ar", str(SR), "-f", "f32le", "-"], capture_output=True, check=True, timeout=300)
        x = np.frombuffer(r.stdout, np.float32)
        pistes.append(x / max(float(np.percentile(np.abs(x), 99.9)) if len(x) else 0.0, 1e-4))
    n = max((len(x) for x in pistes), default=0)
    m = np.zeros(n, np.float32)
    for x in pistes:
        m[: len(x)] += x
    return np.clip(m * (0.3 / max(float(np.percentile(np.abs(m), 99.9)) if n else 0.0, 1e-4)), -1, 1)


def transcrire(audio: np.ndarray, prompt: str | None = None) -> list[dict]:
    import whisper_local
    res = whisper_local.transcrire(audio, prompt=prompt)
    out = []
    for s in res["segments"]:
        t = s["text"].strip()
        if t and not any(h in t.lower() for h in HALLU):
            out.append({"start": round(float(s["start"]), 2), "end": round(float(s["end"]), 2), "text": t})
    return out


def main(cfg_path: str) -> None:
    cfg = json.loads(Path(cfg_path).read_text())
    work = travail.dossier(cfg["name"])
    lv = {k: level_db(work / f"mic_{k}.wav") for k in cfg["mics"]}
    actifs, _ = verifier_micros(lv)
    progres(0.1)
    sortie = work / "debut_transcript.json"
    if not actifs:
        sortie.write_text("[]")
        return
    audio = melange([cfg["mics"][k] for k in actifs])
    progres(0.3)
    segs = attribuer(transcrire(audio, invite(cfg)), activites({k: lv[k] for k in actifs}))
    sortie.write_text(json.dumps(segs, ensure_ascii=False, indent=1))
    progres(1.0)
    print(f"début transcrit : {len(segs)} phrases", flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
