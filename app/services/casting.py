"""Casting : qui est qui dans les rushes.

- tâche `pre_analyse` : son, synchro, détection (moteur/casting.py), début transcrit (moteur/ecoute_debut.py),
  prénoms et rôles proposés par l'IA, suggestion de casting, extraits pour l'écran Casting ;
- clés du moteur et renommage des fichiers à la validation (le moteur veut la caméra d'une personne sous la clé de
  son micro et le plan large sous LARGE) ;
- extraits : boucle muette de 3 s par caméra, vérification d'une personne (sa caméra avec le son de son micro).

projet.json["casting"] : ids (identifiants techniques stables -> fichiers), cles (clé actuelle de chaque
identifiant), detection, confiances, prenoms, durees. etat.json["casting"] : choix courants et validation.
"""
import os
import re
import subprocess
import time
import unicodedata
import uuid
from pathlib import Path

from app.fichiers import ecrire_json_atomique, lire_json
from app.ia.claude import IAEchec, IAIndisponible, commande, proposer
from app.projet import modele as M
from app.projet.stockage import lire_etat, modifier
from app.ressources.encodeur import encodeur
from app.taches.atelier import ErreurTache

from .contexte import config, lancer_script, profil
from .session import chemin_rush, construire_session

DOSSIER = "casting"
PALETTE = ["#F2A93B", "#4FC3F7", "#C792EA", "#7FD99A", "#FF7A7A", "#FFD866", "#9FA8FF", "#F48FB1"]
BOUCLE_S, VERIF_S, ECOUTE_S = 3.0, 5.0, 8.0
NOM_MAX = 30
ETAPES = [("extract.py", "Lecture du son des rushes"), ("sync.py", "Synchronisation des caméras"),
          ("casting.py", "Qui est sur quelle caméra"), ("ecoute_debut.py", "Écoute du début de la conversation")]
POIDS_ETAPES = [0.35, 0.15, 0.35, 0.1]  # part de la jauge (l'extraction relit les rushes : le plus long)


def _lancer(cmd, **kw):
    """point d'entrée des ffmpeg du casting (remplacé dans les tests)"""
    return subprocess.run(cmd, **kw)


# ---------- identifiants ----------

def ids_du_projet(pj: dict) -> dict:
    return ((pj.get("casting") or {}).get("ids")) or {}


def micros(pj: dict) -> list[str]:
    return [k for k, v in ids_du_projet(pj).items() if v["type"] == "micro"]


def cameras(pj: dict) -> list[str]:
    return [k for k, v in ids_du_projet(pj).items() if v["type"] == "camera"]


def libelle(pj: dict, ident: str) -> str:
    """nom lisible d'un micro ou d'une caméra : le nom de son (premier) fichier, sans extension"""
    f = (ids_du_projet(pj).get(ident) or {}).get("fichiers") or [ident]
    return Path(f[0]).stem


def couleur(index: int) -> str:
    return PALETTE[index % len(PALETTE)]


# ---------- prénoms et rôles ----------

CONSIGNE_PRENOMS = (
    "Voici le début d'un podcast transcrit automatiquement : chaque ligne donne le micro qui parle. Trouve le prénom "
    "de la personne de chaque micro (seulement s'il est dit dans l'extrait : présentation, « merci X », « bonjour X ») "
    "et qui anime (pose les questions, présente l'émission). Réponds UNIQUEMENT avec ce JSON : "
    '{"personnes": {"MIC_1": {"prenom": "Prénom ou null", "role": "animateur ou invité"}}} avec une entrée par micro. '
    "N'invente aucun prénom : null si tu ne sais pas. Pas de texte avant ou après, pas de balises de code.")


def valider_prenoms(obj, micros_: list[str]) -> dict:
    """{micro: {"nom": prénom ou "", "role": ...}} ; ValueError si la réponse n'est pas exploitable"""
    pers = obj.get("personnes") if isinstance(obj, dict) else None
    if not isinstance(pers, dict):
        raise ValueError("clé personnes absente")
    out = {}
    for m in micros_:
        v = pers.get(m) if isinstance(pers.get(m), dict) else {}
        p = v.get("prenom")
        p = " ".join(p.split()) if isinstance(p, str) else ""
        if len(p) > NOM_MAX or p.lower() in ("null", "none", "inconnu") or any(c.isdigit() for c in p):
            p = ""
        role = "animateur" if str(v.get("role", "")).lower().startswith("anim") else "invité"
        out[m] = {"nom": p, "role": role}
    if sum(x["role"] == "animateur" for x in out.values()) > 1:
        raise ValueError("plusieurs animateurs")
    return out


