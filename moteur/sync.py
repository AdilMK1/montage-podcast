"""Étape 2 : cale chaque cam sur la référence micros, avec mesure de la dérive.

Les micros (Reaper) sont la référence : temps_micro = offset + temps_cam * (1 + dérive).
1. Calage grossier : corrélation des enveloppes d'énergie sur toute la durée.
2. Affinage : sondes de 30 s toutes les 3 min, GCC-PHAT sur la forme d'onde 8 kHz.
3. Régression linéaire sur les sondes fiables -> offset + dérive (ppm).

Usage : python sync.py sessions/exemple2.json
"""
import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import fftconvolve

import travail
from extract import cam_files

SR = 8000
ENV_HOP = 80  # 100 Hz
PROBE_LEN = 30.0
PROBE_EVERY = 180.0
SEARCH = 1.0  # ± s autour du calage grossier


def load(p: Path) -> np.ndarray:
    x, sr = sf.read(p, dtype="float32")
    assert sr == SR, p
    return x


def envelope(x: np.ndarray) -> np.ndarray:
    n = len(x) // ENV_HOP
    e = np.sqrt(np.mean(x[: n * ENV_HOP].reshape(n, ENV_HOP) ** 2, axis=1))
    e = np.log(e + 1e-5)
    # retire la tendance lente (niveau de gain différent entre cam et micro)
    k = 200
    e -= np.convolve(e, np.ones(k) / k, mode="same")
    return (e - e.mean()) / (e.std() + 1e-9)


def xcorr_lag(ref: np.ndarray, sig: np.ndarray) -> tuple[int, float]:
    """Retourne le décalage (échantillons) tel que sig[t] ~ ref[t + lag], et un score."""
    c = fftconvolve(ref, sig[::-1], mode="full")
    i = int(np.argmax(c))
    lag = i - (len(sig) - 1)
    peak = c[i]
    # score : pic / 2e pic hors voisinage
    c2 = c.copy()
    c2[max(0, i - 50): i + 50] = -np.inf
    return lag, float(peak / (np.max(c2) + 1e-9))


def gcc_phat(ref: np.ndarray, sig: np.ndarray) -> tuple[float, float]:
    n = len(ref) + len(sig)
    nfft = 1 << (n - 1).bit_length()
    R = np.fft.rfft(ref, nfft)
    S = np.fft.rfft(sig, nfft)
    X = R * np.conj(S)
    X /= np.abs(X) + 1e-12
    c = np.fft.irfft(X, nfft)
    c = np.concatenate((c[-(len(sig) - 1):], c[: len(ref)]))
    i = int(np.argmax(c))
    # interpolation parabolique pour une précision sous l'échantillon
    if 0 < i < len(c) - 1:
        a, b, d = c[i - 1], c[i], c[i + 1]
        frac = 0.5 * (a - d) / (a - 2 * b + d + 1e-12)
    else:
        frac = 0.0
    lag = i - (len(sig) - 1) + frac
    score = c[i] / (np.median(np.abs(c)) + 1e-12)
    return lag, float(score)


def sync_cam(ref: np.ndarray, cam: np.ndarray, env_ref: np.ndarray) -> dict:
    env_cam = envelope(cam)
    lag, conf = xcorr_lag(env_ref, env_cam)
    coarse = lag * ENV_HOP / SR  # temps_micro = coarse + temps_cam

    probes = []
    cam_dur = len(cam) / SR
    t = PROBE_LEN
    while t + PROBE_LEN < cam_dur - PROBE_LEN:
        seg = cam[int(t * SR): int((t + PROBE_LEN) * SR)]
        tm0 = t + coarse - SEARCH
        if tm0 >= 0 and (tm0 + PROBE_LEN + 2 * SEARCH) * SR < len(ref):
            win = ref[int(tm0 * SR): int((tm0 + PROBE_LEN + 2 * SEARCH) * SR)]
            l, s = gcc_phat(win, seg)
            probes.append({"t_cam": t, "offset": float(tm0 + l / SR - t), "score": s})
        t += PROBE_EVERY

    good = [p for p in probes if p["score"] > 12 and abs(p["offset"] - coarse) < 0.5]
    if len(good) >= 3:
        tc = np.array([p["t_cam"] for p in good])
        off = np.array([p["offset"] for p in good])
        b, a = np.polyfit(tc, off, 1)
        resid = off - (a + b * tc)
        # rejette les aberrants puis recalcule
        keep = np.abs(resid) < max(3 * np.median(np.abs(resid)), 0.002)
        b, a = np.polyfit(tc[keep], off[keep], 1)
        resid = off[keep] - (a + b * tc[keep])
        n_used = int(keep.sum())
    else:
        a, b, resid, n_used = coarse, 0.0, np.array([0.0]), 0

    return {
        "coarse_offset_s": coarse,
        "coarse_confidence": conf,
        "offset_s": float(a),
        "drift_ppm": float(b * 1e6),
        "drift_ms_per_hour": float(b * 3600 * 1000),
        "residual_ms_median": float(np.median(np.abs(resid)) * 1000),
        "residual_ms_max": float(np.max(np.abs(resid)) * 1000),
        "probes_used": n_used,
        "probes_total": len(probes),
        "cam_duration_s": cam_dur,
        "covers_mic_s": [float(a), float(a + cam_dur * (1 + b))],
        "probes": probes,
    }


def main(cfg_path: str) -> None:
    cfg = json.loads(Path(cfg_path).read_text())
    work = travail.dossier(cfg["name"])
    mics = [load(work / f"mic_{k}.wav") for k in cfg["mics"]]
    n = min(len(m) for m in mics)
    ref = sum(m[:n] for m in mics)
    env_ref = envelope(ref)
    out = {"mic_duration_s": n / SR, "cams": {}}
    for cam, k, path in cam_files(cfg):
        r = sync_cam(ref, load(work / f"cam_{k}.wav"), env_ref)
        r.update(cam=cam, path=path)
        out["cams"][k] = r
        print(f"{k:8s} offset {r['offset_s']:+9.4f} s | dérive {r['drift_ppm']:+6.1f} ppm "
              f"({r['drift_ms_per_hour']:+6.1f} ms/h) | résidu méd {r['residual_ms_median']:.2f} ms "
              f"max {r['residual_ms_max']:.2f} ms | sondes {r['probes_used']}/{r['probes_total']} "
              f"| couvre {r['covers_mic_s'][0]:.1f} -> {r['covers_mic_s'][1]:.1f} s", flush=True)
    (work / "sync.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    main(sys.argv[1])
