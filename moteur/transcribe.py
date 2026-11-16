"""Étape 4 : transcription au mot de chaque micro (Whisper large-v3-turbo, GPU du Mac, français forcé).

Chaque micro est transcrit à part : le locuteur est connu. On ne lui donne que les passages où
son micro domine (le reste est la voix de l'autre captée par le micro, ou du silence où Whisper
invente du texte). Les passages sont mis bout à bout, puis les timecodes sont replacés sur la
timeline des micros.

Avant de chercher qui parle, on écarte les micros qui ne portent pas la voix d'une personne : un micro
silencieux, ou un micro qui a le même son qu'un autre (à un gain près : même fichier exporté deux fois,
mélange de la table de mixage). Deux micros identiques sont transcrits UNE fois comme une seule voix, au nom
du premier. Ces cas sont notés dans work/<nom>/alertes.json ({"micros_identiques": [...],
"micros_silencieux": [...]}), lu par l'app ; le fichier n'existe pas quand tout va bien.

Sorties dans work/<nom>/ : transcript_<MIC>.json (brut), transcript.json (fusionné, au mot)
et transcript.txt (lisible, avec timecodes).

Usage : python transcribe.py sessions/exemple2.json
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

import travail
from edit import level_db, runs, speaker_states

MODEL = "mlx-community/whisper-large-v3-turbo"  # (whisper_local choisit le moteur selon la machine)
SR = 16000
PAD = 0.3
JOIN_GAP = 1.5
SPACER = 0.6
# phrases que Whisper invente sur du bruit
HALLU = ("sous-titr", "amara.org", "merci d'avoir regardé", "abonnez-vous")
# micros identiques : niveaux corrélés au-delà de IDENT_CORR et écart de niveau quasi constant (p90 - p10 sous
# IDENT_ECART_DB) quand l'un des deux parle. Vrais micros d'une personne chacun : corrélation 0,25 à 0,55, écart
# qui varie de 15 à 25 dB (Exemple, Yanis, Sarah x Inès, d'autres).
IDENT_CORR = 0.95
IDENT_ECART_DB = 3.0
# micro silencieux : presque rien (p95 sous SILENCE_DB) ou aucun relief entre fond et parole (p95 - p10)
SILENCE_DB = -80.0
RELIEF_DB = 6.0
ALERTES = "alertes.json"


def tc(t: float) -> str:
    h, r = divmod(int(t), 3600)
    m, s = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def own_masks_n(lv: dict[str, np.ndarray], dominance: float = 6.0) -> list[np.ndarray]:
    """3 micros ou plus : un micro « parle » quand il dépasse son seuil et qu'il est à moins de
    `dominance` dB du micro le plus fort (niveaux recalés sur le p95 de chacun : gains différents)."""
    names = list(lv)
    n = min(len(v) for v in lv.values())
    L = np.stack([lv[k][:n] - np.percentile(lv[k][:n], 95) for k in names])
    gates = [np.percentile(l, 10) + 0.5 * (0 - np.percentile(l, 10)) for l in L]
    top = L.max(0)
    w = np.ones(50) / 50
    out = []
    for i, l in enumerate(L):
        m = ((l > gates[i]) & (l >= top - dominance)).astype(float)
        out.append((np.convolve(m, w, mode="same") > 0.5).astype(np.int8))
    return out


def silencieux(l: np.ndarray) -> bool:
    p10, p95 = np.percentile(l, [10, 95])
    return bool(p95 < SILENCE_DB or p95 - p10 < RELIEF_DB)


def identiques(a: np.ndarray, b: np.ndarray) -> bool:
    """même son sur deux micros (à un gain près) : on ne peut pas savoir qui parle en comparant leurs niveaux"""
    n = min(len(a), len(b))
    a, b = a[:n], b[:n]
    if n < 100 or np.std(a) < 1e-6 or np.std(b) < 1e-6:
        return False
    fort = (a > np.percentile(a, 50)) | (b > np.percentile(b, 50))
    d = (a - b)[fort]
    return bool(np.corrcoef(a, b)[0, 1] > IDENT_CORR and np.percentile(d, 90) - np.percentile(d, 10) < IDENT_ECART_DB)


def verifier_micros(lv: dict[str, np.ndarray]) -> tuple[list[str], dict]:
    """micros à transcrire (un seul par groupe de micros identiques, aucun silencieux) et alertes à signaler"""
    muets = [k for k in lv if silencieux(lv[k])]
    actifs, doubles = [], []
    for k in lv:
        if k in muets:
            continue
        jumeau = next((a for a in actifs if identiques(lv[a], lv[k])), None)
        if jumeau is None:
            actifs.append(k)
        else:
            doubles += [x for x in (jumeau, k) if x not in doubles]
    alertes = {}
    if doubles:
        alertes["micros_identiques"] = doubles
    if muets:
        alertes["micros_silencieux"] = muets
    return actifs, alertes


def passages(lv: dict[str, np.ndarray], actifs: list[str]) -> dict[str, list[tuple[float, float]]]:
    """passages à transcrire pour chaque micro actif : 2 micros -> qui domine l'autre ; 1 micro -> partout où il
    y a de la voix ; 3 ou plus -> own_masks_n"""
    if len(actifs) == 2:
        st, _, _ = speaker_states({k: lv[k] for k in actifs})
        return {k: regions(st, i + 1) for i, k in enumerate(actifs)}
    owns = own_masks_n({k: lv[k] for k in actifs}) if actifs else []
    return {k: regions(None, 0, o) for k, o in zip(actifs, owns)}


def ecrire_alertes(work: Path, alertes: dict) -> None:
    f = Path(work) / ALERTES
    if alertes:
        f.write_text(json.dumps(alertes, ensure_ascii=False, indent=1))
    else:
        f.unlink(missing_ok=True)


def regions(st: np.ndarray, idx: int, own: np.ndarray | None = None) -> list[tuple[float, float]]:
    """Passages (s) où le micro idx parle (seul ou en même temps que l'autre)."""
    if own is None:
        own = ((st == idx) | (st == 3)).astype(np.int8)
    out = []
    for l, s, e in runs(own):
        if not l:
            continue
        s, e = max(0.0, s / 100 - PAD), e / 100 + PAD
        if out and s - out[-1][1] < JOIN_GAP:
            out[-1] = (out[-1][0], e)
        else:
            out.append((s, e))
    return out


def invite(cfg: dict) -> str | None:
    """noms propres du projet donnés à Whisper pour qu'il les écrive correctement"""
    noms = [n for n in cfg.get("vocabulaire", []) if n]
    return f"Noms propres : {', '.join(noms)}." if noms else None


def progres(f: float) -> None:
    """avancement (0-1) lu par l'app pour sa jauge (fichier donné par MONTAGE_PROGRES)"""
    import os
    p = os.environ.get("MONTAGE_PROGRES")
    if p:
        try:
            Path(p).write_text(f"{f:.3f}")
        except OSError:
            pass


_TQDM = None
_AVANCE = None  # avancement 0-1 du micro en cours (faster-whisper : pas de barre tqdm)


def suivre(debut: float, part: float) -> None:
    """la barre de Whisper (en trames) devient l'avancement de l'étape : de debut à debut + part"""
    global _TQDM, _AVANCE
    _AVANCE = lambda f: progres(debut + part * min(1.0, f))  # noqa: E731
    import tqdm
    _TQDM = _TQDM or tqdm.tqdm

    class Jauge(_TQDM):
        def update(self, n=1):
            r = super().update(n)
            if self.total and not self.disable:  # faster-whisper garde une barre éteinte : ne pas la suivre
                progres(debut + part * min(1.0, self.n / self.total))
            return r

    tqdm.tqdm = Jauge


def transcribe(wav: Path, regs, out: Path, prompt: str | None = None) -> list[dict]:
    if out.exists():
        return json.loads(out.read_text())
    if not regs:  # aucun passage à ce micro : transcript vide (Whisper n'a rien à écouter)
        out.write_text("[]")
        return []
    import whisper_local

    x, sr = sf.read(wav, dtype="float32")
    assert sr == SR
    # gain : les micros sont enregistrés très bas
    peak = np.percentile(np.abs(x), 99.9)
    x = np.clip(x * (0.3 / max(peak, 1e-4)), -1, 1)

    pieces, table, pos = [], [], 0.0  # table : (début dans le montage, début réel, durée)
    gap = np.zeros(int(SPACER * SR), dtype=np.float32)
    for s, e in regs:
        seg = x[int(s * SR): int(e * SR)]
        pieces += [seg, gap]
        table.append((pos, s, len(seg) / SR))
        pos += (len(seg) + len(gap)) / SR
    audio = np.concatenate(pieces)
    starts = np.array([t[0] for t in table])

    def real(t: float) -> float:
        i = max(0, int(np.searchsorted(starts, t, side="right")) - 1)
        p, s, d = table[i]
        return s + min(max(t - p, 0.0), d)

    res = whisper_local.transcrire(audio, prompt=prompt, mots=True, temperatures=(0.0, 0.2, 0.4, 0.6), barre=True,
                                   avance=_AVANCE)

    sents = []
    for seg in res["segments"]:
        text = seg["text"].strip()
        if not text or any(h in text.lower() for h in HALLU):
            continue
        words = [{"w": w["word"].strip(), "start": round(real(w["start"]), 3), "end": round(real(w["end"]), 3),
                  "p": round(w["probability"], 3)} for w in seg.get("words", []) if w["word"].strip()]
        if not words:
            continue
        sents.append({"start": words[0]["start"], "end": words[-1]["end"], "text": text, "words": words})
    out.write_text(json.dumps(sents, ensure_ascii=False, indent=1))
    return sents


def main(cfg_path: str) -> None:
    cfg = json.loads(Path(cfg_path).read_text())
    work = travail.dossier(cfg["name"])
    names = list(cfg["mics"])
    lv = {k: level_db(work / f"mic_{k}.wav") for k in names}
    actifs, alertes = verifier_micros(lv)
    ecrire_alertes(work, alertes)
    if "micros_identiques" in alertes:
        print(f"ATTENTION micros identiques : {', '.join(alertes['micros_identiques'])} ont le même son "
              f"(pas un micro par personne) ; transcrits une seule fois, comme une seule voix", flush=True)
    if "micros_silencieux" in alertes:
        print(f"ATTENTION micros silencieux : {', '.join(alertes['micros_silencieux'])} ; pas transcrits", flush=True)
    par_micro = passages(lv, actifs)

    merged = []
    tous = [par_micro.get(k, []) for k in names]
    durees = [sum(e - s for s, e in r) for r in tous]
    total, fait = sum(durees) or 1.0, 0.0
    for i, k in enumerate(names):
        regs = tous[i]
        if k not in actifs:
            print(f"transcription {k} : micro écarté (voir alertes.json), transcript vide", flush=True)
            continue
        print(f"transcription {k} : {len(regs)} passages, {durees[i] / 60:.0f} min…", flush=True)
        if not regs:
            print(f"micro {k} : aucun passage où il domine les autres, transcript vide pour ce micro", flush=True)
        progres(fait / total)
        suivre(fait / total, durees[i] / total)  # la jauge avance pendant la transcription de chaque micro
        wav16 = work / f"mic16_{k}.wav"
        if regs and not wav16.exists():
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", cfg["mics"][k], "-ac", "1", "-ar", str(SR),
                            "-c:a", "pcm_s16le", str(wav16)], check=True)
        for s in transcribe(wav16, regs, work / f"transcript_{k}.json", invite(cfg)):
            merged.append({**s, "speaker": k})
        fait += durees[i]
    progres(1.0)
    merged.sort(key=lambda s: s["start"])
    (work / "transcript.json").write_text(json.dumps(merged, ensure_ascii=False, indent=1))
    lines = [f"[{tc(s['start'])}] {s['speaker']} : {s['text']}" for s in merged]
    (work / "transcript.txt").write_text("\n".join(lines), encoding="utf-8")
    n_words = sum(len(s["words"]) for s in merged)
    print(f"{len(merged)} phrases, {n_words} mots -> {work / 'transcript.txt'}")


if __name__ == "__main__":
    main(sys.argv[1])