def _questions(segments: list[dict], m: str) -> int:
    return sum(s.get("text", "").count("?") for s in segments if s.get("micro") == m)


def completer(prop: dict, micros_: list[str], segments: list[dict]) -> dict:
    """prénoms manquants ou en double -> « Personne N » ; sans animateur : celui qui pose le plus de questions
    dans l'extrait, sinon le premier micro"""
    out, vus = {}, set()
    for i, m in enumerate(micros_):
        p = dict(prop.get(m) or {"nom": "", "role": "invité"})
        if not p["nom"] or p["nom"].casefold() in vus:
            p["nom"] = f"Personne {i + 1}"
        vus.add(p["nom"].casefold())
        out[m] = p
    if not any(p["role"] == "animateur" for p in out.values()) and micros_:
        q = {m: _questions(segments, m) for m in micros_}
        anim = max(micros_, key=lambda m: (q[m], -micros_.index(m))) if max(q.values()) > 0 else micros_[0]
        out[anim]["role"] = "animateur"
    return out


def proposer_prenoms(d, micros_: list[str], segments: list[dict], executer=subprocess.run, journal=None):
    """(prénoms et rôles, « ia » ou « defaut »)"""
    pj = lire_json(Path(d) / "projet.json", {}) or {}
    cmd = commande(config())
    if cmd and pj.get("auto_ia", True) is not False and segments and micros_:
        lignes = "\n".join(f"[{s['start']:.1f} s] {s.get('micro')} : {s['text']}" for s in segments)
        texte = f"{CONSIGNE_PRENOMS}\n<micros>{', '.join(micros_)}</micros>\n<debut>\n{lignes}\n</debut>"
        try:
            prop = proposer(texte, lambda o: valider_prenoms(o, micros_), cmd=cmd, delai=90, essais=2,
                            executer=executer, journal=journal, cwd=str(d))
            if any(p["nom"] for p in prop.values()):
                return completer(prop, micros_, segments), "ia"
            return completer(prop, micros_, segments), "defaut"
        except (IAIndisponible, IAEchec):
            pass
    return completer({}, micros_, segments), "defaut"


# ---------- suggestion ----------

def suggestion(pj: dict, det: dict, prenoms: dict) -> tuple[dict, dict]:
    """(réglages du casting proposés, confiance de chaque personne)"""
    mics, cams = micros(pj), cameras(pj)
    large = (det.get("large") or {}).get("camera") or (cams[0] if len(cams) == 1 else None)
    asso = det.get("association") or {}
    serrees = [c for c in cams if c != large]
    if asso.get("possible"):
        aff = {m: asso.get("affectation", {}).get(m) for m in mics}
        conf = {m: ("sure" if (asso.get("marges", {}).get(m) or 0) >= 0.15 else "a_verifier") if aff.get(m) else None
                for m in mics}
    else:  # pas d'association à l'oreille : caméras dans l'ordre, à placer d'après les visages
        aff = {m: (serrees[i] if i < len(serrees) else None) for i, m in enumerate(mics)}
        conf = {m: "impossible" for m in mics}
    pers = [{"micro": m, "nom": prenoms[m]["nom"], "role": prenoms[m]["role"], "camera": aff.get(m)} for m in mics]
    return {"large": large, "cameras": cams, "personnes": pers}, conf


# ---------- tâche ----------

def _detection(d) -> dict:
    return lire_json(Path(d) / "casting_detection.json", {}) or {}


