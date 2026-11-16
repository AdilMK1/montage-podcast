"""Règles du process : chaque action est permise ou refusée avec une raison en français.

appliquer(etat, action) -> nouvel état (l'état reçu n'est jamais modifié) ; lève Refus sinon.
C'est le serveur qui appelle cette fonction : l'interface n'a aucune logique de process.
"""
import math
from copy import deepcopy

from . import modele as M


class Refus(Exception):
    """action non permise ; le message est affiché tel quel à l'utilisateur"""


def _exige(condition, raison: str):
    if not condition:
        raise Refus(raison)


_ABSENT = object()
_LIBELLES = {"reglages": "réglages", "spec": "description du short", "retenu": "short retenu ou non",
             "empreinte": "empreinte de fabrication", "passages": "passages à retirer", "garder": "garder ou non",
             "shorts": "propositions de shorts", "id": "identifiant", "alertes": "alertes", "raison": "raison",
             "a": "début du passage", "b": "fin du passage", "debut": "départ de l'essai", "format": "format",
             "duree": "durée", "rendu_s": "durée du rendu",
             "packs": "packs", "pack": "pack", "adopter": "pack de reprise",
             "origine": "empreinte d'origine du pack de reprise"}
NOMBRE = (int, float)


def _champ(a: dict, cle: str, types=None, defaut=_ABSENT):
    """lit un champ d'action ; Refus clair s'il manque ou n'a pas le bon type (bool n'est pas un nombre)"""
    nom = _LIBELLES.get(cle, cle)
    if cle not in a:
        if defaut is _ABSENT:
            raise Refus(f"Information manquante : {nom}.")
        return defaut
    v = a[cle]
    if types is not None:
        tt = types if isinstance(types, tuple) else (types,)
        if not isinstance(v, tt) or (isinstance(v, bool) and bool not in tt):
            raise Refus(f"Information invalide : {nom}.")
    return v


def fini(v) -> bool:
    """nombre fini ; un entier immense (JSON l'accepte) n'est pas fini, sans OverflowError"""
    try:
        return math.isfinite(v)
    except OverflowError:
        return False


def _empreinte_recue(a: dict) -> str:
    emp = _champ(a, "empreinte", str)
    _exige(emp, "Information invalide : empreinte de fabrication.")
    return emp


def _short(e, action) -> dict:
    sh = M.trouver_short(e, _champ(action, "id", str))
    _exige(sh is not None, "Ce short n'existe pas dans la série en cours.")
    return sh


# ---------- casting ----------

NOM_MAX = 40


def _casting(e) -> dict:
    _exige(not M.casting_manuel(e), "Ce podcast a été créé avec les noms choisis à la main : pas de casting à faire.")
    _exige(e["casting"].get("pret"), "La pré-analyse n'est pas finie : attends la suggestion de casting.")
    return e["casting"]["reglages"]


def _personne(r: dict, micro) -> dict:
    p = next((x for x in r["personnes"] if x["micro"] == micro), None)
    _exige(p is not None, "Ce micro n'existe pas dans le casting.")
    return p


def _camera(r: dict, cam) -> str:
    _exige(isinstance(cam, str) and cam in r["cameras"], "Cette caméra n'existe pas dans le casting.")
    return cam


def _casting_pret(e, a):
    _exige(not M.casting_manuel(e), "Ce podcast a été créé avec les noms choisis à la main : pas de casting à faire.")
    r = _champ(a, "reglages", dict)
    _exige(isinstance(r.get("personnes"), list) and isinstance(r.get("cameras"), list),
           "Information invalide : suggestion de casting.")
    e["casting"] = {"pret": True, "reglages": r, "valide": None}


def _renommer_personne(e, a):
    p = _personne(_casting(e), a.get("micro"))
    nom = " ".join(_champ(a, "nom", str).split())
    _exige(nom, "Le prénom ne peut pas être vide.")
    _exige(len(nom) <= NOM_MAX, f"Ce prénom est trop long ({NOM_MAX} caractères au plus).")
    p["nom"] = nom


