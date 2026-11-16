"""Vues : les données prêtes à afficher, construites depuis etat.json, les tâches et les fichiers du projet.

L'interface n'a aucune logique de process : elle affiche ces vues et envoie des actions.
"""
import json
import os
import time
import uuid
from pathlib import Path

import psutil

from app.fichiers import lire_json
from app.packs import bibliotheque as B
from app.packs.projets import pack_projet
from app.projet import modele as M
from app.projet.import_v1 import importer
from app.projet.stockage import NOM, lire_etat
from app.ressources import disque
from app.ressources.encodeur import libelle
from app.projet.regles import Refus, appliquer
from app.services import casting as K
from app.services.apercus import chemin_apercu
from app.services.taches_analyse import avertissements
from app.services import coupes
from app.services.taches_episode import ESSAI, duree_xml, estimations
from app.taches import file
from app.taches.modele import ACTIFS, FINIS
from app.taches.progression import restant, texte_duree
from app.taches.superviseur import atelier_vivant

TITRES = {"pre_analyse": "Pré-analyse des rushes", "analyse": "Analyse des rushes", "son": "Nouveau réglage du son", "proxys": "Proxys (copies légères pour le montage)",
          "ia_shorts": "Propositions de shorts par l'IA", "ia_passages": "Passages à retirer de l'épisode (IA)",
          "apercus": "Aperçus des propositions", "shorts": "Fabrication des shorts", "montage": "Montage de l'épisode",
          "essai": "Essai d'export de 3 minutes", "export": "Export de l'épisode", "coupes": "Coupes dans l'épisode exporté",
          "livraison": "Préparation de la livraison"}
ETAPES = [("casting", "Casting"), ("analyse", "Analyse"), ("couleur", "Couleur"), ("son", "Son"), ("shorts", "Shorts"),
          ("passages", "Épisode"), ("livraison", "Livraison")]


def _tache(t: dict, maintenant: float) -> dict:
    p = t.get("progression") or {}
    f = p.get("fraction")
    actif = t["statut"] in ACTIFS
    return {"id": t["id"], "projet": t["projet"], "type": t["type"], "titre": TITRES.get(t["type"], t["type"]),
            "statut": t["statut"], "actif": actif, "texte": p.get("texte", ""),
            "pourcent": round(100 * f) if f is not None else None,
            "restant": texte_duree(restant(t["debut"], f, maintenant, t.get("fraction_debut"))) if actif and t.get("debut") else "",
            "ecoule": texte_duree(maintenant - t["debut"]) if actif and t.get("debut") else "",
            "depuis_vie": round(maintenant - t["signe_vie"]) if actif and t.get("signe_vie") else None,
            "erreur": _message(t.get("erreur")), "actions": _actions(t.get("erreur")), "cree": t["cree"], "fin": t.get("fin")}


def _message(e) -> str | None:
    """l'erreur d'une tâche est un texte ou {message, actions} (ErreurTache) : l'interface reçoit toujours un texte"""
    if isinstance(e, dict):
        return e.get("message") or "Ça n'a pas marché."
    return e


def _actions(e) -> list[str] | None:
    """actions proposées par une ErreurTache (None : l'interface garde ses actions par défaut)"""
    return list(e.get("actions") or []) if isinstance(e, dict) and "actions" in e else None


def _avertissements(d: Path) -> list[str]:
    """ce que l'analyse a remarqué sur les micros (même son sur deux micros, micro silencieux), en clair"""
    return avertissements(d)


def remplacee(d, t: dict) -> bool:
    """une tâche en échec relancée par « réessayer » (drapeau taches/<id>.remplacee) ne compte plus"""
    return t.get("statut") == "echec" and (Path(d) / "taches" / f"{t['id']}.remplacee").exists()


def taches_du_projet(d, n_finies: int = 10) -> list[dict]:
    d, now = Path(d), time.time()
    ts = [t for f in sorted((d / "taches").glob("*.json")) if (d / "taches").exists()
          for t in [lire_json(f)] if isinstance(t, dict) and "statut" in t and not remplacee(d, t)]
    actives = sorted((t for t in ts if t["statut"] not in FINIS), key=lambda t: (t.get("priorite", 5), t["cree"]))
    finies = sorted((t for t in ts if t["statut"] in FINIS), key=lambda t: t.get("fin") or 0, reverse=True)[:n_finies]
    return [_tache(t, now) for t in actives + finies]


