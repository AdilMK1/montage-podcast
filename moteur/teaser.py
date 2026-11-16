"""Étape 5 (option) : teaser d'ouverture façon « cold open », en motion design.

Prend une liste d'extraits (spec JSON), et produit :
- la vidéo du teaser (4K ProRes 10 bits, étalonnable comme la cam d'origine) : gros plan de l'invité
  seulement, un zoom avant lent par plan, sujet décalé à gauche ou à droite ;
- les sous-titres dynamiques en vidéo transparente (QuickTime Animation, alpha), placés du côté libre,
  sans jamais passer sur la silhouette : mots qui apparaissent un par un, empilés en colonne,
  MAJUSCULES Lato (la police de la référence), mots clés en Lato Black vert ou blanc, ombre portée douce ;
- transitions entre extraits : glissé latéral (whip pan) avec flou de mouvement, sens alterné ;
- la musique et les bruitages (teaser_son.py), en deux WAV séparés posés sous le teaser ;
- la session de montage mise à jour (le son du teaser reste sur les pistes micro) ;
- un aperçu MP4 (non étalonné) pour juger le rythme sans ouvrir Premiere.

Usage : python teaser.py sessions/exemple2_teaser_spec.json [--sous-titres]  (sans re-rendre la vidéo)
"""
import json
import random
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

import cv2
import habillage
import travail
import teaser_son
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).parent
FONTS = {False: ROOT / "fonts" / "Lato-Regular.ttf", True: ROOT / "fonts" / "Lato-Black.ttf"}
GREEN = (42, 157, 122)
WHITE = (255, 255, 255)
W, H = 3840, 2160
SHORT = 3  # un mot de 3 lettres ou moins reste sur la ligne du mot suivant
MAX_LINES = 6
POP = 4  # images d'apparition d'un mot
NORM, BIG = (0.064, False), (0.100, True)  # (taille en part de la hauteur, gras)
TRANS = 5  # images de transition de chaque côté d'un changement d'extrait
# un seul zoom avant lent par plan (retour : le va-et-vient zoom / dézoom fait cheap)
MOVES = [(1.38, 1.48), (1.46, 1.56), (1.40, 1.50), (1.50, 1.60)]
SLIDE = 0.55  # glissé de transition : décalage max, en part de la largeur
SUBJECT_X = {"gauche": 0.30, "droite": 0.70}  # où l'on place le visage dans l'image
SUBJECT_Y = 0.34
MARGIN = 0.035  # écart minimum entre la silhouette et le texte, et avec le bord de l'image


@lru_cache(maxsize=None)
def font(size, bold):
    return ImageFont.truetype(str(FONTS[bold]), size)


def words_of(sentences, speaker, a, b):
    """Mots de l'invité entre a et b (temps micros), apostrophes recollées (j + 'ai -> J'AI)."""
    out = []
    for s in sentences:
        if s["speaker"] != speaker or s["end"] < a or s["start"] > b:
            continue
        for w in s["words"]:
            t = w["w"].strip()
            if not t or w["start"] < a - 0.05 or w["start"] > b - 0.15:
                continue
            if out and (t[0] in "'’-" or out[-1][0].endswith(("'", "’"))):
                out[-1] = (out[-1][0] + t, out[-1][1], w["end"])
            else:
                out.append((t.lstrip("'’") if not out else t, w["start"], w["end"]))  # extrait qui démarre sur « qu|'il »
    return out


def clean(t):
    return t.upper().strip(",.;:!?…")


