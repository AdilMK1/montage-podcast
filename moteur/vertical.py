"""Shorts / Reels verticaux (1080x1920) tirés de l'épisode, même DA que le teaser du podcast.

Image : rushs 4K recadrés en 9:16 sur le visage, un mouvement lent par plan et un saut de cadre (large / serré)
à chaque coupe ; les blancs de parole sont resserrés (jump cuts cachés par le changement de cadre).
Les rushs ont déjà le rendu de l'export (écart mesuré 2-5 / 255 : pas d'étalonnage appliqué dans Premiere).
Son : micros v2 (son_v2.py), voix à -14 LUFS (réseaux), musique Mixkit dessous, bruitages teaser_son.
Habillage : logo de l'émission, accroche en haut, sous-titres mot à mot Lato MAJUSCULES (mots clés
Lato Black vert ou blanc, halo + ombre portée comme le teaser), B-roll en écran partagé (haut), carton de fin
noir + logo sur l'impact.

Usage : python vertical.py sessions/shorts_exemple2.json [début du nom d'un short …]
"""
import json
import os
import random
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
import pyloudnorm as pyln
import soundfile as sf
from PIL import Image, ImageDraw, ImageFilter, ImageFont

import teaser
import travail
import teaser_son as ts

ROOT = Path(__file__).parent
W, H, FPS = 1080, 1920, 25
GREEN = teaser.GREEN
ACCENT = (14, 157, 138)  # spec « couleur » : remplace le vert de la DA Exemple
USE_LOGO = True  # spec « logo » : false pour une émission sans logo de l'émission
HOOK_Y = 0.135  # spec « accroche_y » : hauteur de l'accroche (0.49 : sous le menton quand le rush remplit le cadre)
LOGO_MARGE = 0.045  # spec « logo_marge » : retrait du logo depuis le bord droit
GRADES = {}  # spec « etalonnage_cams » : {nom de fichier: filtre} (une colo par caméra)
LOGO_POS = "haut"  # spec « logo_position » : "bas" = centré tout en bas, opaque (réf. Reels CRAIE, 11/11/2026)
GRADE = ""  # spec « etalonnage » : filtre ffmpeg appliqué aux rushs (même courbe que le format long)
EXACT = "accurate_rnd+full_chroma_int"
WHITE = teaser.WHITE
LATO, LATO_BLACK = teaser.FONTS[False], teaser.FONTS[True]
OSWALD = ROOT / "fonts/Oswald.ttf"
LOGO = ROOT / "assets/logo/logo blanc.png"
SR = 48000

GAP = 0.40  # silence retiré au-delà (s)
SILENCE_DB = -30.0  # micro v2 : pauses entre -35 et -60 dB, parole au-dessus de -27
PAD = (0.08, 0.14)  # marge gardée avant le 1er mot / après le dernier mot d'un morceau
COUPER_EUH = os.environ.get("MONTAGE_EUH", "1") != "0"  # retire les « euh » des shorts (désactivable par extrait : "couper_euh": false)
MAX_PLAN = 6.5  # un plan plus long est coupé sur la plus grande respiration (sans couper de son)
MOVES = [(1.00, 1.05), (1.24, 1.29), (1.08, 1.13), (1.32, 1.37)]  # large / serré en alternance
EYES = 0.30  # hauteur des yeux dans le cadre
DA = None  # spec « da » : "craie" = habillage DA CRAIE (Inter + DK Crayon Crumble, EggShell, Deep Mocha, Blaze Orange)
CRAYON = "fonts/DKCrayonCrumble.ttf"
EGG, MOCHA, BLAZE = (233, 226, 208), (57, 48, 41), (247, 92, 3)
SUBSTYLE = None  # spec « sous_titres » : style Premiere (ex. ST REEL CRAIE), sinon style teaser Lato
SUB_Y = 0.665  # centre du bloc de sous-titres (plein écran) ; écran partagé : sur la jonction
NORM, BIG = (0.040, False), (0.060, True)
LINE_W = 0.80  # largeur max d'une ligne de sous-titres
SLIDE = 0.55
TRANS = 5
END = 2.2  # carton de fin (s)
VOICE_LUFS = -14.0

# réglages venus de la spec (pack + projet) : configurer() repart de ces valeurs à chaque appel
_REGLABLES = ("GREEN", "ACCENT", "USE_LOGO", "HOOK_Y", "LOGO_MARGE", "LOGO_POS", "GRADE", "LOGO", "EYES", "DA",
              "CRAYON", "EGG", "MOCHA", "BLAZE", "SUBSTYLE")
_DEFAUTS = {k: globals()[k] for k in _REGLABLES}


@lru_cache(maxsize=None)
@lru_cache(maxsize=None)
def vfont(path, size, wght, opsz):
    """police variable (Inter) : graisse et taille optique réglées comme dans Premiere (« Inter 18pt ExtraLight »)"""
    f = ImageFont.truetype(str(ROOT / path), size)
    try:
        f.set_variation_by_axes([opsz, wght])
    except Exception:
        pass
    return f


def disp(w):
    """mot affiché : MAJUSCULES (style teaser) ou casse d'origine (spec sous_titres.casse = "normale")"""
    if SUBSTYLE and SUBSTYLE.get("casse") == "normale":
        return w[3].strip(",.;:…") if len(w) > 3 else w[0]
    return w[0]


def tlen(f, w):
    """largeur avec l'approche (tracking Premiere en millièmes d'em)"""
    tr = SUBSTYLE.get("approche", 0) / 1000 * f.size if SUBSTYLE else 0
    return f.getlength(w) + tr * len(w)


def ttext(d, xy, w, f, fill):
    tr = SUBSTYLE.get("approche", 0) / 1000 * f.size if SUBSTYLE else 0
    if not tr:
        d.text(xy, w, font=f, fill=fill)
        return
    x, y = xy
    for ch in w:
        d.text((x, y), ch, font=f, fill=fill)
        x += f.getlength(ch) + tr



def progres(f):
    """avancement (0-1) lu par l'app pour sa jauge (fichier donné par MONTAGE_PROGRES)"""
    import os
    p = os.environ.get("MONTAGE_PROGRES")
    if p:
        try:
            Path(p).write_text(f"{f:.3f}")
        except OSError:
            pass


def font(path, size):
    """police absente (version partagée sans les polices sous licence) : police manuscrite libre à la place"""
    if not Path(path).is_file():
        path = ROOT / "fonts/Kalam-Bold.ttf"
    return ImageFont.truetype(str(path), size)


def load(spec):
    cfg = json.loads((ROOT / spec["session"]).read_text())
    work = travail.dossier(cfg["name"])
    sync = json.loads((work / "sync.json").read_text())["cams"]
    sentences = json.loads((work / "transcript.json").read_text())
    mics = {k: v.replace("(-16 LUFS)", "(v2 automix)") for k, v in cfg["son"]["mics"].items()}
    return cfg, sync, sentences, mics


def cam_for(sync, speaker, t):
    """caméra serrée de ce locuteur qui filme à l'instant t (micro)"""
    for k, v in sync.items():
        if v.get("cam", k).startswith(speaker) and v["covers_mic_s"][0] <= t <= v["covers_mic_s"][1] and k != "LARGE":
            return k
    raise LookupError((speaker, t))


