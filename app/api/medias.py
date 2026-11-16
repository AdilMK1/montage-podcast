"""Médias : quels fichiers l'interface a le droit de lire, et envoi avec plages HTTP (lecture vidéo / audio)."""
import json
import mimetypes
import os
from pathlib import Path

from app.fichiers import lire_json
from app.services.session import chemin_rush


TYPES = {".m4a": "audio/mp4"}  # le système dit « audio/mp4a-latm », que les navigateurs ne lisent pas toujours


def autorise(d, chemin) -> bool:
    """vrai seulement pour un fichier du dossier du projet ou des dossiers des rushes du projet"""
    d = Path(d).resolve()
    p = Path(os.path.normpath(Path(chemin).absolute()))  # « .. » replié avant de comparer
    try:
        p = p.resolve()
    except OSError:
        return False
    pj = lire_json(d / "projet.json", {}) or {}
    sources = list((pj.get("mics") or {}).values())
    for v in (pj.get("cams") or {}).values():
        sources += [v] if isinstance(v, str) else list(v)
    racines = [d] + [Path(chemin_rush(x)).resolve().parent for x in sources if isinstance(x, str)]
    return any(p == r or r in p.parents for r in racines)


def _plage(entete: str | None, taille: int) -> tuple[int, int, bool] | None:
    """(début, fin, partiel) ; None si la plage demandée est invalide"""
    if not entete or not entete.startswith("bytes="):
        return 0, taille - 1, False
    a, _, b = entete[6:].split(",")[0].partition("-")
    try:
        if a:
            debut, fin = int(a), (int(b) if b else taille - 1)
        elif b:
            debut, fin = max(0, taille - int(b)), taille - 1
        else:
            return None
    except ValueError:
        return None
    fin = min(fin, taille - 1)
    return (debut, fin, True) if 0 <= debut <= fin else None


def envoyer(handler, chemin, garder=False):
    """envoie le fichier (plages HTTP). `handler` est un BaseHTTPRequestHandler. `garder` : le navigateur peut le
    garder une heure (aperçu en cache, redemandé à chaque rendu de l'écran)"""
    p = Path(chemin)
    taille = p.stat().st_size
    plage = _plage(handler.headers.get("Range"), taille)
    if plage is None:
        handler.send_response(416)
        handler.send_header("Content-Range", f"bytes */{taille}")
        handler.send_header("Content-Length", "0")
        handler.end_headers()
        return
    debut, fin, partiel = plage
    handler.send_response(206 if partiel else 200)
    if partiel:
        handler.send_header("Content-Range", f"bytes {debut}-{fin}/{taille}")
    handler.send_header("Content-Type", TYPES.get(p.suffix.lower()) or mimetypes.guess_type(p.name)[0]
                        or "application/octet-stream")
    handler.send_header("Accept-Ranges", "bytes")
    handler.send_header("Content-Length", str(fin - debut + 1))
    handler.send_header("Cache-Control", "private, max-age=3600" if garder else "no-store")
    handler.end_headers()
    try:
        with open(p, "rb") as fh:
            fh.seek(debut)
            reste = fin - debut + 1
            while reste > 0:
                morceau = fh.read(min(1 << 20, reste))
                if not morceau:
                    break
                handler.wfile.write(morceau)
                reste -= len(morceau)
    except (BrokenPipeError, ConnectionResetError):
        pass  # le lecteur a fermé la connexion (saut dans la vidéo) : normal
