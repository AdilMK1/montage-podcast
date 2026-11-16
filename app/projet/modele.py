"""Modèle de l'état d'un projet (etat.json) : données, empreintes, statuts dérivés.

Aucun statut n'est stocké : tout se recalcule depuis les faits (réglages validés, empreintes de fabrication,
décisions humaines). Une empreinte = hachage des entrées qui ont servi à produire quelque chose ; si elle a changé,
la production est « à refaire ».
"""
import hashlib
import json

VERSION = 1


CASTING_MANUEL = {"manuel": True}


def nouvel_etat(casting: bool = False) -> dict:
    """casting=True : projet créé à partir d'un dossier seul (pré-analyse puis casting à valider) ; sinon casting
    « manuel » (noms donnés à la création, projets d'avant le casting) : considéré validé"""
    return {
        "version": VERSION,
        "casting": {"pret": False, "reglages": None, "valide": None} if casting else dict(CASTING_MANUEL),
        "analyse": {"fait": False},
        "couleur": {"reglages": {}, "valide": None},
        "son": {"reglages": {}, "valide": None, "applique": None},
        "proxys": {"prets": False},
        "series": [],
        "serie_active": None,
        # pack de shorts du podcast (id dans la bibliothèque packs/) ; None : projet d'avant les packs, pas encore
        # repris. packs : {id: empreinte du contenu} des packs utilisés par le projet, tenu à jour par le serveur.
        # (pack_origine, facultatif : {id, empreinte} du pack donné à la reprise d'un projet d'avant les packs)
        "pack": None, "packs": {},
        # essai : l'essai d'export de 3 minutes rendu pour ce montage ({empreinte, format, debut, duree, rendu_s}) ;
        # apercu_valide : empreinte de l'épisode dont l'essai a été validé (nom gardé de l'ancien « aperçu ») ;
        # vitesses : {"essai"|"export": {format: secondes de rendu par seconde d'épisode}}, mesurées ;
        # coupes : coupes rapides dans le fichier exporté [{id, a, b}] (heures de l'export) ; coupes_faites :
        # empreinte des coupes appliquées (fichier « (coupé) » à jour)
        "episode": {"passages": None, "passages_revus": False, "montage": None, "duree": None, "essai": None,
                    "apercu_valide": None, "export": None, "vitesses": {}, "coupes": [], "coupes_faites": None},
        "livraison": {"fait": None},
    }


def nouveau_short(sid: str, spec: dict) -> dict:
    return {"id": sid, "spec": spec, "retenu": False, "fabrique": None, "alertes": [], "alertes_ok": True,
            "decision": None}


def empreinte(obj) -> str:
    txt = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(txt.encode("utf-8")).hexdigest()[:16]


def _valide(e: dict, cle: str) -> bool:
    v = e[cle]["valide"]
    return v is not None and v == empreinte(e[cle]["reglages"])


def casting_manuel(e: dict) -> bool:
    return bool((e.get("casting") or CASTING_MANUEL).get("manuel"))


def empreinte_casting(e: dict) -> str | None:
    """« manuel », l'empreinte du casting validé s'il n'a pas changé depuis, sinon None"""
    if casting_manuel(e):
        return "manuel"
    c = e["casting"]
    return c["valide"] if c.get("pret") and c["valide"] is not None and c["valide"] == empreinte(c["reglages"]) else None


def casting_valide(e: dict) -> bool:
    return empreinte_casting(e) is not None


def _avec_casting(e: dict, base: dict) -> dict:
    """l'empreinte du casting entre dans celles des fabrications, sauf pour un projet manuel (empreintes inchangées)"""
    return base if casting_manuel(e) else {**base, "casting": empreinte_casting(e)}


def reglages_valides(e: dict) -> bool:
    """couleur ET son validés, et pas modifiés depuis"""
    return _valide(e, "couleur") and _valide(e, "son")


def son_a_recalculer(e: dict) -> bool:
    """le son traité ne correspond plus aux réglages du son (à recalculer avant de pouvoir valider)"""
    return e["son"].get("applique") != empreinte(e["son"]["reglages"])


