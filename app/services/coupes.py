"""Coupes rapides dans l'épisode exporté, sans le réexporter depuis les rushes.

Le fichier exporté (x264) est recopié tel quel entre ses images clés ; seules les quelques secondes entre une coupe et
l'image clé voisine sont réencodées, avec les réglages x264 lus dans le fichier lui-même (même format d'image, donc
assemblables sans réencoder le reste). Le son est recoupé à l'échantillon près (fondus de 15 ms aux jointures) puis
réencodé : c'est rapide. Un export qui n'est pas en x264 (puce vidéo) est réencodé en entier depuis l'export, ce qui
reste bien plus court qu'un export depuis les rushes.

Toutes les heures sont celles du fichier exporté (pas des rushes). Fonctions pures testées à part ; la tâche est
dans taches_episode.coupes.
"""
import json
import re
import subprocess
from functools import lru_cache
from pathlib import Path

FONDU_S = 0.015      # fondu du son de part et d'autre d'une jointure (évite le clic)
COPIE_MIN_S = 0.5    # en dessous, un morceau entre deux images clés est réencodé plutôt que recopié
EPS = 1e-3

_SOURCE = re.compile(r" EPISODE .*(1080p|4k)\.mp4$")
SUFFIXE = " (coupé)"


# ---------- fichiers ----------

def sources(d) -> list[Path]:
    """exports complets du projet (« … EPISODE … 1080p.mp4 » / « … 4k.mp4 »), du plus ancien au plus récent ; jamais
    l'essai, une version coupée ou un fichier ajouté à la main"""
    s = Path(d) / "sorties"
    return sorted((f for f in s.glob("*.mp4") if _SOURCE.search(f.name)), key=lambda f: f.stat().st_mtime) \
        if s.exists() else []


def chemin_coupe(source: Path) -> Path:
    return source.with_name(source.stem + SUFFIXE + source.suffix)


# ---------- calcul (pur) ----------

def normaliser(coupes, duree: float, fps: float) -> list[tuple[float, float]]:
    """coupes [(a, b)] calées sur les images, ramenées dans [0, durée], triées, fusionnées si elles se touchent"""
    def img(t):
        return round(round(t * fps) / fps, 6)
    out = []
    for a, b in sorted((min(a, b), max(a, b)) for a, b in coupes):
        a, b = max(0.0, img(a)), min(duree, img(b)) if b < duree - EPS else duree
        if b - a < 1 / fps - EPS:
            continue
        if out and a <= out[-1][1] + EPS:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def a_garder(coupes, duree: float) -> list[tuple[float, float]]:
    """complément des coupes (normalisées) dans [0, durée]"""
    out, t = [], 0.0
    for a, b in coupes:
        if a > t + EPS:
            out.append((t, a))
        t = max(t, b)
    if t < duree - EPS:
        out.append((t, duree))
    return out


def plan(garder, cles, copie: bool = True) -> list[tuple]:
    """morceaux de l'épisode coupé, dans l'ordre : ("enc", a, b) à réencoder, ("copie", k1, k2) à recopier tel quel
    (k1, k2 : images clés). Sans copie (export pas en x264) : tout est réencodé."""
    out = []
    for s, e in garder:
        k = [c for c in cles if s - EPS <= c <= e + EPS] if copie else []
        if len(k) < 2 or k[-1] - k[0] < COPIE_MIN_S:
            out.append(("enc", s, e))
            continue
        k1, k2 = k[0], k[-1]
        if k1 - s > EPS:
            out.append(("enc", s, k1))
        out.append(("copie", k1, k2))
        if e - k2 > EPS:
            out.append(("enc", k2, e))
    return out


def _quote(p) -> str:
    return "'" + Path(p).as_posix().replace("'", "'\\''") + "'"


def liste_concat(src, morceaux, dts: dict, fichiers: dict) -> str:
    """liste pour le « concat demuxer » de ffmpeg. Un morceau recopié s'arrête au DTS de l'image clé suivante (le
    démultiplexeur compare la fin au temps de décodage : avec les images B, la borne en temps d'affichage laisserait
    passer l'image clé suivante) ; sa durée est donnée à part pour placer exactement le morceau suivant."""
    lignes = ["ffconcat version 1.0", "stream", "exact_stream_id 1"]
    for i, m in enumerate(morceaux):
        if m[0] == "copie":
            lignes += [f"file {_quote(src)}", f"inpoint {m[1]:.6f}", f"outpoint {dts[m[2]]:.6f}",
                       f"duration {m[2] - m[1]:.6f}"]
        else:
            lignes += [f"file {_quote(fichiers[i])}"]
    return "\n".join(lignes) + "\n"


