"""Étape 3 : choisit la cam selon qui parle et exporte un XML (FCP7) pour Premiere.

Règles de réalisation (v1) :
- un micro "parle" quand il domine l'autre de DOMINANCE dB (centre calibré sur l'épisode) ;
- les deux en même temps (chevauchement, rires) -> plan large ;
- silence -> on garde le plan en cours ;
- les "ouais / hmm" de moins de MIN_TURN s ne font pas couper ;
- coupe LEAD s avant le premier mot ;
- plan de MIN_SHOT s minimum ; les échanges rapides passent en plan large ;
- monologue de plus de MAX_SHOT s -> respiration en plan large au moment le plus calme ;
- cam absente (arrêtée, pas encore lancée) -> plan large.

Dans la séquence, les 3 cams sont empilées et coupées aux mêmes endroits, seule la cam
choisie est active : pour changer d'angle, sélectionner le plan et Maj+E (activer).

Usage : python edit.py sessions/exemple2.json
"""
import json
import random
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape

import numpy as np
import soundfile as sf

import travail

SR = 8000
HOP = 80  # 10 ms
DOMINANCE = 6.0
MIN_TURN = 0.8
GAP_MERGE = 1.0
OVERLAP_MIN = 1.0
LEAD = 0.2
MIN_SHOT = 2.5
MAX_SHOT = (25.0, 45.0)  # durée sur un même visage avant un plan large (tirée au hasard)
WIDE_FIRST = 8.0  # pas de plan large avant 8 s de prise de parole
WIDE_LEN = (6.0, 14.0)  # durée visée du plan large, arrondie à la fin de phrase
WIDE_MAX = 18.0
WIDE_EVERY = None  # écart max entre deux plans larges (s), réglable par session (realisation.wide_every)
WIDE = "LARGE"


# ---------- analyse audio ----------

def level_db(p: Path) -> np.ndarray:
    x, _ = sf.read(p, dtype="float32")
    n = len(x) // HOP
    return 20 * np.log10(np.sqrt(np.mean(x[: n * HOP].reshape(n, HOP) ** 2, axis=1)) + 1e-7)


def runs(labels: np.ndarray):
    """Découpe un tableau d'étiquettes en (étiquette, début, fin) en trames."""
    edges = np.flatnonzero(np.diff(labels)) + 1
    starts = np.concatenate(([0], edges))
    ends = np.concatenate((edges, [len(labels)]))
    return [(labels[s], s, e) for s, e in zip(starts, ends)]


def speaker_states(lv: dict[str, np.ndarray]) -> tuple[np.ndarray, list[str], dict]:
    names = list(lv)
    a, b = (lv[k] for k in names)
    n = min(len(a), len(b))
    a, b = a[:n], b[:n]
    gate_a = np.percentile(a, 10) + 0.5 * (np.percentile(a, 95) - np.percentile(a, 10))
    gate_b = np.percentile(b, 10) + 0.5 * (np.percentile(b, 95) - np.percentile(b, 10))
    loud = (a > gate_a) | (b > gate_b)
    d = a - b
    # centre = milieu entre les deux groupes (A parle / B parle) de l'écart de niveau (k-means 1D)
    x = d[loud]
    lo, hi = np.percentile(x, 10), np.percentile(x, 90)
    for _ in range(50):
        c = (lo + hi) / 2
        lo, hi = np.median(x[x < c]), np.median(x[x >= c])
    center = (lo + hi) / 2

    # 0 = silence, 1 = A, 2 = B, 3 = les deux
    st = np.zeros(n, dtype=np.int8)
    st[loud & (d > center + DOMINANCE)] = 1
    st[loud & (d < center - DOMINANCE)] = 2
    st[(a > gate_a) & (b > gate_b) & (np.abs(d - center) <= DOMINANCE)] = 3
    # lissage : étiquette majoritaire sur 0,5 s
    w = 50
    counts = np.stack([np.convolve(st == k, np.ones(w), mode="same") for k in range(4)])
    st = np.argmax(counts, axis=0).astype(np.int8)
    calib = {"center_db": float(center), "groups_db": [float(lo), float(hi)],
             "gate_db": [float(gate_a), float(gate_b)]}
    return st, names, calib


