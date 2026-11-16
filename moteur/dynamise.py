"""Zooms doux dans un XML de montage, recette validée sur Exemple 2 (zooms_xml.py) : un seul mouvement par plan.

Plans serrés de plus de MIN_SHOT s, en alternance :
- poussée lente PUSH (100 -> 108 %, mouvement lissé) sur tout le plan ;
- plan resserré PUNCH (118 %) à partir d'une pause de parole vers le milieu du plan (plans de 12 s et plus).
Plan large : jamais zoomé. Pause cherchée dans les micros (session : sync + micros v2).

Usage : python dynamise.py sessions/x.json montage.xml [sortie.xml]   (par défaut : remplace le fichier)
"""
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import soundfile as sf

import travail
from zooms_xml import Seq, set_scale, zoom

ROOT = Path(__file__).parent
MIN_SHOT = 8.0
PUSH, PUNCH = 1.08, 1.18
PUNCH_MIN = 12.0


def mic_db(paths):
    """niveau des micros additionnés, dB par tranche de 10 ms"""
    tot = None
    for p in paths:
        f = sf.SoundFile(p)
        hop = f.samplerate // 100
        e = []
        for blk in f.blocks(blocksize=hop * 6000, dtype="float32", always_2d=True):
            x = blk.mean(1)
            n = len(x) // hop
            e.append((x[:n * hop].reshape(n, hop) ** 2).mean(1))
        e = np.concatenate(e)
        tot = e if tot is None else tot[:len(e)] + e[:len(tot)]
    return 10 * np.log10(np.convolve(tot, np.ones(25) / 25, "same") + 1e-12)  # fenêtre 0,25 s


def main(session, src, dst=None):
    cfg = json.loads(Path(session).read_text())
    sync = json.loads((travail.dossier(cfg["name"]) / "sync.json").read_text())["cams"]
    db = mic_db(cfg.get("son", {}).get("mics", cfg["mics"]).values())
    tree = ET.parse(src)
    root = tree.getroot()
    seq_el = root.find(".//sequence")
    fps = int(seq_el.findtext("rate/timebase"))
    seq = Seq(root)
    tracks = [t for t in seq_el.find("media/video").findall("track")
              if any((c.findtext("name") or "").startswith("CAM ") for c in t.findall("clipitem"))]
    clips = sorted(((t, c) for t in tracks for c in list(t.findall("clipitem"))
                    if c.findtext("enabled") != "FALSE" and c.findtext("name") != "CAM LARGE"),
                   key=lambda x: int(x[1].findtext("start")))

    def pause_in(c, a, b):
        """image de séquence de la pause la plus marquée entre 30 et 70 % du plan (proche du milieu)"""
        sc = sync[c.find("file").get("id").replace("file-cam-", "")]
        i0 = int(c.findtext("in"))
        to_mic = lambda f: sc["offset_s"] + (i0 + f - a) / fps * (1 + sc["drift_ppm"] * 1e-6)
        fr = np.arange(a + int((b - a) * 0.3), a + int((b - a) * 0.7))
        lv = np.array([db[min(len(db) - 1, int(to_mic(f) * 100))] for f in fr])
        lv += 3 * np.abs(fr - (a + b) / 2) / fps  # léger biais vers le milieu
        return int(fr[np.argmin(lv)])

    n, stats = 0, {"poussées": 0, "plans resserrés": 0}
    for t, c in clips:
        a, b = int(c.findtext("start")), int(c.findtext("end"))
        if (b - a) / fps < MIN_SHOT:
            continue
        if n % 2 == 0 or (b - a) / fps < PUNCH_MIN:
            zoom(seq, t, c, a, b, 1.0, PUSH)
            stats["poussées"] += 1
        else:
            _, right = seq.split(t, c, pause_in(c, a, b))
            set_scale(right, [(0, PUNCH)])
            stats["plans resserrés"] += 1
        n += 1
    ET.indent(tree, "")
    out = dst or src
    tree.write(out, encoding="UTF-8", xml_declaration=True)
    txt = open(out, encoding="utf-8").read()
    open(out, "w", encoding="utf-8").write(txt.replace("<?xml version='1.0' encoding='UTF-8'?>",
                                                       '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>'))
    print(f"{stats['poussées']} poussées lentes, {stats['plans resserrés']} plans resserrés -> {out}")


if __name__ == "__main__":
    main(*sys.argv[1:4])
