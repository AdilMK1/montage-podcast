"""Aperçu MP4 léger (540p) d'un XML de montage produit par edit.py, sans Premiere.

Image : les clips actifs des pistes de caméras bout à bout, puis les habillages (vidéos alpha) par-dessus.
Son : toutes les pistes audio additionnées (paires stéréo d'habillage moyennées), limiteur.
Pour juger le rythme, les coupes et l'habillage avant d'ouvrir Premiere : pas d'étalonnage, pas d'effets.

Usage : python apercu_xml.py montage.xml sortie.mp4
Export final depuis les rushs (pas les proxys), couleurs BT.709, étalonnage d'une cam par un filtre ffmpeg :
python apercu_xml.py montage.xml sortie.mp4 --export 1920x1080 --etalonnage C8990 "<filtre>"
Test sur un court passage de la timeline : ajouter --extrait <début_s> <fin_s>
"""
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote

import cv2
import numpy as np
import soundfile as sf

import travail

W, H, SR = 960, 540, 48000
SRC_W, SRC_H = 1280, 720  # taille de lecture des plans zoomés (celle des proxys)
CRF_ZOOM = 18  # qualité des plans en mouvement : plus bas, le zoom lent reste régulier


PROXYS = None  # dossier des proxys (proxys.py) à côté du XML : lus à la place des rushs 4K s'ils existent
EXPORT = False
EXTRAIT = None
GRADE = {}  # nom de rush -> filtre ffmpeg
CRF_BASE, CRF_FINAL, PRESET_FINAL = 26, 20, "veryfast"
BT709 = ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709"]
EXACT = "accurate_rnd+full_chroma_int"  # sans ça, l'aller-retour YUV/RGB des plans zoomés les assombrit de 2 %



def progres(f):
    """avancement (0-1) lu par l'app pour sa jauge (fichier donné par MONTAGE_PROGRES)"""
    import os
    p = os.environ.get("MONTAGE_PROGRES")
    if p:
        try:
            Path(p).write_text(f"{f:.3f}")
        except OSError:
            pass

def grade(path):
    f = GRADE.get(Path(path).stem)
    return f + "," if f else ""


def setup_export(size, filters):
    global W, H, SRC_W, SRC_H, EXPORT, CRF_BASE, CRF_FINAL, PRESET_FINAL, CRF_ZOOM
    W, H = map(int, size.split("x"))
    SRC_W, SRC_H = (3840, 2160) if W > 1920 else (2560, 1440)
    EXPORT, CRF_BASE, CRF_ZOOM = True, 13, 13
    CRF_FINAL, PRESET_FINAL = (17, "fast") if W > 1920 else (16, "medium")
    if W > 1920:  # 4K : fichiers intermédiaires plus légers, ils tiennent sur le Mac
        CRF_BASE = CRF_ZOOM = 16
    GRADE.update(filters)


def path_of(c, files):
    f = c.find("file")
    if f.find("pathurl") is not None:
        path = unquote(f.findtext("pathurl").replace("file://localhost", ""))
        px = PROXYS / (Path(path).stem + ".mp4") if PROXYS else None
        files[f.get("id")] = str(px) if px and px.exists() and Path(path).suffix.lower() == ".mp4" else path
    return files[f.get("id")]


def zoom_of(c):
    """courbe du Basic Motion du clip : [(image relative au clip, facteur)] (1 = pas de zoom), relatif à l'échelle de base"""
    p = c.find(".//parameter[parameterid='scale']")
    if p is None:
        return [(0, 1.0)]
    d = int(c.findtext("end")) - int(c.findtext("start"))
    keys = [(int(k.findtext("when")), float(k.findtext("value"))) for k in p.findall("keyframe")]
    keys = [k for k in keys if k[0] <= d] or [(0, float(p.findtext("value")))]
    base = 100.0  # caméras 4K dans une séquence 4K
    return [(t, v / base) for t, v in keys]