def layout(words, keys):
    """Regroupe les mots en lignes puis en pages. Un mot clé (ou groupe clé) a sa propre ligne."""
    toks = [(clean(t), s, e, t) for t, s, e in words]
    for i in range(len(toks) - 1, 0, -1):  # "KM" "HEURE" -> "KM/H"
        if toks[i - 1][0] == "KM" and toks[i][0] == "HEURE":
            toks[i - 1:i + 1] = [("KM/H", toks[i - 1][1], toks[i][2], toks[i][3])]

    def key_at(i):
        return next((k for k in keys if [x[0] for x in toks[i:i + len(k.split())]] == k.split()), None)

    lines, i = [], 0
    while i < len(toks):
        hit = key_at(i)
        if hit:
            n = len(hit.split())
            prev = lines[-1] if lines else None
            if prev and not prev["key"] and all(len(w[0]) <= SHORT for w in prev["words"]) \
                    and not prev["words"][-1][3].endswith((".", ",", "?", "!")):
                # « MA » + « GRAND-MÈRE » sur la même ligne, seul le mot clé est en gras
                lines[-1] = {"words": prev["words"] + toks[i:i + n], "key": keys[hit], "from": len(prev["words"])}
            else:
                lines.append({"words": toks[i:i + n], "key": keys[hit], "from": 0})
            i += n
            continue
        line = [toks[i]]
        i += 1
        while len(line) < 2 and len(line[-1][0]) <= SHORT and i < len(toks) and not key_at(i):
            line.append(toks[i])
            i += 1
        lines.append({"words": line, "key": None})
    pages, cur = [], []
    for ln in lines:
        cur.append(ln)
        end = ln["words"][-1][3]
        if (end.endswith((".", "?", "!")) or (end.endswith(",") and len(cur) >= 3)
                or (ln["key"] and len(cur) >= 4) or len(cur) >= MAX_LINES):
            pages.append(cur)
            cur = []
    if cur:
        pages.append(cur)
    return pages


# ---------- cadrage ----------

def framing(z, side, face):
    """Fenêtre de recadrage (x, y en part de l'image source) pour un zoom z, visage placé à gauche/droite."""
    w = h = 1 / z
    x = min(max(face[0] - SUBJECT_X[side] * w, 0), 1 - w)
    y = min(max(face[1] - SUBJECT_Y * h, 0), 1 - h)
    return x, y


def free_zone(moves, side, face, body):
    """Bande libre (x0, x1) en part de l'image finale, du côté opposé au sujet, sur tout l'extrait."""
    edges = []
    for zs, ze in moves:
        for z in (zs, ze):
            x, _ = framing(z, side, face)
            edges.append(((body[0] - x) * z, (body[1] - x) * z))
    if side == "gauche":
        return max(e[1] for e in edges) + MARGIN, 1 - MARGIN
    return MARGIN, min(e[0] for e in edges) - MARGIN


