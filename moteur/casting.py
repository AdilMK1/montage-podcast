"""Pré-analyse : qui est qui dans les rushes (après extract.py et sync.py).

- pièges des micros : même son sur deux micros, micro silencieux, niveau très bas (comme transcribe.py) ;
- plan large : la caméra où l'on voit le plus souvent au moins 2 visages (images réparties, détecteur YuNet) ;
- micro <-> caméra : corrélation entre l'activité de parole de chaque micro (niveaux, recalés par la synchro) et
  le mouvement de la bouche du visage principal de chaque caméra serrée, sur des fenêtres réparties où l'on parle
  à plusieurs ; affectation qui maximise la somme des corrélations (toutes les permutations : peu de personnes) ;
- moments où chaque micro parle seul (extraits de vérification) et forme d'onde résumée de chaque micro.

Sortie : work/<nom>/casting_detection.json (lu par l'app) et alertes.json (comme transcribe.py).

Usage : python casting.py session.json
"""
import itertools
import json
from concurrent.futures import ThreadPoolExecutor
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

import travail
from edit import level_db, speaker_states
from extract import cam_files
from transcribe import ecrire_alertes, own_masks_n, progres, verifier_micros

MODELE = Path(__file__).resolve().parent / "assets" / "models" / "face_detection_yunet_2023mar.onnx"
TRAMES_S = 100  # niveaux : une valeur toutes les 10 ms (edit.level_db)
N_IMAGES = 12  # images par caméra pour trouver le plan large
LARGEUR_LARGE = 640
N_FENETRES, FENETRE = 12, 10.0  # fenêtres pour associer micros et caméras
IPS, LARGEUR = 5, 480
LECTEURS = 3  # lectures ffmpeg en parallèle (le décodage logiciel est plus rapide que VideoToolbox ici, mesuré)
LISSAGE = 9  # images (~2 s) : sur la démo, la séparation est nettement meilleure lissée
SEUIL_DETECTION = 0.6
MARGE_SURE = 0.15
MOMENT, N_MOMENTS = 5.0, 3
N_ONDE = 200
NIVEAU_BAS_DB = -45.0
FORMAT = 1


# ---------- son ----------