def pre_analyse(ctx):
    d = Path(ctx.projet_dir)
    e = lire_etat(d)
    if M.casting_manuel(e):
        raise ErreurTache("Ce podcast a été créé avec les noms choisis à la main : pas de pré-analyse à faire.", [])
    construire_session(d, e)
    durees, pos = {}, 0.0
    for (script, texte), part in zip(ETAPES, POIDS_ETAPES):
        if not ctx.est_fait(script):
            t0 = time.time()
            try:
                lancer_script(ctx, script, d / "session.json", texte=texte, debut=pos, fin=pos + part)
            except ErreurTache:
                if script != "ecoute_debut.py":  # sans le début transcrit : prénoms par défaut, on continue
                    raise
                ecrire_json_atomique(d / "debut_transcript.json", [])
            durees[script] = round(time.time() - t0, 1)
            ctx.morceau_fait(script)
        pos += part
    pj = lire_json(d / "projet.json", {}) or {}
    det = _detection(d)
    segments = lire_json(d / "debut_transcript.json", []) or []
    ctx.progres(0.95, "Prénoms et rôles")
    t0 = time.time()
    prenoms, source = proposer_prenoms(d, micros(pj), segments, journal=ctx.journal)
    durees["prenoms"] = round(time.time() - t0, 1)
    reglages, conf = suggestion(pj, det, prenoms)
    _ecrire_casting(d, detection=det, suggestion=reglages, confiances=conf, prenoms=source, durees={**(pj.get("casting") or {}).get(
        "durees", {}), **durees})
    ctx.progres(0.97, "Préparation de l'écran de casting")
    t0 = time.time()
    preparer_extraits(d, reglages)
    _ecrire_casting(d, durees={**(lire_json(d / "projet.json", {})["casting"].get("durees") or {}),
                               "extraits": round(time.time() - t0, 1)})
    if not lire_etat(d)["casting"].get("pret"):  # une reprise ne remplace pas les choix déjà faits
        modifier(d, {"type": "casting_pret", "reglages": reglages})


def _ecrire_casting(d, **champs):
    f = Path(d) / "projet.json"
    pj = lire_json(f, {}) or {}
    pj.setdefault("casting", {}).update(champs)
    ecrire_json_atomique(f, pj)


# ---------- clés du moteur et renommage ----------

def _cle_nom(nom: str) -> str:
    s = unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]+", "_", s.upper()).strip("_")[:20]


def cles_du_casting(pj: dict, reglages: dict) -> dict:
    """{identifiant: clé} : micro -> prénom (figé après la 1re validation), sa caméra -> même clé, plan large ->
    LARGE, autre caméra -> son identifiant"""
    c = pj.get("casting") or {}
    actuelles, figees = c.get("cles") or {}, bool(c.get("cles_figees"))
    out, prises = {}, {"LARGE"}
    for i, p in enumerate(reglages["personnes"]):
        m = p["micro"]
        if figees:
            k = actuelles.get(m, m)
        else:
            base = _cle_nom(p.get("nom") or "") or f"PERSONNE_{i + 1}"
            if base in ("LARGE",) or re.fullmatch(r"(MIC|CAM)_\d+", base):
                base = f"PERSONNE_{i + 1}"
            k, n = base, 2
            while k in prises:
                k, n = f"{base}_{n}", n + 1
        out[m] = k
        prises.add(k)
    for cam in reglages["cameras"]:
        if cam == reglages.get("large"):
            out[cam] = "LARGE"
        else:
            p = next((x for x in reglages["personnes"] if x["camera"] == cam), None)
            out[cam] = out[p["micro"]] if p else cam
    return out


def _cles_fichiers(ids: dict, ident: str, cle: str) -> list[str]:
    """clés des fichiers de travail d'une caméra (CAM, ou CAM_1, CAM_2… si elle est en morceaux)"""
    f = ids[ident].get("fichiers") or []
    return [cle] if ids[ident]["type"] == "micro" or len(f) <= 1 else [f"{cle}_{i + 1}" for i in range(len(f))]


MODELES_MICRO = ("mic_{}.wav", "mic16_{}.wav", "transcript_{}.json")
MODELES_CAMERA = ("cam_{}.wav", "vignettes/{}.jpg")