def render_video(pieces, fps, out):
    """pieces : [(fichier cam, temps cam début, nb images, zoom début, zoom fin, côté, visage, entrée, sortie)].
    entrée / sortie : transition animée au début / à la fin du morceau (changement d'extrait)."""
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb48le", "-s", f"{W}x{H}",
                            "-r", str(fps), "-i", "-", "-vf", "scale=out_color_matrix=bt709:out_range=tv",
                            "-c:v", "prores_ks", "-profile:v", "2", "-pix_fmt", "yuv422p10le",
                            "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
                            "-color_range", "tv", str(out)], stdin=subprocess.PIPE)
    for path, tc, n, zs, ze, side, face, t_in, t_out, dirs, *lin in pieces:
        dec = subprocess.Popen(["ffmpeg", "-v", "error", "-ss", f"{tc:.4f}", "-i", path, "-frames:v", str(n),
                                "-vf", f"scale={W}:{H}:in_color_matrix=bt709:in_range=tv",
                                "-f", "rawvideo", "-pix_fmt", "rgb48le", "-"], stdout=subprocess.PIPE)
        for k in range(n):
            buf = dec.stdout.read(W * H * 6)
            if len(buf) < W * H * 6:
                break
            src = np.frombuffer(buf, np.uint16).reshape(H, W, 3)
            p = k / max(n - 1, 1)
            # mouvement doux (ease in-out) ; sur un extrait resserré, la courbe vient de l'extrait entier
            z = zs + (ze - zs) * (p if lin else 3 * p * p - 2 * p * p * p)
            x, y = framing(z, side, face)
            m = np.float32([[z, 0, -x * W * z], [0, z, -y * H * z]])
            # u : force de la transition (1 sur la coupe, 0 hors transition)
            # glissé latéral (whip pan) : l'image sort d'un côté en accélérant, la suivante arrive du côté
            # opposé en freinant, avec un flou de mouvement horizontal proportionnel à la vitesse
            dx = 0.0
            if t_in and k < TRANS:
                u = 1 - k / TRANS
                dx = -dirs[0] * SLIDE * W * u * u
            elif t_out and n - 1 - k < TRANS:
                u = 1 - (n - 1 - k) / TRANS
                dx = dirs[1] * SLIDE * W * u * u
            if not dx:
                enc.stdin.write(cv2.warpAffine(src, m, (W, H), flags=cv2.INTER_CUBIC).tobytes())
                continue
            m[0, 2] += dx
            img = cv2.warpAffine(src, m, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
            blur = int(2 * SLIDE * W * u / TRANS) | 1
            enc.stdin.write(cv2.blur(img, (blur, 1), borderType=cv2.BORDER_REFLECT).tobytes())
        dec.stdout.close()
        dec.wait()
    enc.stdin.close()
    enc.wait()


# ---------- sous-titres ----------

def render_subs(bites, fps, out_mov, y0=0.20):
    total = max(b["seq_end"] for b in bites)
    n = int(round(total * fps))
    rng = random.Random(3)
    events = []  # (début, fin, [(mot, apparition, x, y, police, couleur)])
    for b in bites:
        off = b["seq_start"] - b["mic_start"]
        zx0, zx1 = b["zone"][0] * W, b["zone"][1] * W
        for pi, page in enumerate(b["pages"]):
            p_end = (b["pages"][pi + 1][0]["words"][0][1] + off if pi + 1 < len(b["pages"]) else b["seq_end"])
            items, y = [], y0 * H
            for ln in page:
                styles = [BIG if ln["key"] and j >= ln.get("from", 0) else NORM for j in range(len(ln["words"]))]
                fonts = [font(int(H * s), wt) for s, wt in styles]
                width = sum(f.getlength(w[0] + " ") for f, w in zip(fonts, ln["words"])) - fonts[-1].getlength(" ")
                if width > zx1 - zx0:  # ligne trop large pour la zone libre : on réduit la police
                    k = (zx1 - zx0) / width
                    fonts = [font(int(f.size * k), wt) for f, (_, wt) in zip(fonts, styles)]
                    width *= k
                x = zx0 + rng.uniform(0, 0.35) * max(0.0, zx1 - zx0 - width)  # colonne en escalier
                h = max(f.size for f in fonts)
                for j, ((t, s, e, _), f) in enumerate(zip(ln["words"], fonts)):
                    k = ln["key"] and j >= ln.get("from", 0)
                    col = (GREEN if ln["key"] == "vert" else WHITE) if k else WHITE
                    items.append((t, max(b["seq_start"], s + off), x, y + h - f.size, f, col))
                    x += f.getlength(t + " ")
                y += h * 1.08
            events.append((max(b["seq_start"], page[0]["words"][0][1] + off), min(p_end, b["seq_end"]), items))

    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{W}x{H}",
                             "-r", str(fps), "-i", "-", "-c:v", "qtrle", "-pix_fmt", "argb", str(out_mov)],
                            stdin=subprocess.PIPE)
    blank = np.zeros((H, W, 4), np.uint8).tobytes()
    cache = {}
    for k in range(n):
        t = k / fps
        # le texte disparaît pendant la transition de sortie de l'extrait
        page = next((ev for ev in events if ev[0] <= t < ev[1] and not any(
            b["seq_end"] - (TRANS - 1) / fps <= t < b["seq_end"] + (TRANS - 1) / fps for b in bites[:-1])), None)
        if not page:
            proc.stdin.write(blank)
            continue
        shown = [(i, it) for i, it in enumerate(page[2]) if it[1] <= t]
        state = (id(page), tuple((i, min(POP, int((t - it[1]) * fps))) for i, it in shown))
        if state not in cache:
            txt = Image.new("RGBA", (W, H))
            d = ImageDraw.Draw(txt)
            for i, (w, s, x, y, f, col) in shown:
                age = min(POP, int((t - s) * fps))
                a = int(255 * (0.4 + 0.6 * age / POP))
                dy = (POP - age) * f.size * 0.04  # petit rebond vers le haut à l'apparition
                d.text((x, y + dy), w, font=f, fill=col + (a,))
            # ombres façon référence, calculées en quart de résolution (4x plus rapide, invisible à l'œil) :
            # un halo gris large autour du bloc + une ombre portée douce décalée en bas à droite
            q = 4
            small = txt.getchannel("A").resize((W // q, H // q), Image.BILINEAR)
            halo = small.filter(ImageFilter.GaussianBlur(H * 0.016 / q)).point(lambda v: min(150, int(v * 1.6)))
            drop = small.filter(ImageFilter.GaussianBlur(H * 0.004 / q)).point(lambda v: int(v * 0.75))
            off = (round(H * 0.0035 / q), round(H * 0.0045 / q))
            shade = Image.new("L", small.size)
            shade.paste(drop, off)
            alpha = Image.fromarray(np.maximum(np.asarray(halo), np.asarray(shade)))
            shadow = Image.new("RGBA", (W, H), (12, 10, 10, 0))
            shadow.putalpha(alpha.resize((W, H), Image.BILINEAR))
            cache = {state: Image.alpha_composite(shadow, txt).tobytes()}  # les états ne reviennent pas
        proc.stdin.write(cache[state])
    proc.stdin.close()
    proc.wait()


# ---------- aperçu ----------

def dur_of(path):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                                capture_output=True, text=True).stdout)