def _associer_micro(e, a):
    r = _casting(e)
    p = _personne(r, a.get("micro"))
    cam = _champ(a, "camera", (str, type(None)))
    if cam is not None:
        _camera(r, cam)
        _exige(cam != r.get("large"), "Cette caméra est le plan large : désigne d'abord un autre plan large.")
        autre = next((x for x in r["personnes"] if x["camera"] == cam and x is not p), None)
        if autre is not None:  # la caméra était à quelqu'un : les deux échangent
            autre["camera"] = p["camera"]
    p["camera"] = cam


def _echanger_personnes(e, a):
    r = _casting(e)
    pa, pb = _personne(r, a.get("a")), _personne(r, a.get("b"))
    _exige(pa is not pb, "Choisis deux personnes différentes.")
    quoi = a.get("quoi", "cameras")
    _exige(quoi in ("cameras", "noms"), "On échange les caméras ou les noms.")
    cles = ("camera",) if quoi == "cameras" else ("nom", "role")
    for k in cles:
        pa[k], pb[k] = pb[k], pa[k]


def _designer_large(e, a):
    r = _casting(e)
    cam = _camera(r, a.get("camera"))
    ancien = r.get("large")
    for p in r["personnes"]:
        if p["camera"] == cam:  # la personne filmée par cette caméra prend l'ancien plan large
            p["camera"] = ancien
    r["large"] = cam


def _definir_animateur(e, a):
    r = _casting(e)
    p = _personne(r, a.get("micro"))
    for x in r["personnes"]:
        x["role"] = "animateur" if x is p else "invité"


def _valider_casting(e, a):
    r = _casting(e)
    noms = [p["nom"].strip() for p in r["personnes"]]
    _exige(all(noms), "Donne un prénom à chaque personne.")
    _exige(len({n.casefold() for n in noms}) == len(noms), "Deux personnes ont le même prénom : distingue-les.")
    _exige(sum(p["role"] == "animateur" for p in r["personnes"]) <= 1, "Une seule personne anime.")
    e["casting"]["valide"] = M.empreinte(r)


# ---------- analyse et réglages ----------

def _analyse_finie(e, a):
    e["analyse"]["fait"] = True
    if not M.casting_manuel(e):  # avec quel casting : le changer ensuite rend l'analyse « à refaire »
        e["analyse"]["casting"] = _champ(a, "casting", (str, type(None)), defaut=M.empreinte_casting(e))


def _regler_couleur(e, a):
    e["couleur"] = {"reglages": _champ(a, "reglages", dict), "valide": None}


def _valider_couleur(e, a):
    e["couleur"]["valide"] = M.empreinte(e["couleur"]["reglages"])


def _regler_son(e, a):
    _exige(e["analyse"]["fait"], "Le son se règle une fois l'analyse terminée.")
    e["son"] = {"reglages": _champ(a, "reglages", dict), "valide": None, "applique": e["son"].get("applique")}


def _valider_son(e, a):
    _exige(e["analyse"]["fait"], "Le son se règle une fois l'analyse terminée.")
    _exige(not M.son_a_recalculer(e), "Le son se recalcule avec tes derniers réglages : attends la fin pour valider.")
    e["son"]["valide"] = M.empreinte(e["son"]["reglages"])


def _son_calcule(e, a):
    e["son"]["applique"] = _empreinte_recue(a)


# ---------- shorts ----------

def _spec_short(a: dict) -> dict:
    """description d'un short reçue de l'interface ; son « pack », s'il y en a un, est un id non vide (son existence
    dans la bibliothèque est vérifiée par le serveur)"""
    spec = _champ(a, "spec", dict)
    _exige("pack" not in spec or (isinstance(spec["pack"], str) and spec["pack"]),
           "Information invalide : pack du short.")
    return spec


