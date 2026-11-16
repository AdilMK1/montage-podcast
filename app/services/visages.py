"""Centre du visage dans chaque caméra (pour recadrer les shorts) + une vignette par caméra.

Port de app.pipeline.visages_et_vignettes (v1) sur le dossier du projet.
"""
import subprocess
from pathlib import Path

from app.fichiers import ecrire_json_atomique, lire_json

from .contexte import MOTEUR
from .session import chemin_rush


def cam_files(cams: dict) -> list[tuple[str, str, str]]:
    """(cam, clé du fichier, chemin) : une cam coupée en plusieurs fichiers donne CAM_1, CAM_2…"""
    out = []
    for k, p in cams.items():
        if isinstance(p, str):
            out.append((k, k, p))
        else:
            out += [(k, f"{k}_{i + 1}", q) for i, q in enumerate(p)]
    return out


def visages_et_vignettes(d):
    import cv2
    import numpy as np
    d = Path(d)
    pj = lire_json(d / "projet.json")
    sync = (lire_json(d / "sync.json", {}) or {}).get("cams", {})
    (d / "vignettes").mkdir(exist_ok=True)
    model = str(MOTEUR / "assets/models/face_detection_yunet_2023mar.onnx")
    visages = {}
    for cam, key, path in cam_files({k: chemin_rush(v) for k, v in pj["cams"].items()}):
        dur = sync.get(key, {}).get("cam_duration_s", 60)
        pts = []
        for i, f in enumerate((0.2, 0.4, 0.6, 0.8)):
            r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{dur * f:.1f}", "-i", path, "-frames:v", "1",
                                "-vf", "scale=960:-2", "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True)
            img = cv2.imdecode(np.frombuffer(r.stdout, np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                continue
            if i == 1:
                cv2.imwrite(str(d / "vignettes" / f"{key}.jpg"), img)
            if cam == "LARGE":
                continue
            det = cv2.FaceDetectorYN.create(model, "", (img.shape[1], img.shape[0]), 0.7)
            _, faces = det.detect(img)
            if faces is not None and len(faces):
                x, y, w, h = max(faces, key=lambda f: f[2] * f[3])[:4]
                pts.append(((x + w / 2) / img.shape[1], (y + h / 2) / img.shape[0]))
        if pts:
            visages[key] = [round(float(np.median([p[0] for p in pts])), 3), round(float(np.median([p[1] for p in pts])), 3)]
        elif cam != "LARGE":
            visages[key] = [0.5, 0.4]
    ecrire_json_atomique(d / "visages.json", visages)