def appliquer_cles(d, nouvelles: dict):
    """renomme tout ce qui porte les clés (fichiers de travail, sync.json, alertes, visages, transcript, projet.json)
    des clés actuelles vers `nouvelles` ; en deux temps (noms provisoires) pour qu'un échange n'écrase rien"""
    d = Path(d)
    pj = lire_json(d / "projet.json", {}) or {}
    ids = ids_du_projet(pj)
    anciennes = (pj.get("casting") or {}).get("cles") or {k: k for k in ids}
    fmic, fcam = {}, {}  # clé de fichier ancienne -> nouvelle
    for ident, v in ids.items():
        a, n = anciennes.get(ident, ident), nouvelles.get(ident, ident)
        cible = fmic if v["type"] == "micro" else fcam
        cible.update(zip(_cles_fichiers(ids, ident, a), _cles_fichiers(ids, ident, n)))

    renommages = []
    for table, modeles in ((fmic, MODELES_MICRO), (fcam, MODELES_CAMERA)):
        for a, n in table.items():
            if a != n:
                renommages += [(d / m.format(a), d / m.format(n)) for m in modeles if (d / m.format(a)).exists()]
    marque = uuid.uuid4().hex[:6]
    provisoires = [(src, src.with_name(f".{marque}.{src.name}"), dst) for src, dst in renommages]
    for src, tmp, _ in provisoires:
        os.replace(src, tmp)
    for _, tmp, dst in provisoires:
        os.replace(tmp, dst)

    sync = lire_json(d / "sync.json")
    if isinstance(sync, dict) and isinstance(sync.get("cams"), dict):
        cam_de = {a: nouvelles.get(i, i) for i, a in anciennes.items() if ids.get(i, {}).get("type") == "camera"}
        sync["cams"] = {fcam.get(k, k): {**v, **({"cam": cam_de.get(v["cam"], v["cam"])} if "cam" in v else {})}
                        for k, v in sync["cams"].items()}
        ecrire_json_atomique(d / "sync.json", sync)
    al = lire_json(d / "alertes.json")
    if isinstance(al, dict):
        ecrire_json_atomique(d / "alertes.json", {k: [fmic.get(x, x) for x in v] if isinstance(v, list) else v
                                                  for k, v in al.items()})
    vis = lire_json(d / "visages.json")
    if isinstance(vis, dict):
        ecrire_json_atomique(d / "visages.json", {fcam.get(k, k): v for k, v in vis.items()})
    tr = lire_json(d / "transcript.json")
    if isinstance(tr, list):
        ecrire_json_atomique(d / "transcript.json", [{**s, "speaker": fmic.get(s.get("speaker"), s.get("speaker"))}
                                                     if isinstance(s, dict) else s for s in tr])

    cle = {i: nouvelles.get(i, i) for i in ids}
    pers_avant = pj.get("personnes") or {}
    pj["mics"] = {cle[i]: v["fichiers"][0] for i, v in ids.items() if v["type"] == "micro"}
    pj["cams"] = {cle[i]: (v["fichiers"][0] if len(v["fichiers"]) == 1 else list(v["fichiers"]))
                  for i, v in ids.items() if v["type"] == "camera"}
    pj["personnes"] = {cle[i]: pers_avant.get(anciennes.get(i, i)) or {"nom": "", "fonction": "", "role": "invité"}
                       for i, v in ids.items() if v["type"] == "micro"}
    pj["casting"]["cles"] = cle
    ecrire_json_atomique(d / "projet.json", pj)


def appliquer_noms(d, reglages: dict):
    """à la validation : clés du moteur (renommage), prénoms et rôles dans projet.json ; clés des micros figées"""
    d = Path(d)
    appliquer_cles(d, cles_du_casting(lire_json(d / "projet.json", {}) or {}, reglages))
    pj = lire_json(d / "projet.json", {}) or {}
    cles = pj["casting"]["cles"]
    for p in reglages["personnes"]:
        k = cles[p["micro"]]
        pj["personnes"][k] = {**pj["personnes"].get(k, {}), "nom": p["nom"], "role": p["role"]}
        pj["personnes"][k].setdefault("fonction", "")
    noms = pj.setdefault("noms_propres", [])  # les prénoms guident la transcription (« Sarah », pas « Sara »)
    for p in reglages["personnes"]:
        if not re.fullmatch(r"Personne \d+", p["nom"]) and p["nom"].casefold() not in {n.casefold() for n in noms}:
            noms.append(p["nom"])
    pj["casting"]["cles_figees"] = True
    ecrire_json_atomique(d / "projet.json", pj)


# ---------- extraits ----------

