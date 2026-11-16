"""Aperçus instantanés : le passage brut (image + son traité), pour décider avant de fabriquer.

Source vidéo : le proxy s'il est prêt, sinon le rush (≈ 16 s pour 30 s de 4K 10 bits sur un M5). En cache.
"""
from pathlib import Path

from app.projet.modele import empreinte

from .session import chemin_rush


def cle_camera(sync_cams: dict, cam: str, t: float) -> str:
    """caméra serrée de `cam` qui filme à l'instant t (micro) ; sinon une autre serrée ; sinon le plan large"""
    def filme(v):
        return v["covers_mic_s"][0] <= t <= v["covers_mic_s"][1]
    serrees = {k: v for k, v in sync_cams.items() if not k.startswith("LARGE")}
    for k, v in serrees.items():
        if (k == cam or v.get("cam", k).startswith(cam)) and filme(v):
            return k
    for k, v in list(serrees.items()) + [(k, v) for k, v in sync_cams.items() if k.startswith("LARGE")]:
        if filme(v):
            return k
    raise ValueError(f"aucune caméra ne filme à {t:.1f} s")


def source_video(d, v: dict) -> str:
    px = Path(d) / "sorties" / "PROXYS" / (Path(v["path"]).stem + ".mp4")
    return str(px) if px.exists() else v["path"]


def sons_traites(d, pj: dict) -> list[str]:
    return [str(Path(d) / "son" / f"{Path(chemin_rush(p)).stem} (v2 automix).wav") for p in pj["mics"].values()]


def temps_camera(v: dict, t: float) -> float:
    return max(0.0, (t - v["offset_s"]) / (1 + v["drift_ppm"] * 1e-6))


def chemin_apercu(d, short: dict) -> Path:
    return Path(d) / "apercus" / f"short_{short['id']}_{empreinte(short['spec'].get('extraits', []))[:8]}.mp4"


def commande_apercu(d, pj: dict, sync_cams: dict, micro: str, extraits: list, sortie, enc: list) -> list[str]:
    ins, filt, paires, n = [], [], [], 0
    wavs = sons_traites(d, pj)
    for i, e in enumerate(extraits):
        a, b = e["rush"]
        dur = b - a
        v = sync_cams[cle_camera(sync_cams, e.get("cam") or micro, a)]
        ins += ["-ss", f"{temps_camera(v, a):.3f}", "-t", f"{dur:.3f}", "-i", source_video(d, v)]
        vi, n = n, n + 1
        ais = []
        for w in wavs:
            ins += ["-ss", f"{a:.3f}", "-t", f"{dur:.3f}", "-i", w]
            ais.append(n)
            n += 1
        filt.append(f"[{vi}:v]scale=-2:540,setsar=1,fps=25[v{i}]")
        filt.append("".join(f"[{j}:a]" for j in ais) + f"amix=inputs={len(ais)}:normalize=0[a{i}]")
        paires.append(f"[v{i}][a{i}]")
    filt.append("".join(paires) + f"concat=n={len(extraits)}:v=1:a=1[v][a]")
    return ["ffmpeg", "-v", "error", "-nostdin", "-y", *ins, "-filter_complex", ";".join(filt), "-map", "[v]",
            "-map", "[a]", *enc, "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", "-progress", "pipe:1",
            "-nostats", str(sortie)]


def chemin_apercu_passage(d, a: float, b: float) -> Path:
    return Path(d) / "apercus" / f"passage_{a:.2f}_{b:.2f}.mp4"


def commande_apercu_passage(d, pj: dict, sync_cams: dict, a: float, b: float, sortie, enc: list) -> list[str]:
    """plan large + son, 1 s avant / après le passage retiré.

    Un passage peut tomber là où aucune caméra ne filme encore (caméras lancées après les micros) ou plus (fin) :
    on prend la caméra qui couvre le plus le passage (le plan large à égalité), et l'image est noire là où elle
    ne filme pas ; sans aucune caméra, on garde le son sur fond noir."""
    a0, b0 = max(0.0, a - 1.0), b + 1.0
    dur = b0 - a0

    def recouvre(v):
        c0, c1 = v["covers_mic_s"]
        return max(0.0, min(b0, c1) - max(a0, c0))
    cands = sorted(sync_cams.items(), key=lambda kv: (round(recouvre(kv[1]), 1), kv[0].startswith("LARGE")),
                   reverse=True)
    ins, filt = [], []
    if cands and recouvre(cands[0][1]) > 0.04:
        v = cands[0][1]
        va, vb = max(a0, v["covers_mic_s"][0]), min(b0, v["covers_mic_s"][1])
        ins += ["-ss", f"{temps_camera(v, va):.3f}", "-t", f"{vb - va:.3f}", "-i", source_video(d, v)]
        filt.append(f"[0:v]scale=-2:540,setsar=1,fps=25,tpad=start_duration={va - a0:.3f}:"
                    f"stop_duration={b0 - vb:.3f}:color=black[v]")
    else:
        ins += ["-f", "lavfi", "-t", f"{dur:.3f}", "-i", "color=c=black:s=960x540:r=25"]
        filt.append("[0:v]setsar=1[v]")
    ais = []
    for i, w in enumerate(sons_traites(d, pj), start=1):
        ins += ["-ss", f"{a0:.3f}", "-t", f"{dur:.3f}", "-i", w]
        ais.append(i)
    filt.append("".join(f"[{j}:a]" for j in ais) + f"amix=inputs={len(ais)}:normalize=0[a]")
    return ["ffmpeg", "-v", "error", "-nostdin", "-y", *ins, "-filter_complex", ";".join(filt), "-map", "[v]",
            "-map", "[a]", "-t", f"{dur:.3f}", *enc, "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
            "-progress", "pipe:1", "-nostats", str(sortie)]
