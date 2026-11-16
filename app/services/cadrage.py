"""Cadrage des shorts et propositions de l'IA.

- plage filmée : temps (micro) où au moins une caméra serrée filme ;
- caméra de secours : si la caméra de la personne qui parle ne filme pas encore (lancée après les micros), on montre
  l'autre caméra serrée (la personne qui écoute), puis on revient sur elle ;
- validation des propositions de shorts et d'épisode (garde-fous : bornes, plage, doublons, durée) ;
- passages retirés de l'épisode (pour etat.json) à partir de episode.json.
"""
import re
from pathlib import Path

from app.fichiers import lire_json
from app.projet.import_v1 import trous

from .transcript import mots, phrases

DUREE_MIN, DUREE_MAX = 8, 90


def _serrees(d) -> dict:
    c = (lire_json(Path(d) / "sync.json", {}) or {}).get("cams", {})
    return {k: tuple(v["covers_mic_s"]) for k, v in c.items() if not k.startswith("LARGE")}


def plage_filmee(d) -> tuple[float, float]:
    c = _serrees(d)
    if not c:
        return 0.0, 1e9
    return max(0.0, min(v[0] for v in c.values()) + 0.1), max(v[1] for v in c.values()) - 0.1


def couvrir(d, micro: str, extraits: list) -> list:
    c = _serrees(d)
    mien = next((v for k, v in c.items() if k.startswith(micro)), None)
    if not mien:
        return extraits
    out = []
    for e in extraits:
        a, b = e["rush"]
        if e.get("cam") or (a >= mien[0] and b <= mien[1]):
            out.append(e)
            continue

        def autre(x, y):
            return next((k for k, v in c.items() if not k.startswith(micro) and v[0] <= x and y <= v[1]), None)
        morceaux = []
        if a < mien[0]:
            morceaux.append(([a, min(b, mien[0])], autre(a, min(b, mien[0]))))
        if b > mien[0] and a < mien[1]:
            morceaux.append(([max(a, mien[0]), min(b, mien[1])], None))
        if b > mien[1]:
            morceaux.append(([max(a, mien[1]), b], autre(max(a, mien[1]), b)))
        for (x, y), cam in morceaux:
            if y - x < 0.04:
                continue
            if cam is None and not (mien[0] <= x and y <= mien[1]):
                raise ValueError(f"aucune caméra ne filme entre {x:.1f} s et {y:.1f} s")
            out.append({**e, "rush": [round(x, 3), round(y, 3)], **({"cam": cam} if cam else {})})
    return out


def dans_plage(d, a: float, b: float):
    lo, hi = plage_filmee(d)
    if a >= lo and b <= hi:
        return a, b
    ph = phrases(d)
    if a < lo:
        a = next((p["a"] for p in ph if p["a"] >= lo), lo)
    if b > hi:
        b = max([p["b"] for p in ph if a < p["b"] <= hi] or [hi])
    return (round(a, 2), round(b, 2)) if b - a >= 3 else None


def valider_shorts(obj, d) -> dict:
    sh = obj.get("shorts") if isinstance(obj, dict) else None
    if not isinstance(sh, list) or not sh:
        raise ValueError("pas de liste « shorts »")
    out = []
    for x in sh:
        if not isinstance(x, dict):
            continue
        ex = [e for e in x.get("extraits", []) if isinstance(e, dict) and isinstance(e.get("rush"), list)
              and len(e["rush"]) == 2 and e["rush"][1] > e["rush"][0]]
        for e in ex:
            e["rush"] = dans_plage(d, *e["rush"])
        ex = [e for e in ex if e["rush"]]
        x["extraits"] = ex
        duree = sum(e["rush"][1] - e["rush"][0] for e in ex)
        if not ex or not x.get("nom") or duree < DUREE_MIN or duree > DUREE_MAX:
            continue
        x["nom"] = re.sub(r"[/\\:*?\"<>|]", "", x["nom"]).strip()
        x["accroche"] = [l.replace("—", ",").replace("–", ",") for l in x.get("accroche", [])]
        out.append(x)
    gardes, retenus = [], []
    for x in out:  # pas deux shorts sur le même passage
        z = [tuple(e["rush"]) for e in x["extraits"]]
        duree = sum(b - a for a, b in z)
        double = any(sum(max(0, min(b, d1) - max(a, c1)) for a, b in z for c1, d1 in g)
                     > 0.5 * min(duree, sum(d1 - c1 for c1, d1 in g)) for g in gardes)
        if not double:
            gardes.append(z)
            retenus.append(x)
    if not retenus:
        raise ValueError("aucun short exploitable")
    for i, x in enumerate(retenus):
        x["nom"] = f"{i + 1:02d} " + re.sub(r"^\d+\s*", "", x["nom"])
    obj["shorts"] = retenus
    return obj


def valider_episode(obj) -> dict:
    if not isinstance(obj, dict) or not isinstance(obj.get("montage"), list) or not obj["montage"]:
        raise ValueError("pas de « montage »")
    return obj


def passages(d, ep: dict) -> list[dict]:
    """passages retirés de l'épisode (trous entre les morceaux gardés), au format de etat.json"""
    W = mots(d)
    if not W:
        return []
    fin = W[-1][2] + 1.0
    morceaux = [m["rush"] for m in ep.get("montage", []) if "rush" in m] or [ep.get("trim_s", [0, fin])]
    raisons = {round(c["debut"], 1): c.get("raison", "") for c in ep.get("coupes", []) if "debut" in c}
    return [{"id": f"{a:.2f}-{b:.2f}", "a": round(a, 2), "b": round(b, 2), "raison": raisons.get(round(a, 1), "") or ""}
            for a, b in trous(morceaux, fin)]
