"""Tâches « analyse » (rushes -> synchro, transcript, son traité, visages) et « son » (recalcul du son traité).

Micros qui ne sont pas un micro par personne (transcribe.py les note dans alertes.json) : deux micros au même
son sont transcrits comme une seule voix, un micro silencieux est écarté. L'analyse va quand même au bout
(transcript d'une voix, épisode surtout en plan large, shorts possibles) et l'utilisateur voit un avertissement
(avertissements(), exposé par la vue du projet). Si rien n'a pu être transcrit : ErreurTache qui dit quoi faire.
"""
from pathlib import Path

from app.fichiers import lire_json
from app.ia.claude import commande
from app.projet import modele as M
from app.projet.stockage import lire_etat, modifier
from app.taches.atelier import ErreurTache

from .contexte import config, creer_si_absente, lancer_script
from .noms import corriger_transcript
from .session import construire_session
from .transcript import transcript_ia
from .visages import visages_et_vignettes

_PISTES = ("les pistes séparées de chaque micro (export de Reaper ou de la table de mixage), puis crée le podcast "
           "avec ces fichiers.")
PISTES = "Récupère " + _PISTES


def _alertes(d) -> dict:
    a = lire_json(Path(d) / "alertes.json", {}) or {}
    return a if isinstance(a, dict) else {}


def _noms(d, micros: list[str]) -> str:
    """« Sarah » et « Yanis » (prénom de la personne du micro, sinon le nom du micro)"""
    pers = (lire_json(Path(d) / "projet.json", {}) or {}).get("personnes", {}) or {}
    n = [f"« {(pers.get(k) or {}).get('nom') or k} »" for k in micros]
    return n[0] if len(n) == 1 else ", ".join(n[:-1]) + " et " + n[-1]


def avertissements(d) -> list[str]:
    """ce que l'utilisateur doit savoir sur ses micros après l'analyse, en français simple"""
    a, out = _alertes(d), []
    ident = [str(k) for k in a.get("micros_identiques") or []]
    muets = [str(k) for k in a.get("micros_silencieux") or []]
    if ident:
        out.append(f"Les micros {_noms(d, ident)} ont exactement le même son : ce n'est pas un micro par personne. "
                   f"La conversation est transcrite comme une seule voix, au nom de {_noms(d, ident[:1])}, et "
                   f"l'épisode ne peut pas suivre qui parle (surtout du plan large). Pour un vrai montage, récupère {_PISTES}")
    if muets:
        un = len(muets) == 1
        out.append(f"{'Le micro' if un else 'Les micros'} {_noms(d, muets)} {'n’a' if un else 'n’ont'} enregistré aucun "
                   f"son : {'sa voix n’est' if un else 'leurs voix ne sont'} pas dans le transcript. Vérifie le fichier "
                   f"choisi pour {'ce micro' if un else 'ces micros'}.")
    return out


def _verifier_transcript(d):
    """transcript vide après transcribe.py : rien ne peut suivre (son, shorts, épisode) -> dire quoi faire"""
    tr = lire_json(Path(d) / "transcript.json", None)
    if tr != []:
        return
    a = _alertes(d)
    if a.get("micros_identiques"):
        raise ErreurTache("Les deux micros ont exactement le même son : ce n'est pas un micro par personne. " + PISTES,
                          ["rapport"])
    if a.get("micros_silencieux"):
        raise ErreurTache("Les micros n'ont enregistré aucun son. Vérifie que tu as choisi les bons fichiers de micros, "
                          "puis crée le podcast avec ces fichiers.", ["rapport"])
    raise ErreurTache("Aucune parole n'a été trouvée dans les micros. Vérifie que tu as choisi les bons fichiers de "
                      "micros, puis crée le podcast avec ces fichiers.", ["rapport"])


ETAPES = [("extract.py", "Lecture du son des rushes"), ("sync.py", "Synchronisation des caméras"),
          ("transcribe.py", "Transcription de la conversation"), ("son_v2.py", "Nettoyage du son")]


def ia_disponible(d) -> bool:
    pj = lire_json(Path(d) / "projet.json", {}) or {}
    return bool(commande(config())) and pj.get("auto_ia", True) is not False


def _cles_fichiers_cams(pj: dict) -> list[str]:
    return [f for k, v in (pj.get("cams") or {}).items()
            for f in ([k] if isinstance(v, str) else [f"{k}_{i + 1}" for i in range(len(v))])]


def deja_fait(d, pj: dict, script: str) -> bool:
    """étape faite par la pré-analyse (projet avec casting) : son extrait de chaque rush, synchro de chaque fichier"""
    d = Path(d)
    if script == "extract.py":
        fs = [d / f"mic_{k}.wav" for k in pj.get("mics") or {}] + [d / f"cam_{k}.wav" for k in _cles_fichiers_cams(pj)]
        return all(f.exists() and f.stat().st_size > 0 for f in fs)
    if script == "sync.py":
        s = lire_json(d / "sync.json", {}) or {}
        return "mic_duration_s" in s and set(s.get("cams") or {}) == set(_cles_fichiers_cams(pj))
    return False


def analyse(ctx):
    d = Path(ctx.projet_dir)
    pj = lire_json(d / "projet.json", {}) or {}
    e = lire_etat(d)
    if not M.casting_valide(e):
        raise ErreurTache("Valide d'abord le casting : l'analyse complète a besoin de savoir qui est qui.", [])
    casting = M.empreinte_casting(e)
    construire_session(d, e)
    n = len(ETAPES) + 1
    for i, (script, texte) in enumerate(ETAPES):
        if ctx.est_fait(script) or (not M.casting_manuel(e) and deja_fait(d, pj, script)):
            continue
        lancer_script(ctx, script, d / "session.json", texte=texte, debut=i / n, fin=(i + 1) / n)
        if script == "transcribe.py":
            _verifier_transcript(d)
            corriger_transcript(d / "transcript.json", pj.get("noms_propres", []))
        ctx.morceau_fait(script)
    ctx.progres(len(ETAPES) / n, "Repérage des visages")
    visages_et_vignettes(d)
    transcript_ia(d)
    modifier(d, {"type": "son_calcule", "empreinte": M.empreinte(e["son"]["reglages"])})
    modifier(d, {"type": "analyse_finie", "casting": casting})
    if ia_disponible(d):
        creer_si_absente(d, "ia_shorts")
    creer_si_absente(d, "ia_passages")
    if not lire_etat(d)["proxys"]["prets"]:
        creer_si_absente(d, "proxys")


TOURS_SON = 3


def son(ctx):
    """recalcule le son traité ; si les réglages changent pendant le calcul, recommence avec les nouveaux (au plus
    TOURS_SON fois), puis enregistre l'empreinte des réglages réellement appliqués"""
    d = Path(ctx.projet_dir)
    for tour in range(TOURS_SON):
        e = lire_etat(d)
        emp = M.empreinte(e["son"]["reglages"])
        construire_session(d, e)
        texte = "Nettoyage du son" if not tour else "Nettoyage du son avec ton dernier réglage"
        lancer_script(ctx, "son_v2.py", d / "session.json", texte=texte)
        if M.empreinte(lire_etat(d)["son"]["reglages"]) == emp:
            break
    modifier(d, {"type": "son_calcule", "empreinte": emp})