def _personnes(pj: dict) -> list[dict]:
    """une couleur par personne (ordre des micros), la même que sur l'écran Casting"""
    pers = pj.get("personnes") or {}
    return [{"id": k, "nom": pers.get(k, {}).get("nom") or k.title(), "role": pers.get(k, {}).get("role", "invité"),
             "couleur": K.couleur(i)} for i, k in enumerate(pj.get("mics", {}))]


def _premiere_etape(st: dict) -> str:
    return next((nom for k, nom in ETAPES if st.get(k) != "valide"), "Terminé")


FICHIERS_V1 = ("sync.json", "transcript.json", "shorts.json", "episode.json", "reponses.json", "proxys.json")


def est_v1(d: Path) -> bool:
    """projet de la v1 pas encore ouvert dans la 2.0 : ses fichiers sont là, mais pas etat.json"""
    return not (d / NOM).exists() and any((d / f).exists() for f in FICHIERS_V1)


def importer_v1_si_besoin(d: Path):
    """première ouverture d'un projet de la v1 : etat.json est créé depuis ses fichiers, et c'est le seul fichier
    ajouté (ni verrou ni fichier temporaire laissé). Écrit à côté puis lié sous son nom : jamais d'écrasement d'un
    etat.json apparu entre-temps, et personne ne lit un fichier à moitié écrit."""
    if not est_v1(d):
        return
    tmp = d / f".{NOM}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(importer(d), f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.link(tmp, d / NOM)
    except FileExistsError:
        pass
    finally:
        tmp.unlink(missing_ok=True)


def _etat(d: Path) -> dict:
    """lecture seule : un projet de la v1 pas encore ouvert est montré tel qu'il sera importé, sans rien écrire"""
    return importer(d) if est_v1(d) else lire_etat(d)


def vue_carte(d) -> dict:
    d = Path(d)
    pj = lire_json(d / "projet.json", {}) or {}
    st = M.statuts(_etat(d))
    vign = next((f for f in [d / "vignettes" / "LARGE.jpg", *sorted((d / "vignettes").glob("*.jpg"))] if f.exists()),
                None) if (d / "vignettes").exists() else None
    actives = [t for t in taches_du_projet(d, 0) if t["actif"]]
    return {"id": d.name, "titre": pj.get("titre", d.name), "cree": pj.get("cree", ""),
            "personnes": " · ".join(p["nom"] for p in _personnes(pj)),
            "vignette": str(vign) if vign else None, "etape": _premiere_etape(st), "statuts": st,
            "tache": actives[0] if actives else None}


def _short(d: Path, e: dict, sh: dict, pack_podcast: str, noms: dict) -> dict:
    spec, nom = sh["spec"], sh["spec"].get("nom", "")
    video = d / "shorts" / e["serie_active"] / f"{nom}.mp4"
    poster = video.parent / "posters" / f"{nom}.jpg"
    ap = chemin_apercu(d, sh)
    ex = spec.get("extraits", [])
    pid = M.pack_du_short(e, sh) or pack_podcast
    return {"id": sh["id"], "num": nom[:2] if nom[:2].isdigit() else "", "titre": nom[3:] if nom[:2].isdigit() else nom,
            "accroche": " ".join(spec.get("accroche", [])).replace("*", ""), "spec": spec,
            "statut": M.statut_short(e, sh), "alertes": sh["alertes"], "alertes_ok": sh["alertes_ok"],
            "debut": ex[0]["rush"][0] if ex else None, "duree": round(sum(x["rush"][1] - x["rush"][0] for x in ex)),
            "apercu": str(ap) if ap.exists() else None, "video": str(video) if video.exists() and sh["fabrique"] else None,
            "poster": str(poster) if poster.exists() else None, "pourquoi": spec.get("_", ""),
            # pack : celui choisi pour ce short (None : celui du podcast) ; habillage : clé de l'image habillée
            "pack": spec.get("pack") or None, "pack_nom": noms.get(pid, pid),
            "habillage": M.empreinte([pid, (e.get("packs") or {}).get(pid), spec.get("accroche") or [],
                                      spec.get("micro"), ex[0] if ex else None])[:12]}


def _a_verifier(d: Path) -> list[dict]:
    """points que l'IA demande de vérifier avant publication (episode.json, « markers » : aussi dans le XML)"""
    ep = lire_json(d / "episode.json", {}) or {}
    out = []
    for m in ep.get("markers") or [] if isinstance(ep, dict) else []:
        if isinstance(m, dict) and m.get("comment") and isinstance(m.get("start"), (int, float)):
            out.append({"a": m["start"], "b": m.get("end", m["start"]), "texte": str(m["comment"])})
    return sorted(out, key=lambda m: m["a"])