def turns_from_states(st: np.ndarray) -> list[tuple[int, float, float]]:
    fr = HOP / SR
    rs = [(int(l), s * fr, e * fr) for l, s, e in runs(st)]
    out = []
    for l, s, e in rs:
        if l in (1, 2) and e - s < MIN_TURN:
            l = 0  # relance courte : on ne coupe pas
        if l == 3 and e - s < OVERLAP_MIN:
            l = 0
        out.append((l, s, e))
    # fusionne un même locuteur séparé par un court silence
    merged = []
    for l, s, e in out:
        if l == 0:
            continue
        if merged and merged[-1][0] == l and s - merged[-1][2] < GAP_MERGE:
            merged[-1] = (l, merged[-1][1], e)
        else:
            merged.append((l, s, e))
    return merged


# ---------- réalisation ----------

def merge_same(shots):
    out = []
    for c, s, e in shots:
        if out and out[-1][0] == c:
            out[-1] = (c, out[-1][1], e)
        else:
            out.append((c, s, e))
    return out


def phrases(sents, pause=0.35):
    """(début, fin) des bouts de phrase : la transcription regroupe parfois 30 s de parole en une « phrase »,
    on recoupe donc aussi aux virgules / points et aux respirations entre deux mots"""
    out = []
    for x in sents:
        ws = x.get("words") or [{"w": "", "start": x["start"], "end": x["end"]}]
        a = ws[0]["start"]
        for w, nxt in zip(ws, ws[1:] + [None]):
            if nxt is None or w["w"].endswith((",", ".", "?", "!", "…")) or nxt["start"] - w["end"] > pause:
                out.append((a, w["end"]))
                if nxt is not None:
                    a = nxt["start"]
    return sorted(out)


def wide_window(s, e, limit, bounds, rng):
    """Plan large calé sur des phrases entières dans le plan [s, e], ou None.

    bounds : (début, fin) des phrases du locuteur. Le plan large commence au début d'une phrase
    située après `limit` et s'arrête à la fin de la phrase qui atteint la durée visée."""
    target = rng.uniform(*WIDE_LEN)
    for i, (a, _) in enumerate(bounds):
        if a < s + max(WIDE_FIRST, limit) or a > e - MIN_SHOT - WIDE_LEN[0]:
            continue
        for _, b in bounds[i:]:
            if b - a > WIDE_MAX or b > e - MIN_SHOT:
                break
            if b - a >= target:
                return a - LEAD, b
        # pas de fenêtre propre à partir de cette phrase : on essaie la suivante
    return None