def _proposer_shorts(e, a):
    _exige(e["analyse"]["fait"], "Attends la fin de l'analyse : l'IA a besoin du transcript.")
    specs = _champ(a, "shorts", list)
    _exige(specs, "Aucune proposition reçue.")
    _exige(all(isinstance(x, dict) for x in specs), "Information invalide : propositions de shorts.")
    specs = [{k: v for k, v in x.items() if k != "pack"} for x in specs]  # l'IA ne choisit pas de pack
    sid = f"S{len(e['series']) + 1}"
    e["series"].append({"id": sid, "shorts": [M.nouveau_short(f"{sid}-{i + 1:02d}", spec)
                                              for i, spec in enumerate(specs)]})
    e["serie_active"] = sid


def _ajouter_short(e, a):
    _exige(e["analyse"]["fait"], "Attends la fin de l'analyse : le transcript n'est pas prêt.")
    spec = _spec_short(a)
    s = M.serie_active(e)
    if s is None:
        s = {"id": f"S{len(e['series']) + 1}", "shorts": []}
        e["series"].append(s)
        e["serie_active"] = s["id"]
    s["shorts"].append(M.nouveau_short(f"{s['id']}-{len(s['shorts']) + 1:02d}", spec))


def _modifier_short(e, a):
    sh = _short(e, a)
    spec = _spec_short(a)
    # l'interface renvoie 39.0 sous la forme 39 : une valeur égale garde sa forme d'origine, pour que les
    # empreintes (aperçu, fabrication) ne changent que si le contenu change vraiment
    sh["spec"] = {k: (sh["spec"][k] if k in sh["spec"] and sh["spec"][k] == v else v) for k, v in spec.items()}


def _retenir_short(e, a):
    sh = _short(e, a)
    sh["retenu"] = _champ(a, "retenu", bool)


def _lancer_fabrication(e, a):
    _exige(M.casting_valide(e), "Valide d'abord le casting.")
    _exige(M.reglages_valides(e), "Valide d'abord la couleur et le son.")
    _exige(M.a_fabriquer(e), "Aucun short à fabriquer : retiens au moins une proposition.")


# Résultats de tâches longues (short_fabrique, montage_fini, export_fini) : on enregistre l'empreinte reçue SANS
# refuser si les prérequis ont changé pendant la tâche. Le résultat sera simplement « à refaire » (son empreinte ne
# correspond plus) ; la sécurité vient des statuts dérivés et de livrables(), pas d'un refus ici.

def _short_fabrique(e, a):
    sh = _short(e, a)
    emp = _empreinte_recue(a)
    alertes = _champ(a, "alertes", list, defaut=[])
    _exige(all(isinstance(x, str) for x in alertes), "Information invalide : alertes.")
    sh.update(fabrique=emp, alertes=list(alertes), alertes_ok=not alertes, decision=None)


def _confirmer_alertes(e, a):
    sh = _short(e, a)
    _exige(sh["fabrique"] is not None, "Ce short n'est pas encore fabriqué.")
    _exige(M.statut_short(e, sh) == "a_controler", "Ce short n'est pas en attente de contrôle.")
    sh["alertes_ok"] = True


def _decider_short(e, a):
    sh = _short(e, a)
    _exige(a.get("decision") in ("garder", "jeter"), "La décision doit être garder ou jeter.")
    _exige(M.statut_short(e, sh) in ("a_controler", "garde", "jete"),
           "Ce short n'est pas à jour : refais-le avant de décider.")
    if a["decision"] == "garder":
        # un short jeté reste « jeté » même pas à jour : le garder exige qu'il soit à jour
        _exige(M.short_a_jour(e, sh), "Ce short n'est pas à jour : refais-le avant de décider.")
        _exige(sh["alertes_ok"], "Réécoute d'abord les coupes signalées.")
    sh["decision"] = a["decision"]


