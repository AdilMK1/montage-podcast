"""Aperçus des packs : une image fixe 1080x1920 dessinée par le vrai moteur des shorts (moteur/apercu_pack.py,
importé dans ce processus), en cache par empreinte (réglages, date et taille des fichiers, fond, textes).

- apercu_pack : éditeur et écran Packs (accroche et sous-titres d'exemple, fond neutre ou image d'un podcast) ;
- habillage_short : étape Shorts, le pack du short sur la vignette de sa caméra, avec son accroche et ses mots."""
import os
import sys
import uuid
from pathlib import Path

from app.fichiers import lire_json
from app.projet import modele as M
from app.projet.stockage import lire_etat
from app.services.transcript import mots

from . import bibliotheque as B
from .projets import pack_projet
from .reglages import valider

VERSION_APERCU = 1  # à monter si le dessin de l'aperçu change (vide le cache)
GARDER = 300  # images gardées dans le cache
_module = None


def moteur():
    """moteur/apercu_pack.py (chargé une fois : ~2 s, ensuite ~0,1 s par image)"""
    global _module
    if _module is None:
        if str(B.MOTEUR) not in sys.path:
            sys.path.append(str(B.MOTEUR))
        import apercu_pack
        _module = apercu_pack
    return _module


def _signature(chemins) -> dict:
    out = {}
    for c in chemins:
        if c:
            try:
                st = Path(c).stat()
                out[str(c)] = [st.st_mtime_ns, st.st_size]
            except OSError:
                out[str(c)] = None
    return out


def _menage(cache: Path):
    """garde les GARDER images les plus récentes (un autre fil peut en effacer en même temps)"""
    fs = []
    for f in cache.glob("*.jpg"):
        try:
            fs.append((f.stat().st_mtime, f))
        except OSError:
            continue
    for _, f in sorted(fs)[:-GARDER]:
        try:
            f.unlink(missing_ok=True)
        except OSError:  # Windows : image en cours d'envoi, effacée la prochaine fois
            continue


def rendre(cache, spec: dict, fond, accroche, lignes) -> Path:
    cle = M.empreinte({"v": VERSION_APERCU, "spec": spec, "accroche": accroche, "lignes": lignes,
                       "fichiers": _signature([spec["sous_titres"]["police"], spec["police_accent"],
                                               spec.get("logo_fichier"), fond])})
    cache = Path(cache)
    f = cache / f"{cle}.jpg"
    if f.exists():
        try:
            os.utime(f)  # resservie : redevient récente, le ménage la garde
        except OSError:
            pass
        return f
    cache.mkdir(parents=True, exist_ok=True)
    img = moteur().image(spec, str(fond) if fond else None, accroche, lignes)
    tmp = cache / f".{cle}.{uuid.uuid4().hex[:6]}.jpg"
    try:
        img.save(tmp, "JPEG", quality=88)
        try:
            os.replace(tmp, f)
        except OSError:  # Windows : la même image, posée par un autre fil, est en cours d'envoi ; on sert celle-là
            if not f.is_file():
                raise
    finally:
        tmp.unlink(missing_ok=True)
    _menage(cache)
    return f


def apercu_pack(racine, cache, pid, reglages=None, fond=None) -> Path:
    """aperçu d'un pack ; `reglages` : ceux en cours d'édition (validés ici, Refus sinon)"""
    if reglages is not None:
        reglages = valider(reglages, B.disponibles(racine, pid))
    return rendre(cache, B.spec_moteur(racine, pid, reglages), fond, None, None)


def _vignette(d: Path, prefere=None) -> Path | None:
    v = Path(d) / "vignettes"
    if not v.is_dir():
        return None
    for f in ([v / f"{prefere}.jpg"] if prefere else []) + [v / "LARGE.jpg", *sorted(v.glob("*.jpg"))]:
        if f.is_file():
            return f
    return None


def fonds(racine_projets) -> list[dict]:
    """podcasts dont une image peut servir de fond à l'aperçu (les plus récents d'abord)"""
    r = Path(racine_projets)
    ds = [d for d in (r.iterdir() if r.is_dir() else []) if d.is_dir() and _vignette(d)]
    ds.sort(key=lambda d: _vignette(d).stat().st_mtime, reverse=True)
    return [{"id": d.name, "titre": (lire_json(d / "projet.json", {}) or {}).get("titre") or d.name} for d in ds[:12]]


def fond(racine_projets, pid) -> Path | None:
    """image de fond d'un podcast (jamais hors du dossier des projets) ; None : fond neutre"""
    if not isinstance(pid, str) or not pid:
        return None
    r = Path(racine_projets).resolve()
    d = (r / pid).resolve()
    return _vignette(d) if d.parent == r else None


def lignes_du_short(d, sh) -> list[list[str]] | None:
    """les premiers mots du passage, sur deux lignes (le dernier mot sert de mot clé dans l'aperçu)"""
    ex = (sh["spec"].get("extraits") or [{}])[0].get("rush")
    if not ex:
        return None
    try:
        ws = [w[0] for w in mots(d) if ex[0] - 0.05 <= w[1] < ex[1]][:7]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if len(ws) < 3:
        return None
    k = (len(ws) + 1) // 2
    return [ws[:k], ws[k:]]


def habillage_short(d, racine, cache, sid) -> Path:
    """image du short habillé par SON pack (le sien, sinon celui du podcast)"""
    d = Path(d)
    e = lire_etat(d)
    sh = M.trouver_short(e, sid)
    if sh is None:
        raise FileNotFoundError("Ce short est introuvable.")
    pid = M.pack_du_short(e, sh) or pack_projet(d, e)
    if not B.existe(racine, pid):
        pid = B.AUCUN
    pj = lire_json(d / "projet.json", {}) or {}
    micro = sh["spec"].get("micro") or next(
        (k for k, v in (pj.get("personnes") or {}).items() if v.get("role") == "invité"), None)
    return rendre(cache, B.spec_moteur(racine, pid), _vignette(d, micro), list(sh["spec"].get("accroche") or []),
                  lignes_du_short(d, sh))