def options_x264(entete: bytes) -> dict | None:
    """réglages x264 inscrits dans le fichier (SEI) : crf, ref, bframes ; None si le fichier n'est pas en x264 / crf"""
    m = re.search(rb"x264 - core .*? options: (.*?)(?:\x00|$)", entete, re.S)
    if not m:
        return None
    opts = dict(re.findall(r"(\w+)=([^ ]+)", m.group(1).decode("latin-1")))
    if opts.get("rc") != "crf" or "crf" not in opts:
        return None
    return {"crf": opts["crf"], "ref": opts.get("ref", "1"), "bframes": opts.get("bframes", "3")}


def filtre_son(garder) -> str:
    out, ent = [], []
    for i, (s, e) in enumerate(garder):
        f = min(FONDU_S, (e - s) / 2)
        out.append(f"[0:a]atrim={s:.6f}:{e:.6f},asetpts=PTS-STARTPTS,afade=t=in:d={f:.6f},"
                   f"afade=t=out:st={e - s - f:.6f}:d={f:.6f}[a{i}]")
        ent.append(f"[a{i}]")
    return ";".join(out) + ";" + "".join(ent) + f"concat=n={len(garder)}:v=0:a=1[a]"


# ---------- lecture du fichier exporté ----------

def _sortie(cmd) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise OSError(r.stderr.strip()[-300:] or "ffprobe a échoué")
    return r.stdout


def infos(src) -> dict:
    """durée, images/s, débit du son, images clés {pts: dts}, réglages x264 (None si pas x264)"""
    j = json.loads(_sortie(["ffprobe", "-v", "error", "-show_entries",
                            "format=duration:stream=codec_type,id,r_frame_rate,bit_rate,color_range,color_space,"
                            "color_transfer,color_primaries", "-of", "json", str(src)]))
    v = next(s for s in j["streams"] if s["codec_type"] == "video")
    a = next((s for s in j["streams"] if s["codec_type"] == "audio"), {})
    n, _, dd = v["r_frame_rate"].partition("/")
    pk = _sortie(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=pts_time,dts_time,flags",
                  "-of", "csv=p=0", str(src)])
    cles = {}
    for ligne in pk.split():
        x = ligne.rstrip(",").split(",")
        if len(x) >= 3 and "K" in x[2] and x[0] != "N/A" and x[1] != "N/A":
            cles[float(x[0])] = float(x[1])
    entete = subprocess.run(["ffmpeg", "-v", "error", "-t", "1", "-i", str(src), "-map", "0:v:0", "-c", "copy",
                             "-bsf:v", "h264_mp4toannexb", "-f", "h264", "-"], capture_output=True).stdout
    couleurs = []
    for cle, opt in (("color_primaries", "-color_primaries"), ("color_transfer", "-color_trc"),
                     ("color_space", "-colorspace"), ("color_range", "-color_range")):
        if v.get(cle) and v[cle] != "unknown":
            couleurs += [opt, v[cle]]
    vid = str(v.get("id") or "0x1")
    return {"duree": float(j["format"]["duration"]), "fps": float(n) / float(dd or 1), "couleurs": couleurs,
            "video_id": int(vid, 16) if vid.startswith("0x") else int(vid),
            "son_debit": int(a.get("bit_rate") or 320000), "son": bool(a), "cles": cles,
            "x264": options_x264(entete)}


def compter_images(f) -> int:
    return len([x for x in _sortie(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                    "packet=pts_time", "-of", "csv=p=0", str(f)]).split() if x.strip(",")])


@lru_cache(maxsize=1)
def encodeur_son() -> str:
    """AAC d'Apple (rapide) si ffmpeg l'a, sinon l'AAC de ffmpeg"""
    try:
        r = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    except OSError:
        return "aac"
    return "aac_at" if re.search(r"\baac_at\b", r) else "aac"