def clips(track, files, fps):
    out = []
    for c in track.findall("clipitem"):
        p = path_of(c, files)
        if c.findtext("enabled") == "FALSE":
            continue
        out.append({"path": p, "start": int(c.findtext("start")) / fps, "end": int(c.findtext("end")) / fps,
                    "in": int(c.findtext("in")) / fps, "ch": int(c.findtext("sourcetrack/trackindex") or 1),
                    "zoom": zoom_of(c)})
    return out


def cut(track, a, b, fps):
    """ne garde que le passage [a, b] de la timeline ; l'extrait repart de zéro"""
    out = []
    for c in track:
        if c["end"] <= a or c["start"] >= b:
            continue
        off = max(0.0, a - c["start"])
        out.append({**c, "start": max(c["start"], a) - a, "end": min(c["end"], b) - a, "in": c["in"] + off,
                    "zoom": [(t - off * fps, v) for t, v in c["zoom"]]})
    return out


def moving(c):
    z = [v for _, v in c["zoom"]]
    return max(z) - min(z) > 1e-3


def zoom_vf(c, fps):
    z = c["zoom"][0][1]
    fit = f"scale={W}:{H}:flags=lanczos+{EXACT}:out_color_matrix=bt709:out_range=tv,format=yuv420p" if EXPORT else f"scale={W}:{H}"
    if abs(z - 1) < 1e-3:
        return f"{grade(c['path'])}{fit},fps={fps},setsar=1"
    return f"{grade(c['path'])}crop=iw/{z:.4f}:ih/{z:.4f},{fit},fps={fps},setsar=1"


def render_moving(group, fps, out):
    """Poussée : une seule lecture pour tous les morceaux d'un même mouvement, zoom sous-pixel image par image.
    (zoompan arrondit au pixel : sur un proxy 720p ça donne des saccades.)"""
    n = sum(round((c["end"] - c["start"]) * fps) for c in group)
    curve = []
    for c in group:
        k = round((c["end"] - c["start"]) * fps)
        curve += list(np.interp(np.arange(k), *zip(*c["zoom"])))
    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-ss", f"{group[0]['in']:.3f}", "-i", group[0]["path"], "-frames:v", str(n),
                            "-vf", f"fps={fps},{grade(group[0]['path'])}scale={SRC_W}:{SRC_H}" + (f":flags=lanczos+{EXACT}:in_color_matrix=bt709:in_range=tv:out_range=pc" if EXPORT else ""),
                            *(["-sws_flags", EXACT] if EXPORT else []), "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], stdout=subprocess.PIPE)
    color = ["-vf", f"scale=flags={EXACT}:in_range=pc:out_color_matrix=bt709:out_range=tv", *BT709] if EXPORT else []
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(fps),
                            "-i", "-", *color, "-c:v", "libx264", "-preset", "veryfast", "-crf", str(CRF_ZOOM), "-pix_fmt", "yuv420p",
                            str(out)], stdin=subprocess.PIPE)
    size = SRC_W * SRC_H * 3
    frame = None
    for z in curve:
        buf = dec.stdout.read(size)
        if len(buf) == size:
            frame = np.frombuffer(buf, np.uint8).reshape(SRC_H, SRC_W, 3)
        s = z * W / SRC_W
        m = np.float32([[s, 0, W / 2 - s * SRC_W / 2], [0, s, H / 2 - s * SRC_H / 2]])
        enc.stdin.write(cv2.warpAffine(frame, m, (W, H), flags=cv2.INTER_CUBIC).tobytes())
    dec.stdout.close()
    dec.wait()
    enc.stdin.close()
    enc.wait()


def groups_of(base, fps):
    """plans à la suite ; les morceaux contigus d'une même poussée (même rush, images qui se suivent) n'en font qu'un"""
    out = []
    for c in base:
        p = out[-1][-1] if out else None
        same = (p and moving(p) and moving(c) and p["path"] == c["path"] and abs(p["end"] - c["start"]) < 1e-6
                and abs(p["in"] + p["end"] - p["start"] - c["in"]) < 1.5 / fps)
        if same:
            out[-1].append(c)
        else:
            out.append([c])
    return out


