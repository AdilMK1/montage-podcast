"""Transcript d'un projet : mots au temps près, phrases recollées, version compacte pour l'IA."""
import re
from pathlib import Path

from app.fichiers import lire_json


def mots(d) -> list[tuple[str, float, float, str]]:
    """[(mot, début, fin, micro)] triés par début, sans les segments de traduction"""
    s = lire_json(Path(d) / "transcript.json", []) or []
    return sorted(((w["w"], w["start"], w["end"], x["speaker"]) for x in s if not x.get("traduction")
                   for w in x.get("words", [])), key=lambda w: w[1])


def phrases(d) -> list[dict]:
    """phrases {a, b, sp, t} recollées depuis les mots : même micro, pause < 1,2 s, coupées sur . ? !"""
    out, cur = [], None
    for w, a, b, sp in mots(d):
        colle = w[:1] in "'’-!?.,…" or (cur is not None and cur["t"].endswith(("'", "’")))
        if cur and (sp == cur["sp"] or colle) and a - cur["b"] < 1.2 and not (cur["t"].endswith((".", "?", "!")) and not colle):
            cur["t"] += w if colle else " " + w
            cur["b"] = b
        else:
            if cur:
                out.append(cur)
            cur = {"a": a, "b": b, "sp": sp, "t": w}
    if cur:
        out.append(cur)
    for p in out:
        p["t"] = re.sub(r"\s+([,.?!…])", r"\1", p["t"]).strip()
    return out


def transcript_ia(d) -> str:
    """une phrase par ligne avec ses temps exacts : l'IA choisit ses bornes directement dedans (écrit transcript_ia.txt)"""
    d = Path(d)
    pers = (lire_json(d / "projet.json", {}) or {}).get("personnes", {})
    lignes = [f"[{p['a']:.2f} → {p['b']:.2f}] {p['sp']}"
              + (f" ({pers[p['sp']]['nom']})" if pers.get(p["sp"], {}).get("nom") else "") + f" : {p['t']}"
              for p in phrases(d)]
    txt = ("# Une phrase par ligne : [début → fin] MICRO (nom) : texte. Temps en secondes (temps des micros).\n"
           "# Un extrait commence au « début » d'une phrase et finit à la « fin » d'une phrase (ajoute 0,2 s).\n"
           + "\n".join(lignes))
    (d / "transcript_ia.txt").write_text(txt, encoding="utf-8")
    return txt