def music_from_track(track, total, duck, out, lufs=-30):
    """Musique existante (ex. Mixkit) coupée à la durée du teaser + intro, dosée sous la voix,
    baissée pendant les inserts qui ont leur propre son (duck : [(début, fin)]), fondu de fin."""
    vol = ",".join(f"volume=enable='between(t,{a:.2f},{b:.2f})':volume=0.3" for a, b in duck)
    af = f"atrim=0:{total:.3f},loudnorm=I={lufs}:TP=-3," + (vol + "," if vol else "") + \
         f"afade=t=in:d=0.05,afade=t=out:st={total - 1.5:.3f}:d=1.5"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(track), "-af", af, "-ar", "48000", "-ac", "2",
                    "-c:a", "pcm_s24le", str(out)], check=True)
    return out


def apercu(cfg, montage, video, mov, out, intro, overlays, son):
    """MP4 1080p non étalonné de tout le début : teaser (vidéo animée + son de l'invité) puis l'intro
    (inserts bout à bout), avec par-dessus les B-roll et la carte (overlays : [(fichier, début séquence)]),
    les sous-titres, la musique et les bruitages."""
    tmp = travail.dossier(cfg["name"]) / "apercu"
    tmp.mkdir(exist_ok=True)
    harmo = cfg.get("son", {})
    guest = montage[0]["micros"][0]
    mic = harmo.get("mics", {}).get(guest, cfg["mics"][guest])
    norm = "" if harmo else "loudnorm=I=-16,"  # sons déjà harmonisés (son.py) : on ne retouche pas les niveaux
    fps = cfg["fps"]
    # 1. base : teaser (image animée + micro de l'invité, à l'image près comme dans le XML) puis l'intro
    trims = "".join(f"[0:a]atrim={round(m['rush'][0] * fps) / fps}:{round(m['rush'][1] * fps) / fps},asetpts=PTS-STARTPTS[a{i}];"
                    for i, m in enumerate(montage))
    ins = []
    for path, (s0, s1), o in intro:
        ins += ["-ss", str(s0), "-t", str(s1 - s0), "-i", path]
        wav = None if o.get("son_brut") else harmo.get("inserts", {}).get(path)
        ins += ["-ss", str(s0), "-t", str(s1 - s0), "-i", wav or path]  # même minutage, son harmonisé
    k = len(intro)
    graph = (trims + "".join(f"[a{i}]" for i in range(len(montage))) + f"concat=n={len(montage)}:v=0:a=1,"
             + norm + "aformat=channel_layouts=stereo:sample_rates=48000[ta];[1:v]scale=1920:1080,setsar=1[tv];"
             + "".join(f"[{2 * i + 2}:v]scale=1920:1080,fps=25,setsar=1[v{i}];[{2 * i + 3}:a]aresample=48000,"
                       f"aformat=channel_layouts=stereo[ia{i}];" for i in range(k))
             + "[tv][ta]" + "".join(f"[v{i}][ia{i}]" for i in range(k)) + f"concat=n={k + 1}:v=1:a=1[v][a]")
    base = tmp / "base.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", mic, "-i", str(video), *ins, "-filter_complex", graph,
                    "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
                    "-c:a", "pcm_s16le", str(base.with_suffix(".mov"))], check=True)
    base = base.with_suffix(".mov")
    # 2. habillage par-dessus, dans l'ordre des pistes : B-roll et carte, puis sous-titres ; son : + musique + bruitages
    inputs, chain, last = ["-i", str(base)], "", "[0:v]"
    for n_, (f, start) in enumerate(overlays + [(mov, 0.0)], 1):
        inputs += ["-i", str(f)]
        chain += (f"[{n_}:v]scale=1920:1080,setpts=PTS-STARTPTS+{start:.3f}/TB[o{n_}];"
                  f"{last}[o{n_}]overlay=eof_action=pass[b{n_}];")
        last = f"[b{n_}]"
    m0 = len(overlays) + 2
    inputs += ["-i", str(son[0]), "-i", str(son[1])]
    chain += f"[0:a][{m0}:a][{m0 + 1}:a]amix=inputs=3:duration=first:normalize=0[a]"
    subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", chain, "-map", last, "-map", "[a]",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "192k", str(out)],
                   check=True)