def main(xml, out):
    global PROXYS
    PROXYS = None if EXPORT else Path(xml).parent / "PROXYS"
    seq = ET.parse(xml).getroot().find(".//sequence")
    fps = int(seq.findtext("rate/timebase"))
    total = int(seq.findtext("duration")) / fps
    files = {}
    vt = [clips(t, files, fps) for t in seq.find("media/video").findall("track")]
    at = [clips(t, files, fps) for t in seq.find("media/audio").findall("track")]
    if EXTRAIT:
        vt = [cut(t, *EXTRAIT, fps) for t in vt]
        at = [cut(t, *EXTRAIT, fps) for t in at]
        total = EXTRAIT[1] - EXTRAIT[0]
    cams = [t for t in vt if t and all(Path(c["path"]).suffix.lower() == ".mp4" for c in t)]
    over = [t for t in vt if t and t not in cams]
    base = sorted((c for t in cams for c in t), key=lambda c: c["start"])

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        # 1. image de base : un morceau par plan (trous éventuels en noir)
        parts, t = [], 0.0
        groups = groups_of(base, fps)
        for i, g in enumerate(groups):
            c = g[0]
            if c["start"] > t + 1e-3:
                p = tmp / f"n{i:04d}.mp4"
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=black:s={W}x{H}:r={fps}",
                                "-t", f"{c['start'] - t:.3f}", "-c:v", "libx264", "-preset", "veryfast", str(p)], check=True)
                parts.append(p)
            p = tmp / f"v{i:04d}.mp4"
            if moving(c):
                render_moving(g, fps, p)
            else:
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{c['in']:.3f}", "-i", c["path"],
                                "-frames:v", str(round((c["end"] - c["start"]) * fps)), "-an",
                                "-vf", zoom_vf(c, fps), "-c:v", "libx264", "-preset", "veryfast",
                                "-crf", str(CRF_BASE), "-pix_fmt", "yuv420p", *(BT709 + ["-sws_flags", EXACT] if EXPORT else []), str(p)], check=True)
            parts.append(p)
            t = g[-1]["end"]
            print(f"\rplans {i + 1}/{len(groups)}", end="", flush=True)
            progres(0.9 * (i + 1) / len(groups))
        print()
        lst = tmp / "list.txt"
        lst.write_text("".join(f"file '{p}'\n" for p in parts))
        video = tmp / "base.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy",
                        str(video)], check=True)

        # 2. son : toutes les pistes
        mix = np.zeros(int(total * SR) + SR)
        # un fichier stéréo posé sur deux pistes (canal 1 / canal 2) compte pour moitié sur chacune
        count = {}
        for tr in at:
            for c in tr:
                count[(c["path"], c["start"])] = count.get((c["path"], c["start"]), 0) + 1
        for tr in at:
            for c in tr:
                d = c["end"] - c["start"]
                raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{c['in']:.3f}", "-t", f"{d:.3f}", "-i", c["path"],
                                      "-af", f"pan=mono|c0=c{c['ch'] - 1}", "-ar", str(SR), "-f", "f32le", "-"],
                                     capture_output=True, check=True).stdout
                x = np.frombuffer(raw, np.float32)
                i0 = int(c["start"] * SR)
                mix[i0:i0 + len(x)] += x[:len(mix) - i0] / count[(c["path"], c["start"])]
        mix = mix[:int(total * SR)]
        wav = tmp / "son.wav"
        if EXPORT:  # limiteur sur les seuls pics : un gain global ferait baisser tout l'épisode pour l'impact du logo
            brut = tmp / "son_brut.wav"
            sf.write(brut, np.stack([mix, mix], 1).astype(np.float32), SR, subtype="FLOAT")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(brut), "-af", "alimiter=limit=0.87:level=false:latency=1",
                            "-c:a", "pcm_s24le", str(wav)], check=True)
        else:
            mix *= min(1.0, 0.89 / (np.abs(mix).max() + 1e-9))
            sf.write(wav, np.stack([mix, mix], 1).astype(np.float32), SR, subtype="PCM_24")

        # 3. habillages par-dessus + son
        inputs, chain, last = ["-i", str(video)], "", "[0:v]"
        # la séquence peut finir sur un insert posé au-dessus des caméras (outro) : on prolonge l'image de base en noir
        # jusqu'à la fin, sinon l'habillage est coupé avec elle
        vdur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
                                    capture_output=True, text=True).stdout or 0)
        if total - vdur > 0.04:
            chain, last = f"[0:v]tpad=stop_mode=add:stop_duration={total - vdur:.3f}[p0];", "[p0]"
        k, ni = 1, 1  # k : numéro d'habillage, ni : prochain numéro d'entrée ffmpeg (-i)
        for tr in over:
            for c in tr:
                d = c["end"] - c["start"]
                if Path(c["path"]).suffix.lower() in (".png", ".jpg", ".jpeg", ".tif", ".tiff"):
                    # image fixe (filigrane) : bouclée, sinon elle ne dure qu'une image
                    inputs += ["-loop", "1", "-framerate", str(fps), "-t", f"{d:.3f}", "-i", c["path"]]
                    src = f"[{ni}:v]setpts=PTS-STARTPTS"
                    ni += 1
                else:
                    # vidéo d'habillage lue DANS le filtre (movie=) et pas en entrée -i : avec plusieurs entrées -i,
                    # ffmpeg 8.1 se fige au hasard (0 % CPU, fichier bloqué vers 6,8 Mo), cf. nuits du 10 et 11/11.
                    # Lien sans espaces ni parenthèses pour ne pas avoir à échapper le chemin dans le graphe.
                    link = tmp / f"habillage{k}{Path(c['path']).suffix.lower()}"
                    travail.lien(c["path"], link)
                    src = f"movie={travail.chemin_filtre(link)},trim=start={c['in']:.3f}:duration={d:.3f},setpts=PTS-STARTPTS"
                # habillage décalé : précédé d'images transparentes plutôt que d'un décalage de timestamps
                chain += (f"{src},scale={W}:{H},format=rgba,tpad=start_duration={c['start']:.3f}:color=black@0[o{k}];"
                          f"{last}[o{k}]overlay=eof_action=pass[b{k}];")
                last = f"[b{k}]"
                k += 1
        inputs += ["-i", str(wav)]
        cmd = ["ffmpeg", "-v", "error", "-y", *inputs]
        if chain:
            cmd += ["-filter_complex", chain.rstrip(";"), "-map", last]
        else:
            cmd += ["-map", "0:v"]
        # sans habillage on garde l'image telle quelle : un 2e encodage écrase les mouvements très lents
        vcodec = ["-c:v", "libx264", "-preset", PRESET_FINAL, "-crf", str(CRF_FINAL), "-pix_fmt", "yuv420p"] if chain else ["-c:v", "copy"]
        cmd += ["-map", f"{ni}:a", *vcodec, *(BT709 if EXPORT else []), "-c:a", "aac", "-b:a", "320k" if EXPORT else "160k",
                "-movflags", "+faststart", str(out)]
        subprocess.run(cmd, check=True)
    print("->", out)


if __name__ == "__main__":
    a = sys.argv[1:]
    filters = {a[i + 1]: a[i + 2] for i, v in enumerate(a) if v == "--etalonnage"}
    GRADE.update(filters)
    if "--export" in a:
        setup_export(a[a.index("--export") + 1], filters)
    if "--extrait" in a:
        i = a.index("--extrait")
        EXTRAIT = (float(a[i + 1]), float(a[i + 2]))
    main(a[0], a[1])