def _morceaux(d, pj: dict, cam: str) -> list[dict]:
    """morceaux d'une caméra avec leur synchro : [{chemin, offset, derive, debut, fin}] (temps micro)"""
    ids, cles = ids_du_projet(pj), (pj.get("casting") or {}).get("cles") or {}
    sync = (lire_json(Path(d) / "sync.json", {}) or {}).get("cams") or {}
    out = []
    for fk, f in zip(_cles_fichiers(ids, cam, cles.get(cam, cam)), ids[cam]["fichiers"]):
        s = sync.get(fk)
        if s:
            out.append({"chemin": chemin_rush(f), "offset": s["offset_s"], "derive": s.get("drift_ppm", 0) * 1e-6,
                        "debut": s["covers_mic_s"][0], "fin": s["covers_mic_s"][1]})
    return out


def _temps_camera(morceaux, t: float, duree: float):
    for m in morceaux:
        if m["debut"] <= t and t + duree <= m["fin"]:
            return m["chemin"], (t - m["offset"]) / (1 + m["derive"])
    return None


def _moments(det: dict, micro: str | None) -> list[float]:
    mics = det.get("micros") or {}
    if micro is not None:
        return list((mics.get(micro) or {}).get("moments") or [])
    return [t for v in mics.values() for t in (v.get("moments") or [])]


def _ffmpeg(args, out: Path):
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(f".{out.stem}.{uuid.uuid4().hex[:6]}.tmp{out.suffix}")
    try:
        r = _lancer(["ffmpeg", "-v", "error", "-nostdin", "-y", *args, str(tmp)], capture_output=True,
                    stdin=subprocess.DEVNULL, timeout=180)
        if r.returncode or not tmp.exists():
            raise ValueError("L'extrait n'a pas pu être fabriqué : le rush est peut-être illisible, ou son disque "
                             "débranché.")
        os.replace(tmp, out)
    finally:
        tmp.unlink(missing_ok=True)
    return out


def _moment_camera(d, pj, det, cam: str, micro: str | None, duree: float):
    """(t micro, chemin, t caméra) : premier moment où `micro` (ou n'importe qui) parle, filmé par cette caméra ;
    à défaut le milieu de la plage filmée"""
    morc = _morceaux(d, pj, cam)
    for t in _moments(det, micro) + ([] if micro is None else _moments(det, None)):
        ou = _temps_camera(morc, t, duree)
        if ou:
            return t, *ou
    if morc:
        m = morc[0]
        t = max(m["debut"], 0.0) + max(0.0, (m["fin"] - max(m["debut"], 0.0)) / 2 - duree / 2)
        ou = _temps_camera(morc, t, duree)
        if ou:
            return t, *ou
    return None


def _personne_de(reglages: dict, cam: str) -> str | None:
    return next((p["micro"] for p in reglages.get("personnes", []) if p.get("camera") == cam), None)


def boucle(d, cam: str, reglages: dict | None = None) -> Path:
    """3 s muettes de la caméra, à un moment où sa personne (ou quelqu'un) parle ; en cache"""
    d = Path(d)
    pj = lire_json(d / "projet.json", {}) or {}
    if cam not in cameras(pj):
        raise ValueError("Cette caméra n'existe pas dans le casting.")
    out = d / DOSSIER / f"boucle_{cam}.mp4"
    if out.exists():
        return out
    reglages = reglages or (lire_etat(d)["casting"].get("reglages") or {})
    m = _moment_camera(d, pj, _detection(d), cam, _personne_de(reglages, cam), BOUCLE_S)
    if m is None:
        raise FileNotFoundError("Cette caméra ne filme pas la conversation : pas d'extrait possible.")
    _, chemin, tc = m
    return _ffmpeg(["-ss", f"{tc:.3f}", "-t", f"{BOUCLE_S}", "-i", chemin, "-an", "-vf", "scale=480:-2",
                    *encodeur("apercu", profil()), "-movflags", "+faststart"], out)


