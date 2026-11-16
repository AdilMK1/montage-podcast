"""Podcasts et packs : quel pack chaque podcast utilise, reprise des projets d'avant les packs, mise à jour des
empreintes (etat.json « packs ») quand la bibliothèque change ou quand on choisit un pack.

Reprise (une fois par projet) : le pack du podcast devient son ancien preset et `pack_origine` retient l'empreinte de
ce pack tel que migré depuis le preset ; tant que le pack n'en change pas, ses shorts gardent leurs empreintes d'avant
(modele._avec_pack). Si le pack du preset n'est pas encore lisible, la reprise attend (jamais figée sur neutre).

Un pack utilisé mais illisible (dossier disparu, pack.json abîmé) n'envoie pas d'empreinte : l'état garde la dernière
connue (regles._packs_complets), ses shorts ne passent pas « à refaire » pour ça ; la fabrication dira qu'il manque."""
import threading
from pathlib import Path

from app.fichiers import lire_json
from app.projet.regles import Refus
from app.projet.stockage import EtatIllisible, Occupe, VerrouImpossible, lire_etat, modifier

from . import bibliotheque as B

PRESETS = B.RACINE_APP / "presets"
# choisir un pack (podcast, short) et supprimer un pack passent l'un après l'autre : un pack ne disparaît pas juste
# après avoir été choisi (usages vérifiés sous ce verrou)
VERROU_CHOIX = threading.RLock()
PROBLEMES = (EtatIllisible, Occupe, VerrouImpossible, OSError)  # un projet abîmé ou occupé ne bloque pas les autres


def _dossiers(racine_projets) -> list[Path]:
    r = Path(racine_projets)
    return sorted(f.parent for f in r.glob("*/projet.json")) if r.is_dir() else []


def pack_projet(d, e) -> str:
    """pack du podcast : celui de l'état ; projet d'avant les packs : son preset (projet.json), sinon « neutre »"""
    if e.get("pack"):
        return e["pack"]
    preset = (lire_json(Path(d) / "projet.json", {}) or {}).get("preset")
    return B.slug(preset) if isinstance(preset, str) and preset.strip() else "neutre"


def _packs_des_shorts(e) -> set[str]:
    return {sh["spec"]["pack"] for s in e["series"] for sh in s["shorts"]
            if isinstance(sh["spec"].get("pack"), str) and sh["spec"]["pack"]}


def ids_utilises(d, e) -> set[str]:
    """pack du podcast + packs choisis short par short (toutes séries)"""
    return {pack_projet(d, e)} | _packs_des_shorts(e)


def empreintes(racine_packs, ids) -> dict:
    """{id: empreinte} des packs lisibles (un pack introuvable ou abîmé est omis)"""
    out = {}
    for pid in sorted(ids):
        try:
            out[pid] = B.empreinte_pack(racine_packs, pid)
        except FileNotFoundError:
            continue
    return out


def _attendu(racine_packs, presets, pid) -> bool:
    """le pack `pid` va (re)devenir lisible : son dossier existe (pack.json abîmé, en cours d'écriture) ou son preset
    attend encore sa migration (pack pas encore créé à ce lancement) ; la reprise est alors reportée"""
    if pid == B.AUCUN or not B.ID.match(pid):
        return False
    if (Path(racine_packs) / pid).is_dir():
        return True
    if B.migration_finie(racine_packs) or presets is None or not Path(presets).is_dir():
        return False
    return any(B.slug(f.stem) == pid for f in Path(presets).glob("*.json"))


def pack_de_reprise(d, e, racine_packs, presets=PRESETS) -> str | None:
    """pack que prendra un projet d'avant les packs : son preset devenu pack ; neutre (puis Aucun pack) seulement si
    ce preset n'existe nulle part ; None : reprise reportée (pack du preset pas encore lisible)"""
    for pid in (pack_projet(d, e), "neutre"):
        if pid in empreintes(racine_packs, {pid}):
            return pid
        if _attendu(racine_packs, presets, pid):
            return None
    return B.AUCUN