def _repecher_short(e, a):
    sh = _short(e, a)
    _exige(M.statut_short(e, sh) == "jete", "Ce short n'est pas jeté.")
    sh["decision"] = None  # redevient « à contrôler », ou « à refaire » si les réglages ont changé


# ---------- packs de shorts ----------
# Les empreintes des packs viennent du serveur (app/packs/projets.py), qui lit la bibliothèque : l'état reste pur.

def _packs_recus(a) -> dict:
    p = _champ(a, "packs", dict)
    _exige(all(isinstance(k, str) and k and (v is None or isinstance(v, str)) for k, v in p.items()),
           "Information invalide : packs.")
    return dict(p)


def _packs_complets(e, recus: dict) -> dict:
    """empreintes reçues ; celles des packs encore utilisés (podcast, shorts de toutes les séries) qui manquent sont
    gardées, celles des packs qui ne servent plus disparaissent. Contrat avec le serveur (app/packs/projets.py) : il
    envoie les empreintes à jour des packs utilisés ; un oubli ne fait pas passer des shorts « à refaire »."""
    utilises = {e.get("pack")} | {sh["spec"]["pack"] for s in e["series"] for sh in s["shorts"]
                                  if isinstance(sh["spec"].get("pack"), str) and sh["spec"]["pack"]}
    anciens = e.get("packs") or {}
    return {**{k: anciens[k] for k in utilises if k in anciens}, **recus}


def _choisir_pack(e, a):
    pid = _champ(a, "pack", str)
    packs = _packs_recus(a)
    _exige(pid and packs.get(pid) is not None, "Ce pack n'existe pas : choisis-en un autre.")
    e["pack"] = pid
    e["packs"] = _packs_complets(e, packs)


def _synchroniser_packs(e, a):
    """empreintes à jour des packs utilisés ; « adopter » : reprise d'un projet d'avant les packs (une seule fois) ;
    « origine » : empreinte du pack tel que migré depuis le preset (sinon son empreinte actuelle)"""
    packs = _packs_recus(a)
    pid = _champ(a, "adopter", (str, type(None)), defaut=None)
    origine = _champ(a, "origine", (str, type(None)), defaut=None)
    if pid and not e.get("pack"):
        _exige(packs.get(pid) is not None, "Information invalide : pack de reprise (empreinte manquante).")
        e["pack"] = pid
        e["pack_origine"] = {"id": pid, "empreinte": origine or packs[pid]}
    e["packs"] = _packs_complets(e, packs)


# ---------- épisode ----------

def _proposer_passages(e, a):
    _exige(e["analyse"]["fait"], "Attends la fin de l'analyse : l'IA a besoin du transcript.")
    ps = _champ(a, "passages", list)
    _exige(all(isinstance(p, dict) for p in ps), "Information invalide : passages à retirer.")
    out, vus = [], set()
    for p in ps:
        pid, deb, fin = _champ(p, "id", (str, int)), _champ(p, "a", NOMBRE), _champ(p, "b", NOMBRE)
        _exige(fini(deb), "Information invalide : début du passage.")
        _exige(fini(fin), "Information invalide : fin du passage.")
        _exige(deb < fin, f"Le passage {pid} doit commencer avant sa fin.")
        _exige(str(pid) not in vus, f"Deux passages ont le même identifiant : {pid}.")  # 1 et "1" : même passage
        vus.add(str(pid))
        raison = _champ(p, "raison", (str, type(None)), defaut="")  # l'IA renvoie parfois null
        out.append({"id": pid, "a": deb, "b": fin, "raison": raison or "", "garder": False})
    e["episode"].update(passages=out, passages_revus=False)


def _decider_passage(e, a):
    ps = e["episode"]["passages"] or []
    pid = _champ(a, "id", (str, int))
    p = next((x for x in ps if x["id"] == pid), None)
    _exige(p is not None, "Ce passage n'existe pas.")
    p["garder"] = _champ(a, "garder", bool)