def main(spec_path):
    global GREEN
    spec = json.loads(Path(spec_path).read_text())
    if "couleur" in spec:  # autre émission que Exemple : remplace le vert des mots clés et de la carte invité
        GREEN = habillage.TEAL = tuple(spec["couleur"])
    cfg = json.loads((ROOT / spec["session"]).read_text())
    work = travail.dossier(cfg["name"])
    sentences = json.loads((work / "transcript.json").read_text())
    sync = json.loads((work / "sync.json").read_text())["cams"]
    fps, cam, guest = cfg["fps"], spec["cam"], spec["micro"]
    teaser_son.KEY_GAIN = spec.get("bruitages_mots", teaser_son.KEY_GAIN)
    face, body = spec["sujet"]["visage"], spec["sujet"]["corps"]

    def sc_at(x):
        """cam serrée de l'invité qui filme à l'instant x (temps micro) : une cam peut être en plusieurs fichiers"""
        if cam in sync:
            return sync[cam]
        return next(v for k, v in sync.items() if v.get("cam") == cam and v["covers_mic_s"][0] <= x <= v["covers_mic_s"][1])

    montage, bites, pieces, t, j = [], [], [], 0.0, 0
    cuts = []  # coupes à l'intérieur d'un extrait (temps séquence), pour les petits swish
    brolls = []  # [{fichier, src, debut (séquence), duree, nom}]
    side = spec.get("premier_cote", "gauche")
    for b in spec["extraits"]:
        segs = b.get("coupes")  # extrait resserré (resserre.py) : morceaux sans les blancs + mots recalés sur la voix
        if segs:
            a = segs[0][0]
            e = a + sum(y - x for x, y in segs)
            words = []
            for w, s0, s1 in b["mots"]:
                if words and (w[0] in "'’-" or words[-1][0].endswith(("'", "’"))):
                    words[-1] = (words[-1][0] + w, words[-1][1], a + s1)
                else:
                    words.append((w, a + s0, a + s1))
        else:
            a, e = b["rush"]
            words = words_of(sentences, guest, a, e)
        if b.get("texte"):  # texte corrigé à la main (transcript faux, ex. son de cam) : mots répartis selon leur longueur
            w0 = words[0][1] if words else a + 0.1
            w1 = words[-1][2] if words else e - 0.1
            toks = b["texte"].split()
            tot = sum(len(x) + 1 for x in toks)
            words, c = [], 0
            for x in toks:
                s0 = w0 + (w1 - w0) * c / tot
                c += len(x) + 1
                words.append((x, s0, w0 + (w1 - w0) * c / tot))

        # "zoom_sur" : mots où l'on coupe pour changer de mouvement ("LE@2" = 2e « le » de l'extrait)
        def at(c):
            w, _, k = c.partition("@")
            return [s for t_, s, _ in words if clean(t_) == clean(w)][int(k or 1) - 1] - 0.06
        bounds = [a] + [at(c) for c in b.get("zoom_sur", [])] + [e]
        side = b.get("cote", side)
        fb = b.get("visage", face)  # visage mesuré pour cet extrait (l'invité bouge)
        moves, first, q = [], len(pieces), t
        whole = MOVES[j % len(MOVES)]
        total = sum(round(y * fps) - round(x * fps) for x, y in segs) if segs else 0
        done = 0
        ease = lambda u: 3 * u * u - 2 * u ** 3
        for x, y in (segs or zip(bounds, bounds[1:])):
            f0, f1 = round(x * fps), round(y * fps)
            if segs:  # un seul mouvement continu sur tout l'extrait : les coupes de blancs restent discrètes
                zs = whole[0] + (whole[1] - whole[0]) * ease(done / total)
                done += f1 - f0
                ze = whole[0] + (whole[1] - whole[0]) * ease(done / total)
            else:
                zs, ze = MOVES[j % len(MOVES)]
                j += 1
            moves.append((zs, ze))
            montage.append({"rush": [f0 / fps, f1 / fps], "cam": cam, "micros": [guest], "sans_video": True})
            sc = sc_at(f0 / fps)
            pieces.append([sc["path"], (f0 / fps - sc["offset_s"]) / (1 + sc["drift_ppm"] * 1e-6), f1 - f0, zs, ze, side, fb,
                           False, False, [0, 0]] + ([True] if segs else []))
            if len(pieces) > first + 1 and not segs:
                cuts.append(q)
            q += (f1 - f0) / fps
        if segs:
            j += 1
        pieces[first][7] = bool(bites)  # entrée animée sauf pour le tout premier plan
        pieces[-1][8] = True  # sortie animée (retirée plus bas pour le dernier extrait)
        # sens du glissé : vers la gauche puis vers la droite, en alternance (entrée = sens de la sortie précédente)
        d = -1 if len(bites) % 2 == 0 else 1
        pieces[-1][9][1] = d
        if bites:
            pieces[first][9][0] = -1 if (len(bites) - 1) % 2 == 0 else 1
        if "broll" in b:  # plan de coupe (B-roll) par-dessus une partie de l'extrait, la voix continue
            br = b["broll"]
            x0 = at(br["de"]) + 0.06 if br.get("de") else a
            x1 = at(br["a"]) if br.get("a") else e
            brolls.append({"fichier": br["fichier"], "src": br.get("src", 0.0), "debut": t + x0 - a, "duree": x1 - x0,
                           "nom": br.get("nom", Path(br["fichier"]).stem)})
        bites.append({"seq_start": t, "seq_end": t + (total / fps if segs else (round(e * fps) - round(a * fps)) / fps), "mic_start": a,
                      "zone": free_zone(moves, side, fb, [body[0] + fb[0] - face[0], body[1] + fb[0] - face[0]]),
                      "pages": layout(words, {k.upper(): v for k, v in b.get("mots_cles", {}).items()})})
        t = bites[-1]["seq_end"]
        side = "droite" if side == "gauche" else "gauche"  # on alterne d'un extrait à l'autre

    pieces[-1][8] = False  # le dernier extrait finit sec, sur l'impact
    trans = [b["seq_end"] for b in bites[:-1]]
    # apparition de chaque mot clé (temps séquence) : petit impact sonore
    keys = [max(b["seq_start"], ln["words"][ln.get("from", 0)][1] + b["seq_start"] - b["mic_start"])
            for b in bites for pg in b["pages"] for ln in pg if ln["key"]]

    out_dir = Path(cfg["mics"][guest]).parent
    video = out_dir / f'{cfg["name"]} TEASER VIDEO.mov'
    mov = out_dir / f'{cfg["name"]} TEASER SOUS-TITRES.mov'
    if "--sous-titres" not in sys.argv or not video.exists():  # --sous-titres : on garde la vidéo déjà rendue
        render_video(pieces, fps, video)
    render_subs(bites, fps, mov)
    sess = json.loads((ROOT / spec["session"]).read_text())
    body_m = [m for m in sess["montage"] if not m.get("micros")]  # on remplace l'ancien teaser
    intro = []  # les inserts qui suivent le teaser, jusqu'au 1er morceau de l'épisode
    for m in body_m:
        if "insert" not in m:
            break
        intro.append((m["insert"], m["src"], {k: m[k] for k in ("son_brut",) if k in m}))
    # temps d'un fichier d'intro (ex. 39,6 s dans INTRO OUTRO CTA) -> temps séquence (1er insert seulement) ;
    # sans insert d'intro (l'animateur fait l'intro en plateau, Exemple 1) : temps micro dans le 1er morceau d'épisode
    def seq_intro(x):
        return t + x - (intro[0][1][0] if intro else body_m[0]["rush"][0])
    intro_len = sum(s1 - s0 for _, (s0, s1), _ in intro)
    whooshes = []

    # intro habillée : carte invité au moment où l'animateur dit son nom, B-roll sur ses phrases
    sp_in = spec.get("intro", {})
    for br in sp_in.get("broll", []):
        brolls.append({"fichier": br["fichier"], "src": br.get("src", 0.0), "debut": seq_intro(br["de"]),
                       "duree": br["a"] - br["de"], "nom": br.get("nom", Path(br["fichier"]).stem)})
    broll_dir = out_dir / f'{cfg["name"]} B-ROLL'
    broll_dir.mkdir(exist_ok=True)
    for i, br in enumerate(sorted(brolls, key=lambda x: x["debut"]), 1):
        br["out"] = broll_dir / f'{i:02d} {br["nom"]}.mov'
        habillage.broll_clip(ROOT / br["fichier"], br["src"], br["duree"], br["out"], fps)
    overlays = [(br["out"], round(br["debut"] * fps) / fps) for br in brolls]
    hab = [{"fichier": str(video), "debut_s": 0.0}]
    hab += [{"fichier": str(f), "debut_s": d, "piste": "B-ROLL"} for f, d in overlays]
    if "carte" in sp_in:
        c = sp_in["carte"]
        card = out_dir / f'{cfg["name"]} CARTE INVITE.mov'
        if "--carte" in sys.argv or not card.exists():
            cut = work / "carte" / "invite_detoure.png"
            if c.get("detoure"):  # détourage déjà retouché à la main (ex. bras de l'animateur retiré)
                cut = ROOT / c["detoure"]
            else:
                habillage.cutout(ROOT / c["photo"], cut)
            habillage.render_card(cut, c["nom"], c["titre"], c.get("accroche", ""), card, fps, c["a"] - c["de"])
        overlays.append((card, round(seq_intro(c["de"]) * fps) / fps))
        hab.append({"fichier": str(card), "debut_s": overlays[-1][1]})
        whooshes.append((seq_intro(c["de"]) + 0.1, 1))
    hab.append({"fichier": str(mov), "debut_s": 0.0})

    music = out_dir / f'{cfg["name"]} TEASER MUSIQUE.wav'
    sfx = out_dir / f'{cfg["name"]} TEASER BRUITAGES.wav'
    dirs = [-1 if i % 2 == 0 else 1 for i in range(len(trans))]
    if "musique" in spec:
        # musique existante sur le teaser + l'intro, baissée sous les inserts qui ont leur propre son (BFM…)
        # baissée sous les inserts qui ont leur propre son (« baisse » : bouts de nom, ex. BFM), arrêtée avant
        # l'insert à son brut (écran noir + logo et son impact)
        duck, q, end = [], t, None
        for path, (s0, s1), o in intro:
            if o.get("son_brut"):
                end = q
                break
            if any(b in Path(path).name for b in spec["musique"].get("baisse", ["BFM"])):
                duck.append((q, q + s1 - s0))
            q += s1 - s0
        music_from_track(ROOT / spec["musique"]["fichier"], end or (t + intro_len), duck, music,
                         spec["musique"].get("lufs", -30))
        teaser_son.render(t, trans, cuts, keys, None, sfx, dirs, whooshes)
    else:
        teaser_son.render(t, trans, cuts, keys, music, sfx, dirs, whooshes)
    hab += [{"fichier": str(music), "debut_s": 0.0}, {"fichier": str(sfx), "debut_s": 0.0}]
    sess["montage"] = montage + body_m
    sess["habillage"] = hab
    (ROOT / spec["session"]).write_text(json.dumps(sess, indent=2, ensure_ascii=False) + "\n")
    print(f"{len(montage)} plans, {t:.1f} s -> {video.name} + {mov.name}")
    for b in bites:
        print(f"  zone texte {b['zone'][0]:.2f}-{b['zone'][1]:.2f}")

    out = out_dir / f'{cfg["name"]} TEASER APERCU.mp4'
    apercu(cfg, montage, video, mov, out, intro, overlays, (music, sfx))
    print(f"aperçu : {out}")


if __name__ == "__main__":
    main(sys.argv[1])
