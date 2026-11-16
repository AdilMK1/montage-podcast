"""Crée etat.json à partir d'un projet de la v1.1 (prudent : ce qui n'est pas sûr reste à valider).

Usage : .venv/bin/python -m app.projet.import_v1 projets/<ID> [--force]
(refuse d'écraser un etat.json existant sans --force)
"""
import json
import sys
from pathlib import Path

from . import modele as M
from .stockage import NOM, Occupe, VerrouImpossible, ecrire_etat, verrou

ECART_MIN = 0.8  # un trou plus court entre deux morceaux gardés n'est pas un passage retiré
NON_VERIFIE = "Coupes non vérifiées (import v1)"


def _lire(f: Path, defaut=None):
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return defaut


def trous(morceaux: list, fin: float) -> list[tuple[float, float]]:
    """passages retirés = trous entre les morceaux gardés (et avant / après)"""
    out, t = [], 0.0
    for a, b in sorted(morceaux):
        if a - t > ECART_MIN:
            out.append((t, a))
        t = max(t, b)
    if fin - t > ECART_MIN:
        out.append((t, fin))
    return out


def importer(d) -> dict:
    d = Path(d)
    if not d.is_dir():
        raise FileNotFoundError(f"Dossier de projet introuvable : {d}")
    e = M.nouvel_etat()
    pj = _lire(d / "projet.json", {}) or {}
    rg = pj.get("reglages") or {}
    rep = (_lire(d / "reponses.json", {}) or {}).get("blocs", {})
    vs = (rep.get("verdict_shorts") or {}).get("valeur", {}) or {}
    vc = (rep.get("verdict_coupes") or {}).get("valeur", {}) or {}

    e["analyse"]["fait"] = all((d / f).exists() for f in ("sync.json", "transcript.json", "visages.json"))
    for cle, src, ok in (("couleur", "image", "image_valide"), ("son", "son", "son_valide")):
        if rg.get(src) is not None:
            e[cle]["reglages"] = rg[src]
            if rg.get(ok):
                e[cle]["valide"] = M.empreinte(rg[src])
                if cle == "son":
                    e[cle]["applique"] = e[cle]["valide"]  # le son de la v1 validé avait été recalculé

    shorts = [x for x in (_lire(d / "shorts.json", {}) or {}).get("shorts", [])
              if isinstance(x, dict) and isinstance(x.get("nom"), str) and x.get("nom")]  # sans nom : ignoré
    if shorts:
        verif = _lire(d / "verif_coupes.json", {})
        verif = verif if isinstance(verif, dict) else {}
        e["series"] = [{"id": "S1", "shorts": []}]
        e["serie_active"] = "S1"
        for i, spec in enumerate(shorts):
            nom = spec["nom"]
            sh = M.nouveau_short(f"S1-{i + 1:02d}", spec)
            statut = (vs.get(nom) or {}).get("statut")
            sh["retenu"] = statut != "non"
            if sh["retenu"] and (d / "shorts" / f"{nom}.mp4").exists() and M.reglages_valides(e):
                sh["fabrique"] = M.empreinte_short(e, sh)
                # pas de vérification des coupes en v1 : on ne peut pas le garder d'office
                sh["alertes"] = list((verif.get(nom) or {}).get("absents", [])) if nom in verif else [NON_VERIFIE]
                sh["alertes_ok"] = not sh["alertes"]
                if statut == "ok" and sh["alertes_ok"]:
                    sh["decision"] = "garder"
            if statut == "non":
                sh["decision"] = "jeter"
            e["series"][0]["shorts"].append(sh)

    ep = _lire(d / "episode.json")
    segs = _lire(d / "transcript.json", []) or []
    fins = [w["end"] for s in segs if isinstance(s, dict) and not s.get("traduction")  # comme la v1
            for w in s.get("words") or []]
    if ep and ep.get("montage") and fins:
        fin = max(fins) + 1.0
        ps = [{"id": f"{a:.2f}-{b:.2f}", "a": round(a, 2), "b": round(b, 2), "raison": "",
               "garder": (vc.get(f"{a:.2f}-{b:.2f}") or {}).get("statut") == "garder"}
              for a, b in trous([m["rush"] for m in ep["montage"] if "rush" in m], fin)]
        e["episode"]["passages"] = ps
        # revus seulement si la v1 a un verdict pour chacun (sinon il reste à vérifier)
        e["episode"]["passages_revus"] = bool(vc) and all(p["id"] in vc for p in ps)

    px = _lire(d / "proxys.json", {}) or {}
    e["proxys"]["prets"] = bool(px) and px.get("faits", 0) >= px.get("total", 1) and not px.get("en_cours")
    return e


def main(argv: list[str]) -> int:
    args = [x for x in argv if x != "--force"]
    if len(args) != 1:
        print("Usage : python -m app.projet.import_v1 projets/<ID> [--force]")
        return 2
    dossier, force = Path(args[0]), "--force" in argv
    if not dossier.is_dir():
        print(f"Dossier de projet introuvable : {dossier}. Rien n'a été écrit.")
        return 1
    try:
        with verrou(dossier):
            if (dossier / NOM).exists() and not force:
                print(f"{dossier / NOM} existe déjà : rien n'a été écrit. Relance avec --force pour l'écraser.")
                return 1
            ecrire_etat(dossier, importer(dossier))
    except (Occupe, VerrouImpossible) as x:
        print(f"{x} Rien n'a été écrit.")
        return 1
    print(f"{NOM} écrit dans {dossier}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