def serie_active(e: dict) -> dict | None:
    return next((s for s in e["series"] if s["id"] == e["serie_active"]), None)


def trouver_short(e: dict, sid: str) -> dict | None:
    s = serie_active(e)
    return next((x for x in s["shorts"] if x["id"] == sid), None) if s else None


def pack_du_short(e: dict, sh: dict) -> str | None:
    """pack d'un short : le sien (spec « pack »), sinon celui du podcast ; None : projet d'avant les packs pas encore
    repris (il garde son preset, hors empreinte)"""
    p = sh["spec"].get("pack")
    return p if isinstance(p, str) and p else e.get("pack")


def _avec_pack(e: dict, sh: dict, base: dict) -> dict:
    """le contenu du pack (son empreinte, tenue à jour par le serveur dans e["packs"]) entre dans l'empreinte d'un
    short. Exception : un projet repris d'avant les packs (« pack_origine ») garde ses empreintes d'avant tant que son
    pack d'origine n'a pas changé : ses shorts déjà fabriqués restent « à jour »."""
    pid = pack_du_short(e, sh)
    if pid is None:
        return base
    h = (e.get("packs") or {}).get(pid)
    if e.get("pack_origine") == {"id": pid, "empreinte": h}:
        return base
    return {**base, "pack": [pid, h]}


def empreinte_short(e: dict, sh: dict) -> str | None:
    if not reglages_valides(e):
        return None
    return empreinte(_avec_pack(e, sh, _avec_casting(
        e, {"couleur": e["couleur"]["valide"], "son": e["son"]["valide"], "spec": sh["spec"]})))


def statut_short(e: dict, sh: dict) -> str:
    """propose | retenu | a_refaire | a_controler | garde | jete

    Un short jeté reste jeté même si les réglages changent : on ne refabrique pas ce que la personne a écarté
    (elle peut le repêcher, il redevient alors « à contrôler » ou « à refaire »)."""
    if not sh["retenu"]:
        return "propose"
    if sh["decision"] == "jeter":
        return "jete"
    if sh["fabrique"] is None:
        return "retenu"
    if sh["fabrique"] != empreinte_short(e, sh):
        return "a_refaire"
    if sh["decision"] == "garder":
        return "garde"
    return "a_controler"


def short_a_jour(e: dict, sh: dict) -> bool:
    """fabriqué avec les réglages et la description actuels"""
    return sh["fabrique"] is not None and sh["fabrique"] == empreinte_short(e, sh)


def a_fabriquer(e: dict) -> list[str]:
    s = serie_active(e)
    return [x["id"] for x in (s["shorts"] if s else []) if statut_short(e, x) in ("retenu", "a_refaire")]


def empreinte_episode(e: dict) -> str | None:
    ep = e["episode"]
    if not reglages_valides(e) or ep["passages"] is None or not ep["passages_revus"]:
        return None
    return empreinte(_avec_casting(e, {
        "couleur": e["couleur"]["valide"], "son": e["son"]["valide"],
        "passages": sorted([str(p["id"]), p["a"], p["b"], bool(p["garder"])] for p in ep["passages"])}))


def essai_a_jour(e: dict) -> bool:
    """l'essai d'export de 3 minutes a été rendu avec l'épisode actuel (même montage, couleur, son, passages)"""
    cur, ep = empreinte_episode(e), e["episode"]
    essai = ep.get("essai") or {}
    return cur is not None and ep["montage"] == cur and essai.get("empreinte") == cur


def coupes(e: dict) -> list[dict]:
    return e["episode"].get("coupes") or []


def empreinte_coupes(e: dict) -> str | None:
    """coupes rapides à appliquer au fichier exporté (None s'il n'y en a pas) : changent avec l'export lui-même"""
    c = coupes(e)
    return empreinte({"export": e["episode"]["export"], "coupes": sorted([x["a"], x["b"]] for x in c)}) if c else None