_DUREES_XML: dict = {}


def _duree_episode(e: dict, xml: Path | None) -> float | None:
    """durée de l'épisode monté : enregistrée au montage, sinon lue dans le XML (projet monté avant l'essai)"""
    if e["episode"].get("duree"):
        return e["episode"]["duree"]
    if xml is None:
        return None
    cle = (str(xml), xml.stat().st_mtime)
    if cle not in _DUREES_XML:
        _DUREES_XML[cle] = duree_xml(xml)
    return _DUREES_XML[cle]


def _episode(d: Path, e: dict, st: dict) -> dict:
    sorties = d / "sorties"
    video = sorties / ESSAI
    exports = coupes.sources(d)
    xml = next(iter(sorted(sorties.glob("*.xml"))), None) if sorties.exists() else None
    ess = e["episode"].get("essai")
    duree = _duree_episode(e, xml)
    return {"essai": {**{k: ess.get(k) for k in ("format", "debut", "duree", "rendu_s")},
                      "video": str(video) if video.exists() and st["apercu"] in ("a_valider", "valide") else None}
            if ess else None,
            "duree": duree, "estimations": estimations(e["episode"].get("vitesses") or {}, duree),
            "export": str(exports[-1]) if exports and st["export"] == "valide" else None,
            "coupes": M.coupes(e), "coupe": (str(coupes.chemin_coupe(exports[-1]))
                                             if exports and st["export"] == "valide" and st["coupes"] == "valide" else None),
            "xml": str(xml) if xml else None}


def vue_projet(d, packs=None) -> dict:
    """`packs` : dossier de la bibliothèque (noms des packs et liste du choix) ; sans lui, noms = identifiants"""
    d = Path(d)
    importer_v1_si_besoin(d)
    pj = lire_json(d / "projet.json", {}) or {}
    e = lire_etat(d)
    st = M.statuts(e)
    serie = M.serie_active(e)
    taches = taches_du_projet(d)
    livraisons = sorted((d / "EXPORT").iterdir(), reverse=True) if (d / "EXPORT").exists() else []
    liv = M.livrables(e)
    pack = pack_projet(d, e)
    liste = B.lister(packs) if packs else []
    noms = {p["id"]: p["nom"] for p in liste}
    return {
        "id": d.name, "titre": pj.get("titre", d.name), "personnes": _personnes(pj), "statuts": st,
        "casting": {"statut": st["casting"], "manuel": M.casting_manuel(e)},
        "etape": _premiere_etape(st), "noms_propres": pj.get("noms_propres", []), "brief": pj.get("brief", ""),
        "couleur": e["couleur"], "son": e["son"], "son_a_recalculer": M.son_a_recalculer(e),
        "cams": [c for c in pj.get("cams", {})], "mics": [m for m in pj.get("mics", {})],
        "serie": serie["id"] if serie else None, "series": [s["id"] for s in e["series"]],
        "shorts": [_short(d, e, x, pack, noms) for x in (serie["shorts"] if serie else [])],
        "pack": {"id": pack, "nom": noms.get(pack, pack)},
        "packs": [{"id": p["id"], "nom": p["nom"]} for p in liste],
        "passages": [{**p, "apercu": None} for p in (e["episode"]["passages"] or [])],
        "passages_revus": e["episode"]["passages_revus"],
        "a_verifier": _a_verifier(d),
        "avertissements": _avertissements(d),
        "episode": _episode(d, e, st),
        "livraisons": [{"dossier": str(x), "nom": x.name, "fichiers": sorted(f.name for f in x.glob("*.mp4"))}
                       for x in livraisons if x.is_dir()],
        "livrables": liv,
        "peut": {"fabriquer": M.reglages_valides(e) and bool(M.a_fabriquer(e)),
                 "monter": e["episode"]["passages_revus"] and M.reglages_valides(e),
                 "essayer": st["montage"] == "valide" and not any(t["type"] == "essai" and t["statut"] not in FINIS
                                                                  for t in taches),
                 "exporter": st["apercu"] == "valide",
                 "couper": st["export"] == "valide" and not any(t["type"] in ("coupes", "export") and t["statut"] not in FINIS
                                                                for t in taches),
                 "livrer": bool(liv["shorts"] or liv["episode"]) and st["livraison"] != "valide"},
        "taches": taches,
        "proxys_prets": e["proxys"]["prets"],
    }