def _valider_passages(e, a):
    _exige(e["episode"]["passages"] is not None, "Les passages à retirer ne sont pas encore repérés.")
    e["episode"]["passages_revus"] = True


def _proxys_prets(e, a):
    e["proxys"]["prets"] = True


def _lancer_montage(e, a):
    _exige(e["episode"]["passages_revus"], "Vérifie d'abord les passages retirés de l'épisode.")
    _exige(M.casting_valide(e), "Valide d'abord le casting.")
    _exige(M.reglages_valides(e), "Valide d'abord la couleur et le son.")


FORMATS = ("1080p", "4k")


def _nombre(a: dict, cle: str, mini: float = 0.0, strict: bool = False, defaut=_ABSENT):
    v = _champ(a, cle, NOMBRE, defaut=defaut)
    if v is not None:
        _exige(fini(v) and (v > mini if strict else v >= mini), f"Information invalide : {_LIBELLES.get(cle, cle)}.")
    return v


def _format(a: dict, defaut=_ABSENT) -> str:
    fmt = _champ(a, "format", str, defaut=defaut)
    _exige(fmt in FORMATS, "Information invalide : format (1080p ou 4k).")
    return fmt


def _montage_a_jour(e):
    cur = M.empreinte_episode(e)
    _exige(cur is not None and e["episode"]["montage"] == cur, "Le montage n'est pas à jour : remonte l'épisode.")
    return cur


def _mesure(e, a, quoi: str):
    """vitesse de rendu mesurée (secondes de rendu par seconde d'épisode) de l'essai ou de l'export, par format,
    si la tâche l'a envoyée ; gardée d'un montage à l'autre (c'est la vitesse du Mac sur ce podcast)"""
    if "rendu_s" in a or "duree" in a:
        fmt, duree, rendu = _format(a), _nombre(a, "duree", strict=True), _nombre(a, "rendu_s")
        v = e["episode"].get("vitesses") or {}
        v = {k: dict(v.get(k) or {}) for k in ("essai", "export")}
        v[quoi][fmt] = round(rendu / duree, 4)
        e["episode"]["vitesses"] = v


def _montage_fini(e, a):
    # nouveau montage : l'essai est à refaire et à revoir
    e["episode"].update(montage=_empreinte_recue(a), apercu_valide=None, essai=None)
    if "duree" in a:
        e["episode"]["duree"] = _nombre(a, "duree")


def _lancer_essai(e, a):
    _montage_a_jour(e)
    _format(a, defaut="1080p")
    _nombre(a, "debut", defaut=0.0)


def _essai_fini(e, a):
    emp = _empreinte_recue(a)
    fmt, debut = _format(a), _nombre(a, "debut")
    duree, rendu = _nombre(a, "duree", strict=True), _nombre(a, "rendu_s")
    _mesure(e, a, "essai")
    # un nouvel essai (autre départ, autre format) se revoit : la validation précédente tombe
    e["episode"].update(essai={"empreinte": emp, "format": fmt, "debut": debut, "duree": duree, "rendu_s": rendu},
                        apercu_valide=None)


def _valider_apercu(e, a):
    """« Valider l'essai » (nom interne gardé)"""
    cur = _montage_a_jour(e)
    _exige(M.essai_a_jour(e), "L'essai de 3 minutes n'est pas encore rendu pour ce montage : attends-le ou refais-le.")
    e["episode"]["apercu_valide"] = cur


def _lancer_export(e, a):
    cur = M.empreinte_episode(e)
    _exige(cur is not None and M.essai_a_jour(e) and e["episode"]["apercu_valide"] == cur,
           "Valide d'abord l'essai de 3 minutes.")


def _export_fini(e, a):
    ep, emp = e["episode"], _empreinte_recue(a)
    # nouveau fichier : les coupes rapides sont à réappliquer ; même épisode (même minutage) : elles restent valables,
    # sinon leurs heures ne veulent plus rien dire
    ep["coupes_faites"] = None
    if emp != ep["export"]:
        ep["coupes"] = []
    ep["export"] = emp
    _mesure(e, a, "export")


