"""Routes de la bibliothèque des packs (/api/packs…) : liste, lecture, création (et duplication), renommage,
modification, suppression, export / import (.zip), fichiers (logo, police), aperçus. Toute modification d'un pack
met à jour les empreintes des podcasts qui l'utilisent : leurs shorts déjà fabriqués passent « à refaire »."""
import json

from app.packs import apercu as A
from app.packs import archive as Z
from app.packs import bibliotheque as B
from app.packs import projets as P

from . import medias

TAILLE_MAX = 50 * 1024 * 1024  # corps brut accepté (zip, logo, police)
BRUTS = ("/api/packs/importer", "/api/packs/fichier")


def _id(d: dict) -> str:
    v = d.get("id")
    if not isinstance(v, str) or not v:
        raise FileNotFoundError("Ce pack est introuvable.")
    return v


def vue_pack(app, pid) -> dict:
    p = B.lire(app.racine_packs, pid)
    dispo = B.disponibles_avec(p["fichiers"])
    return {**p, "polices": dispo["police"], "musiques": dispo["musique"], "logos": dispo["logo"],
            "utilise_par": P.usages(app.racine_projets).get(pid, []), "fonds": A.fonds(app.racine_projets)}


def _empreinte(app, pid) -> str | None:
    """None : pack illisible (disparu entre-temps, fichier bloqué) ; il reste dans la liste"""
    try:
        return B.empreinte_pack(app.racine_packs, pid)
    except OSError:  # FileNotFoundError compris
        return None


def liste(app) -> dict:
    u = P.usages(app.racine_projets)
    out = []
    for p in B.lister(app.racine_packs):
        h = _empreinte(app, p["id"])
        out.append({**p, "utilise_par": u.get(p["id"], []), "empreinte": h, "illisible": h is None})
    # defaut : le pack que la création prendra si on n'en choisit pas (dernier utilisé, config, neutre, aucun)
    return {"packs": out, "dernier": B.dernier(app.racine_packs), "defaut": app.pack_defaut()}


def _reglages_url(q: dict):
    if not q.get("r"):
        return None
    try:
        r = json.loads(q["r"])
    except ValueError:
        r = None
    if not isinstance(r, dict):
        raise ValueError("Réglages du pack invalides.")
    return r


def get(h, chemin: str, q: dict):
    app = h.app
    if chemin == "/api/packs":
        h.envoyer_json(liste(app))
    elif chemin == "/api/packs/pack":
        h.envoyer_json(vue_pack(app, _id(q)))
    elif chemin == "/api/packs/apercu":
        r = _reglages_url(q)
        f = A.apercu_pack(app.racine_packs, app.cache_packs(), _id(q), r, A.fond(app.racine_projets, q.get("fond")))
        medias.envoyer(h, f, garder=bool(q.get("v")) and r is None)
    elif chemin == "/api/packs/habillage":
        f = A.habillage_short(app.pdir(q["projet"]), app.racine_packs, app.cache_packs(), q["short"])
        medias.envoyer(h, f, garder=True)
    elif chemin == "/api/packs/exporter":
        pid = _id(q)
        h.envoyer_octets(Z.exporter(app.racine_packs, pid), "application/zip", nom=f"{pid}.zip")
    else:
        raise FileNotFoundError("Cette adresse n'existe pas dans l'app.")


def post(h, chemin: str, b: dict):
    app = h.app
    if chemin == "/api/packs/creer":
        h.envoyer_json({"ok": True, "pack": B.creer(app.racine_packs, b.get("nom"), depuis=b.get("depuis"))})
    elif chemin == "/api/packs/renommer":
        B.renommer(app.racine_packs, _id(b), b.get("nom"))
        h.envoyer_json({"ok": True})
    elif chemin == "/api/packs/modifier":
        pid = _id(b)
        B.enregistrer(app.racine_packs, pid, b.get("reglages"))
        n = P.synchroniser_tous(app.racine_projets, app.racine_packs, pid)
        h.envoyer_json({"ok": True, "pack": vue_pack(app, pid), "podcasts": n})
    elif chemin == "/api/packs/supprimer":
        pid = _id(b)
        P.supprimer_pack(app.racine_projets, app.racine_packs, pid)
        h.envoyer_json({"ok": True})
    else:
        raise FileNotFoundError("Cette adresse n'existe pas dans l'app.")


def post_brut(h, chemin: str, q: dict, octets: bytes):
    app = h.app
    if chemin == "/api/packs/importer":
        h.envoyer_json({"ok": True, "pack": Z.importer(app.racine_packs, octets)})
    elif chemin == "/api/packs/fichier":
        pid = _id(q)
        nom = B.ajouter_fichier(app.racine_packs, pid, q.get("nom", ""), octets)
        P.synchroniser_tous(app.racine_projets, app.racine_packs, pid)  # un fichier utilisé a pu être remplacé
        h.envoyer_json({"ok": True, "fichier": nom, "pack": vue_pack(app, pid)})
    else:
        raise FileNotFoundError("Cette adresse n'existe pas dans l'app.")