# ---------- écran Casting ----------

def _cite(noms: list[str]) -> str:
    n = [f"« {x} »" for x in noms]
    return n[0] if len(n) == 1 else ", ".join(n[:-1]) + " et " + n[-1]


def _messages(pj: dict, det: dict, conf: dict, reglages: dict) -> list[str]:
    """ce que l'écran Casting explique, en français simple"""
    mics = det.get("micros") or {}
    lib = {m: K.libelle(pj, m) for m in K.micros(pj)}
    out = []
    ident = [lib[m] for m in lib if (mics.get(m) or {}).get("identique")]
    muets = [lib[m] for m in lib if (mics.get(m) or {}).get("muet")]
    bas = [lib[m] for m in lib if (mics.get(m) or {}).get("bas") and lib[m] not in muets]
    if ident:
        out.append(f"Les micros {_cite(ident)} ont exactement le même son : ce n'est pas un micro par personne. L'app ne "
                   "peut pas savoir à l'oreille qui est sur quelle caméra : vérifie chaque personne d'après son visage. "
                   "Tu peux continuer : la conversation sera transcrite comme une seule voix. Pour un montage qui suit "
                   "qui parle, récupère les pistes séparées de chaque micro (export de Reaper ou de la table de mixage).")
    if muets:
        un = len(muets) == 1
        out.append(f"{'Le micro' if un else 'Les micros'} {_cite(muets)} {'n’a' if un else 'n’ont'} enregistré aucun son : "
                   f"vérifie {'ce fichier' if un else 'ces fichiers'}. Tu peux continuer sans "
                   f"{'cette voix' if un else 'ces voix'}.")
    if bas:
        un = len(bas) == 1
        out.append(f"{'Le micro' if un else 'Les micros'} {_cite(bas)} {'est' if un else 'sont'} très bas (le son "
                   f"sera remonté) : écoute-{'le' if un else 'les'} pour vérifier que c'est la bonne piste.")
    asso = det.get("association") or {}
    if asso.get("raison") == "un_seul" and not ident and len(lib) > 1:
        out.append("Une seule voix est exploitable : l'app ne peut pas savoir à l'oreille qui est sur quelle caméra. "
                   "Vérifie chaque personne d'après son visage.")
    if asso.get("raison") == "pas_de_camera":
        out.append("Il n'y a qu'une caméra : l'épisode sera en plan large.")
    if (det.get("large") or {}).get("confiance") == "a_verifier" and len(reglages.get("cameras") or []) > 1:
        out.append("Le plan large n'est pas évident : vérifie la caméra marquée « Plan large ».")
    if any(v == "a_verifier" for v in conf.values()):
        out.append("Vérifie les personnes marquées « à vérifier » : écoute-les avec leur caméra.")
    return out


