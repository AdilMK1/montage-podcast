"""Tâches de rendu : proxys (en fond), aperçus des propositions, fabrication des shorts."""
import os
from pathlib import Path

from app.fichiers import lire_json
from app.projet import modele as M
from app.projet.stockage import lire_etat, modifier
from app.ressources import disque
from app.ressources.encodeur import encodeur
from app.taches.atelier import ErreurTache

from .apercus import chemin_apercu, commande_apercu
from .cadrage import couvrir
from .contexte import duree, erreur_rushes, lancer_script, packs, profil
from .couleur import ecrire_etalonnage
from .session import chemin_rush, construire_session, spec_shorts

GO = 1_000_000_000


def _controle_disque(d, besoin: int):
    ok, libre = disque.verifier(d, int(besoin))
    if not ok:
        raise ErreurTache(disque.message_manque(int(besoin), libre), ["liberer_disque", "reessayer"])


def proxys(ctx):
    d = Path(ctx.projet_dir)
    pj = lire_json(d / "projet.json", {}) or {}
    sources = [chemin_rush(x) for v in pj.get("cams", {}).values() for x in (v if isinstance(v, list) else [v])]
    out = d / "sorties" / "PROXYS"
    out.mkdir(parents=True, exist_ok=True)
    durees = {s: duree(s) for s in sources}
    restants = [s for s in sources if not (out / f"{Path(s).stem}.mp4").exists()]
    _controle_disque(d, sum(durees[s] for s in restants) * 4e6 / 8 * 1.1)
    enc, n = encodeur("proxy", profil()), len(sources)
    for i, s in enumerate(sources):
        nom = Path(s).stem
        dst = out / f"{nom}.mp4"
        if not ctx.est_fait(nom) and not dst.exists():
            ctx.progres(i / n, f"Proxy {i + 1} sur {n} : {Path(s).name}")
            tmp = out / f".{nom}.mp4"
            rc = ctx.executer(["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", s, "-map", "0:v:0", "-map", "0:a:0?",
                               "-vf", "scale=-2:720", *enc, "-g", "25", "-c:a", "aac", "-b:a", "128k",
                               "-movflags", "+faststart", "-progress", "pipe:1", "-nostats", str(tmp)],
                              debut=i / n, fin=(i + 1) / n, total_s=durees[s] or None)
            if rc or not tmp.exists():
                tmp.unlink(missing_ok=True)
                erreur_rushes(d)
                raise ErreurTache(f"Le proxy de « {Path(s).name} » n'a pas pu être fabriqué. Réessaie ; si ça "
                                  "recommence, envoie un rapport.", ["reessayer", "rapport"])
            os.replace(tmp, dst)
        if not ctx.est_fait(nom):
            ctx.morceau_fait(nom)
    modifier(d, {"type": "proxys_prets"})


def apercus(ctx):
    d = Path(ctx.projet_dir)
    e = lire_etat(d)
    serie = M.serie_active(e)
    if not serie:
        return
    pj = lire_json(d / "projet.json", {}) or {}
    sync = (lire_json(d / "sync.json", {}) or {}).get("cams", {})
    invite = next((k for k, v in (pj.get("personnes") or {}).items() if v.get("role") == "invité"), next(iter(pj["mics"])))
    ids = ctx.params.get("ids") or [x["id"] for x in serie["shorts"]]
    enc = encodeur("apercu", profil())
    (d / "apercus").mkdir(exist_ok=True)
    for i, sid in enumerate(ids):
        sh = M.trouver_short(e, sid)
        if sh is None or ctx.est_fait(sid):
            continue
        out = chemin_apercu(d, sh)
        if not out.exists():
            micro = sh["spec"].get("micro") or invite
            extraits = couvrir(d, micro, sh["spec"]["extraits"])
            ctx.progres(i / len(ids), f"Aperçu {i + 1} sur {len(ids)}")
            tmp = out.with_name("." + out.name)
            rc = ctx.executer(commande_apercu(d, pj, sync, micro, extraits, tmp, enc), debut=i / len(ids),
                              fin=(i + 1) / len(ids), total_s=sum(x["rush"][1] - x["rush"][0] for x in extraits))
            if rc or not tmp.exists():
                tmp.unlink(missing_ok=True)
                raise ErreurTache("Un aperçu n'a pas pu être préparé. Réessaie ; si ça recommence, envoie un rapport.",
                                  ["reessayer", "rapport"])
            os.replace(tmp, out)
        ctx.morceau_fait(sid)


def _titre(nom: str) -> str:
    return nom[3:] if nom[:2].isdigit() else nom  # comme sur la carte du short (vues.vue_short)


def shorts(ctx):
    d = Path(ctx.projet_dir)
    e = lire_etat(d)
    if not M.reglages_valides(e):
        raise ErreurTache("Valide d'abord la couleur et le son.", [])
    ids = ctx.params.get("ids") or M.a_fabriquer(e)
    if not ids:
        return
    ecrire_etalonnage(d, e["couleur"]["reglages"])
    construire_session(d, e)
    _controle_disque(d, len(ids) * 0.2 * GO)
    (d / "shorts" / e["serie_active"]).mkdir(parents=True, exist_ok=True)  # vertical.py ne crée que le dernier niveau
    n = len(ids)
    for i, sid in enumerate(ids):
        if ctx.est_fait(sid):
            continue
        e = lire_etat(d)
        sh = M.trouver_short(e, sid)
        emp = M.empreinte_short(e, sh) if sh else None
        if sh is None or emp is None:  # série changée ou réglages dévalidés entre-temps : on saute
            ctx.morceau_fait(sid)
            continue
        nom = sh["spec"]["nom"]
        try:
            spec = spec_shorts(d, e, [sid], packs=packs())
        except FileNotFoundError as x:
            raise ErreurTache(f"{x} Ouvre « Packs de shorts » pour le réparer, puis réessaie.", ["reessayer"]) from None
        lancer_script(ctx, "vertical.py", spec, nom, texte=f"Short {i + 1} sur {n} : {_titre(nom)}",
                      debut=i / n, fin=(i + 0.85) / n)
        lancer_script(ctx, "verif_coupes.py", spec, nom, texte="Réécoute des coupes", debut=(i + 0.85) / n,
                      fin=(i + 1) / n)
        alertes = ((lire_json(d / "verif_coupes.json", {}) or {}).get(nom) or {}).get("absents", [])
        video = d / "shorts" / e["serie_active"] / f"{nom}.mp4"
        poster = video.parent / "posters" / f"{nom}.jpg"
        poster.parent.mkdir(parents=True, exist_ok=True)
        ctx.executer(["ffmpeg", "-v", "error", "-nostdin", "-y", "-ss", "1.6", "-i", str(video), "-frames:v", "1",
                      "-vf", "scale=432:-2", "-q:v", "3", str(poster)])
        modifier(d, {"type": "short_fabrique", "id": sid, "empreinte": emp, "alertes": alertes})
        ctx.morceau_fait(sid)