def coupes_a_jour(e: dict) -> bool:
    """pas de coupe, ou le fichier coupé correspond aux coupes actuelles"""
    emp = empreinte_coupes(e)
    return emp is None or e["episode"].get("coupes_faites") == emp


def export_a_jour(e: dict) -> bool:
    cur, ep = empreinte_episode(e), e["episode"]
    return bool(cur and ep["export"] == cur and ep["apercu_valide"] == cur)


def livrables(e: dict) -> dict:
    s = serie_active(e)
    shorts = [x["id"] for x in (s["shorts"] if s else []) if statut_short(e, x) == "garde"]
    ep = export_a_jour(e) and coupes_a_jour(e)
    # les coupes entrent dans l'empreinte de la livraison : couper à nouveau rend la livraison à refaire
    return {"shorts": shorts, "episode": ep, **({"coupes": empreinte_coupes(e)} if ep and coupes(e) else {})}


def statuts(e: dict) -> dict:
    """statut de chaque phase : a_faire | a_valider | valide | a_refaire"""
    ep = e["episode"]
    cur = empreinte_episode(e)

    def reglage(cle, possible=True):
        if not possible:
            return "a_faire"
        return "valide" if _valide(e, cle) else "a_valider"

    s = serie_active(e)
    st_sh = [statut_short(e, x) for x in (s["shorts"] if s else [])]
    if not st_sh:
        shorts = "a_faire"
    elif any(x in ("garde", "jete") for x in st_sh) and not any(x in ("retenu", "a_refaire", "a_controler")
                                                                 for x in st_sh):
        shorts = "valide"
    else:
        shorts = "a_valider"

    passages = "a_faire" if ep["passages"] is None else ("valide" if ep["passages_revus"] else "a_valider")
    montage = "a_faire" if ep["montage"] is None else ("valide" if ep["montage"] == cur else "a_refaire")
    # « apercu » = l'essai d'export de 3 minutes (nom interne gardé) : à faire tant qu'il n'est pas rendu pour ce
    # montage, à valider une fois rendu, à refaire si l'épisode a changé (couleur, son, passages)
    if ep["montage"] is None:
        apercu = "a_faire"
    elif ep["montage"] != cur:
        apercu = "a_refaire"
    elif not essai_a_jour(e):
        apercu = "a_faire"
    else:
        apercu = "valide" if ep["apercu_valide"] == cur else "a_valider"
    # export valide seulement s'il correspond à l'épisode courant ET à un aperçu validé de cet épisode (comme
    # livrables) ; un export qui existe mais ne correspond plus (épisode changé, ou aperçu pas / plus validé, par ex.
    # après un remontage) est « a_refaire » : il faudra (re)valider l'aperçu puis relancer l'export.
    if ep["export"] is None:
        export = "a_faire"
    elif export_a_jour(e):
        export = "valide"
    else:
        export = "a_refaire"
    # coupes rapides dans l'export : aucune | a_faire (fichier coupé pas à jour) | valide
    coupes_st = "aucune" if not coupes(e) else ("valide" if coupes_a_jour(e) else "a_faire")

    liv = livrables(e)
    if not (liv["shorts"] or liv["episode"]):
        livraison = "a_faire"
    else:
        livraison = "valide" if e["livraison"]["fait"] == empreinte(liv) else "a_valider"

    if casting_manuel(e):
        casting = "valide"
    elif not e["casting"].get("pret"):
        casting = "a_faire"
    else:
        casting = "valide" if casting_valide(e) else "a_valider"
    if not e["analyse"]["fait"]:
        analyse = "a_faire"
    else:  # faite avec un autre casting que celui validé maintenant : à refaire
        analyse = "valide" if e["analyse"].get("casting", "manuel") == empreinte_casting(e) else "a_refaire"

    return {"casting": casting, "analyse": analyse,
            "couleur": reglage("couleur"), "son": reglage("son", e["analyse"]["fait"]),
            "shorts": shorts, "passages": passages, "montage": montage, "apercu": apercu, "export": export,
            "coupes": coupes_st, "livraison": livraison}