def activites(lv: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """activité de parole (0/1 toutes les 10 ms) de chaque micro : 1 micro -> au-dessus de son seuil ;
    2 -> speaker_states (le micro parle, seul ou avec l'autre) ; 3 et plus -> own_masks_n"""
    noms = list(lv)
    if not noms:
        return {}
    n = min(len(v) for v in lv.values())
    if len(noms) == 1:
        x = lv[noms[0]][:n]
        p10, p95 = np.percentile(x, [10, 95])
        return {noms[0]: (x > p10 + 0.5 * (p95 - p10)).astype(np.int8)}
    if len(noms) == 2:
        st, _, _ = speaker_states({k: lv[k][:n] for k in noms})
        return {k: ((st == i + 1) | (st == 3)).astype(np.int8) for i, k in enumerate(noms)}
    return dict(zip(noms, own_masks_n({k: lv[k][:n] for k in noms})))


def par_image(a: np.ndarray, debut: float, duree: float, ips: int = IPS) -> np.ndarray:
    """moyenne de l'activité (10 ms) sur chaque image de la fenêtre [debut, debut + duree]"""
    pas = TRAMES_S // ips
    x = np.asarray(a, float)[int(round(debut * TRAMES_S)):int(round((debut + duree) * TRAMES_S))]
    x = x[: len(x) // pas * pas]
    return x.reshape(-1, pas).mean(1) if len(x) else np.zeros(0)


def fenetres(act: dict[str, np.ndarray], lo: float, hi: float, n: int = N_FENETRES,
             duree: float = FENETRE) -> list[float]:
    """débuts (temps micro) de n fenêtres, une par n-ième de [lo, hi] : celle où les micros parlent le plus
    tous les deux (la moins active des personnes), à égalité celle où l'on parle le plus"""
    if hi - lo < duree or not act:
        return []
    bornes = np.linspace(lo, hi - duree, n + 1)
    out = []
    for a, b in zip(bornes, bornes[1:]):
        best, score = None, None
        for t in np.arange(a, max(a, b - 1e-6) + 1e-9, 1.0):
            fr = [float(np.mean(x)) if len(x) else 0.0 for x in (par_image(v, t, duree) for v in act.values())]
            s = (min(fr), sum(fr))
            if score is None or s > score:
                best, score = float(t), s
        if best is not None and (not out or best - out[-1] >= duree):
            out.append(round(best, 2))
    return out


def moments(act: dict[str, np.ndarray], lo: float, hi: float, n: int = N_MOMENTS,
            duree: float = MOMENT) -> dict[str, list[float]]:
    """pour chaque micro, les débuts (temps micro) des n fenêtres où il parle le plus nettement seul"""
    out = {}
    if hi - lo < duree:
        return {k: [] for k in act}
    debuts = np.arange(lo, hi - duree, 1.0)
    fr = {k: np.array([np.mean(par_image(v, t, duree, 10)) for t in debuts]) for k, v in act.items()}
    for k in act:
        autres = [fr[j] for j in act if j != k]
        s = fr[k] - (np.max(autres, axis=0) if autres else 0)
        pris = []
        for i in np.argsort(-s, kind="stable"):
            if fr[k][i] < 0.3 or len(pris) >= n:
                break
            if all(abs(debuts[i] - t) >= duree for t in pris):
                pris.append(float(debuts[i]))
        out[k] = [round(t, 2) for t in pris]
    return out


def onde(lv: np.ndarray, n: int = N_ONDE) -> list[float]:
    """forme d'onde résumée : n valeurs entre 0 et 1 (niveau le plus fort de chaque tranche, sur 50 dB)"""
    if len(lv) == 0:
        return [0.0] * n
    tr = [x.max() for x in np.array_split(np.asarray(lv, float), n) if len(x)]
    tr += [tr[-1]] * (n - len(tr))
    haut = float(np.max(lv))
    bas = max(float(np.percentile(lv, 5)), haut - 50)
    return [round(float(np.clip((v - bas) / max(haut - bas, 1e-6), 0, 1)), 3) for v in tr]


def niveau_bas(lv: np.ndarray) -> bool:
    """micro très bas : même ses passages forts restent sous -45 dB"""
    return bool(len(lv) and np.percentile(lv, 95) < NIVEAU_BAS_DB)


# ---------- image ----------

def plan_large(comptes: dict[str, list[int]], aires: dict[str, list[float]] | None = None):
    """(caméra, confiance, scores) : la caméra où l'on voit le plus souvent au moins 2 visages ; à égalité, plus de
    visages en moyenne, puis des visages plus petits. Confiance « sure » si nette (au moins la moitié des images
    et 0,3 d'écart avec la suivante)."""
    if not comptes:
        return None, None, {}
    scores = {c: (float(np.mean([x >= 2 for x in v])) if v else 0.0) for c, v in comptes.items()}
    aires = aires or {}

    def cle(c):
        v, a = comptes[c], aires.get(c) or [1.0]
        return scores[c], float(np.mean(v)) if v else 0.0, -float(np.mean(a))
    ordre = sorted(comptes, key=cle, reverse=True)
    best = ordre[0]
    ecart = scores[best] - (scores[ordre[1]] if len(ordre) > 1 else 0.0)
    sure = len(ordre) == 1 or (scores[best] >= 0.5 and ecart >= 0.3)
    return best, "sure" if sure else "a_verifier", {c: round(s, 3) for c, s in scores.items()}


def zone_bouche(face, l: int, h: int) -> tuple[int, int, int, int] | None:
    """(x0, y0, x1, y1) de la zone de la bouche d'un visage YuNet (coins de la bouche : valeurs 10 à 13)"""
    x, y, fw, fh = (float(v) for v in face[:4])
    cx0, cx1 = sorted((float(face[10]), float(face[12])))
    my = (float(face[11]) + float(face[13])) / 2
    mw = max(cx1 - cx0, fw * 0.3)
    x0, x1 = int(max(cx0 - 0.3 * mw, 0)), int(min(cx1 + 0.3 * mw, l))
    y0, y1 = int(max(my - 0.18 * fh, 0)), int(min(my + 0.35 * fh, h))
    return (x0, y0, x1, y1) if x1 - x0 >= 4 and y1 - y0 >= 4 else None


def serie_bouche(images, detecter) -> np.ndarray:
    """mouvement de la bouche du plus grand visage, image par image (NaN sans visage) : écart moyen de gris avec
    l'image précédente dans la zone de la bouche"""
    out, avant = [], None
    for img in images:
        gris = img.mean(axis=2).astype(np.float32) if img.ndim == 3 else img.astype(np.float32)
        faces = detecter(img)
        z = None
        if faces is not None and len(faces):
            f = max(faces, key=lambda v: float(v[2]) * float(v[3]))
            z = zone_bouche(f, gris.shape[1], gris.shape[0])
        if z is None or avant is None:
            out.append(np.nan)
        else:
            x0, y0, x1, y1 = z
            out.append(float(np.mean(np.abs(gris[y0:y1, x0:x1] - avant[y0:y1, x0:x1]))))
        avant = gris
    return np.array(out, float)


def lisser(x, w: int = LISSAGE) -> np.ndarray:
    x = np.asarray(x, float)
    ok = np.isfinite(x)
    if not ok.any():
        return np.zeros_like(x)
    x = np.where(ok, x, np.nanmean(x))
    return np.convolve(x, np.ones(w) / w, "same") if w > 1 and len(x) >= w else x


def centrer(x) -> np.ndarray:
    x = np.asarray(x, float)
    s = x.std()
    return (x - x.mean()) / s if s > 1e-9 else np.zeros_like(x)


def correlation(activite: list[np.ndarray], bouche: list[np.ndarray]) -> float:
    """corrélation entre la parole d'un micro et la bouche d'une caméra, fenêtre par fenêtre (lissées, centrées)"""
    A, B = [], []
    for a, b in zip(activite, bouche):
        n = min(len(a), len(b))
        if n < 3 or np.isfinite(np.asarray(b[:n], float)).sum() < 3:
            continue
        A.append(centrer(lisser(a[:n])))
        B.append(centrer(lisser(b[:n])))
    if not A:
        return 0.0
    A, B = np.concatenate(A), np.concatenate(B)
    if A.std() < 1e-9 or B.std() < 1e-9:
        return 0.0
    return float(np.corrcoef(A, B)[0, 1])


def affecter(scores: dict[str, dict[str, float]], micros: list[str], cameras: list[str]):
    """({micro: caméra ou None}, {micro: marge}) : l'affectation (une caméra par micro au plus) qui maximise la
    somme des corrélations ; marge d'un micro = perte de la meilleure affectation qui lui donne autre chose"""
    if not micros:
        return {}, {}
    cams = list(cameras) + [None] * max(0, len(micros) - len(cameras))
    essais = []
    for perm in itertools.permutations(cams, len(micros)):
        total = sum(scores.get(m, {}).get(c, 0.0) if c else 0.0 for m, c in zip(micros, perm))
        essais.append((total, perm))
    essais.sort(key=lambda t: -t[0])
    best_total, best = essais[0]
    marges = {}
    for i, m in enumerate(micros):
        autre = next((t for t, p in essais if p[i] != best[i]), None)
        marges[m] = round(best_total - autre, 3) if autre is not None else None
    return dict(zip(micros, best)), marges


# ---------- lecture des rushes ----------

_TAILLES: dict[str, tuple[int, int]] = {}


def taille(chemin: str) -> tuple[int, int]:
    if chemin not in _TAILLES:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                            "-of", "csv=p=0", chemin], capture_output=True, text=True, timeout=60)
        w, h = (int(v) for v in r.stdout.strip().split(",")[:2])
        _TAILLES[chemin] = (w, h)
    return _TAILLES[chemin]


