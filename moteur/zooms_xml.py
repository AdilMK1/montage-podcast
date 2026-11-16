"""Retours l'invité (Exemple 2) appliqués au XML de montage, à rouvrir dans Premiere.

- son : micros v2 (son_v2.py : automix, sans écho ni grain, recalés sur l'image) à la place des v1 ;
- zooms (échelle Basic Motion, autour du centre de l'image), un seul mouvement par plan :
  intro poussée vers 0:50, plan serré vers 1:07 puis poussée jusqu'au logo, CTA abonnés poussée lente,
  épisode : plans serrés de plus de MIN_ZOOM_SHOT alternés poussée lente / plan resserré coupé sur une pause.
Les <when> des images clés : relatifs au début du clip ou au point d'entrée selon les logiciels ; on écrit les
deux jeux (début et entrée), en coupant le clip si besoin pour que les deux ne se chevauchent jamais.
L'exposition des plans larges reste à faire dans Premiere (Lumetri, pas importé depuis un XML).

Usage : python zooms_xml.py
"""
import copy
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote

import numpy as np
import soundfile as sf

ROOT = Path(__file__).parent
EXEMPLE = Path("~/Podcasts/EXEMPLE")
SRC = EXEMPLE / "EXEMPLE/ANCIENS XML/EXEMPLE2 MONTAGE AVEC TEASER.xml"
DST = EXEMPLE / "EXEMPLE/EXEMPLE2 MONTAGE V2 (retours Exemple).xml"
EXPORT = EXEMPLE / "EXEMPLE FINAL.mp4"
SON = EXEMPLE / "EXEMPLE/SON -16 LUFS"
FPS = 25
MIN_ZOOM_SHOT = 8.0
PUSH, PUNCH = 1.08, 1.18
BODY_START = 82.24 * FPS  # fin de l'intro (logo l'émission)

_audio = None


def pause_near(t, lo, hi):
    """image la plus calme (fenêtre 0,25 s) de l'export entre lo et hi (s), au plus près de t ; en images"""
    global _audio
    if _audio is None:
        wav = ROOT / "work/EXEMPLE2/export_mono_8k.wav"
        if not wav.exists():
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(EXPORT), "-vn", "-ac", "1", "-ar", "8000", str(wav)], check=True)
        _audio, _ = sf.read(wav, dtype="float32")
    sr = 8000
    x = _audio[int(lo * sr):int(hi * sr)] ** 2
    db = 10 * np.log10(np.convolve(x, np.ones(int(0.25 * sr)) / (0.25 * sr), "same") + 1e-9)
    db += 3 * np.abs(np.arange(len(db)) / sr + lo - t)
    return round((lo + np.argmin(db) / sr) * FPS)


class Seq:
    def __init__(self, root):
        self.root = root
        self.next_id = 1 + max(int(c.get("id").split("-")[1]) for c in root.iter("clipitem"))

    def split(self, track, c, at):
        """coupe le clip c à l'image de séquence at ; renvoie (gauche, droite)"""
        a, b, i = (int(c.findtext(k)) for k in ("start", "end", "in"))
        assert a < at < b
        d = copy.deepcopy(c)
        d.set("id", f"clip-{self.next_id}")
        self.next_id += 1
        c.find("end").text = str(at)
        c.find("out").text = str(i + at - a)
        d.find("start").text = str(at)
        d.find("in").text = str(i + at - a)
        kids = list(track)
        track.insert(kids.index(c) + 1, d)
        return c, d


def base_scale(c):
    p = c.find(".//parameter[parameterid='scale']")
    return float(p.findtext("value")) if p is not None else 100.0


def set_scale(c, points):
    """points : [(image relative au début du clip, facteur)] ; facteur constant si un seul point"""
    base = base_scale(c)
    filt = next((f for f in c.findall("filter") if f.findtext("effect/effectid") == "basic"), None)
    if filt is None:
        filt = ET.SubElement(c, "filter")
        eff = ET.SubElement(filt, "effect")
        for k, v in (("name", "Basic Motion"), ("effectid", "basic"), ("effectcategory", "motion"),
                     ("effecttype", "motion"), ("mediatype", "video")):
            ET.SubElement(eff, k).text = v
    eff = filt.find("effect")
    for p in eff.findall("parameter"):
        if p.findtext("parameterid") == "scale":
            eff.remove(p)
    p = ET.SubElement(eff, "parameter", authoringApp="PremierePro")
    for k, v in (("parameterid", "scale"), ("name", "Scale"), ("valuemin", "0"), ("valuemax", "1000")):
        ET.SubElement(p, k).text = v
    ET.SubElement(p, "value").text = f"{base * points[0][1]:.3f}"
    if len(points) > 1:
        i = int(c.findtext("in"))
        offsets = (0, i) if i else (0,)
        for off in offsets:
            for t, z in points:
                k = ET.SubElement(p, "keyframe")
                ET.SubElement(k, "when").text = str(off + t)
                ET.SubElement(k, "value").text = f"{base * z:.3f}"