# ---------- coupes rapides dans l'épisode exporté ----------

def _export_valide(e):
    _exige(M.statuts(e)["export"] == "valide",
           "Exporte d'abord l'épisode : les coupes rapides se font dans le fichier exporté.")


def _ajouter_coupe(e, a):
    _export_valide(e)
    deb, fin = _nombre(a, "a"), _nombre(a, "b")
    _exige(fin > deb, "La coupe doit finir après son début.")
    duree = e["episode"].get("duree")
    _exige(not duree or deb < duree, "Cette coupe commence après la fin de l'épisode.")
    c = list(M.coupes(e))
    c.append({"id": max((x["id"] for x in c), default=0) + 1, "a": float(deb), "b": float(fin)})
    e["episode"]["coupes"] = c


def _retirer_coupe(e, a):
    cid = _champ(a, "id", int)
    c = M.coupes(e)
    _exige(any(x["id"] == cid for x in c), "Cette coupe n'existe pas.")
    e["episode"]["coupes"] = [x for x in c if x["id"] != cid]


def _lancer_coupes(e, a):
    _export_valide(e)
    _exige(M.coupes(e), "Ajoute d'abord une coupe.")
    _exige(not M.coupes_a_jour(e), "Les coupes sont déjà appliquées.")


def _coupes_finies(e, a):
    e["episode"]["coupes_faites"] = _empreinte_recue(a)


# ---------- livraison ----------

def _livrer(e, a):
    liv = M.livrables(e)
    _exige(liv["shorts"] or liv["episode"], "Rien à livrer : garde au moins un short ou exporte l'épisode.")
    e["livraison"]["fait"] = M.empreinte(liv)


ACTIONS = {
    "casting_pret": _casting_pret, "renommer_personne": _renommer_personne, "associer_micro": _associer_micro,
    "echanger_personnes": _echanger_personnes, "designer_large": _designer_large,
    "definir_animateur": _definir_animateur, "valider_casting": _valider_casting,
    "analyse_finie": _analyse_finie,
    "regler_couleur": _regler_couleur, "valider_couleur": _valider_couleur,
    "regler_son": _regler_son, "valider_son": _valider_son,
    "son_calcule": _son_calcule,
    "proposer_shorts": _proposer_shorts, "ajouter_short": _ajouter_short, "modifier_short": _modifier_short,
    "retenir_short": _retenir_short, "lancer_fabrication": _lancer_fabrication, "short_fabrique": _short_fabrique,
    "confirmer_alertes": _confirmer_alertes, "decider_short": _decider_short, "repecher_short": _repecher_short,
    "proposer_passages": _proposer_passages, "decider_passage": _decider_passage,
    "valider_passages": _valider_passages, "proxys_prets": _proxys_prets, "lancer_montage": _lancer_montage,
    "montage_fini": _montage_fini, "lancer_essai": _lancer_essai, "essai_fini": _essai_fini,
    "valider_apercu": _valider_apercu, "lancer_export": _lancer_export,
    "export_fini": _export_fini, "ajouter_coupe": _ajouter_coupe, "retirer_coupe": _retirer_coupe,
    "lancer_coupes": _lancer_coupes, "coupes_finies": _coupes_finies, "livrer": _livrer,
    "choisir_pack": _choisir_pack, "synchroniser_packs": _synchroniser_packs,
}


def appliquer(etat: dict, action: dict) -> dict:
    _exige(isinstance(action, dict) and isinstance(action.get("type"), str), "Action invalide : type d'action manquant.")
    f = ACTIONS.get(action["type"])
    _exige(f is not None, f"Action inconnue : {action.get('type')}")
    e = deepcopy(etat)
    f(e, action)
    return e