def lire_images(chemin: str, debut: float, duree: float, ips: int, largeur: int) -> np.ndarray:
    """images (n, h, l, 3) en BGR, à ips images par seconde (ips=0 : une seule image), réduites à `largeur`.
    Décodage logiciel : sur un Mac M5, 0,8 s par fenêtre de 10 s en 1440p contre 1,4 s avec VideoToolbox, et
    4,5 s contre 4,1 s en 4K ; pour une image seule, VideoToolbox coûte 0,8 s de démarrage."""
    w, h = taille(chemin)
    l, hh = largeur, max(2, int(round(h * largeur / w / 2)) * 2)
    vf = (f"fps={ips}," if ips else "") + f"scale={l}:{hh}"
    cmd = ["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{max(debut, 0):.3f}", "-t", f"{duree:.3f}",
           "-i", chemin, "-an", "-vf", vf, *([] if ips else ["-frames:v", "1"]), "-pix_fmt", "bgr24",
           "-f", "rawvideo", "-"]
    r = subprocess.run(cmd, capture_output=True, timeout=300)
    a = np.frombuffer(r.stdout, np.uint8)
    n = len(a) // (l * hh * 3)
    return a[: n * l * hh * 3].reshape(n, hh, l, 3)


class Detecteur:
    def __init__(self):
        import cv2
        self.cv2, self.det, self.taille = cv2, None, None

    def __call__(self, img):
        t = (img.shape[1], img.shape[0])
        if self.det is None:
            self.det = self.cv2.FaceDetectorYN.create(str(MODELE), "", t, SEUIL_DETECTION)
        if t != self.taille:
            self.det.setInputSize(t)
            self.taille = t
        _, faces = self.det.detect(np.ascontiguousarray(img))
        return faces