def zoom(seq, track, c, t0, t1, z0, z1):
    """poussée z0 -> z1 (lissée) entre les images de séquence t0 et t1, à l'intérieur du clip c ;
    coupe le clip en morceaux plus courts que leur point d'entrée pour que les deux jeux d'images clés
    (relatifs au début / au point d'entrée) ne se mélangent pas"""
    a, b = int(c.findtext("start")), int(c.findtext("end"))

    def z(t):
        u = min(max((t - t0) / (t1 - t0), 0), 1)
        return z0 + (z1 - z0) * u * u * (3 - 2 * u)

    pieces = [c]
    while True:
        last = pieces[-1]
        la, lb, li = (int(last.findtext(k)) for k in ("start", "end", "in"))
        if li <= 1 or lb - la < li:  # point d'entrée 0/1 : rien à séparer (plan au tout début du rush)
            break
        pieces[-1:] = seq.split(track, last, la + li - 1)
    for p in pieces:
        pa, pb = int(p.findtext("start")), int(p.findtext("end"))
        ts = sorted({pa, pb, *[t for t in range(pa, pb + 1, 5)], *[t for t in (t0, t1) if pa < t < pb]})
        set_scale(p, [(t - pa, z(t)) for t in ts])


def clip_at(tracks, frame, enabled=True):
    for t in tracks:
        for c in t.findall("clipitem"):
            if int(c.findtext("start")) <= frame < int(c.findtext("end")) and (c.findtext("enabled") != "FALSE") == enabled:
                return t, c
    raise LookupError(frame)


def main():
    tree = ET.parse(SRC)
    root = tree.getroot()
    seq_el = root.find(".//sequence")
    seq_el.find("name").text = DST.stem
    seq = Seq(root)
    vt = seq_el.find("media/video").findall("track")
    rush, inserts = vt[:3], vt[3:5]

    # son : micros v2
    for f in root.iter("file"):
        name = f.findtext("name") or ""
        if name.startswith("AUDIO ") and "(-16 LUFS)" in name:
            new = SON / name.replace("(-16 LUFS)", "(v2 automix)")
            assert new.exists(), new
            f.find("name").text = new.name
            f.find("pathurl").text = "file://localhost" + quote(str(new))

    # intro
    t, c = clip_at(inserts, round(55 * FPS))  # INTRO 1 ZOOM
    zoom(seq, t, c, round(48.92 * FPS), int(c.findtext("end")), 1.0, 1.12)
    t, c = clip_at(inserts, round(70 * FPS))  # INTRO 2 ZOOM
    p1, p2 = pause_near(67.2, 66.4, 68.4), pause_near(73.0, 71.5, 74.5)
    _, mid = seq.split(t, c, p1)
    mid, end = seq.split(t, mid, p2)
    set_scale(mid, [(0, PUNCH)])
    zoom(seq, t, end, p2, int(end.findtext("end")), 1.0, PUSH)
    # CTA abonnés
    cta = next(c for c in inserts[0].findall("clipitem") if c.findtext("name").startswith("INTRO OUTRO CTA")
               and 15000 < int(c.findtext("start")) < 20000)
    zoom(seq, inserts[0], cta, int(cta.findtext("start")), int(cta.findtext("end")), 1.0, 1.10)

    # épisode
    covered = [(int(c.findtext("start")), int(c.findtext("end"))) for t in inserts for c in t.findall("clipitem")]
    shots = sorted(((t, c) for t in rush for c in list(t.findall("clipitem")) if c.findtext("enabled") != "FALSE"),
                   key=lambda x: int(x[1].findtext("start")))
    n, stats = 0, {"push": 0, "punch": 0}
    for t, c in shots:
        a, b = int(c.findtext("start")), int(c.findtext("end"))
        if a < BODY_START or c.findtext("name") == "CAM LARGE" or (b - a) < MIN_ZOOM_SHOT * FPS \
                or any(x <= a < y for x, y in covered):
            continue
        kind = "push" if n % 2 == 0 or b - a < 12 * FPS else "punch"
        n += 1
        stats[kind] += 1
        if kind == "push":
            zoom(seq, t, c, a, b, 1.0, PUSH)
        else:
            cut = pause_near((a + b) / 2 / FPS, (a + (b - a) * 0.3) / FPS, (a + (b - a) * 0.7) / FPS)
            _, right = seq.split(t, c, cut)
            set_scale(right, [(0, PUNCH)])

    ET.indent(tree, "")
    tree.write(DST, encoding="UTF-8", xml_declaration=True)
    txt = DST.read_text()
    DST.write_text(txt.replace("<?xml version='1.0' encoding='UTF-8'?>", '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>'))
    print(stats, "->", DST.name)


if __name__ == "__main__":
    main()