def vue_casting(d) -> dict:
    """données de l'écran Casting (contrat : docs/superpowers/plans/2026-11-15-casting-serveur.md)"""
    from .actions import taches_en_cours
    d = Path(d)
    pj = lire_json(d / "projet.json", {}) or {}
    e = lire_etat(d)
    st = M.statuts(e)["casting"]
    taches = [t for t in taches_du_projet(d) if t["type"] == "pre_analyse"]
    base = {"statut": st, "manuel": M.casting_manuel(e), "pret": bool(e["casting"].get("pret")),
            "tache": taches[0] if taches else None}
    if M.casting_manuel(e):
        return {**base, "large": None, "large_confiance": None, "association_possible": False, "messages": [],
                "cameras": [], "micros": [], "personnes": [], "prenoms": None, "peut_valider": False,
                "raison": "Ce podcast a été créé avec les noms choisis à la main : pas de casting à faire."}
    c = pj.get("casting") or {}
    det, conf = c.get("detection") or {}, c.get("confiances") or {}
    r = e["casting"].get("reglages") or {"large": None, "cameras": K.cameras(pj), "personnes": []}
    sugg = {p["micro"]: p.get("camera") for p in (c.get("suggestion") or {}).get("personnes", [])}
    scores = (det.get("association") or {}).get("scores") or {}
    dc, dm = det.get("cameras") or {}, det.get("micros") or {}
    ids = K.ids_du_projet(pj)
    cas = d / K.DOSSIER
    cameras = [{"id": c_, "nom": K.libelle(pj, c_), "fichiers": [Path(f).name for f in ids[c_]["fichiers"]],
                "morceaux": len(ids[c_]["fichiers"]), "large": c_ == r.get("large"),
                "visages_plusieurs": (dc.get(c_) or {}).get("visages_plusieurs"),
                "personne": next((p["micro"] for p in r["personnes"] if p.get("camera") == c_), None),
                "image": K.existant(cas / f"image_{c_}.jpg"), "boucle": K.existant(cas / f"boucle_{c_}.mp4")}
               for c_ in K.cameras(pj)]
    micros = [{"id": m, "nom": K.libelle(pj, m), "fichier": Path(ids[m]["fichiers"][0]).name,
               "onde": (dm.get(m) or {}).get("onde") or [], "extrait": K.existant(cas / f"ecoute_{m}.m4a"),
               "niveau_db": (dm.get(m) or {}).get("niveau_db"), "bas": bool((dm.get(m) or {}).get("bas")),
               "muet": bool((dm.get(m) or {}).get("muet")), "identique": bool((dm.get(m) or {}).get("identique"))}
              for m in K.micros(pj)]
    ordre = K.micros(pj)
    personnes = []
    for p in r["personnes"]:
        m, cam = p["micro"], p.get("camera")
        cf = conf.get(m) if cam == sugg.get(m) else ("choisi" if cam else None)
        personnes.append({"micro": m, "nom": p["nom"], "role": p["role"], "camera": cam,
                          "couleur": K.couleur(ordre.index(m) if m in ordre else 0), "confiance": cf,
                          "score": (scores.get(m) or {}).get(cam) if cam else None,
                          "verification": K.verification_prete(d, m, cam)})
    raison = None
    if not base["pret"]:
        raison = "La pré-analyse n'est pas finie : attends la suggestion de casting."
    elif taches_en_cours(d):
        raison = "Une tâche tourne encore sur ce podcast : attends qu'elle finisse pour valider le casting."
    else:
        try:
            appliquer(e, {"type": "valider_casting"})
        except Refus as x:
            raison = str(x)
    asso = det.get("association") or {}
    return {**base, "large": r.get("large"), "large_confiance": (det.get("large") or {}).get("confiance"),
            "association_possible": bool(asso.get("possible")),
            "messages": _messages(pj, det, conf, r) if base["pret"] else [],
            "cameras": cameras, "micros": micros, "personnes": personnes, "prenoms": c.get("prenoms"),
            "peut_valider": raison is None and st != "valide", "raison": raison}


def etat_machine(racine, profil: dict, ia: bool) -> dict:
    libre = disque.libre(racine)
    return {"processeur": psutil.cpu_percent(interval=None), "memoire": psutil.virtual_memory().percent,
            "disque": {"libre": disque.texte(libre), "niveau": disque.niveau(libre)},
            "encodeur": libelle(profil), "ia": ia}


def maintenu_eveille(battement, vivant: bool) -> bool:
    """l'atelier empêche la veille tant qu'il a au moins une tâche en cours (ids listés dans son battement)"""
    b = lire_json(battement) if vivant else None
    return bool(vivant and isinstance(b, dict) and b.get("en_cours"))


def vue_activite(racine, battement, profil: dict, ia: bool) -> dict:
    now = time.time()
    titres = {}

    def podcast(d) -> str:
        if d not in titres:
            pj = lire_json(Path(d) / "projet.json", {})
            titres[d] = (pj.get("titre") if isinstance(pj, dict) else None) or Path(d).name
        return titres[d]
    toutes = [{**_tache(t, now), "podcast": podcast(d)} for d, t in file.lister(racine) if not remplacee(d, t)]
    groupes = {"en_cours": [t for t in toutes if t["actif"]],
               "en_attente": [t for t in toutes if t["statut"] == "en_attente"],
               "echec": [t for t in toutes if t["statut"] == "echec"],
               "terminees": sorted([t for t in toutes if t["statut"] in ("terminee", "annulee")],
                                   key=lambda t: t["fin"] or 0, reverse=True)[:20]}
    vivant = atelier_vivant(battement)
    machine = {**etat_machine(racine, profil, ia), "eveille": maintenu_eveille(battement, vivant)}
    if not vivant or machine["disque"]["niveau"] == "rouge" or groupes["echec"]:
        voyant = "rouge"
    elif any(t["statut"] == "semble_bloquee" for t in groupes["en_cours"]) or machine["disque"]["niveau"] == "orange":
        voyant = "orange"
    else:
        voyant = "vert"
    return {"atelier": {"vivant": vivant}, "voyant": voyant, "groupes": groupes, "machine": machine,
            "en_cours": len(groupes["en_cours"])}