def direct(turns, names, total, energy, coverage, sentences=(), seed=7):
    rng = random.Random(seed)
    cam_of = {1: names[0], 2: names[1], 3: WIDE}
    # 1. un plan par tour de parole, coupé juste avant le premier mot
    shots = []
    cur, t0 = WIDE, 0.0
    for l, s, e in turns:
        c = cam_of[l]
        cut = max(0.0, s - LEAD)
        if c != cur and cut > t0:
            shots.append((cur, t0, cut))
            cur, t0 = c, cut
    shots.append((cur, t0, total))
    shots = merge_same(shots)

    # 2. plans trop courts -> plan large (échanges rapides), puis on refusionne
    shots = merge_same([(WIDE if e - s < MIN_SHOT else c, s, e) for c, s, e in shots])
    # un plan large encore trop court est absorbé par le plan précédent
    fixed = []
    for c, s, e in shots:
        if fixed and e - s < MIN_SHOT:
            fixed[-1] = (fixed[-1][0], fixed[-1][1], e)
        else:
            fixed.append((c, s, e))
    shots = merge_same(fixed)

    # 3. monologues longs : un vrai plan large, sur des phrases entières, de durée variable
    bounds = {k: phrases([x for x in sentences if x["speaker"] == k]) for k in names}
    out = []
    for c, s, e in shots:
        limit = rng.uniform(*MAX_SHOT)
        while c != WIDE and e - s > limit:
            w = wide_window(s, e, limit, bounds.get(c, []), rng)
            if w is None and e - s > MAX_SHOT[1]:  # pas de fenêtre idéale : on prend la première phrase possible
                w = wide_window(s, e, WIDE_FIRST, bounds.get(c, []), rng)
            if w is None:
                break
            out += [(c, s, w[0]), (WIDE, w[0], w[1])]
            s = w[1]
            limit = rng.uniform(*MAX_SHOT)
        out.append((c, s, e))
    shots = merge_same(out)

    # 3b. échanges rapides : chaque plan est court donc l'étape 3 ne met jamais de large (Exemple 1 : 5 min 42 sans).
    # Au-delà de WIDE_EVERY s sans plan large : un large dans le plan en cours s'il est assez long, sinon
    # tout un plan court (relance, question) passe en large.
    if WIDE_EVERY:
        out, last = [], 0.0
        for c, s, e in shots:
            if c == WIDE:
                last = e
            elif e - last > WIDE_EVERY:
                w = wide_window(s, e, WIDE_FIRST, bounds.get(c, []), rng)
                if w is not None:
                    out += [(c, s, w[0]), (WIDE, w[0], w[1])]
                    s, last = w[1], w[1]
                elif s - last > WIDE_EVERY * 0.6 and MIN_SHOT * 1.2 <= e - s <= WIDE_MAX:
                    c, last = WIDE, e
            out.append((c, s, e))
        shots = merge_same(out)

    # 4. cam pas disponible sur une partie du plan -> plan large sur cette partie
    # (une cam peut être en plusieurs fichiers : coverage[c] = liste d'intervalles)
    out = []
    for c, s, e in shots:
        if c == WIDE:
            out.append((c, s, e))
            continue
        t = s
        for a, b in sorted(coverage[c]):
            if b <= t or a >= e:
                continue
            if a > t:
                out.append((WIDE, t, a))
            # un bout de moins de MIN_SHOT avant/après un trou de la cam passe en plan large
            piece = min(e, b) - max(t, a)
            out.append((c if piece >= MIN_SHOT or piece == e - s else WIDE, max(t, a), min(e, b)))
            t = min(e, b)
        if t < e:
            out.append((WIDE, t, e))
    shots = merge_same(out)

    # 5. plan large lui-même absent (trou entre deux fichiers) -> visage du dernier qui a parlé
    def covered(c, t):
        return any(a <= t < b for a, b in coverage[c])

    out, face = [], names[0]
    for c, s, e in shots:
        if c != WIDE:
            face = c
        cuts = sorted({s, e, *(x for a, b in coverage[WIDE] for x in (a, b) if s < x < e)})
        for a, b in zip(cuts, cuts[1:]):
            m = (a + b) / 2
            if c == WIDE and not covered(WIDE, m):
                c2 = face if covered(face, m) else next((n for n in names if covered(n, m)), WIDE)
                out.append((c2, a, b))
            else:
                out.append((c, a, b))
    return merge_same(out)


# ---------- export XML (FCP7 / xmeml v4) ----------

PROBE_CACHE = travail.racine() / "probe_cache.json"


def probe(path: str) -> dict:
    """Caractéristiques d'une vidéo, gardées en cache : le XML se refait même disque externe débranché."""
    cache = json.loads(PROBE_CACHE.read_text()) if PROBE_CACHE.exists() else {}
    if not Path(path).exists() and path in cache:
        return cache[path]
    cache[path] = _probe(path)
    PROBE_CACHE.write_text(json.dumps(cache, indent=1, ensure_ascii=False))
    return cache[path]