# ---------- synchro ----------

def fichiers_par_camera(cfg: dict, sync: dict) -> dict[str, list[dict]]:
    """{caméra: [{chemin, offset, derive, debut, fin (temps micro)}]}"""
    out = {}
    for cam, cle, chemin in cam_files(cfg):
        s = sync["cams"].get(cle)
        if not s:
            continue
        a, b = s["covers_mic_s"]
        out.setdefault(cam, []).append({"cle": cle, "chemin": chemin, "offset": s["offset_s"],
                                        "derive": s["drift_ppm"] * 1e-6, "debut": a, "fin": b})
    return out


def temps_camera(morceaux: list[dict], t: float, duree: float = 0.0):
    """(chemin, temps dans le fichier) du morceau qui filme [t, t + duree] (temps micro), sinon None"""
    for m in morceaux:
        if m["debut"] <= t and t + duree <= m["fin"]:
            return m["chemin"], (t - m["offset"]) / (1 + m["derive"])
    return None


def plage_commune(par_cam: dict[str, list[dict]], duree_micros: float) -> tuple[float, float]:
    lo = max([0.0] + [min(m["debut"] for m in v) for v in par_cam.values()])
    hi = min([duree_micros] + [max(m["fin"] for m in v) for v in par_cam.values()])
    return lo, hi


# ---------- étapes ----------

def chercher_plan_large(par_cam, lo, hi, detecter, n=N_IMAGES):
    comptes, aires = {c: [] for c in par_cam}, {c: [] for c in par_cam}
    lectures = []
    for cam, morceaux in par_cam.items():
        a = max(lo, min(m["debut"] for m in morceaux))
        b = min(hi, max(m["fin"] for m in morceaux))
        for t in np.linspace(a, b, n + 2)[1:-1]:
            ou = temps_camera(morceaux, float(t))
            if ou is not None:
                lectures.append((cam, ou))
    with ThreadPoolExecutor(LECTEURS) as ex:
        images = list(ex.map(lambda x: lire_images(x[1][0], x[1][1], 0.04, 0, LARGEUR_LARGE), lectures))
    for (cam, _), imgs in zip(lectures, images):
        if len(imgs):
            faces = detecter(imgs[0])
            nb = 0 if faces is None else len(faces)
            comptes[cam].append(nb)
            if nb:
                aires[cam].append(max(float(f[2]) * float(f[3]) for f in faces) / (imgs[0].shape[0] * imgs[0].shape[1]))
    return comptes, aires


