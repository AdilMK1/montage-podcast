"""Une action de l'interface : appliquée par les règles du projet (refus -> Refus), puis ses effets (tâches à créer,
étalonnage à réécrire). Les « lanceurs » sont d'abord essayés sur une copie de l'état : rien n'est écrit s'ils sont
refusés, et la tâche n'est créée que s'ils sont permis."""
from contextlib import nullcontext
from pathlib import Path

from app.fichiers import lire_json
from app.projet import modele as M
from app.projet.regles import Refus, appliquer
from app.packs import bibliotheque as B
from app.packs import projets as P
from app.projet.stockage import lire_etat, modifier
from app.services import casting
from app.services.contexte import creer_si_absente
from app.services.contexte import packs as packs_app
from app.services.couleur import ecrire_etalonnage
from app.taches.modele import FINIS

LANCEURS = {"lancer_fabrication": "shorts", "lancer_montage": "montage", "lancer_essai": "essai", "lancer_export": "export",
            "lancer_coupes": "coupes", "livrer": "livraison"}


def _params(action: dict) -> dict | None:
    t = action["type"]
    if t == "lancer_export":
        return {"format": action.get("format", "1080p")}
    if t == "lancer_essai":  # départ = minute de l'épisode monté (en secondes), 0 : ce que le public voit en premier
        return {"format": action.get("format", "1080p"), "debut": action.get("debut", 0)}
    return None


def _montage_si_pret(d: Path, e: dict):
    st = M.statuts(e)
    if e["episode"]["passages_revus"] and M.reglages_valides(e) and st["montage"] != "valide":
        creer_si_absente(d, "montage")


def taches_en_cours(d) -> list[str]:
    """types des tâches pas finies du projet (en attente ou en cours), hors proxys (indépendants des noms)"""
    dt = Path(d) / "taches"
    ts = [lire_json(f) for f in sorted(dt.glob("*.json"))] if dt.exists() else []
    return [t["type"] for t in ts if isinstance(t, dict) and t.get("statut") not in FINIS and t.get("type") != "proxys"]


def _valider_casting(d: Path, action: dict) -> dict:
    """renomme d'après le casting (clés du moteur), enregistre la validation, puis lance l'analyse complète si elle
    n'est pas à jour ; refusé tant qu'une tâche du projet tourne (elle lit les fichiers qu'on renomme)"""
    if taches_en_cours(d):
        raise Refus("Une tâche tourne encore sur ce podcast : attends qu'elle finisse pour valider le casting.")
    e = appliquer(lire_etat(d), action)  # essai : lève Refus si non permis
    casting.appliquer_noms(d, e["casting"]["reglages"])
    e = modifier(d, action)
    if M.statuts(e)["analyse"] != "valide":
        creer_si_absente(d, "analyse")
    return e


def executer(d, action: dict, packs=None) -> dict:
    """`packs` : dossier de la bibliothèque (celui de l'app par défaut, lu seulement par les actions sur les packs)"""
    d = Path(d)
    if not isinstance(action, dict) or not isinstance(action.get("type"), str):
        raise Refus("Action invalide.")
    t = action["type"]

    def racine():
        return Path(packs) if packs else packs_app()

    if t == "valider_casting":
        return _valider_casting(d, action)

    if t == "synchroniser_packs":  # empreintes des packs : seulement le serveur, qui lit la bibliothèque
        raise Refus("Action invalide.")

    if t == "choisir_pack":  # les empreintes viennent de la bibliothèque, jamais de l'interface
        p = action.get("pack")
        if not isinstance(p, str) or not p:
            raise Refus("Choisis un pack.")
        P.adopter_si_besoin(d, racine())
        return P.choisir(d, racine(), p)

    if t in LANCEURS:
        appliquer(lire_etat(d), action)  # essai : lève Refus si non permis
        if t == "lancer_essai" and "essai" in taches_en_cours(d):  # il ne prendrait pas le nouveau départ
            raise Refus("Un essai est déjà en cours : attends qu'il finisse pour en refaire un.")
        creer_si_absente(d, LANCEURS[t], _params(action))
        return lire_etat(d)

    if t == "proposer_shorts_ia":
        if not lire_etat(d)["analyse"]["fait"]:
            raise Refus("Attends la fin de l'analyse : l'IA a besoin du transcript.")
        creer_si_absente(d, "ia_shorts")
        return lire_etat(d)

    spec = action.get("spec") if t in ("modifier_short", "ajouter_short") else None
    pack_du_short = isinstance(spec, dict) and "pack" in spec
    with P.VERROU_CHOIX if pack_du_short else nullcontext():  # le pack choisi ne peut pas être supprimé entre-temps
        if pack_du_short:
            if not isinstance(spec["pack"], str) or not B.existe(racine(), spec["pack"]):
                raise Refus("Ce pack n'existe pas : choisis-en un autre.")
            P.adopter_si_besoin(d, racine())
        avant = lire_etat(d)
        e = modifier(d, action)

    if t in ("regler_couleur", "valider_couleur"):
        ecrire_etalonnage(d, e["couleur"]["reglages"])
    if t == "regler_son" and M.son_a_recalculer(e):
        creer_si_absente(d, "son")
    if t == "ajouter_short":
        creer_si_absente(d, "apercus")
        if pack_du_short:
            P.synchroniser(d, racine())
            e = lire_etat(d)
    if t == "modifier_short":
        old = M.trouver_short(avant, action.get("id"))
        if old and old["spec"].get("extraits") != action["spec"].get("extraits"):
            creer_si_absente(d, "apercus")
        if old and old["spec"].get("pack") != action["spec"].get("pack"):  # empreinte du nouveau pack
            P.synchroniser(d, racine())
            e = lire_etat(d)
    if t in ("valider_passages", "valider_couleur", "valider_son"):
        _montage_si_pret(d, e)
    return e
