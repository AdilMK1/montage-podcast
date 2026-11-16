"""Aperçus des rushes à la création, avant tout projet : une image de chaque caméra, un extrait de chaque micro
(là où il parle fort) et son niveau, et la détection de fichiers son identiques. Tout est en cache."""
import hashlib
import json
import os
import struct
import subprocess
import threading
import uuid
from pathlib import Path

import numpy as np

from app.services.contexte import duree

AUDIO = {".wav", ".aif", ".aiff", ".mp3", ".m4a", ".flac"}
VIDEO = {".mp4", ".mov", ".mxf", ".m4v"}
EXTRAIT = 8.0  # secondes d'écoute
SR = 8000  # échantillonnage de l'analyse : assez pour la voix, rapide à lire
SEUIL_BAS = -45.0  # dB : en dessous, le son est très bas
BLOC = 1 << 16

_calculs = threading.BoundedSemaphore(3)  # une carte pleine de clips ne lance pas 30 ffmpeg à la fois
_verrous: dict[str, threading.Lock] = {}
_verrou = threading.Lock()


def _cle(f: Path) -> str:
    st = f.stat()
    return hashlib.md5(f"{f.resolve()}|{st.st_size}|{st.st_mtime}".encode()).hexdigest()[:12]


def _source(chemin, exts, message) -> Path:
    f = Path(chemin)
    if f.suffix.lower() not in exts or not f.is_file():
        raise FileNotFoundError(message)
    return f


def _une_fois(cle):
    """un seul calcul à la fois pour un même fichier (l'image ou l'extrait demandés deux fois en même temps)"""
    with _verrou:
        return _verrous.setdefault(cle, threading.Lock())


def _ffmpeg(args, out: Path):
    """ffmpeg vers un fichier temporaire, puis renommé : jamais de fichier à moitié écrit dans le cache"""
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(f"{out.stem}.{uuid.uuid4().hex[:6]}.tmp{out.suffix}")
    try:
        with _calculs:
            subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", *args, str(tmp)],
                           check=True, capture_output=True, stdin=subprocess.DEVNULL, timeout=120)
        os.replace(tmp, out)
    finally:
        tmp.unlink(missing_ok=True)


def image_rush(cache, chemin) -> Path:
    """une image d'une vidéo (à 40 % de sa durée : les gens sont assis et parlent), en cache"""
    f = _source(chemin, VIDEO, "Cette vidéo est introuvable.")
    cle = _cle(f)
    out = Path(cache) / f"{cle}.jpg"
    with _une_fois(cle + "i"):
        if not out.exists():
            _ffmpeg(["-ss", f"{duree(f) * 0.4:.2f}", "-i", str(f), "-frames:v", "1", "-vf", "scale=480:-2",
                     "-q:v", "4"], out)
    return out