# ---------- découpage ----------

def words_fixed(sentences, speaker, a, b, fix):
    """mots de l'extrait, corrigés : « corrections » remplace une suite de mots (même nombre de mots, « _ » pour en coller deux),
    « ajouts » insère des mots oubliés par la transcription après un mot, répartis dans le blanc qui suit"""
    words = teaser.words_of(sentences, speaker, a, b)
    for src, dst in fix.get("corrections", {}).items():
        src_t, dst_t = src.split(), dst.split()
        assert len(src_t) == len(dst_t), src
        for i in range(len(words) - len(src_t) + 1):
            if [teaser.clean(w[0]) for w in words[i:i + len(src_t)]] == src_t:
                for k, d in enumerate(dst_t):
                    w = words[i + k]
                    tail = w[0][len(w[0].rstrip(",.;:!?…")):]
                    words[i + k] = (d.replace("_", " ") + tail, w[1], w[2])  # « _ » : deux mots affichés pour un mot transcrit
    for add in fix.get("ajouts", []):
        i = next((i for i, w in enumerate(words) if teaser.clean(w[0]) == add["apres"]), None)
        if i is None or i + 1 >= len(words):
            continue
        t0, t1 = words[i][2], words[i + 1][1]
        new = add["texte"].split()
        step = (t1 - t0) / (len(new) + 1)
        words[i + 1:i + 1] = [(x, t0 + (k + 0.5) * step, t0 + (k + 1) * step) for k, x in enumerate(new)]
    return words


_mic = {}


def silence_in(path, a, b, thr_db=SILENCE_DB):
    """plus longue plage vraiment muette du micro entre a et b -> (début, fin) ou None.
    Les temps de mots de la transcription ne suffisent pas : un mot prolongé ou oublié tombe souvent dans un « blanc »."""
    if path not in _mic:
        _mic[path] = sf.SoundFile(path)
    f = _mic[path]
    f.seek(int(a * f.samplerate))
    x = f.read(max(1, int((b - a) * f.samplerate)), dtype="float32", always_2d=True).mean(1)
    hop = int(0.01 * f.samplerate)
    n = len(x) // hop
    if n < 5:
        return None
    rms = np.sqrt((x[:n * hop].reshape(n, hop) ** 2).mean(1))
    quiet = np.convolve(20 * np.log10(rms + 1e-9) < thr_db, np.ones(3), "same") == 3  # 30 ms d'affilée
    best, run = None, None
    for i, q in enumerate(list(quiet) + [False]):
        if q and run is None:
            run = i
        elif not q and run is not None:
            if best is None or i - run > best[1] - best[0]:
                best = (run, i)
            run = None
    return (a + best[0] * 0.01, a + best[1] * 0.01) if best else None


def plans_of(ex, sentences, speaker, fix, mic):
    """morceaux de parole (temps micro) d'un extrait, blancs > GAP retirés (s'ils sont vraiment muets),
    puis plans de MAX_PLAN au plus"""
    a, b = ex["rush"]
    words = words_fixed(sentences, speaker, a, b, fix)
    if not ex.get("resserrer", True):
        chunks = [[a, b, words]]
    else:
        # on coupe les vrais silences de plus de GAP, en gardant PAD de part et d'autre
        chunks = [[a, None, [words[0]]]] if words else []
        for w0, w in zip(words, words[1:]):
            q = silence_in(mic, w0[2] - 0.15, w[1] + 0.05) if w[1] - w0[2] > 0.25 else None
            if q and q[1] - q[0] > GAP + PAD[0] + PAD[1]:
                chunks[-1][1] = q[0] + PAD[1]
                chunks.append([q[1] - PAD[0], None, [w]])
            else:
                chunks[-1][2].append(w)
        if chunks:
            chunks[0][0] = max(a, words[0][1] - PAD[0])
            chunks[-1][1] = min(b, words[-1][2] + PAD[1])
        if chunks and ex.get("couper_euh", COUPER_EUH):  # « euh » retirés (effacés du transcript, retrouvés dans le son)
            import euh
            cuts_h = euh.hesitations(mic, a, b, cache_dir=Path(mic).parent, mots=words)
            split = []
            for c0, c1, ws in chunks:
                for h0, h1 in cuts_h:
                    if c0 + 0.1 < h0 and h1 < c1 - 0.1:
                        split.append([c0, h0, [w for w in ws if w[1] < h0]])
                        ws = [w for w in ws if w[1] >= h0]
                        c0 = h1
                split.append([c0, c1, ws])
            chunks = [c for c in split if c[1] - c[0] > 0.05]
    # mots imposés pour couper (« zoom_sur », comme le teaser), puis coupe des plans trop longs
    forced = []
    for c in ex.get("zoom_sur", []):
        wd, _, k = c.partition("@")
        hits = [s for t_, s, _ in words if teaser.clean(t_) == teaser.clean(wd)]
        forced.append(hits[int(k or 1) - 1] - 0.06)
    out = []
    for c0, c1, ws in chunks:
        cuts = sorted(x for x in forced if c0 + 0.8 < x < c1 - 0.8)
        bounds = [c0, *cuts, c1]
        for x0, x1 in zip(bounds, bounds[1:]):
            todo = [(x0, x1)]
            while todo:
                y0, y1 = todo.pop(0)
                if y1 - y0 <= MAX_PLAN:
                    out.append((y0, y1))
                    continue
                inner = [w for w in ws if y0 + 1.5 < w[1] < y1 - 1.5]
                if not inner:
                    out.append((y0, y1))
                    continue
                prev = {id(w): p for p, w in zip(ws, ws[1:])}
                best = max(inner, key=lambda w: (w[1] - prev[id(w)][2] if id(w) in prev else 0)
                           - 0.05 * abs(w[1] - (y0 + y1) / 2))
                m = best[1] - 0.04
                todo[:0] = [(y0, m), (m, y1)]
    return [(round(x * FPS) / FPS, round(y * FPS) / FPS) for x, y in out if y - x >= 2 / FPS]


# ---------- image ----------

