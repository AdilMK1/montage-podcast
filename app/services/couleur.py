"""Étape « Image » : réglages de couleur -> filtres ffmpeg, étalonnage du projet, images d'aperçu, harmonisation.

Port de app/reglages.py (v1) : les fonctions reçoivent le dossier du projet `d` ; les réglages image viennent de
etat.json et sont passés en paramètre. Les filtres sont écrits dans projet.json["etalonnage"] {nom de fichier: filtre
ffmpeg}, lu par l'épisode (aperçu et export) et par les shorts.
"""
import hashlib
import subprocess
from pathlib import Path

from app.fichiers import ecrire_json_atomique, lire_json

from .contexte import duree
from .session import chemin_rush
from .transcript import phrases

LOOKS = {  # valeurs des curseurs (-1 … 1) que pose chaque look
    "naturel": {"lumiere": 0, "contraste": 0, "saturation": 0, "temperature": 0},
    "chaud": {"lumiere": 0.05, "contraste": 0.1, "saturation": 0.1, "temperature": 0.45},
    "contraste": {"lumiere": 0, "contraste": 0.4, "saturation": 0.2, "temperature": 0},
    "doux": {"lumiere": 0.2, "contraste": -0.25, "saturation": -0.1, "temperature": 0.1},
    "cinema": {"lumiere": -0.05, "contraste": 0.3, "saturation": -0.25, "temperature": 0.2},
}


def cams(pj: dict) -> list[tuple[str, list[str]]]:
    """(nom de la caméra, [fichiers]) dans l'ordre du projet, plan large d'abord"""
    c = pj.get("cams", {})
    out = [(k, [chemin_rush(x) for x in (v if isinstance(v, list) else [v])]) for k, v in c.items()]
    return sorted(out, key=lambda kv: kv[0] != "LARGE")


def filtre(p: dict) -> str:
    """réglages d'une caméra -> chaîne de filtres ffmpeg ("" si rien à faire)"""
    parts = []
    eqb = p.get("equilibre") or [1, 1, 1]
    t = float(p.get("temperature", 0) or 0)
    rr, gg, bb = eqb[0] * (1 + 0.09 * t), eqb[1], eqb[2] * (1 - 0.09 * t)
    if max(abs(rr - 1), abs(gg - 1), abs(bb - 1)) > 0.003:
        parts.append(f"colorchannelmixer=rr={rr:.4f}:gg={gg:.4f}:bb={bb:.4f}")
    if p.get("lut") and Path(p["lut"]).exists():
        f = str(p["lut"]).replace("\\", "/").replace("'", r"\'").replace(":", r"\:")
        parts.append(f"lut3d=file='{f}'")
    l, c, s = (float(p.get(k, 0) or 0) for k in ("lumiere", "contraste", "saturation"))
    if abs(l) + abs(c) + abs(s) > 0.001:
        parts.append(f"eq=brightness={0.07 * l:.4f}:contrast={1 + 0.3 * c:.4f}:saturation={1 + 0.5 * s:.4f}")
    return ",".join(parts)


def ecrire_etalonnage(d, reglages_image: dict) -> dict:
    """réglages image -> projet.json["etalonnage"] {nom de fichier: filtre}, lu par le moteur ; renvoie le dict"""
    d = Path(d)
    pj = lire_json(d / "projet.json", {}) or {}
    et = {}
    for cam, fichiers in cams(pj):
        f = filtre(reglages_image.get(cam, {}))
        if f:
            for x in fichiers:
                et[Path(x).stem] = f
    pj["etalonnage"] = et
    ecrire_json_atomique(d / "projet.json", pj)
    return et


def image_source(d, cam) -> Path:
    """une image de la caméra (au milieu d'une phrase, vers 40 % de l'épisode), en cache"""
    d = Path(d)
    out = d / "apercus" / f"image_{cam}_source.jpg"
    if out.exists():
        return out
    out.parent.mkdir(exist_ok=True)
    pj = lire_json(d / "projet.json", {}) or {}
    src = dict(cams(pj))[cam][0]
    sync = (lire_json(d / "sync.json", {}) or {}).get("cams", {})
    sc = sync.get(cam) or next((v for k, v in sync.items() if k.startswith(cam)), None) or {"offset_s": 0, "drift_ppm": 0}
    ph = phrases(d)
    t = ph[int(len(ph) * 0.4)]["a"] + 1.0 if ph else (duree(src) or 60.0) * 0.4
    tc = max(0.0, (t - sc["offset_s"]) / (1 + sc["drift_ppm"] * 1e-6))
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{tc:.2f}", "-i", src, "-frames:v", "1",
                    "-vf", "scale=1280:-2:in_color_matrix=bt709:in_range=tv", "-q:v", "2", str(out)], check=True)
    return out


def apercu_image(d, cam, p: dict) -> Path:
    """l'image de la caméra avec les réglages p, en cache"""
    src = image_source(d, cam)
    f = filtre(p)
    if not f:
        return src
    out = src.with_name(f"image_{cam}_{hashlib.md5(f.encode()).hexdigest()[:10]}.jpg")
    if not out.exists():
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vf", f, "-q:v", "2", str(out)], check=True)
    return out


def harmoniser(d) -> dict:
    """équilibre des couleurs : les zones neutres (murs, fonds peu saturés) de chaque caméra calées sur celles du plan
    de référence (le plan large). Renvoie {cam: [r, g, b]}"""
    import cv2
    import numpy as np
    pj = lire_json(Path(d) / "projet.json", {}) or {}
    ref, gains = None, {}
    for cam, _ in cams(pj):
        img = cv2.imread(str(image_source(d, cam))).astype(np.float32) / 255.0
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        m = (hsv[..., 1] < 0.28) & (hsv[..., 2] > 0.15) & (hsv[..., 2] < 0.92)
        px = img[m] if m.sum() > 2000 else img.reshape(-1, 3)
        moy = px.mean(0)[::-1]  # RGB
        if ref is None:
            ref = moy
            gains[cam] = [1.0, 1.0, 1.0]
            continue
        g = ref / np.maximum(moy, 1e-3)
        g = np.clip(g / (0.299 * g[0] + 0.587 * g[1] + 0.114 * g[2]), 0.88, 1.14)  # la teinte seulement, pas la lumière
        gains[cam] = [round(float(x), 4) for x in g]
    return gains