def _probe(path: str) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height,r_frame_rate:format=duration", "-of", "json", path],
                         capture_output=True, text=True, check=True).stdout
    j = json.loads(out)
    s = j["streams"][0]
    num, den = map(int, s["r_frame_rate"].split("/"))
    return {"w": s["width"], "h": s["height"], "fps": num // den, "dur": float(j["format"]["duration"])}


def rate(tb: int) -> str:
    return f"<rate><timebase>{tb}</timebase><ntsc>FALSE</ntsc></rate>"


def pathurl(p: str) -> str:
    return "file://localhost" + quote(p)


def file_video(fid, path, info):
    return (f'<file id="{fid}"><name>{escape(Path(path).name)}</name><pathurl>{escape(pathurl(path))}</pathurl>'
            f'{rate(info["fps"])}<duration>{int(info["dur"] * info["fps"])}</duration>'
            f'<media><video><samplecharacteristics>{rate(info["fps"])}<width>{info["w"]}</width>'
            f'<height>{info["h"]}</height><pixelaspectratio>square</pixelaspectratio></samplecharacteristics></video>'
            f'</media></file>')


def file_audio(fid, path, dur, fps):
    return (f'<file id="{fid}"><name>{escape(Path(path).name)}</name><pathurl>{escape(pathurl(path))}</pathurl>'
            f'{rate(fps)}<duration>{int(dur * fps)}</duration><media><audio><samplecharacteristics>'
            f'<depth>24</depth><samplerate>44100</samplerate></samplecharacteristics><channelcount>2</channelcount>'
            f'</audio></media></file>')


SCALE = ('<filter><effect><name>Basic Motion</name><effectid>basic</effectid><effectcategory>motion</effectcategory>'
         '<effecttype>motion</effecttype><mediatype>video</mediatype><parameter authoringApp="PremierePro">'
         '<parameterid>scale</parameterid><name>Scale</name><valuemin>0</valuemin><valuemax>1000</valuemax>'
         '<value>{}</value></parameter></effect></filter>')


def build_xml(cfg, sync, shots, fps, program, only=None, name=None):
    """program : la séquence, dans l'ordre. ("rush", f0, f1, opts) = images f0 à f1 des micros (cams calées
    dessus), ("insert", chemin, f0, f1) = images f0 à f1 d'une vidéo déjà montée (intro, CTA, outro).
    opts (facultatif) : {"cam": "LARGE"} impose la cam du morceau, {"micros": ["FRED"]} coupe les autres
    micros (teaser : on n'entend que l'invité), {"zoom": 125} recadre (zoom sec), {"sans_video": True}
    désactive les cams (l'image vient d'une vidéo d'habillage, ex. teaser déjà animé).
    cfg["habillage"] : vidéos posées tout en haut, une piste chacune (teaser animé, sous-titres…).

    only : ne garder que ce fichier (ex. "EXEMPLE_2"), sans les micros, pour un XML d'ajout à coller
    dans une séquence déjà travaillée : mêmes pistes, mêmes timecodes."""
    cams = list(cfg["cams"])
    files = {c: [(k, v) for k, v in sync["cams"].items() if v.get("cam", k) == c] for c in cams}
    info = {k: probe(v.get("path") or cfg["cams"][k]) for k, v in sync["cams"].items()}
    seq_w = max(i["w"] for i in info.values())
    seq_h = max(i["h"] for i in info.values())
    written = set()
    pos, p = [], 0  # position de chaque morceau dans la séquence
    for seg in program:
        pos.append(p)
        p += seg[2] - seg[1] if seg[0] == "rush" else seg[3] - seg[2]
    total_frames = p
    rush = [(seg[1], seg[2], q, (seg[3:] or [{}])[0]) for seg, q in zip(program, pos) if seg[0] == "rush"]

    def fref(fid, full):
        if fid in written:
            return f'<file id="{fid}"/>'
        written.add(fid)
        return full

    vtracks = []
    n = 0
    def cam_items(cam, k, sc):
        nonlocal n
        a = sc["offset_s"]
        b = sc["drift_ppm"] * 1e-6
        cov0, cov1 = sc["covers_mic_s"]
        fid = f"file-cam-{k}"
        items = []
        def shots_of(r0, r1, o):
            return [(o["cam"], r0 / fps, r1 / fps)] if "cam" in o else shots

        for (c, s, e), (r0, r1, q, o) in ((x, r) for r in rush for x in shots_of(*r[:2], r[3])):
            f0, f1 = max(round(s * fps), r0), min(round(e * fps), r1)
            # bornes de couverture du fichier, arrondies vers l'intérieur
            g0, g1 = max(f0, int(np.ceil(cov0 * fps))), min(f1, int(np.floor(cov1 * fps)) - 1)
            if g1 <= g0:
                continue
            tc = (g0 / fps - a) / (1 + b)  # correction de dérive à chaque plan
            # Premiere lit in/out dans la cadence de la séquence, pas celle du rush (testé : la cam 100 i/s
            # était décalée). Seul le <file> porte la cadence réelle.
            src_in = round(tc * fps)
            src_out = src_in + (g1 - g0)
            scale = round(100 * seq_w / info[k]["w"] * o.get("zoom", 100) / 100)
            n += 1
            items.append(
                f'<clipitem id="clip-{n}"><name>CAM {cam}</name><enabled>{"TRUE" if c == cam and not o.get("sans_video") else "FALSE"}</enabled>'
                f'<duration>{int(info[k]["dur"] * fps)}</duration>{rate(fps)}<start>{g0 - r0 + q}</start><end>{g1 - r0 + q}</end>'
                f'<in>{src_in}</in><out>{src_out}</out>'
                f'{fref(fid, file_video(fid, sc.get("path") or cfg["cams"][k], info[k]))}'
                f'{SCALE.format(scale) if scale != 100 else ""}</clipitem>')
        return items

    for cam in cams:
        items = [it for k, sc in files[cam] if not only or k == only for it in cam_items(cam, k, sc)]
        vtracks.append(f'<track>{"".join(items)}<enabled>TRUE</enabled><locked>FALSE</locked></track>')

    atracks = []
    son = cfg.get("son", {})  # versions harmonisées à -16 LUFS (son.py) ; sinon les fichiers d'origine
    for k, path in ({} if only else cfg["mics"]).items():
        path = son.get("mics", {}).get(k, path)
        dur = sf.info(path).duration
        fid = f"file-mic-{k}"
        items = []
        for r0, r1, q, o in rush:
            n += 1
            on = "TRUE" if k in o.get("micros", [k]) else "FALSE"
            items.append(
                f'<clipitem id="clip-{n}"><name>MIC {k}</name><enabled>{on}</enabled>'
                f'<duration>{int(dur * fps)}</duration>{rate(fps)}<start>{q}</start><end>{q + r1 - r0}</end>'
                f'<in>{r0}</in><out>{r1}</out>{fref(fid, file_audio(fid, path, dur, fps))}'
                f'<sourcetrack><mediatype>audio</mediatype><trackindex>1</trackindex></sourcetrack></clipitem>')
        atracks.append(f'<track>{"".join(items)}<enabled>TRUE</enabled><locked>FALSE</locked></track>')

    # inserts (intro, CTA, outro) : piste vidéo au-dessus des cams + 2 pistes son (stéréo)
    ins = [(seg[1], seg[2], seg[3], q, (seg[4:] or [{}])[0]) for seg, q in zip(program, pos) if seg[0] == "insert" and not only]
    if ins:
        vitems, aitems = [], [[], []]
        for path, f0, f1, q, o in ins:
            fi = probe(path)
            scale = round(100 * seq_w / fi["w"])
            fid = "file-ins-" + quote(Path(path).stem, safe="")
            full = (f'<file id="{fid}"><name>{escape(Path(path).name)}</name><pathurl>{escape(pathurl(path))}'
                    f'</pathurl>{rate(fi["fps"])}<duration>{int(fi["dur"] * fi["fps"])}</duration><media><video>'
                    f'<samplecharacteristics>{rate(fi["fps"])}<width>{fi["w"]}</width><height>{fi["h"]}</height>'
                    '<pixelaspectratio>square</pixelaspectratio></samplecharacteristics></video><audio>'
                    '<samplecharacteristics><depth>16</depth><samplerate>48000</samplerate></samplecharacteristics>'
                    '<channelcount>2</channelcount></audio></media></file>')
            head = f'<duration>{int(fi["dur"] * fps)}</duration>{rate(fps)}<start>{q}</start><end>{q + f1 - f0}</end><in>{f0}</in><out>{f1}</out>'
            n += 1
            vitems.append(f'<clipitem id="clip-{n}"><name>{escape(Path(path).stem)}</name><enabled>TRUE</enabled>'
                          f'{head}{fref(fid, full)}{SCALE.format(scale) if scale != 100 else ""}</clipitem>')
            # son : la version harmonisée (WAV à part, même minutage) sauf si l'insert garde son son tel quel
            wav = None if o.get("son_brut") else son.get("inserts", {}).get(path)
            if wav:
                wd = sf.info(wav).duration
                wfid = "file-son-" + quote(Path(wav).stem, safe="")
                ahead = f'<duration>{int(wd * fps)}</duration>{rate(fps)}<start>{q}</start><end>{q + f1 - f0}</end><in>{f0}</in><out>{f1}</out>'
            for ch in (0, 1):
                n += 1
                src_ = (f'{ahead}{fref(wfid, file_audio(wfid, wav, wd, fps))}' if wav else f'{head}{fref(fid, full)}')
                aitems[ch].append(f'<clipitem id="clip-{n}"><name>{escape(Path(path).stem)}</name><enabled>TRUE'
                                  f'</enabled>{src_}<sourcetrack><mediatype>audio</mediatype>'
                                  f'<trackindex>{ch + 1}</trackindex></sourcetrack></clipitem>')
        vtracks.append(f'<track>{"".join(vitems)}<enabled>TRUE</enabled><locked>FALSE</locked></track>')
        atracks += [f'<track>{"".join(a)}<enabled>TRUE</enabled><locked>FALSE</locked></track>' for a in aitems]

    hab = [] if only else cfg.get("habillage", [])
    # cfg["habillage"] : [{"fichier", "debut_s", "src": [a, b] (facultatif, sinon tout le fichier),
    # "piste": nom (facultatif : les éléments d'une même piste partagent une piste, ex. les B-roll)}]
    vgroups, agroups = {}, {}
    for i, h in enumerate(hab):
        audio = Path(h["fichier"]).suffix.lower() == ".wav"
        (agroups if audio else vgroups).setdefault(h.get("piste", i), []).append(h)
    for group in agroups.values():
        # son d'habillage (musique, bruitages) : stéréo sur 2 pistes son
        items = [[], []]
        for h in group:
            dur = sf.info(h["fichier"]).duration
            fid = "file-hab-" + quote(Path(h["fichier"]).stem, safe="")
            s0, s1 = h.get("src", [0, dur])
            q, f0, f1 = round(h["debut_s"] * fps), round(s0 * fps), round(s1 * fps)
            for ch in (0, 1):
                n += 1
                items[ch].append(
                    f'<clipitem id="clip-{n}"><name>{escape(Path(h["fichier"]).stem)}</name><enabled>TRUE</enabled>'
                    f'<duration>{int(dur * fps)}</duration>{rate(fps)}<start>{q}</start><end>{q + f1 - f0}</end><in>{f0}</in><out>{f1}</out>'
                    f'{fref(fid, file_audio(fid, h["fichier"], dur, fps))}<sourcetrack><mediatype>audio</mediatype>'
                    f'<trackindex>{ch + 1}</trackindex></sourcetrack></clipitem>')
        atracks += [f'<track>{"".join(it)}<enabled>TRUE</enabled><locked>FALSE</locked></track>' for it in items]
    for group in vgroups.values():
        items = []
        for h in group:
            fi = probe(h["fichier"])
            fid = "file-hab-" + quote(Path(h["fichier"]).stem, safe="")
            s0, s1 = h.get("src", [0, fi["dur"]])
            q, f0, f1 = round(h["debut_s"] * fps), round(s0 * fps), int(s1 * fps)
            n += 1
            items.append(f'<clipitem id="clip-{n}"><name>{escape(Path(h["fichier"]).stem)}</name><enabled>TRUE</enabled>'
                         f'<duration>{int(fi["dur"] * fps)}</duration>{rate(fps)}<start>{q}</start><end>{q + f1 - f0}</end>'
                         f'<in>{f0}</in><out>{f1}</out>{fref(fid, file_video(fid, h["fichier"], fi))}'
                         f'{SCALE.format(round(100 * seq_w / fi["w"])) if fi["w"] != seq_w else ""}</clipitem>')
        vtracks.append(f'<track>{"".join(items)}<enabled>TRUE</enabled><locked>FALSE</locked></track>')

    # filigrane (logo en haut à droite) : sur chaque morceau de l'épisode, pas sur le teaser ni les inserts
    if cfg.get("filigrane") and not only:
        png = cfg["filigrane"]
        fid = "file-filigrane"
        big = 10 * 3600 * fps
        items = []
        for r0, r1, q, o in rush:
            if o:  # morceaux du teaser
                continue
            n += 1
            full = (f'<file id="{fid}"><name>{escape(Path(png).name)}</name><pathurl>{escape(pathurl(png))}</pathurl>'
                    f'{rate(fps)}<duration>{big}</duration><media><video><samplecharacteristics>{rate(fps)}'
                    f'<width>{seq_w}</width><height>{seq_h}</height><pixelaspectratio>square</pixelaspectratio>'
                    '</samplecharacteristics></video></media></file>')
            items.append(f'<clipitem id="clip-{n}"><name>LOGO FILIGRANE</name><enabled>TRUE</enabled><duration>{big}</duration>'
                         f'{rate(fps)}<start>{q}</start><end>{q + r1 - r0}</end><in>0</in><out>{r1 - r0}</out>{fref(fid, full)}</clipitem>')
        vtracks.append(f'<track>{"".join(items)}<enabled>TRUE</enabled><locked>FALSE</locked></track>')

    def seq_frame(f):
        """image des micros -> image de la séquence (None si coupée au montage)"""
        # un même passage peut être utilisé deux fois (teaser + épisode) : on prend le plus long morceau
        hits = [(r1 - r0, f - r0 + q) for r0, r1, q, _ in rush if r0 <= f < r1]
        return max(hits)[1] if hits else None

    markers = "".join(
        f'<marker><name>{escape(m["name"])}</name><comment>{escape(m.get("comment", ""))}</comment>'
        f'<in>{seq_frame(round(m["start"] * fps))}</in><out>{seq_frame(round(m["start"] * fps)) + round((m["end"] - m["start"]) * fps)}</out></marker>'
        for m in ([] if only else cfg.get("markers", [])) if seq_frame(round(m["start"] * fps)) is not None)
    name = name or f'{cfg["name"]} PREMONTAGE AUTO'
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n<xmeml version="4">'
            f'<sequence id="seq-1"><name>{escape(name)}</name><duration>{total_frames}</duration>{rate(fps)}{markers}'
            '<timecode><rate><timebase>25</timebase><ntsc>FALSE</ntsc></rate><string>00:00:00:00</string>'
            '<frame>0</frame><displayformat>NDF</displayformat></timecode>'
            f'<media><video><format><samplecharacteristics>{rate(fps)}<width>{seq_w}</width><height>{seq_h}</height>'
            '<pixelaspectratio>square</pixelaspectratio><anamorphic>FALSE</anamorphic><fielddominance>none'
            f'</fielddominance></samplecharacteristics></format>{"".join(vtracks)}</video>'
            '<audio><numOutputChannels>2</numOutputChannels><format><samplecharacteristics><depth>16</depth>'
            f'<samplerate>48000</samplerate></samplecharacteristics></format>{"".join(atracks)}</audio></media>'
            '</sequence></xmeml>\n')