def associer(act, par_cam, serrees, debuts, detecter, avance=None):
    """scores {micro: {caméra: corrélation}}"""
    bouche = {c: [] for c in serrees}
    parole = {k: [par_image(v, t, FENETRE) for t in debuts] for k, v in act.items()}

    def lire(x):
        ou = temps_camera(par_cam[x[0]], x[1], FENETRE)
        return None if ou is None else lire_images(ou[0], ou[1], FENETRE, IPS, LARGEUR)
    travaux = [(c, t) for t in debuts for c in serrees]
    with ThreadPoolExecutor(LECTEURS) as ex:  # lectures en parallèle, visages dans ce fil (détecteur unique)
        for i, ((c, _), imgs) in enumerate(zip(travaux, ex.map(lire, travaux))):
            bouche[c].append(np.full(int(FENETRE * IPS), np.nan) if imgs is None else serie_bouche(imgs, detecter))
            if avance:
                avance((i + 1) / len(travaux))
    return {k: {c: round(correlation(parole[k], bouche[c]), 4) for c in serrees} for k in act}


def detecter_casting(cfg: dict, work: Path, detecter=None) -> dict:
    t0 = time.time()
    detecter = detecter or Detecteur()
    noms = list(cfg["mics"])
    lv = {k: level_db(work / f"mic_{k}.wav") for k in noms}
    actifs, alertes = verifier_micros(lv)
    ecrire_alertes(work, alertes)
    sync = json.loads((work / "sync.json").read_text())
    par_cam = fichiers_par_camera(cfg, sync)
    lo, hi = plage_commune(par_cam, sync["mic_duration_s"])
    progres(0.05)

    comptes, aires = chercher_plan_large(par_cam, lo, hi, detecter)
    large, conf_large, scores_large = plan_large(comptes, aires)
    t_large = time.time() - t0
    progres(0.3)

    act = activites({k: lv[k] for k in actifs})
    serrees = [c for c in par_cam if c != large]
    ident = alertes.get("micros_identiques") or []
    if len(actifs) < 2:
        raison = "identiques" if ident else "un_seul"
    elif not serrees:
        raison = "pas_de_camera"
    else:
        raison = None
    asso = {"possible": raison is None, "raison": raison, "scores": {}, "affectation": {}, "marges": {}, "fenetres": []}
    if raison is None:
        debuts = fenetres(act, lo, hi)
        sc = associer(act, par_cam, serrees, debuts, detecter, lambda f: progres(0.3 + 0.65 * f))
        aff, marges = affecter(sc, list(act), serrees)
        asso.update(scores=sc, affectation=aff, marges=marges, fenetres=debuts)
    t_asso = time.time() - t0 - t_large
    mom = moments(act, lo, hi)
    out = {
        "format": FORMAT, "plage": [round(lo, 2), round(hi, 2)],
        "micros": {k: {"niveau_db": round(float(np.percentile(lv[k], 95)), 1), "bas": niveau_bas(lv[k]),
                       "muet": k in (alertes.get("micros_silencieux") or []), "identique": k in ident,
                       "onde": onde(lv[k]), "moments": mom.get(k, [])} for k in noms},
        "cameras": {c: {"visages_plusieurs": scores_large.get(c, 0.0), "images": len(comptes.get(c, [])),
                        "visages_moyen": round(float(np.mean(comptes[c])), 2) if comptes.get(c) else 0.0}
                    for c in par_cam},
        "large": {"camera": large, "confiance": conf_large},
        "association": asso, "alertes": alertes,
        "durees": {"plan_large": round(t_large, 1), "association": round(t_asso, 1), "total": round(time.time() - t0, 1)},
    }
    progres(1.0)
    return out


def main(cfg_path: str) -> None:
    cfg = json.loads(Path(cfg_path).read_text())
    work = travail.dossier(cfg["name"])
    out = detecter_casting(cfg, work)
    (work / "casting_detection.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    a = out["association"]
    print(f"plan large : {out['large']['camera']} ({out['large']['confiance']}) | association : "
          f"{a['affectation'] if a['possible'] else 'impossible (' + str(a['raison']) + ')'} | "
          f"durées {out['durees']}", flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
