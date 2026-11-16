"""Noms propres du projet : corrige les mots du transcript que Whisper a mal écrits."""
import json
import re
from difflib import SequenceMatcher
from pathlib import Path

from app.fichiers import ecrire_json_atomique

SEUIL = 0.8


def _formes(noms) -> list[str]:
    """chaque mot de chaque nom (« Florent Pagny » -> Florent, Pagny), 4 lettres et plus"""
    return sorted({m for n in noms for m in n.split() if len(m) >= 4})


def corriger_mot(mot: str, noms) -> str:
    m = re.match(r"^([\w’'-]+)(\W*)$", mot)
    if not m:
        return mot
    coeur, fin = m.groups()
    if len(coeur) < 4:
        return mot
    meilleur, score = None, 0.0
    for f in _formes(noms):
        if f[0].lower() != coeur[0].lower():
            continue
        r = SequenceMatcher(None, coeur.lower(), f.lower()).ratio()
        if r > score:
            meilleur, score = f, r
    return meilleur + fin if meilleur and score >= SEUIL else mot


def corriger_transcript(fichier, noms) -> int:
    """corrige transcript.json sur place ; renvoie le nombre de mots changés"""
    fichier = Path(fichier)
    if not noms:
        return 0
    segs = json.loads(fichier.read_text(encoding="utf-8"))
    n = 0
    for s in segs:
        for w in s.get("words", []):
            c = corriger_mot(w["w"], noms)
            if c != w["w"]:
                s["text"] = re.sub(rf"(?<!\w){re.escape(w['w'].rstrip('.,!?…'))}(?!\w)", c.rstrip(".,!?…"), s.get("text", ""))
                w["w"], n = c, n + 1
    ecrire_json_atomique(fichier, segs)
    return n