def main(cfg_path: str, ajout: list[str] = (), figes: str | None = None) -> None:
    global MAX_SHOT, WIDE_LEN, WIDE_MAX, WIDE_EVERY
    cfg = json.loads(Path(cfg_path).read_text())
    # "realisation" : réglages propres à une session (ex. montage plus nerveux)
    r = cfg.get("realisation", {})
    MAX_SHOT = tuple(r.get("max_shot", MAX_SHOT))
    WIDE_LEN = tuple(r.get("wide_len", WIDE_LEN))
    WIDE_MAX = r.get("wide_max", WIDE_MAX)
    WIDE_EVERY = r.get("wide_every", WIDE_EVERY)
    work = travail.dossier(cfg["name"])
    sync = json.loads((work / "sync.json").read_text())
    fps = cfg["fps"]

    lv = {k: level_db(work / f"mic_{k}.wav") for k in cfg["mics"]}
    st, names, calib = speaker_states(lv)
    energy = np.maximum(*[v[: len(st)] for v in lv.values()])
    total_frames = int(sync["mic_duration_s"] * fps)
    total = total_frames / fps
    # couverture de chaque fichier arrondie vers l'intérieur à l'image (comme dans build_xml),
    # sinon un plan peut commencer 1 image avant le début du fichier -> image noire
    coverage = {}
    for k, v in sync["cams"].items():
        a, b = v["covers_mic_s"]
        coverage.setdefault(v.get("cam", k), []).append((np.ceil(a * fps) / fps, (np.floor(b * fps) - 1) / fps))

    turns = turns_from_states(st)
    tr = work / "transcript.json"
    sentences = json.loads(tr.read_text()) if tr.exists() else []
    if not sentences:
        print("pas de transcript : pas de plan large dans les monologues (lancer transcribe.py)")
    if figes:
        # plans repris d'un montage déjà livré (ex. séquence déjà étalonnée) : mêmes coupes
        shots = [tuple(x) for x in json.loads(Path(figes).read_text())["shots"]]
        # un bout de plan sur une cam absente (quelques images) est donné au plan précédent
        fixed = []
        for c, s, e in shots:
            ok = c == WIDE or any(a <= s + 1e-6 and e - 1e-6 <= b for a, b in coverage[c])
            if not ok and fixed:
                start = next((max(s, a) for a, b in coverage[c] if b > s and a < e), e)
                fixed[-1] = (fixed[-1][0], fixed[-1][1], start)
                s = start
            if e > s:
                fixed.append((c, s, e))
        shots = merge_same(fixed)
    else:
        shots = direct(turns, names, total, energy, coverage, sentences)
        shots = [(c, round(s * fps) / fps, round(e * fps) / fps) for c, s, e in shots]
        shots = [x for x in shots if x[2] > x[1]]

    # "montage" : morceaux du rush dans l'ordre + vidéos déjà montées insérées entre eux
    montage = cfg.get("montage") or [{"rush": cfg.get("trim_s", [0.0, total])}]
    program = []
    for m in montage:
        if "rush" in m:
            opts = {k: m[k] for k in ("cam", "micros", "zoom", "sans_video") if k in m}
            program.append(("rush", round(m["rush"][0] * fps), min(round(m["rush"][1] * fps), total_frames), opts))
        else:
            program.append(("insert", m["insert"], round(m["src"][0] * fps), round(m["src"][1] * fps),
                            {k: m[k] for k in ("son_brut",) if k in m}))
    kept = [x for x in program if x[0] == "rush"]

    # début / fin gardés (on retire le clap et l'après-émission)
    body = [x for x in kept if not x[3]]  # morceaux de l'épisode (hors teaser)
    t0, t1 = min(x[1] for x in body) / fps, max(x[2] for x in body) / fps  # morceaux pas forcément dans l'ordre du rush (medley tourné après l'au revoir)
    shots = [(c, max(s, t0), min(e, t1)) for c, s, e in shots if e > t0 and s < t1]
    # un bout de plan laissé par la coupe est absorbé par son voisin
    if len(shots) > 1 and shots[0][2] - shots[0][1] < MIN_SHOT:
        shots = [(shots[1][0], t0, shots[1][2])] + shots[2:]
    if len(shots) > 1 and shots[-1][2] - shots[-1][1] < MIN_SHOT:
        shots = shots[:-2] + [(shots[-2][0], shots[-2][1], t1)]
    total = sum(x[2] - x[1] for x in body) / fps
    has_ins = len(program) > len(kept)

    name = cfg.get("sortie") or f'{cfg["name"]} {"MONTAGE AVEC INSERTS" if has_ins else "PREMONTAGE AUTO"}'
    xml = build_xml(cfg, sync, shots, fps, program, name=name)
    out_dir = Path(cfg.get("dossier_sortie") or Path(cfg["mics"][names[0]]).parent)  # app : dossier du projet
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{name}.xml"
    out.write_text(xml, encoding="utf-8")
    if not figes:
        (work / "shots.json").write_text(json.dumps({"calibration": calib, "shots": shots}, indent=1))

    # bilan
    lens = np.array([e - s for _, s, e in shots])
    talk = {names[0]: np.mean(st == 1), names[1]: np.mean(st == 2), "LES DEUX": np.mean(st == 3)}
    print(f"Calibration : centre {calib['center_db']:+.1f} dB")
    print("Temps de parole : " + ", ".join(f"{k} {v:.0%}" for k, v in talk.items()))
    print(f"{len(shots)} plans | durée moyenne {lens.mean():.1f} s | médiane {np.median(lens):.1f} s "
          f"| min {lens.min():.1f} s | max {lens.max():.1f} s")
    inside = [(c, max(s, r0 / fps), min(e, r1 / fps)) for _, r0, r1, _ in body for c, s, e in shots]
    for c in [*cfg["cams"]]:
        tot = sum(max(0, e - s) for k, s, e in inside if k == c)
        print(f"  CAM {c:6s} {tot / total:5.1%} du temps, {sum(1 for k, *_ in shots if k == c)} plans")
    print(f"XML : {out}")

    # XML d'ajout : un seul fichier de rush, à coller dans une séquence déjà travaillée
    for key in ajout:
        name = f'{cfg["name"]} AJOUT {key}'
        p = out_dir / f"{name}.xml"
        p.write_text(build_xml(cfg, sync, shots, fps, program, only=key, name=name), encoding="utf-8")
        print(f"XML d'ajout : {p}")


if __name__ == "__main__":
    # python edit.py sessions/x.json [--ajout EXEMPLE_2] [--plans-figes work/X/shots.json]
    args = sys.argv[1:]
    opt = lambda f: [args[i + 1] for i, a in enumerate(args) if a == f]
    main(args[0], opt("--ajout"), (opt("--plans-figes") or [None])[0])
