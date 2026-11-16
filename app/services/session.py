"""session.json (lu par tous les scripts du moteur) et spec des shorts (lue par vertical.py)."""
import os
from pathlib import Path

from app.fichiers import ecrire_json_atomique, lire_json
from app.packs import bibliotheque as B
from app.packs.projets import pack_projet
from app.projet import modele as M

from .cadrage import couvrir
from .son import config_son

RACINE_APP = Path(__file__).resolve().parents[2]


def chemin_rush(x):
    """chemin de rush : absolu, ou relatif au dossier de l'app (démo portable)"""
    if isinstance(x, list):
        return [chemin_rush(y) for y in x]
    return x if os.path.isabs(x) else str((RACINE_APP / x).resolve())


def construire_session(d, etat: dict) -> dict:
    d = Path(d)
    pj = lire_json(d / "projet.json", {}) or {}
    ep = lire_json(d / "episode.json", {}) or {}
    son = d / "son"
    s = {
        "name": d.name,
        "fps": pj.get("fps", 25),
        "mics": {k: chemin_rush(v) for k, v in pj["mics"].items()},
        "cams": {k: chemin_rush(v) for k, v in pj["cams"].items()},
        "dossier_sortie": str(d / "sorties"),
        "dossier_son": str(son),
        "son": {"mics": {k: str(son / f"{Path(v).stem} (v2 automix).wav") for k, v in pj["mics"].items()},
                "inserts": {}},
        "vocabulaire": list(pj.get("noms_propres", [])),
        **config_son(etat["son"]["reglages"]),
    }
    for k in ("trim_s", "montage", "markers", "realisation", "sortie", "filigrane"):
        if k in ep:
            s[k] = ep[k]
    gardes = [p for p in (etat["episode"]["passages"] or []) if p["garder"]]
    if gardes and "montage" in s:  # passages retirés par l'IA que la personne a choisi de garder : on les remet
        pieces = sorted([m["rush"][:] for m in s["montage"] if "rush" in m] + [[p["a"], p["b"]] for p in gardes])
        fus = []
        for a, b in pieces:
            if fus and a <= fus[-1][1] + 0.05:
                fus[-1][1] = max(fus[-1][1], b)
            else:
                fus.append([a, b])
        s["montage"] = [{"rush": p} for p in fus]
        s["trim_s"] = [fus[0][0], fus[-1][1]]
    s.setdefault("sortie", f"{pj.get('titre', d.name)} EPISODE")
    ecrire_json_atomique(d / "session.json", s)
    return s


def spec_shorts(d, etat: dict, ids: list[str], packs: Path) -> Path:
    """spec lue par vertical.py pour fabriquer les shorts `ids` de la série en cours (écrit shorts_rendu.json) :
    réglages du pack du short (le sien, sinon celui du podcast) avec chemins absolus. Les shorts d'un même appel ont
    le même pack (l'app les fabrique un par un)."""
    d = Path(d)
    pj = lire_json(d / "projet.json", {}) or {}
    shs = [M.trouver_short(etat, sid) for sid in ids]
    pids = {M.pack_du_short(etat, sh) or pack_projet(d, etat) for sh in shs}
    if len(pids) != 1:
        raise ValueError("Ces shorts n'ont pas le même pack : fabrique-les un par un.")
    pid = pids.pop()
    spec = B.spec_moteur(packs, pid)
    defauts = spec.pop("defauts_short", {})
    invite = next((k for k, v in (pj.get("personnes") or {}).items() if v.get("role") == "invité"), next(iter(pj["mics"])))
    spec.update(session=str(d / "session.json"), dossier=str(d / "shorts" / etat["serie_active"]),
                visages=lire_json(d / "visages.json", {}) or {}, etalonnage_cams=pj.get("etalonnage") or {})
    shorts = []
    for sh in shs:
        x = {**defauts, "micro": invite, **sh["spec"]}
        x.pop("pack", None)
        if pid == B.AUCUN:  # « Aucun pack » : ni logo ni musique, même si la spec du short en demande
            x["sans_musique"] = True
        x["extraits"] = couvrir(d, x["micro"], x["extraits"])
        shorts.append(x)
    spec["shorts"] = shorts
    out = d / "shorts_rendu.json"
    ecrire_json_atomique(out, spec)
    return out