def image(d, cam: str, reglages: dict | None = None) -> Path:
    """une image de la caméra au même moment que sa boucle ; en cache"""
    d = Path(d)
    pj = lire_json(d / "projet.json", {}) or {}
    out = d / DOSSIER / f"image_{cam}.jpg"
    if out.exists():
        return out
    reglages = reglages or (lire_etat(d)["casting"].get("reglages") or {})
    m = _moment_camera(d, pj, _detection(d), cam, _personne_de(reglages, cam), BOUCLE_S)
    if m is None:
        raise FileNotFoundError("Cette caméra ne filme pas la conversation : pas d'image possible.")
    return _ffmpeg(["-ss", f"{m[2] + 1:.3f}", "-i", m[1], "-frames:v", "1", "-vf", "scale=480:-2", "-q:v", "4"], out)


def ecoute(d, micro: str) -> Path:
    """8 s du micro, au moment où il parle le plus nettement seul (m4a) ; en cache"""
    d = Path(d)
    pj = lire_json(d / "projet.json", {}) or {}
    if micro not in micros(pj):
        raise ValueError("Ce micro n'existe pas dans le casting.")
    out = d / DOSSIER / f"ecoute_{micro}.m4a"
    if out.exists():
        return out
    t = (_moments(_detection(d), micro) or [0.0])[0]
    src = chemin_rush(ids_du_projet(pj)[micro]["fichiers"][0])
    return _ffmpeg(["-ss", f"{t:.3f}", "-t", f"{ECOUTE_S}", "-i", src, "-vn", "-ac", "1", "-c:a", "aac", "-b:a", "96k",
                    "-af", "afade=t=in:d=0.15", "-movflags", "+faststart"], out)


def verification(d, micro: str, reglages: dict | None = None) -> dict:
    """quelques secondes de la caméra de cette personne avec le son de SON micro au même instant, pris à un moment
    où ce micro parle seul ; en cache. {src, camera, debut, duree}"""
    d = Path(d)
    pj = lire_json(d / "projet.json", {}) or {}
    reglages = reglages or (lire_etat(d)["casting"].get("reglages") or {})
    p = next((x for x in reglages.get("personnes", []) if x["micro"] == micro), None)
    if p is None:
        raise ValueError("Ce micro n'existe pas dans le casting.")
    cam = p.get("camera")
    if not cam:
        raise ValueError("Cette personne n'a pas de caméra : associe-lui d'abord une caméra.")
    m = _moment_camera(d, pj, _detection(d), cam, micro, VERIF_S)
    if m is None:
        raise FileNotFoundError("Cette caméra ne filme pas la conversation : pas d'extrait possible.")
    t, chemin, tc = m
    out = d / DOSSIER / f"verif_{micro}_{cam}_{int(round(t * 100))}.mp4"
    if not out.exists():
        src = chemin_rush(ids_du_projet(pj)[micro]["fichiers"][0])
        _ffmpeg(["-ss", f"{tc:.3f}", "-t", f"{VERIF_S}", "-i", chemin, "-ss", f"{t:.3f}", "-t", f"{VERIF_S}", "-i", src,
                 "-map", "0:v:0", "-map", "1:a:0", "-vf", "scale=640:-2", *encodeur("apercu", profil()),
                 "-ac", "1", "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart"], out)
    return {"src": str(out), "camera": cam, "debut": round(t, 2), "duree": VERIF_S}


def preparer_extraits(d, reglages: dict):
    """boucles, images, écoutes et vérifications de la suggestion, pour un écran Casting instantané ; un extrait
    raté n'empêche pas la suite (il sera refait à la demande)"""
    pj = lire_json(Path(d) / "projet.json", {}) or {}
    travaux = [lambda c=c: boucle(d, c, reglages) for c in cameras(pj)]
    travaux += [lambda c=c: image(d, c, reglages) for c in cameras(pj)]
    travaux += [lambda m=m: ecoute(d, m) for m in micros(pj)]
    travaux += [lambda m=p["micro"]: verification(d, m, reglages) for p in reglages["personnes"] if p.get("camera")]
    for t in travaux:
        try:
            t()
        except (OSError, ValueError, subprocess.SubprocessError):
            continue


def existant(f) -> str | None:
    """chemin d'un extrait déjà prêt, sans le fabriquer"""
    return str(f) if f and Path(f).exists() else None


def verification_prete(d, micro: str, cam: str | None) -> str | None:
    if not cam:
        return None
    fs = sorted((Path(d) / DOSSIER).glob(f"verif_{micro}_{cam}_*.mp4")) if (Path(d) / DOSSIER).exists() else []
    return str(fs[0]) if fs else None