def adopter_si_besoin(d, racine_packs, attente: float = 10.0, presets=PRESETS) -> bool:
    """reprise d'un projet d'avant les packs (pack None) : son preset devient son pack (voir pack_de_reprise) ; son
    « pack d'origine » est ce pack tel que migré depuis le preset (ses shorts ont été fabriqués avec), pour que
    ses shorts passent « à refaire » si le pack a été modifié depuis ; False si rien à faire ou reprise reportée"""
    e = lire_etat(d)
    if e.get("pack"):
        return False
    pid = pack_de_reprise(d, e, racine_packs, presets)
    if pid is None:
        return False
    h = empreintes(racine_packs, _packs_des_shorts(e) | {pid})
    if pid not in h:  # devenu illisible entre-temps : au prochain essai
        return False
    modifier(d, {"type": "synchroniser_packs", "packs": h, "adopter": pid,
                 "origine": B.empreinte_migree(racine_packs, pid) or h[pid]}, attente=attente)
    return True


def adopter_tous(racine_projets, racine_packs, presets=PRESETS) -> int:
    """au démarrage : reprend tous les projets qui ont un etat.json (un projet de la v1 pas encore ouvert est repris
    à sa première ouverture) ; renvoie le nombre de projets repris"""
    n = 0
    for d in _dossiers(racine_projets):
        if not (d / "etat.json").exists():
            continue
        try:
            n += adopter_si_besoin(d, racine_packs, attente=0.5, presets=presets)
        except PROBLEMES:
            continue
    return n


def synchroniser(d, racine_packs, attente: float = 10.0) -> bool:
    """met à jour les empreintes des packs utilisés par ce projet ; False si rien n'a changé"""
    e = lire_etat(d)
    ids = ids_utilises(d, e)
    h = empreintes(racine_packs, ids)
    anciens = e.get("packs") or {}
    if {**{k: v for k, v in anciens.items() if k in ids}, **h} == anciens:  # ce que l'état garderait (regles)
        return False
    modifier(d, {"type": "synchroniser_packs", "packs": h}, attente=attente)
    return True


def synchroniser_tous(racine_projets, racine_packs, pid=None, attente: float = 2.0) -> int:
    """après une modification de la bibliothèque, et au démarrage : chaque projet qui utilise `pid` (tous si None) ;
    renvoie le nombre de projets dont les empreintes ont changé. Un projet occupé est sauté : mis à jour à sa
    prochaine ouverture (/api/projet) ou au prochain démarrage"""
    n = 0
    for d in _dossiers(racine_projets):
        if not (d / "etat.json").exists():
            continue
        try:
            if pid is None or pid in ids_utilises(d, lire_etat(d)):
                n += synchroniser(d, racine_packs, attente=attente)
        except PROBLEMES:
            continue
    return n


def _usages(racine_projets) -> tuple[dict[str, list[str]], list[str]]:
    """({id du pack: [titres des podcasts qui l'utilisent]}, [titres des podcasts illisibles])"""
    out: dict[str, list[str]] = {}
    illisibles = []
    for d in _dossiers(racine_projets):
        titre = (lire_json(d / "projet.json", {}) or {}).get("titre") or d.name
        try:
            e = lire_etat(d)  # projet de la v1 pas encore ouvert : état neuf, donc son preset
        except (EtatIllisible, OSError):
            illisibles.append(titre)
            continue
        for pid in sorted(ids_utilises(d, e)):
            out.setdefault(pid, []).append(titre)
    return out, illisibles


def usages(racine_projets) -> dict[str, list[str]]:
    """{id du pack: [titres des podcasts qui l'utilisent]} (écran Packs)"""
    return _usages(racine_projets)[0]


def supprimer_pack(racine_projets, racine_packs, pid):
    """refusé si des podcasts l'utilisent, ou si un podcast illisible pourrait l'utiliser"""
    with VERROU_CHOIX:
        u, illisibles = _usages(racine_projets)
        if illisibles and pid != B.AUCUN and B.existe(racine_packs, pid):
            raise Refus(f"Le podcast « {illisibles[0]} » est illisible : impossible de savoir s'il utilise ce pack. "
                        "Répare-le ou retire-le avant de supprimer un pack.")
        B.supprimer(racine_packs, pid, u.get(pid, []))


def choisir(d, racine_packs, pid) -> dict:
    """pack du podcast (création, étape Shorts) ; devient le « dernier pack utilisé »"""
    with VERROU_CHOIX:
        if not isinstance(pid, str) or not B.existe(racine_packs, pid):
            raise Refus("Ce pack n'existe pas : choisis-en un autre.")
        e = lire_etat(d)
        e = modifier(d, {"type": "choisir_pack", "pack": pid,
                         "packs": empreintes(racine_packs, {pid} | _packs_des_shorts(e))})
    B.noter_dernier(racine_packs, pid)
    return e