class Cam:
    """lit un rush à partir d'un temps micro, recadré en bande verticale autour du visage"""

    def __init__(self, sync, key, face):
        sc = sync[key]
        self.sc, self.path = sc, sc["path"]
        info = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                               "-of", "csv=p=0", self.path], capture_output=True, text=True).stdout.strip().split(",")
        self.sw, self.sh = int(info[0]), int(info[1])
        self.face = face
        bw = round(self.sh * 9 / 16) // 2 * 2
        self.bx = int(min(max(face[0] * self.sw - bw / 2, 0), self.sw - bw)) // 2 * 2
        self.bw = bw

    def frames(self, t, n):
        ct = (t - self.sc["offset_s"]) / (1 + self.sc["drift_ppm"] * 1e-6)
        gr = (GRADES[Path(self.path).stem] + ",") if GRADES.get(Path(self.path).stem) else GRADE
        p = subprocess.Popen(["ffmpeg", "-v", "error", "-ss", f"{ct:.4f}", "-i", self.path, "-frames:v", str(n), "-an",
                              "-vf", f"crop={self.bw}:{self.sh}:{self.bx}:0,{gr}scale=flags={EXACT}:in_color_matrix=bt709:in_range=tv" if gr
                              else f"crop={self.bw}:{self.sh}:{self.bx}:0,scale=in_color_matrix=bt709:in_range=tv",
                              *(["-sws_flags", EXACT] if gr else []), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        size = self.bw * self.sh * 3
        for _ in range(n):
            buf = p.stdout.read(size)
            if len(buf) < size:
                break
            yield np.frombuffer(buf, np.uint8).reshape(self.sh, self.bw, 3)
        p.stdout.close()
        p.wait()

    def view(self, img, z, out_w, out_h, eyes=None):
        eyes = EYES if eyes is None else eyes
        """fenêtre au zoom z (1 = toute la hauteur), visage centré, yeux à « eyes » du haut"""
        wh = min(self.sh / z, self.bw / z * out_h / out_w)
        ww = wh * out_w / out_h
        fx = self.face[0] * self.sw - self.bx
        fy = self.face[1] * self.sh
        x = min(max(fx - ww / 2, 0), self.bw - ww)
        y = min(max(fy - eyes * wh, 0), self.sh - wh)
        s = out_w / ww
        m = np.float32([[s, 0, -x * s], [0, s, -y * s]])
        return cv2.warpAffine(img, m, (out_w, out_h), flags=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC,
                              borderMode=cv2.BORDER_REFLECT)


def broll_frames(path, start, n):
    """B-roll recadré pour la moitié haute (1080 x 960), poussée lente"""
    w, h = W, H // 2
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-ss", f"{start:.3f}", "-i", str(ROOT / path), "-frames:v", str(n), "-an",
                          "-vf", f"fps={FPS},scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,crop={w}:{h}",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    last = None
    for k in range(n):
        buf = p.stdout.read(w * h * 3)
        if len(buf) == w * h * 3:
            last = np.frombuffer(buf, np.uint8).reshape(h, w, 3)
        z = 1 + 0.06 * k / max(n - 1, 1)
        m = np.float32([[z, 0, (1 - z) * w / 2], [0, z, (1 - z) * h / 2]])
        yield cv2.warpAffine(last, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
    p.stdout.close()
    p.wait()


# ---------- texte ----------

def vlayout(words, keys):
    """lignes du teaser regroupées pour le vertical : lignes pleines (LINE_W), mot clé en gros sur sa ligne,
    2 lignes par page au plus, nouvelle page après une fin de phrase"""
    f = font(LATO, int(H * NORM[0]))
    lines = []
    for ln in (x for pg in teaser.layout(words, keys) for x in pg):
        prev = lines[-1] if lines else None
        if (not ln["key"] and prev and not prev["key"] and not prev["words"][-1][3].endswith((".", "?", "!"))
                and f.getlength(" ".join(w[0] for w in prev["words"] + ln["words"])) <= W * LINE_W):
            prev["words"] = prev["words"] + ln["words"]
        else:
            lines.append(dict(ln))
    pages, cur = [], []
    for ln in lines:
        cur.append(ln)
        if len(cur) == 2 or ln["words"][-1][3].endswith((".", "?", "!")):
            pages.append(cur)
            cur = []
    return pages + ([cur] if cur else [])


def shadowed(txt):
    """halo gris large + ombre portée douce, comme le teaser"""
    a = txt.getchannel("A")
    halo = a.filter(ImageFilter.GaussianBlur(H * 0.012)).point(lambda v: min(150, int(v * 1.6)))
    drop = a.filter(ImageFilter.GaussianBlur(H * 0.003)).point(lambda v: int(v * 0.75))
    shade = Image.new("L", a.size)
    shade.paste(drop, (round(H * 0.0025), round(H * 0.0032)))
    sh = Image.new("RGBA", txt.size, (12, 10, 10, 0))
    sh.putalpha(Image.fromarray(np.maximum(np.asarray(halo), np.asarray(shade))))
    return Image.alpha_composite(sh, txt)


def sub_events(bites):
    """pages de sous-titres -> [(début, fin, [(mot, apparition, police, couleur, n° ligne)], lignes)]"""
    events = []
    for b in bites:
        for pi, page in enumerate(b["pages"]):
            nxt = b["pages"][pi + 1][0]["words"][0][1] if pi + 1 < len(b["pages"]) else None
            items, lines = [], []
            for li, ln in enumerate(page):
                styles = [BIG if ln["key"] and j >= ln.get("from", 0) else NORM for j in range(len(ln["words"]))]
                if SUBSTYLE:
                    st = SUBSTYLE
                    fonts = [vfont(st["police"], int(st["taille"] * (st.get("echelle_cle", 1.0) if bold else 1.0)),
                                   st.get("graisse_cle", st["graisse"]) if bold else st["graisse"], st.get("optique", 18))
                             for _s, bold in styles]
                else:
                    fonts = [font(LATO_BLACK if bold else LATO, int(H * s)) for s, bold in styles]
                width = sum(tlen(f, disp(w) + " ") for f, w in zip(fonts, ln["words"])) - tlen(fonts[-1], " ")
                if width > W * 0.86:
                    k = W * 0.86 / width
                    fonts = ([vfont(SUBSTYLE["police"], int(f.size * k), SUBSTYLE["graisse"], SUBSTYLE.get("optique", 18)) for f in fonts]
                             if SUBSTYLE else [font(LATO_BLACK if bold else LATO, int(f.size * k)) for f, (_, bold) in zip(fonts, styles)])
                    width *= k
                lines.append((width, max(f.size for f in fonts)))
                for j, (w, f) in enumerate(zip(ln["words"], fonts)):
                    key = ln["key"] and j >= ln.get("from", 0)
                    col = (GREEN if ln["key"] == "vert" else WHITE) if key else WHITE
                    items.append((disp(w), b["map"](w[1]), f, col, li))
            start = b["map"](page[0]["words"][0][1])
            end = b["map"](nxt) if nxt is not None else b["seq_end"]
            events.append((start, min(end, b["seq_end"]), items, lines))
    return events


def draw_subs(ev, t, cy):
    _, _, items, lines = ev
    img = Image.new("RGBA", (W, H))
    d = ImageDraw.Draw(img)
    inter = SUBSTYLE.get("interligne", 1.06) if SUBSTYLE else 1.06
    total = sum(h * inter for _, h in lines)
    if SUBSTYLE and cy == H * SUB_Y:  # plein écran : bloc posé en bas (zone bas-centre de Premiere)
        y = H - SUBSTYLE["y_bas"] - total
    else:
        y = cy - total / 2
    xs = {}
    for li, (wd, h) in enumerate(lines):
        # la ligne se recentre à mesure que ses mots apparaissent
        shown = [(w, f) for w, s, f, _, l in items if l == li and s <= t]
        wd = sum(tlen(f, w + " ") for w, f in shown) - (tlen(shown[-1][1], " ") if shown else 0)
        xs[li] = [(W - wd) / 2 + (SUBSTYLE.get("x", 0) if SUBSTYLE else 0), y, h]
        y += h * inter
    for w, s, f, col, li in items:
        x, y, h = xs[li]
        if s <= t:
            age = min(teaser.POP, int((t - s) * FPS))
            a = int(255 * (0.4 + 0.6 * age / teaser.POP))
            dy = (teaser.POP - age) * f.size * 0.04
            ttext(d, (x, y + h - f.size + dy), w, f, col + (a,))
        xs[li][0] = x + tlen(f, w + " ")
    return shadowed(img)


def hook_layer(lines, p):
    """accroche en haut (2 à 3 lignes, mot clé entre * en vert), apparition rapide"""
    img = Image.new("RGBA", (W, H))
    d = ImageDraw.Draw(img)
    y = H * HOOK_Y
    a = int(255 * min(1.0, p * 4))
    for ln in lines:
        parts = [(s, i % 2 == 1) for i, s in enumerate(ln.split("*")) if s]
        size = int(H * 0.040)
        f = font(LATO_BLACK, size)
        wd = sum(f.getlength(s) for s, _ in parts)
        if wd > W * 0.88:
            f = font(LATO_BLACK, int(size * W * 0.88 / wd))
            wd = W * 0.88
        x = (W - wd) / 2
        dy = (1 - min(1.0, p * 4)) * 12
        for s, green in parts:
            d.text((x, y + dy), s, font=f, fill=(GREEN if green else WHITE) + (a,))
            x += f.getlength(s)
        y += f.size * 1.12
    return shadowed(img)


def incrust_layer(it, p):
    """incrustation (spec short « incrustations ») : carte sombre arrondie, barre de couleur à gauche,
    1re ligne en couleur (Oswald), suivantes en blanc ; glisse vers le haut en apparaissant"""
    img = Image.new("RGBA", (W, H))
    d = ImageDraw.Draw(img)
    lines = it["lignes"]
    fs = [font(OSWALD, int(H * (0.047 if i == 0 else 0.031))) for i in range(len(lines))]
    for i, ln in enumerate(lines):
        if fs[i].getlength(ln) > W * 0.80:
            fs[i] = font(OSWALD, int(fs[i].size * W * 0.80 / fs[i].getlength(ln)))
    wd = max(f.getlength(ln) for f, ln in zip(fs, lines))
    ht = sum(f.size * 1.25 for f in fs)
    pad = int(W * 0.035)
    bw, bh = wd + 2 * pad + 14, ht + 1.4 * pad
    x0 = (W - bw) / 2
    y0 = H * it.get("y", 0.415) + (1 - p) * 30
    a = p
    d.rounded_rectangle((x0, y0, x0 + bw, y0 + bh), radius=int(pad * 0.7), fill=(12, 12, 12, int(205 * a)))
    d.rounded_rectangle((x0, y0, x0 + 12, y0 + bh), radius=6, fill=ACCENT + (int(255 * a),))
    y = y0 + 0.7 * pad
    for i, (f, ln) in enumerate(zip(fs, lines)):
        col = ACCENT if i == 0 else (255, 255, 255)
        d.text((x0 + 14 + pad, y), ln, font=f, fill=col + (int(255 * a),))
        y += f.size * 1.25
    return img


def ease(x):
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def soft_shadow(img, r=10, a=0.55):
    """ombre douce sous un calque texte (lisibilité sans boîte)"""
    al = img.getchannel("A").filter(ImageFilter.GaussianBlur(r)).point(lambda v: int(v * a))
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    sh.putalpha(al)
    out = Image.new("RGBA", img.size)
    out.alpha_composite(sh, (0, 3))
    out.alpha_composite(img)
    return out


@lru_cache(maxsize=None)
def craie_vignette():
    """dégradés Deep Mocha haut (accroche, logo, incrustations) et bas (sous-titres), comme les covers CRAIE"""
    g = np.zeros((H, W, 4), np.uint8)
    g[..., :3] = (20, 16, 13)
    y = np.arange(H) / H
    top = np.clip(1 - y / 0.34, 0, 1) ** 1.3 * 0.72
    bot = np.clip((y - 0.46) / 0.54, 0, 1) ** 1.15 * 0.72
    g[..., 3] = (np.maximum(top, bot)[:, None] * 255).astype(np.uint8)
    return Image.fromarray(g, "RGBA")


def clen(f, t, sp):
    """largeur d'un texte crayon avec l'espace de l'Inter (l'espace du DK Crayon Crumble est trop large)"""
    ws = t.split(" ")
    return sum(f.getlength(w) for w in ws) + sp * (len(ws) - 1)


def craie_hook(lines, p):
    """accroche DA CRAIE : Inter Black blanc, mot entre * en DK Crayon Crumble orange qui s'écrit de gauche à droite"""
    img = Image.new("RGBA", (W, H))
    size = int(H * 0.040)
    fi = vfont("fonts/Inter.ttf", size, 900, 32)
    fc = font(ROOT / CRAYON, int(size * 1.45))
    y = H * HOOK_Y
    for li, ln in enumerate(lines):
        q = ease((p - 0.12 * li) / 0.6)
        parts = [(t, i % 2 == 1) for i, t in enumerate(ln.split("*")) if t]
        sp0 = fi.getlength(" ")
        wd = sum(clen(fc, t, sp0) if k else fi.getlength(t) for t, k in parts)
        scale = min(1.0, W * 0.86 / wd) if wd else 1.0
        f_i = vfont("fonts/Inter.ttf", int(size * scale), 900, 32) if scale < 1 else fi
        f_c = font(ROOT / CRAYON, int(size * 1.45 * scale)) if scale < 1 else fc
        sp = f_i.getlength(" ")
        wd = sum(clen(f_c, t, sp) if k else f_i.getlength(t) for t, k in parts)
        x = (W - wd) / 2
        dy = (1 - q) * 18
        lh = f_i.size * 1.18
        for t, k in parts:
            f = f_c if k else f_i
            layer = Image.new("RGBA", (W, H))
            # même ligne de base pour l'Inter et le crayon (ancrage « ls » = gauche / ligne de base)
            base = y + dy + f_i.getmetrics()[0]
            dl = ImageDraw.Draw(layer)
            col = (BLAZE if k else (255, 255, 255)) + (255,)
            if k:
                xx = x
                for w_ in t.split(" "):
                    dl.text((xx, base), w_, font=f, anchor="ls", fill=col)
                    xx += f.getlength(w_) + sp
            else:
                dl.text((x, base), t, font=f, anchor="ls", fill=col)
            a = layer.getchannel("A").point(lambda v, q=q: int(v * q))
            if k:  # écriture : révélé de gauche à droite
                rv = ease((p - 0.25 - 0.12 * li) / 0.6)
                cut = int(x + clen(f, t, sp) * rv)
                m = Image.new("L", (W, H), 0)
                ImageDraw.Draw(m).rectangle((0, 0, cut, H), fill=255)
                a = Image.composite(a, m.point(lambda v: 0), m)
            layer.putalpha(a)
            img.alpha_composite(layer)
            x += clen(f, t, sp) if k else f.getlength(t)
        y += lh
    return soft_shadow(img, 12, 0.6)


@lru_cache(maxsize=None)
def photo_tirage(path, w):
    """photo recadrée 4:5 sur le haut (visage), bord EggShell façon tirage"""
    im = Image.open(ROOT / path).convert("RGB")
    tw, th = im.width, int(im.width * 1.2)
    im = im.crop((0, 0, tw, min(th, im.height)))
    h = int(w * 1.2)
    im = im.resize((w, h), Image.LANCZOS)
    b = max(6, w // 40)
    card = Image.new("RGBA", (w + 2 * b, h + 2 * b), EGG + (255,))
    card.paste(im, (b, b))
    return card


def craie_photo(it, p, t_rel):
    """incrustation photo DA CRAIE : tirage légèrement incliné en haut à gauche, nom au crayon, crédit discret"""
    img = Image.new("RGBA", (W, H))
    w = int(W * it.get("largeur", 0.30))
    card = photo_tirage(it["image"], w)
    k = ease(t_rel / 0.45)
    sc = 0.9 + 0.1 * k
    c2 = card.resize((int(card.width * sc), int(card.height * sc)), Image.LANCZOS)
    droite = it.get("cote", "droite") == "droite"
    c2 = c2.rotate(it.get("angle", 3.5 if droite else -2.5), resample=Image.BICUBIC, expand=True)
    a = k * p
    c2.putalpha(c2.getchannel("A").point(lambda v: int(v * a)))
    centre = it.get("cote") == "centre"
    y0 = int(H * it.get("y", 0.115))
    x0 = (W - c2.width) // 2 + int(W * it.get("decalage_x", 0)) if centre else (int(W * (1 - 0.06)) - c2.width if droite else int(W * it.get("x", 0.07)))
    xr = x0 + c2.width - 6  # bord droit pour aligner les légendes à droite
    def lx(wd):  # x d'une légende selon la position
        return (W - wd) / 2 if centre else ((xr - wd) if droite else x0 + 6)
    sh = Image.new("RGBA", c2.size, (0, 0, 0, 0))
    sh.putalpha(c2.getchannel("A").filter(ImageFilter.GaussianBlur(18)).point(lambda v: int(v * 0.55)))
    img.alpha_composite(sh, (x0 + 8, y0 + 14))
    img.alpha_composite(c2, (x0, y0))
    d = ImageDraw.Draw(img)
    fc = font(ROOT / CRAYON, int(H * 0.040))
    sp = fc.size * 0.26
    ty = y0 + c2.height + 6
    q = ease((t_rel - 0.25) / 0.4) * p
    xx = lx(clen(fc, it["lignes"][0], sp))
    for w_ in it["lignes"][0].split(" "):
        d.text((xx, ty), w_, font=fc, fill=BLAZE + (int(255 * q),))
        xx += fc.getlength(w_) + sp
    ty += fc.size * 1.05
    fi = vfont("fonts/Inter.ttf", int(H * 0.015), 500, 14)
    for ln in it["lignes"][1:]:
        t_ = ln.upper()
        d.text((lx(fi.getlength(t_)), ty), t_, font=fi, fill=EGG + (int(230 * q),))
        ty += fi.size * 1.5
    if it.get("credit"):
        fcr = vfont("fonts/Inter.ttf", int(H * 0.0105), 400, 14)
        d.text((lx(fcr.getlength(it["credit"])), ty + 2), it["credit"], font=fcr, fill=EGG + (int(170 * q),))
    return soft_shadow(img, 12, 0.6)


def craie_incrust(it, p, t_rel):
    """incrustation DA CRAIE, en haut à gauche, sans boîte : trait EggShell qui se dessine, info principale en
    DK Crayon Crumble orange (révélée comme écrite), précision en Inter capitales espacées EggShell"""
    img = Image.new("RGBA", (W, H))
    d = ImageDraw.Draw(img)
    x0 = W * it.get("x", 0.075)
    y0 = H * it.get("y", 0.105)
    lines = it["lignes"]
    a_out = p  # p : 1 pendant l'affichage, descend à 0 en sortie
    k1 = ease(t_rel / 0.35)
    d.rectangle((x0, y0, x0 + W * 0.11 * k1, y0 + 3), fill=EGG + (int(235 * a_out),))
    fc = font(ROOT / CRAYON, int(H * 0.052))
    sp = fc.size * 0.26
    if clen(fc, lines[0], sp) > W * 0.82:
        fc = font(ROOT / CRAYON, int(fc.size * W * 0.82 / clen(fc, lines[0], sp)))
        sp = fc.size * 0.26
    ty = y0 + 14
    layer = Image.new("RGBA", (W, H))
    dl = ImageDraw.Draw(layer)
    xx = x0 - 2
    for w_ in lines[0].split(" "):
        dl.text((xx, ty), w_, font=fc, fill=BLAZE + (255,))
        xx += fc.getlength(w_) + sp
    rv = ease((t_rel - 0.15) / 0.55)
    m = Image.new("L", (W, H), 0)
    ImageDraw.Draw(m).rectangle((0, 0, int(x0 + clen(fc, lines[0], sp) * rv) + 2, H), fill=int(255 * a_out))
    layer.putalpha(Image.composite(layer.getchannel("A"), Image.new("L", (W, H), 0), m))
    img.alpha_composite(layer)
    ty += fc.size * 1.02
    fi = vfont("fonts/Inter.ttf", int(H * 0.0175), 500, 14)
    q = ease((t_rel - 0.45) / 0.4) * a_out
    for ln in lines[1:]:
        tr = 0.12 * fi.size
        xx = x0
        for ch in ln.upper():
            d.text((xx, ty + (1 - q) * 8), ch, font=fi, fill=EGG + (int(240 * q),))
            xx += fi.getlength(ch) + tr
        ty += fi.size * 1.6
    return soft_shadow(img, 14, 0.75)


def craie_end(k, n, lines):
    """carton de fin DA CRAIE : Deep Mocha, logo du pack (la maison EggShell chez CRAIE) qui s'installe, texte crayon
    + Inter"""
    frame = Image.new("RGBA", (W, H), MOCHA + (255,))
    p = ease(k / 14)
    if USE_LOGO:
        lg = Image.open(LOGO).convert("RGBA")
        lw = int(W * (0.40 + 0.03 * (1 - p)))
        im = lg.resize((lw, int(lg.height * lw / lg.width)), Image.LANCZOS)
        im.putalpha(im.getchannel("A").point(lambda v: int(v * p)))
        frame.alpha_composite(im, ((W - im.width) // 2, int(H * 0.36 - im.height / 2 + (1 - p) * 20)))
    d = ImageDraw.Draw(frame)
    y = H * 0.56
    if lines:
        fc = font(ROOT / CRAYON, int(H * 0.058))
        if fc.getlength(lines[0]) > W * 0.86:
            fc = font(ROOT / CRAYON, int(fc.size * W * 0.86 / fc.getlength(lines[0])))
        q = ease((k - 6) / 10)
        d.text(((W - fc.getlength(lines[0])) / 2, y + (1 - q) * 12), lines[0], font=fc, fill=BLAZE + (int(255 * q),))
        y += fc.size * 1.15
        fi = vfont("fonts/Inter.ttf", int(H * 0.017), 500, 14)
        q = ease((k - 10) / 10)
        for ln in lines[1:]:
            tr = 0.14 * fi.size
            wd = sum(fi.getlength(ch) + tr for ch in ln.upper()) - tr
            xx = (W - wd) / 2
            for ch in ln.upper():
                d.text((xx, y), ch, font=fi, fill=EGG + (int(235 * q),))
                xx += fi.getlength(ch) + tr
            y += fi.size * 1.7
    return np.asarray(frame.convert("RGB"))


def incrust_times(items, events):
    """résout les ancres : « mot » (n-ième apparition du mot dans les sous-titres) ou « debut » (s)"""
    out = []
    for it in items:
        t0 = it.get("debut")
        if "mot" in it:
            hits = [s for e in events for (w, s, *_r) in e[2] if it["mot"].upper() in w.upper()]
            hits = [h for h in hits if h >= it.get("apres", 0)]
            if not hits:
                print("incrustation : mot introuvable", it["mot"])
                continue
            t0 = hits[min(it.get("occurrence", 1), len(hits)) - 1] + it.get("decalage", 0)
        t1 = t0 + it.get("duree", 3.5)
        if "fin_mot" in it:  # reste affichée jusqu'à ce mot (ex. tant qu'elle parle de lui)
            ends = [s for e in events for (w, s, *_r) in e[2] if it["fin_mot"].upper() in w.upper() and s > t0]
            if ends:
                t1 = ends[0] + it.get("fin_decalage", 0.6)
        out.append((t0, t1, it))
    return out


PLAT_START = 3.4  # le bandeau des plateformes arrive juste après l'accroche
PLATFORMS = "DISPONIBLE SUR YOUTUBE · APPLE PODCASTS · SPOTIFY"


@lru_cache(maxsize=64)
def platforms_layer(p):
    """petit bandeau discret en bas : point vert + texte, apparition en fondu qui monte légèrement"""
    p = round(p, 2)
    img = Image.new("RGBA", (W, H))
    d = ImageDraw.Draw(img)
    f = font(OSWALD, int(H * 0.0175))
    wd = f.getlength(PLATFORMS)
    r = f.size * 0.22
    x = (W - wd - 3 * r) / 2
    y = H * 0.785 + (1 - p) * 14
    a = int(225 * p)
    d.ellipse((x, y + f.size * 0.55 - r, x + 2 * r, y + f.size * 0.55 + r), fill=ACCENT + (a,))
    d.text((x + 3 * r, y), PLATFORMS, font=f, fill=(255, 255, 255, a))
    return shadowed(img)


@lru_cache(maxsize=None)
def logo_small():
    lg = Image.open(LOGO)
    w = int(W * (0.116 if LOGO_POS == "bas" else 0.13 if DA == "craie" else 0.17))
    lg = lg.resize((w, int(lg.height * w / lg.width)), Image.LANCZOS)
    if LOGO_POS != "bas":
        lg.putalpha(lg.getchannel("A").point(lambda v: int(v * (0.92 if DA == "craie" else 0.85))))
    return lg


def end_card(k, n, lines):
    """noir, le logo arrive sur l'impact, puis le texte de fin"""
    frame = Image.new("RGB", (W, H), (0, 0, 0))
    if USE_LOGO:
        lg = Image.open(LOGO)
        p = min(1.0, k / 12)
        e = 1 - (1 - p) ** 3
        s = 1.10 - 0.10 * e + 0.02 * k / n
        lw = int(W * 0.62 * s)
        im = lg.resize((lw, int(lg.height * lw / lg.width)), Image.BILINEAR)
        a = min(1.0, k / 3)
        frame.paste(im.convert("RGB"), ((W - im.width) // 2, int(H * 0.40 - im.height / 2)),
                    im.getchannel("A").point(lambda v: int(v * a)))
    if k >= 8:
        d = ImageDraw.Draw(frame)
        q = min(1.0, (k - 8) / 6)
        y = H * (0.57 if USE_LOGO else 0.45)
        for i, ln in enumerate(lines):
            f = font(OSWALD, int(H * (0.042 if i == 0 else 0.032)))
            if f.getlength(ln) > W * 0.88:
                f = font(OSWALD, int(f.size * W * 0.88 / f.getlength(ln)))
            col = tuple(int(c * q) for c in (ACCENT if i == 0 else (255, 255, 255)))
            d.text(((W - f.getlength(ln)) / 2, y), ln, font=f, fill=col)
            y += f.size * 1.35
    return np.asarray(frame)


# ---------- rendu ----------

def configurer(spec, sh):
    """règle le rendu d'après la spec (réglages du pack + du projet) et le short. Fichiers (polices, logo, musique) :
    chemins relatifs au dossier du moteur, ou absolus (fichiers d'un pack : ROOT / chemin absolu = ce chemin, aussi
    sous Windows). Repart à chaque appel des valeurs par défaut du module : l'app dessine dans le même processus des
    aperçus de packs différents (moteur/apercu_pack.py)."""
    global GREEN, ACCENT, USE_LOGO, GRADE, HOOK_Y, LOGO_MARGE, LOGO_POS, SUBSTYLE, DA, LOGO, EYES, CRAYON, EGG, MOCHA, BLAZE
    globals().update(_DEFAUTS)
    GRADES.clear()
    GRADES.update(spec.get("etalonnage_cams") or {})
    LOGO_POS = spec.get("logo_position", "haut")
    if "couleur" in spec:
        GREEN = ACCENT = tuple(spec["couleur"])
    USE_LOGO = spec.get("logo", True)
    HOOK_Y = spec.get("accroche_y", 0.135)
    LOGO_MARGE = spec.get("logo_marge", 0.045)
    GRADE = spec["etalonnage"] + "," if spec.get("etalonnage") else ""
    BLAZE = tuple(spec.get("couleur", BLAZE))
    CRAYON = spec.get("police_accent", CRAYON)
    EGG = tuple(spec.get("teintes", {}).get("clair", EGG))
    MOCHA = tuple(spec.get("teintes", {}).get("fond", MOCHA))
    EYES = sh.get("yeux", spec.get("yeux", 0.30))
    SUBSTYLE = spec.get("sous_titres")
    DA = spec.get("da")
    if spec.get("logo_fichier"):
        LOGO = ROOT / spec["logo_fichier"]
    logo_small.cache_clear()


def poser_logo(im, sh):
    """logo du pack sur une image du short (USE_LOGO déjà vérifié)"""
    logo = logo_small()
    if LOGO_POS == "bas":
        im.alpha_composite(logo, ((W - logo.width) // 2, int(H * 0.97) - logo.height))
    elif sh.get("logo", "droite") == "centre":
        im.alpha_composite(logo, ((W - logo.width) // 2, int(H * 0.035)))
    else:  # en haut à droite, comme le filigrane de l'épisode (au centre il passe sous l'interface)
        im.alpha_composite(logo, (W - logo.width - int(W * LOGO_MARGE), int(H * 0.03)))


def render(spec, sh):
    configurer(spec, sh)
    cfg, sync, sentences, mics = load(spec)
    mics = sh.get("son_mics", mics)  # short hors du passage traité : il garde ses micros
    speaker = sh.get("micro", "FRED")
    faces = spec["visages"]
    out_dir = Path(spec["dossier"])
    out_dir.mkdir(exist_ok=True)
    teaser.MAX_LINES = 3

    # 1. plans
    pieces, bites, t = [], [], 0.0
    cuts, trans, j = [], [], 0
    for ei, ex in enumerate(sh["extraits"]):
        fix = {"corrections": {**spec.get("corrections", {}), **sh.get("corrections", {})}, "ajouts": sh.get("ajouts", [])}
        ps = plans_of(ex, sentences, ex.get("micro", speaker), fix, mics[ex.get("micro", speaker)])
        if not ps:
            continue
        seg = []
        for pi, (a, b) in enumerate(ps):
            n = round((b - a) * FPS)
            key = cam_for(sync, ex.get("cam", ex.get("micro", speaker)), a)  # « cam » : montrer quelqu'un qui écoute
            pieces.append({"t": t, "n": n, "mic": a, "cam": key, "z": MOVES[j % len(MOVES)],
                           "slide_in": False, "slide_out": False, "split": ex.get("split")})
            j += 1
            if pi and t not in trans:
                cuts.append(t)
            seg.append((a, b, t))
            t += n / FPS
        if ei and sh.get("glisse"):
            pieces[-len(ps)]["slide_in"] = True
            pieces[-len(ps) - 1]["slide_out"] = True
            trans.append(seg[0][2])
            cuts = [c for c in cuts if c != seg[0][2]]
        elif ei:
            cuts.append(seg[0][2])

        def mapper(seg):
            def f(x):
                for a, b, s in seg:
                    if x < b:
                        return s + max(0.0, x - a)
                return seg[-1][2] + seg[-1][1] - seg[-1][0]
            return f
        m = mapper(seg)
        words = [w for w in words_fixed(sentences, ex.get("micro", speaker), *ex["rush"], fix)
                 if any(a - 0.02 <= w[1] < b for a, b, _ in seg)]
        keys = {k.upper(): v for k, v in {**sh.get("mots_cles", {}), **ex.get("mots_cles", {})}.items()}
        bites.append({"pages": vlayout(words, keys), "map": m, "seq_start": seg[0][2], "seq_end": t, "seg": seg,
                      "words": words})
    total = t
    # sens du glissé, alterné d'une transition à l'autre : l'image sort vers d, la suivante arrive du côté opposé
    for i, x in enumerate(trans):
        d = -1 if i % 2 == 0 else 1
        for p in pieces:
            if p["slide_in"] and abs(p["t"] - x) < 1e-6:
                p["d_in"] = d
            if p["slide_out"] and abs(p["t"] + p["n"] / FPS - x) < 1e-6:
                p["d_out"] = d

    # B-roll (temps séquence) : du mot « de » au mot « a » de l'extrait n° « extrait »
    brolls = []
    for br in sh.get("broll", []):
        bt = bites[br.get("extrait", 0)]

        def at(c, first=True):
            wd, _, k = c.partition("@")
            hits = [w for w in bt["words"] if teaser.clean(w[0]) == teaser.clean(wd)]
            w = hits[int(k or 1) - 1]
            return bt["map"](w[1] if first else w[2])
        s0 = at(br["de"]) - 0.05
        s1 = at(br["a"], False) + 0.1 if br.get("a") else bt["seq_end"]
        brolls.append({"path": br["fichier"], "src": br.get("src", 0.0), "a": s0, "b": min(s1, total)})

    if VERIFY:
        found = {teaser.clean(w[0]) for b in bites for pg in b["pages"] for ln in pg if ln["key"] for w in ln["words"]}
        keys_all = {k.upper() for ex in sh["extraits"] for k in {**sh.get("mots_cles", {}), **ex.get("mots_cles", {})}}
        missing = [k for k in keys_all if not set(k.split()) <= found]
        print(f'{sh["nom"]} : {total:.1f} s, {len(pieces)} plans, B-roll {[(round(b["a"], 1), round(b["b"], 1)) for b in brolls]}'
              + (f', mots clés introuvables : {missing}' if missing else ''))
        return None
    # 2. son : voix (2 micros v2) recollée, fondus de 10 ms à chaque coupe
    voice = []
    data = {k: sf.SoundFile(v) for k, v in mics.items()}
    for b in bites:
        for a, e, _ in b["seg"]:
            n0 = round((e - a) * FPS)
            parts = []
            for k, f in data.items():
                f.seek(int(a * f.samplerate))
                y = f.read(int(round(n0 / FPS * f.samplerate)), dtype="float32", always_2d=True).mean(1)
                for mk, t0, t1 in sh.get("muet", []):  # micro coupé sur une plage (temps micro), ex. fin de question qui déborde
                    if mk == k and t1 > a and t0 < e:
                        y[max(0, int((t0 - a) * f.samplerate)):max(0, int((t1 - a) * f.samplerate))] = 0
                parts.append(y)
            x = sum(parts)
            fd = int(0.01 * 44100)
            x[:fd] *= np.linspace(0, 1, fd)
            x[-fd:] *= np.linspace(1, 0, fd)
            voice.append(x)
    v44 = np.concatenate(voice)
    vtmp = out_dir / ".voix.wav"
    sf.write(vtmp, v44, 44100, subtype="FLOAT")
    v = subprocess.run(["ffmpeg", "-v", "error", "-i", str(vtmp), "-ar", str(SR), "-f", "f32le", "-"],
                       capture_output=True, check=True).stdout
    vtmp.unlink()
    v = np.frombuffer(v, np.float32).astype(np.float64)
    v *= 10 ** ((VOICE_LUFS - pyln.Meter(SR).integrated_loudness(v)) / 20)
    end = 0.0 if spec.get("sans_fin") else END
    full = total + end
    n_s = int(full * SR) + SR
    mix = np.zeros((n_s, 2))
    mix[:len(v), 0] += v
    mix[:len(v), 1] += v
    # musique
    mtmp = out_dir / ".musique.wav"
    mus = {**spec["musique"], **sh.get("musique", {})}  # une musique par short, choisie pour son émotion
    if not sh.get("sans_musique") and (ROOT / mus["fichier"]).is_file():  # a cappella, ou musique absente du partage
        teaser.music_from_track(ROOT / mus["fichier"], full, [], mtmp, mus.get("lufs", -30))
        mu, _ = sf.read(mtmp, dtype="float64", always_2d=True)
        mtmp.unlink()
        mix[:len(mu)] += mu[:n_s]
    # bruitages : glissés, coupes, mots clés, entrée des B-roll, impact du carton de fin
    keys = [b["map"](ln["words"][ln.get("from", 0)][1]) for b in bites for pg in b["pages"] for ln in pg if ln["key"]]
    whooshes = [(br["a"] + 0.05, 1) for br in brolls]
    fx = ts.sfx(total, trans, cuts, keys, [-1 if i % 2 == 0 else 1 for i in range(len(trans))], whooshes)
    fx *= 10 ** (-13 / 20) / (np.abs(fx).max() + 1e-9)
    mix[:min(len(fx), n_s)] += fx[:n_s]
    mix = mix[:int(full * SR)]
    if not end:  # sans carton, la musique et le fond s'éteignent sur la fin de la dernière phrase
        fade = int(0.25 * SR)
        mix[-fade:] *= np.linspace(1, 0, fade)[:, None]
    peak = np.abs(mix).max()
    if peak > 0.89:
        mix *= 0.89 / peak
    wav = out_dir / ".son.wav"
    sf.write(wav, mix.astype(np.float32), SR, subtype="PCM_24")

    # 3. image
    out = out_dir / f'{sh["nom"]}.mp4'
    tmp_out = out_dir / f'.{sh["nom"]}.mp4'
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                            "-r", str(FPS), "-i", "-", "-i", str(wav), "-map", "0:v", "-map", "1:a",
                            "-vf", "scale=out_color_matrix=bt709:out_range=tv", "-c:v", "libx264", "-preset", "slow",
                            "-crf", "16", "-pix_fmt", "yuv420p", "-profile:v", "high", "-color_primaries", "bt709",
                            "-color_trc", "bt709", "-colorspace", "bt709", "-c:a", "aac", "-b:a", "320k",
                            "-movflags", "+faststart", "-shortest", str(tmp_out)], stdin=subprocess.PIPE)
    events = sub_events(bites)
    incrusts = incrust_times(sh.get("incrustations", []), events)
    if DA == "craie":
        he = sh.get("accroche_duree", 3.0) if sh.get("accroche") else 0.0
        incrusts = [(max(a, he + 0.15), max(a, he + 0.15) + (b - a), it) for a, b, it in incrusts]
    icache = {}
    cams = {}
    hook = sh.get("accroche", [])
    hook_end = sh.get("accroche_duree", 3.0)
    cache = {}
    k_glob = 0
    tot_img, fait_img = sum(p["n"] for p in pieces) or 1, 0
    for p in pieces:
        if p["cam"] not in cams:
            cams[p["cam"]] = Cam(sync, p["cam"], faces[p["cam"]])
        cam = cams[p["cam"]]
        n = p["n"]
        zs, ze = p["z"]
        b_iters = {}
        # écran partagé (spec extrait « split » : cam d'une autre personne en haut, synchronisée, ex. l'invité
        # pendant la question de l'animatrice)
        top_cam = None
        if p.get("split"):
            sk = cam_for(sync, p["split"], p["mic"])
            if sk not in cams:
                cams[sk] = Cam(sync, sk, faces[sk])
            top_cam = cams[sk]
            top_it = top_cam.frames(p["mic"], n)
        for k, img in enumerate(cam.frames(p["mic"], n)):
            fait_img += 1
            if fait_img % 25 == 0:
                progres(0.95 * fait_img / tot_img)
            t = p["t"] + k / FPS
            u = k / max(n - 1, 1)
            z = zs + (ze - zs) * (3 * u * u - 2 * u ** 3)
            br = next((x for x in brolls if x["a"] <= t < x["b"]), None)
            if top_cam is not None:
                img2 = next(top_it, None)
                frame = np.empty((H, W, 3), np.uint8)
                frame[:H // 2] = top_cam.view(img2 if img2 is not None else img, z * 1.0, W, H // 2, eyes=0.62)
                frame[H // 2:] = cam.view(img, z * 1.15, W, H // 2, eyes=0.36)
                frame[H // 2 - 2:H // 2 + 2] = EGG if DA == "craie" else ACCENT
                cy = H * 0.5
            elif br:
                top = b_iters.setdefault(id(br), broll_frames(br["path"], br["src"] + max(0.0, t - br["a"]),
                                                             round((br["b"] - t) * FPS) + 2))
                frame = np.empty((H, W, 3), np.uint8)
                frame[:H // 2] = next(top)
                frame[H // 2:] = cam.view(img, z * 1.15, W, H // 2, eyes=0.36)
                frame[H // 2 - 3:H // 2 + 3] = ACCENT
                cy = H * 0.5
            else:
                frame = cam.view(img, z, W, H)
                cy = H * SUB_Y
            # glissé (whip pan) aux changements d'extrait
            dx = 0.0
            if p["slide_in"] and k < TRANS:
                w_ = 1 - k / TRANS
                dx = -p["d_in"] * SLIDE * W * w_ * w_
            elif p["slide_out"] and n - 1 - k < TRANS:
                w_ = 1 - (n - 1 - k) / TRANS
                dx = p["d_out"] * SLIDE * W * w_ * w_
            if dx:
                m = np.float32([[1, 0, dx], [0, 1, 0]])
                frame = cv2.warpAffine(frame, m, (W, H), borderMode=cv2.BORDER_REFLECT)
                frame = cv2.blur(frame, (int(2 * SLIDE * W * w_ / TRANS) | 1, 1), borderType=cv2.BORDER_REFLECT)
            im = Image.fromarray(np.ascontiguousarray(frame)).convert("RGBA")
            if DA == "craie":
                im.alpha_composite(craie_vignette())
            if USE_LOGO:
                poser_logo(im, sh)
            if sh.get("plateformes") and t >= PLAT_START:
                im.alpha_composite(platforms_layer(min(1.0, (t - PLAT_START) / 0.6)))
            for ii, (i0, i1, it) in enumerate(incrusts):
                if i0 <= t < i1:
                    if DA == "craie":
                        tr_ = round(min(t - i0, 1.2), 2)
                        out_ = round(min(1.0, (i1 - t) / 0.35), 2)
                        key_ = (ii, tr_, out_)
                        if key_ not in icache:
                            icache[key_] = (craie_photo if it.get("image") else craie_incrust)(it, out_, tr_)
                    else:
                        key_ = (ii, round(min(1.0, (t - i0) / 0.3, (i1 - t) / 0.25), 2))
                        if key_ not in icache:
                            icache[key_] = incrust_layer(it, key_[1])
                    im.alpha_composite(icache[key_])
            if hook and t < hook_end:
                if DA == "craie":
                    hp = round(min(1.6, t / 0.9), 2) if t < hook_end - 0.3 else round(max(0.0, (hook_end - t) / 0.3), 2)
                    if ("hook", hp) not in icache:
                        icache[("hook", hp)] = craie_hook(hook, hp)
                    im.alpha_composite(icache[("hook", hp)])
                else:
                    im.alpha_composite(hook_layer(hook, min(1.0, t / 0.6) if t < hook_end - 0.25 else (hook_end - t) / 0.25))
            ev = None if sh.get("sans_sous_titres") else next((e for e in events if e[0] <= t < e[1]), None)
            in_trans = any(abs(t - x) < (TRANS - 1) / FPS for x in trans)
            if ev and not in_trans:
                shown = tuple((i, min(teaser.POP, int((t - s) * FPS))) for i, (_, s, *_r) in enumerate(ev[2]) if s <= t)
                state = (id(ev), shown, cy)
                if state not in cache:
                    cache = {state: draw_subs(ev, t, cy)}
                im.alpha_composite(cache[state])
            enc.stdin.write(np.asarray(im.convert("RGB")).tobytes())
            k_glob += 1
    n_end = round(end * FPS)
    for k in range(n_end):
        fin_ = sh.get("fin", ["ÉPISODE COMPLET", "YOUTUBE · APPLE PODCASTS · SPOTIFY"])
        enc.stdin.write((craie_end(k, n_end, fin_) if DA == "craie" else end_card(k, n_end, fin_)).tobytes())
    enc.stdin.close()
    enc.wait()
    wav.unlink()
    tmp_out.rename(out)
    print(f'{sh["nom"]} : {full:.1f} s, {len(pieces)} plans, {len(brolls)} B-roll -> {out}')
    return out


VERIFY = "--verifier" in sys.argv

if __name__ == "__main__":
    sys.argv = [a for a in sys.argv if a != "--verifier"]
    spec = json.loads(Path(sys.argv[1]).read_text())
    only = sys.argv[2:]
    for sh in spec["shorts"]:
        if not only or any(sh["nom"].startswith(o) for o in only):
            render(spec, sh)
