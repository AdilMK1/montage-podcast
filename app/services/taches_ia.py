"""Tâches IA : propositions de shorts, passages à retirer de l'épisode."""
import threading
import time
from pathlib import Path

from app.fichiers import ecrire_json_atomique, lire_json
from app.ia.claude import IAEchec, IAIndisponible, commande, demande, proposer
from app.projet.stockage import modifier
from app.taches.atelier import ErreurTache

from .cadrage import passages, plage_filmee, valider_episode, valider_shorts
from .contexte import CONSIGNES, config, creer_si_absente
from .transcript import mots, transcript_ia

CONSIGNE_SHORTS = ("Propose 6 à 10 shorts (section 3 des consignes) de 20 à 60 s, sans chevauchement entre eux, bornes "
                   "prises sur les temps du transcript (début d'une phrase ; fin d'une phrase + 0,2 s). Mélange accroches "
                   "curiosité et choc, n'invente rien qui ne soit pas dit. Chaque short est une mini-histoire REMONTÉE (sections 5 et 6 : "
                   "ouverture à froid sur la phrase la plus forte, contexte resserré, chute nette ; accroche concrète qui "
                   "ajoute la tension). Réponds UNIQUEMENT avec le JSON complet de shorts.json.")
CONSIGNE_EPISODE = ("Écris episode.json (section 2 des consignes) : trim_s, montage (morceaux gardés), « coupes » "
                    "[{\"debut\": s, \"fin\": s, \"raison\": \"…\"}] pour chaque passage retiré (hors antenne, réglages, "
                    "« on coupe ça », longs blancs), et « apercu » (début d'un passage vivant). Si rien n'est à retirer, "
                    "garde tout. Réponds UNIQUEMENT avec le JSON complet de episode.json.")


def _texte(d: Path, tache: str) -> str:
    pj = lire_json(d / "projet.json", {}) or {}
    tr = transcript_ia(d)
    return demande(CONSIGNES.read_text(encoding="utf-8"), pj.get("personnes", {}), tr, plage_filmee(d), tache,
                   brief=pj.get("brief", "") or "", noms=pj.get("noms_propres", []))


def _appel(ctx, texte: str, valider):
    """appelle l'IA en donnant signe de vie pendant l'attente ; erreurs traduites pour l'utilisateur"""
    fini, t0 = threading.Event(), time.time()

    def pouls():
        while not fini.wait(10):
            ctx.progres(min(0.95, (time.time() - t0) / 90))
    threading.Thread(target=pouls, daemon=True).start()
    try:
        return proposer(texte, valider, cmd=commande(config()), journal=ctx.journal, cwd=str(ctx.projet_dir),
                        sur_essai=lambda k: ctx.progres(None, "L'IA lit la conversation"
                                                        + (f" ({k}e essai)" if k > 1 else "")))
    except IAIndisponible:
        raise ErreurTache("Aucune IA n'est installée sur cet ordinateur : choisis les passages dans le transcript.",
                          ["choisir_au_transcript"])
    except IAEchec as e:
        raise ErreurTache(str(e), ["reessayer", "choisir_au_transcript"])
    finally:
        fini.set()


def ia_shorts(ctx):
    d = Path(ctx.projet_dir)
    obj = _appel(ctx, _texte(d, CONSIGNE_SHORTS), lambda o: valider_shorts(o, d))
    ecrire_json_atomique(d / "shorts.json", obj)
    modifier(d, {"type": "proposer_shorts", "shorts": obj["shorts"]})
    creer_si_absente(d, "apercus")


def ia_passages(ctx):
    d = Path(ctx.projet_dir)
    if commande(config()):
        ep = _appel(ctx, _texte(d, CONSIGNE_EPISODE), valider_episode)
    else:  # sans IA : l'épisode est gardé en entier
        W = mots(d)
        fin = round((W[-1][2] if W else 0.0) + 1.0, 2)
        ep = {"trim_s": [0.0, fin], "montage": [{"rush": [0.0, fin]}]}
    ecrire_json_atomique(d / "episode.json", ep)
    modifier(d, {"type": "proposer_passages", "passages": passages(d, ep)})