def _fmt_wav(f: Path):
    """(canaux, octets par échantillon, fréquence) d'un wav PCM entier ; None sinon (lu par ffmpeg)"""
    with open(f, "rb") as fh:
        tete = fh.read(12)
        if tete[:4] not in (b"RIFF", b"RF64") or tete[8:12] != b"WAVE":
            return None
        while True:
            c = fh.read(8)
            if len(c) < 8:
                return None
            n = struct.unpack("<I", c[4:])[0]
            if c[:4] == b"fmt ":
                tag, canaux, sr, _, _, bits = struct.unpack("<HHIIHH", fh.read(16))
                return (canaux, bits // 8, sr) if tag in (1, 0xFFFE) and bits in (16, 24, 32) else None
            fh.seek(n + (n & 1), 1)


def _energies(f: Path, a: float, b: float) -> np.ndarray:
    """énergie moyenne de chaque seconde entre a et b. Un wav se lit directement, un quart de seconde par seconde
    (4 fois moins de lecture sur une carte SD lente) ; les autres formats passent par ffmpeg."""
    fmt = _fmt_wav(f)
    if fmt:
        canaux, o, sr = fmt
        debut, n = _donnees(f)
        trame = canaux * o
        out = []
        with open(f, "rb") as fh:
            for s in range(int(a), int(b)):
                pos = s * sr * trame
                if pos >= n:
                    break
                fh.seek(debut + pos)
                brut = fh.read(min(sr // 4 * trame, n - pos) // trame * trame)
                if not brut:
                    break
                if o == 3:
                    x = np.frombuffer(brut, np.uint8).reshape(-1, 3).astype(np.int32)
                    x = (x[:, 0] | x[:, 1] << 8 | (x[:, 2] ^ 128) - 128 << 16) / 8388608  # 3e octet signé
                else:
                    x = np.frombuffer(brut, "<i2" if o == 2 else "<i4") / (32768 if o == 2 else 2147483648)
                out.append(float(np.mean(np.square(x, dtype=np.float64))))
        return np.array(out)
    with _calculs:
        r = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{a:.2f}", "-t", f"{b - a:.2f}",
                            "-i", str(f), "-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"],
                           check=True, capture_output=True, stdin=subprocess.DEVNULL, timeout=120)
    x = np.frombuffer(r.stdout, dtype="<i2").astype(np.float64) / 32768
    if not len(x):
        return np.array([])
    return np.add.reduceat(x ** 2, np.arange(0, len(x), SR)) / np.diff(np.append(np.arange(0, len(x), SR), len(x)))


def analyse_micro(cache, chemin) -> dict:
    """{debut, niveau_db, bas} : début de la fenêtre de 8 s la plus énergique entre 20 % et 60 % de la durée, et
    niveau moyen sur cette zone (très bas : ce n'est peut-être pas la bonne piste)"""
    f = _source(chemin, AUDIO, "Ce fichier son est introuvable.")
    cle = _cle(f)
    out = Path(cache) / f"{cle}.json"
    with _une_fois(cle + "a"):
        if out.exists():
            return json.loads(out.read_text())
        d = duree(f)
        a, b = (0.0, d) if d <= EXTRAIT else (min(d * 0.2, d - EXTRAIT), max(d * 0.6, d * 0.2 + EXTRAIT))
        e = _energies(f, a, b)
        niveau = 10 * np.log10(float(np.mean(e)) + 1e-12) if len(e) else -120.0
        debut = a
        if d > EXTRAIT and len(e) > EXTRAIT:
            debut = a + float(np.argmax(np.convolve(e, np.ones(int(EXTRAIT)), "valid")))
        res = {"debut": round(min(debut, max(0.0, d - EXTRAIT)), 2), "niveau_db": round(float(niveau), 1),
               "bas": bool(niveau < SEUIL_BAS)}
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_name(f"{cle}.{uuid.uuid4().hex[:6]}.tmp")
        tmp.write_text(json.dumps(res))
        os.replace(tmp, out)
        return res


def son_micro(cache, chemin) -> Path:
    """extrait de 8 s du micro (m4a léger), au moment où il parle fort"""
    f = _source(chemin, AUDIO, "Ce fichier son est introuvable.")
    debut = analyse_micro(cache, f)["debut"]
    cle = _cle(f)
    out = Path(cache) / f"{cle}.m4a"
    with _une_fois(cle + "s"):
        if not out.exists():
            _ffmpeg(["-ss", f"{debut:.2f}", "-t", f"{EXTRAIT:.0f}", "-i", str(f), "-vn", "-ac", "1", "-c:a", "aac",
                     "-b:a", "96k", "-af", "afade=t=in:d=0.15", "-movflags", "+faststart"], out)
    return out


def _donnees(f: Path) -> tuple[int, int]:
    """(début, longueur) des données audio : l'en-tête (nom, date, réglages de l'enregistreur) n'est pas le son"""
    taille = f.stat().st_size
    with open(f, "rb") as fh:
        tete = fh.read(12)
        if len(tete) == 12 and tete[:4] in (b"RIFF", b"RF64") and tete[8:12] == b"WAVE":
            pos, cible, fmt = 12, b"data", "<I"
        elif len(tete) == 12 and tete[:4] == b"FORM" and tete[8:12] in (b"AIFF", b"AIFC"):
            pos, cible, fmt = 12, b"SSND", ">I"
        else:
            return 0, taille
        while pos + 8 <= taille:
            fh.seek(pos)
            c = fh.read(8)
            n = struct.unpack(fmt, c[4:])[0]
            if c[:4] == cible:
                return pos + 8, (taille - pos - 8 if n in (0, 0xFFFFFFFF) else min(n, taille - pos - 8))
            pos += 8 + n + (n & 1)
    return 0, taille


def empreinte_son(chemin) -> str:
    """longueur des données audio + quelques blocs pris au début, au milieu et à la fin du son"""
    f = Path(chemin)
    debut, n = _donnees(f)
    h = hashlib.md5(str(n).encode())
    with open(f, "rb") as fh:
        for r in (0.05, 0.5, 0.95):
            fh.seek(debut + max(0, int((n - BLOC) * r)))
            h.update(fh.read(min(BLOC, n)))
    return h.hexdigest()


def identiques(chemins) -> list[list[str]]:
    """groupes de fichiers son au contenu audio identique (copies du même enregistrement)"""
    groupes: dict[str, list[str]] = {}
    for c in chemins:
        try:
            groupes.setdefault(empreinte_son(c), []).append(c)
        except OSError:
            continue
    return [g for g in groupes.values() if len(g) > 1]
